# Risques résiduels avant prod 52 jours auto-pilot

**Date** : 2026-04-30
**Thématique** : problème (risque)
**Statut** : actif (4 risques sur 5 non corrigés)

---

## Contexte

Après plusieurs vagues de corrections (pipeline TTS robustifiée, review en 5 salves,
auto-pilot state machine persistée, cap budget cascade), la pipeline est *quasiment*
prête pour la prod 52 jours. Mais 5 risques résiduels ont été identifiés et **doivent
être traités avant de lancer une vraie formation complète**.

Ce mémo les liste, classés par criticité.

## R1 — Calibration TTS empirique non validée à `speed=0.90`

### Problème

Le budget mots par bloc utilise la formule :
```python
estimated_wpm = 192 * (speed / 0.95)  # 192 wpm calé empiriquement à 0.95
```

À `speed=0.90`, ça donne ~182 wpm. Mais Fish Audio S2-Pro n'est pas
nécessairement linéaire en speed — l'intonation et les respirations peuvent
s'adapter différemment à basse vitesse.

Si la calibration réelle à 0.90 est plutôt 175 wpm au lieu de 182, le budget est
surévalué de ~4 % — pile la marge `_DEFAULT_TTS_PREFLIGHT_SAFETY = 0.96` qu'on a.

### Criticité : haute

Si la calibration est off de 5 %, le pré-check va déclencher sur ~30 % des blocs en
prod. La pipeline auto-pilot s'arrêtera quasi systématiquement.

### Action requise

Tester **1 journée complète** à `speed=0.90` avant la prod 52 jours. Mesurer la
durée audio réelle / nombre de mots → calibrer `_TTS_REFERENCE_WPM_AT_095` (à
renommer en `_TTS_REFERENCE_WPM`) et la formule pour matcher l'observation.

Idéalement : tester sur 2-3 RNCP différents pour vérifier que la calibration ne
varie pas selon le sujet du cours.

## R2 — Pas de retry par segment sur échec pré-check

### Problème

Si malgré le cap budget, un bloc déclenche le pré-check (cas pathologique : un seul
paragraphe > budget, ou bloc 7 surchargé), `_synthesize_course_audio_to_fit` lève
`ValueError`. Cette exception remonte à `_execute_ap_step`, l'auto-pilot passe en
`auto_pilot_error`, **fin de pipeline sans retry**.

### Criticité : moyenne

Avec le cap budget cascade, ce cas est très improbable pour les blocs 1-6. Reste
le bloc 7 qui n'a pas de cap. Si volume_safety en amont laisse passer un total
> 62 500 mots/jour, bloc 7 explose.

### Action possible

Deux options non exclusives :

1. **Volume_safety symétrique** : ajouter un check "total > seuil haut" dans
   `claude_code_mission_service.py` (par exemple alerter si total > 64 000 mots/jour).
   Empêche le cas en amont.

2. **LLM-shortening de fallback sur bloc 7 uniquement** : si bloc 7 dépasse, et
   seulement bloc 7, faire un appel LLM pour le raccourcir de 15-20 %. Coût
   marginal acceptable car limité au pire cas.

Préférer l'option 1 (préventive, déterministe) à l'option 2 (réactive, LLM).

## R3 — Auto-pilot — pas de compteur max d'itérations par étape

### Problème

`_tick_auto_pilot` se respawn tant que `_determine_next_ap_step` ne retourne pas
`None`. Si un bug logique fait que :
- une étape "réussit" (pas d'exception)
- mais ne fait pas avancer l'état (le check `_determine_next_ap_step` continue à
  retourner la même étape)

→ **boucle infinie**, spam des API LLM/Fish Audio jusqu'à ce que les rate-limits ou
les quotas explosent.

### Criticité : haute

Sur 52 jours et 7 étapes, la complexité est telle qu'un bug logique de ce genre est
plausible. Le coût d'un crash silencieux qui spam les API peut être très élevé
(compte Anthropic ou Fish Audio en surcharge, voire facture inattendue).

### Action requise

Ajouter dans `formation_pipeline_jobs` une colonne `auto_pilot_step_attempts INTEGER
DEFAULT 0`. Dans `_tick_auto_pilot` :

```python
if step == job.get("auto_pilot_step"):  # même étape qu'au tick précédent
    attempts = (job.get("auto_pilot_step_attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS_PER_STEP:  # 3 ou 5
        update_job(job_id, auto_pilot_error=f"Max attempts on step {step}")
        return
    update_job(job_id, auto_pilot_step_attempts=attempts)
else:  # nouvelle étape
    update_job(job_id, auto_pilot_step=step, auto_pilot_step_attempts=1)
```

`MAX_ATTEMPTS_PER_STEP = 3` est un bon défaut. Si une étape échoue 3 fois d'affilée,
arrêter et alerter.

## R4 — Boot recovery `eventlet.sleep(5)` peut être insuffisant

### Problème

`resume_interrupted_auto_pilots` attend 5 s après le boot avant de chercher les
auto-pilots interrompus. Sur démarrage à froid Azure App Service, 5 s peut être
insuffisant pour :
- Initialiser la connexion DB SQLite
- Charger le module `formation_pipeline_service`
- Compléter les migrations DB éventuelles

