# Audit des corrections Codex sur le TTS — speedup, preflight, prompts 3300 mots

**Date** : 2026-04-30
**Statut** : appliqué après itération
**Fichiers impactés** : `backend/services/content_generation_service.py`,
`backend/prompts/prompt-generation-tts-direct.md`,
`backend/prompts/prompt-generation-tts-scratch.md`,
`backend/services/claude_code_mission_service.py`

---

## Contexte

Après avoir identifié le risque de coupure mid-phrase (cf.
`02-problemes/coupure-audio-tts-pleine-phrase.md`), une première vague de corrections
a été produite par Codex (CLI Claude utilisée comme assistant secondaire). Plusieurs
mécanismes ont été ajoutés en cascade. Cet audit consigne lesquels ont été retenus,
modifiés ou rejetés.

## Corrections proposées par Codex (V1)

### C1 — Découpage paragraph-aware (retenu)

`_choose_natural_boundary` privilégie les fins de paragraphe avant les fins de phrase.
Ordre : paragraphe dans fenêtre → phrase dans fenêtre → paragraphe élargi → phrase
élargie → split brut.

**Verdict : adopté tel quel.** L'idée est bonne, l'implémentation propre.

### C2 — Speedup local x1.12 (rejeté après audit)

Si le TTS est trop long, accélérer localement le MP3 via `pydub.effects.speedup`
jusqu'à un facteur x1.12 sans rappeler Fish Audio.

**Verdict : rejeté.** Raisons :

1. **Pitch shift**. `pydub.effects.speedup` accélère sans préserver la pitch — la
   voix devient plus aiguë et "Mickey Mouse". À x1.12 c'est subtil mais audible.
2. **Cumulé sur 52 jours × 7 blocs = 364 blocs**, si 30 % des blocs déclenchent le
   speedup, l'apprenant entend cette voix légèrement modifiée 100+ fois sur la
   formation. Effet pénible.
3. **Casse le ton "vrai prof"** que les prompts cherchent à préserver. Le "Mickey
   subtil" trahit l'effet automatisé.

Correction appliquée : `_DEFAULT_TTS_LOCAL_MAX_SPEEDUP = 1.0` (désactivé par défaut).
Le code reste en place pour qu'un opérateur expérimenté puisse l'activer ponctuellement
via `FORMATION_TTS_LOCAL_MAX_SPEEDUP=1.05` si besoin, mais c'est désactivé en prod.

### C3 — Pré-check budget mots avant Fish Audio (retenu, élargi)

Avant d'appeler Fish Audio, calculer un budget mots prudent
(`_estimated_words_budget_for_course`) basé sur la durée cible et la vitesse TTS.
Si le bloc dépasse, `raise ValueError` sans payer l'appel TTS.

**Verdict : adopté et élargi.** L'idée évite les appels Fish Audio inutiles. On a
ajouté le coefficient `_DEFAULT_TTS_PREFLIGHT_SAFETY = 0.96` (4 % de marge), et plus
tard intégré ce budget directement dans `_choose_natural_boundary` via `word_budget_max`
(cf. `04-solutions/decoupage-blocs-cap-budget-cascade.md`) — ce qui rend le pré-check
quasi-jamais déclenché en pratique, parce que le découpage respecte déjà le budget.

### C4 — Speed Fish Audio descendue à 0.90 (retenu)

`_DEFAULT_TTS_SPEED = 0.90` (au lieu de 0.95 historique). Voix plus posée, plus de
marge audio par mot.

**Verdict : adopté.** Conservateur, n'altère pas la qualité (la voix reste naturelle
à 0.90), donne 5 % de marge supplémentaire sur la durée.

Note : ça change la calibration empirique (192 mots/min était calé à 0.95). Le calcul
linéaire `192 × (0.90/0.95) ≈ 182 wpm` est une approximation prudente — Fish Audio
n'est pas linéaire en speed, mais l'erreur va dans le sens de la sécurité (sous-estime
le débit).

### C5 — Prompts 5 000 → 3 300 mots/passe (retenu)

Au lieu de générer ~15 000 mots/sous-partie (3 passes × 5 000), descendre à
~9 900 mots/sous-partie (3 passes × 3 300).

Avec 6 sous-parties/jour : 6 × 9 900 ≈ **59 400 mots/jour**, vs 90 000 historique.

**Verdict : adopté.** Raisons :
- Le total mots/jour doit rentrer dans le budget audio total (~62 500 mots à speed
  0.90). 60 000 < 62 500 = OK avec 4 % de marge.
- Génère **moins** côté LLM = moins de risque de divagation/dilution = qualité
  pédagogique mieux préservée.
- Coût LLM réduit de 33 %.

### C6 — Volume_safety aligné à 60 000 (retenu)

`_TARGET_WORDS_PER_DAY = 60000` dans `claude_code_mission_service.py` (au lieu de
90000). Le volume_safety regonflerait sinon les cours derrière, annulant l'effet
de C5.

**Verdict : adopté.** Cohérence pipeline : prompts génèrent 60k → volume_safety
vise 60k → découpage TTS découpe en 7 blocs cumulant 60k.

## Risques signalés par l'audit, partiellement traités

### R1 — Calibration TTS empirique (à valider en prod)

Le 192 wpm vient d'une calibration sur un corpus restreint à `speed=0.95`. Le
`182 wpm` extrapolé pour `speed=0.90` est une approximation linéaire — Fish Audio
peut adapter intonation/respirations différemment à basse vitesse.