Si la lecture DB échoue, le `try/except` global swallow l'erreur → **les auto-pilots
ne reprennent pas**.

### Criticité : moyenne

Le worst case est qu'un push staging tue la pipeline et que la reprise échoue. Mais
le mécanisme manuel de relance reste en place : un admin peut faire `POST
/run-auto/<job_id>` pour redémarrer. L'auto-récupération est un *nice to have*, pas
un *must have*.

### Action possible

Remplacer le sleep fixe par un retry/backoff :

```python
def resume_interrupted_auto_pilots():
    for delay in [5, 10, 30, 60]:
        eventlet.sleep(delay)
        try:
            job_ids = get_auto_pilot_jobs_to_resume()
            # ...
            return  # OK, on a réussi
        except Exception as e:
            logger.warning(f"Recovery attempt failed (delay={delay}): {e}")
    logger.error("Boot recovery failed after all retries")
```

## R5 — Heartbeat eventlet bloqué si sync long

### Problème

Le heartbeat lock auto-pilot tourne dans un greenlet :
```python
def _heartbeat():
    while not stop:
        eventlet.sleep(60)  # cooperative yield
        _refresh_ap_lock(job_id)
```

Mais `_execute_ap_step` peut faire des appels sync **qui ne yieldent pas à eventlet**.
Par exemple, `requests` HTTP libère le GIL mais bloque le thread eventlet sauf
monkey-patch (`eventlet.monkey_patch()`).

Si un appel HTTP prend > 60 s sans yield, le heartbeat ne tournera pas, le TTL lock
expire, **un autre worker peut prendre le job → doublons**.

### Criticité : faible-moyenne

Pour que ça crée un problème, il faut :
1. Un appel sync > 5 min sans yield (TTL lock complet)
2. ET un autre worker actif simultanément (multi-worker Azure)
3. ET les deux acquièrent le job alors que le premier travaillait dessus

C'est un combo improbable, mais possible. Le risque concret : double appel TTS, ou
double facturation Anthropic, ou double création de fichiers Azure (gérable car
upload = idempotent en blob).

### Action possible

1. **Vérifier que `eventlet.monkey_patch()` est bien appliqué** dans `main_app.py`.
   Si oui, `requests` yield correctement et le risque tombe.
2. **Ajouter un wrapper qui force un `eventlet.sleep(0)` périodique** dans les
   boucles sync longues (par exemple toutes les 100 segments traités).

## Synthèse des actions avant prod 52 jours

| Risque | Criticité | Action minimum | Action idéale |
|---|---|---|---|
| R1 calibration TTS | Haute | Tester 1 jour à 0.90, ajuster wpm | Tester 3 RNCP différents |
| R2 retry segment | Moyenne | Volume_safety symétrique | + LLM fallback bloc 7 |
| R3 compteur max | Haute | Implémenter MAX_ATTEMPTS_PER_STEP=3 | + alerte email/log structuré |
| R4 boot recovery | Moyenne | Retry/backoff [5,10,30,60] | + healthcheck DB explicite |
| R5 heartbeat | Faible-moyenne | Vérifier monkey_patch | + sleep(0) périodique sync long |

**Priorité 1 (bloquant prod)** : R1 et R3.
**Priorité 2 (à faire avant prod)** : R2, R4.
**Priorité 3 (à investiguer)** : R5.

## Références code

- `backend/services/content_generation_service.py` :
  - `_TTS_REFERENCE_WPM_AT_095`, `_estimated_words_budget_for_course` (R1)
  - `_synthesize_course_audio_to_fit` (R2)
- `backend/routes/formation_routes.py` :
  - `_tick_auto_pilot`, `_determine_next_ap_step` (R3)
  - `resume_interrupted_auto_pilots` (R4)
- `backend/main_app.py` : monkey_patch eventlet (R5)
- Mémos connexes :
  - `04-solutions/auto-pilot-state-machine-db.md`
  - `03-decisions/audit-codex-corrections-tts.md`

## Leçons / Pour le mémoire

- **Une pipeline n'est jamais "finie", elle est "stable assez pour la prochaine
  étape".** Ces 5 risques étaient connus à la fin du dev. Leur résolution sera la
  prochaine itération.

- **Lister explicitement les risques résiduels permet de les hiérarchiser et de
  négocier la sortie en prod.** Sans ce mémo, ces risques deviennent des "trucs en
  tête" qu'on oublie sous pression. Avec, on peut décider en connaissance de cause :
  on lance avec R5 ouvert ? R1 fermé ? Etc.

- **La criticité d'un risque dépend du coût de son occurrence × probabilité.** R3
  (boucle infinie) est haute criticité non parce que probable, mais parce que le
  coût (spam API) est très élevé. R5 (doublons) est plus probable mais le coût
  unitaire est plus faible (1 doublon = pas la fin du monde).

- **Les pipelines auto-pilot sur infra éphémère exigent un design défensif à plusieurs
  couches.** Compteur max + retry boot + monkey_patch + lock TTL + heartbeat = défense
  en profondeur. Aucune couche seule n'est suffisante, mais la combinaison rend les
  modes d'échec rares.

- **Conserver une issue/checklist de risques résiduels facilite la transition vers
  une prod stable.** Sert aussi de "to-do du mémoire technique" — chaque risque résolu
  est un cas étudié à raconter.