**Statut** : non testé sur 1 journée complète à 0.90. À faire avant la prod 52 jours.

### R2 — Si un bloc est trop long, l'auto-pilot s'arrête sans retry

Codex avait laissé : `raise ValueError("...")` qui remonte à `auto_pilot_error` et
stoppe la pipeline. Pas de retry automatique, pas de fallback.

**Statut** : initialement envisagé un retry par LLM-shortening, **rejeté** au profit
du cap budget cascade (cf. `04-solutions/decoupage-blocs-cap-budget-cascade.md`).
Le cap rend ce risque très improbable, mais pas zéro pour le bloc 7. À voir en prod.

### R3 — Auto-pilot — pas de compteur max d'itérations par étape

`_tick_auto_pilot` se respawn tant que `_determine_next_ap_step` ne retourne pas
`None`. Si un bug logique fait réussir une étape sans faire avancer l'état, boucle
infinie.

**Statut** : reconnu, **non corrigé**. À ajouter avant prod 52 jours
(cf. `02-problemes/pipeline-52-jours-risques-residuels.md`).

### R4 — Boot recovery `eventlet.sleep(5)` peut être court

Sur démarrage à froid Azure, 5 s peut être insuffisant pour que la DB soit prête.

**Statut** : reconnu, **non corrigé**. À renforcer avec retry/backoff avant prod.

### R5 — Heartbeat eventlet bloqué si sync long

Si `_execute_ap_step` fait un appel sync qui ne yield pas à eventlet pendant > 60 s,
le heartbeat ne tournera pas, le TTL expire, un autre worker peut prendre le job →
doublons.

**Statut** : reconnu, **non corrigé**. À investiguer : les `requests` HTTP libèrent
le GIL mais bloquent eventlet sauf monkey-patch.

## Trade-offs assumés

### Volume pédagogique 60k vs 90k

Perdre 33 % de contenu par jour est-il problématique ? Sur 52 jours, c'est 1.5
million de mots de moins. Évaluation :
- 60k mots/jour = ~6h de cours audio à 192 wpm. C'est une journée pleine.
- L'apprenant *écoute* le cours, ne le *lit* pas. La densité de mots compte moins
  que la densité d'idées.
- Les 30k mots "perdus" étaient souvent des redites ou de l'étoffement par le LLM
  pour atteindre la cible. Couper l'étoffement améliore plutôt qu'aggrave.

À valider empiriquement sur 1 journée complète : le contenu reste-t-il dense en
notions pédagogiques ?

### Coût Fish Audio préservé

L'objectif principal du pré-check était d'**économiser les appels TTS coûteux**
quand le bloc est trop long. Avec le cap budget en amont, le pré-check n'est presque
jamais déclenché — donc en pratique on n'économise quasiment rien. **C'est OK** :
le pré-check sert maintenant de filet de sécurité (defense in depth).

## Leçons / Pour le mémoire

- **Auditer les contributions d'un assistant LLM avant adoption.** Codex a produit
  6 corrections, dont 1 (speedup x1.12) qui aurait dégradé la qualité finale. Sans
  audit, le bug aurait passé en prod.

- **Le pitch shift est un piège classique du speedup audio.** `pydub.effects.speedup`
  est rapide mais altère la voix. Pour préserver la pitch, il faudrait `librosa` ou
  `pyrubberband` — bibliothèques plus lourdes, dépendances natives. La solution
  algorithmique en amont (cap budget) est strictement préférable.

- **La cohérence inter-modules vaut plus qu'optimiser un seul.** C5 (prompts 60k) sans
  C6 (volume_safety 60k) aurait été annulé par le regonflement post-génération. Penser
  par chaîne, pas par maillon.

- **Les approximations linéaires d'API externes sont fragiles mais utilisables si le
  signe d'erreur est sûr.** Le `192 × (speed/0.95)` n'est pas exact, mais sous-estime
  le débit — donc va dans le sens de la sécurité. Acceptable comme V1, à recalibrer
  en V2 sur données réelles.

- **L'audit collaboratif (humain + LLM) est efficace.** Cet audit a identifié 5 corrections
  bien faites, 1 à rejeter, et 5 risques résiduels. Demander à un LLM de produire
  d'abord, puis auditer avec un humain expérimenté, donne souvent un meilleur résultat
  que demander à un humain de produire seul.

## Références code

- `backend/services/content_generation_service.py` :
  - `_DEFAULT_TTS_SPEED = 0.90`, `_DEFAULT_TTS_LOCAL_MAX_SPEEDUP = 1.0`,
    `_DEFAULT_TTS_PREFLIGHT_SAFETY = 0.96` (~ligne 34)
  - `_synthesize_course_audio_to_fit` (~ligne 318)
- `backend/prompts/prompt-generation-tts-direct.md`,
  `backend/prompts/prompt-generation-tts-scratch.md` : prompts ~3 300 mots/passe
- `backend/services/claude_code_mission_service.py` : `_TARGET_WORDS_PER_DAY = 60000`
  (~ligne 2359)
- CHANGELOG 2026-04-30 : *"fix: TTS auto-pilot — plus de coupure brute en pleine phrase"*
- Mémo connexe : `04-solutions/decoupage-blocs-cap-budget-cascade.md`
