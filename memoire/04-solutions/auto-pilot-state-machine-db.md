# Auto-pilot formation — state machine persistée en DB (résistant aux restarts Azure)

**Date** : 2026-04-30
**Thématique** : solution technique
**Statut** : implémenté

---

## Contexte

L'auto-pilot de la pipeline formation enchaîne 7 étapes longues :
**REAC → KB → global program → daily programs → content (60k mots/jour × 52 jours) →
review (5 salves × 18 segments × 52 jours) → audio (TTS Fish Audio)**.

Durée totale : 2-4 heures pour une formation moyenne.

## Problème

### Le greenlet RAM mourrait silencieusement

Architecture initiale : `_run_auto_pilot()` était un greenlet unique, vivant en RAM
pendant les 2-4 h, avec son état dans un dict in-memory `_AUTO_PILOT_STATE{}`.

Sur Azure App Service, plusieurs causes de mort silencieuse :
1. **Push staging** → 10 workflows GitHub Actions parallèles → restart App Service en
   cours de pipeline
2. **Auto-scale Azure** : redémarrage worker à charge variable
3. **Crash mémoire** : un OOM tue le process Python
4. **Worker recycling** Azure : tourne tous les ~24h

Symptôme observé en prod : push staging à 14h, à 16h on constate `segments_reviewed=0`
et pas de Word 2 généré. La pipeline auto-pilot était morte au moment du restart, **et
personne n'a relancé**.

### Pourquoi un simple "restart sur restart" ne suffit pas

Naïvement, il suffirait de relancer un greenlet au boot. Mais :
- L'**état d'exécution** était en RAM (`_AUTO_PILOT_STATE`) — perdu au restart
- Les **paramètres** de l'auto-pilot (model, tts_mode, use_cc) étaient passés en
  arguments au greenlet — perdus aussi
- Pas de moyen de savoir **où on en était** dans la pipeline (étape ? quel folder ?)
- Risque de **doublons** si plusieurs workers boot en même temps et relancent tous

Il faut donc :
1. Persister l'état d'exécution
2. Persister les paramètres
3. Avoir un mécanisme idempotent (skip ce qui est déjà fait)
4. Avoir un lock pour éviter les doublons multi-workers

## Architecture retenue

### 1. State machine persistée en DB

10 nouvelles colonnes ajoutées à `formation_pipeline_jobs` :

| Colonne | Type | Rôle |
|---|---|---|
| `auto_pilot_enabled` | INTEGER (0/1) | L'auto-pilot est-il actif sur ce job ? |
| `auto_pilot_step` | TEXT | Étape courante : `init` / `reac` / `kb` / `global` / `daily` / `content` / `volume_safety` / `review` / `audio` / `done` |
| `auto_pilot_model` | TEXT | Modèle pour les LLM calls (`sonnet` / `haiku`) |
| `auto_pilot_tts_mode` | TEXT | Mode TTS (`fish_audio` / `gtts` / `mock`) |
| `auto_pilot_use_cc` | INTEGER (0/1) | Utiliser Claude Code subprocess plutôt qu'API ? |
| `auto_pilot_skip_vs` | INTEGER (0/1) | Skipper l'étape volume_safety ? |
| `auto_pilot_volume_done` | INTEGER (0/1) | Volume_safety déjà passé ? (idempotence) |
| `auto_pilot_error` | TEXT | Message d'erreur si la pipeline a crashé |
| `auto_pilot_locked_at` | TIMESTAMP | Lock optimiste posé à cette heure |
| `auto_pilot_lock_owner` | TEXT | PID du worker qui détient le lock |

### 2. Runner court par étape (`_tick_auto_pilot`)

Au lieu d'un greenlet long, **un greenlet exécute UNE étape** puis se respawn pour la
suivante.

```python
def _tick_auto_pilot(job_id):
    if not _acquire_ap_lock(job_id):
        return  # un autre worker s'en occupe

    try:
        step = _determine_next_ap_step(job_id)  # checks idempotents
        if step is None:
            update_job(job_id, auto_pilot_step="done")
            return

        update_job(job_id, auto_pilot_step=step)
        _execute_ap_step(job_id, step, j)        # bloquant, peut être très long
        should_respawn = True

    except Exception as e:
        update_job(job_id, auto_pilot_error=str(e)[:500])

    finally:
        _release_ap_lock(job_id)

    if should_respawn:
        eventlet.spawn(_tick_auto_pilot, job_id)
```

**Bénéfices** :
- Si Azure restart pendant `_execute_ap_step`, on perd l'étape courante mais l'état
  DB reste à jour → la reprise sait où redémarrer.
- Pas de pile d'appels longue à dérouler en cas de crash.
- Visualisable : SELECT auto_pilot_step FROM jobs montre la progression.

### 3. Lock optimiste TTL 5 min + heartbeat 60 s

Plusieurs workers Azure peuvent booter simultanément. Le premier qui pose le lock
gagne ; les autres skip.

```python
def _acquire_ap_lock(job_id):
    UPDATE formation_pipeline_jobs
    SET auto_pilot_locked_at = CURRENT_TIMESTAMP, auto_pilot_lock_owner = ?
    WHERE id = ? AND auto_pilot_enabled = 1
      AND (auto_pilot_locked_at IS NULL
           OR strftime('%s', auto_pilot_locked_at) < ?)  # lock expiré
    return cursor.rowcount == 1
```

TTL 5 min : si le worker meurt pendant l'étape, le lock expire automatiquement et un
autre worker peut reprendre.

Mais une étape `content` dure 2-4 h, plus que le TTL. D'où le **heartbeat** :

```python
def _heartbeat():
    while not stop:
        eventlet.sleep(60)
        _refresh_ap_lock(job_id)
```

Spawn en parallèle de `_execute_ap_step`. Rafraîchit le timestamp toutes les 60 s
tant que le worker est vivant. Si le worker meurt, le heartbeat s'arrête, le TTL
expire dans 5 min max, un autre worker reprend.

### 4. Boot recovery (`resume_interrupted_auto_pilots`)

Au boot de l'app, `main_app.py` spawn un greenlet qui :
1. Attend 5 s (laisse l'app finir d'initialiser)
2. Lit en DB tous les jobs `auto_pilot_enabled=1` ET `step != 'done'` ET lock
   absent/expiré
3. Pour chacun : `eventlet.spawn(_tick_auto_pilot, job_id)`

Fonction utilitaire dans `formation_pipeline_service.py` :
```python
def get_auto_pilot_jobs_to_resume():
    SELECT id FROM formation_pipeline_jobs
    WHERE auto_pilot_enabled = 1
      AND (auto_pilot_step IS NULL OR auto_pilot_step != 'done')
      AND (auto_pilot_locked_at IS NULL
           OR strftime('%s', auto_pilot_locked_at) < ?)
```

### 5. `_determine_next_ap_step` — checks idempotents

Pour chaque étape, vérifier en DB si elle est déjà faite **avant** de la lancer.
Permet à un restart de skipper les étapes déjà complétées sans les refaire.

Exemples :
- REAC : `if not job.reac_text: return "reac"`
- KB : `if kb_stats(job_id).completed > 0: kb_done = True`
- Content : `if completed_segs >= nb_days × 18: content_done = True`
  (compare au **nombre attendu**, pas aux segments existants — sinon faux positif si
  des segments manquent suite à un restart partiel)
- Review : `if not_reviewed_count > 0: return "review"`

## Bugs trouvés et corrigés en cours d'implémentation

### Bug #1 — `NameError: j` dans content API

`_execute_ap_step` utilisait la variable `j` (inexistante dans ce scope) au lieu du
paramètre `job`. Fix trivial mais bloquait toute la branche content API.

### Bug #2 — `expected_segs` calculé sur l'existant

Le check content comparait `completed_segs` au nombre de segments **existants en DB**.
Si un restart en cours de création laissait moins de segments que prévu (ex. 900
sur 936 attendus), le check croyait à tort que c'était fini. Fix : comparer à
`nb_days × 18` (invariant 6 sous-parties × 3 passes).

### Bug #3 — Threads simultanés sur content API

`launch_tts_for_all_days` lançait N threads simultanés (1 par jour). Sur 52 jours,
ça créait 52 connexions Anthropic simultanées → 429 cascading. Fix : remplacer par
une boucle folder-par-folder synchrone dans le greenlet auto-pilot.

### Bug #4 — Health-check non bloquant

`compute_health()` retournait `{ok: False, reason: ...}` mais l'auto-pilot n'agissait
pas dessus. Fix : lever `RuntimeError` si `ok=False`, l'auto-pilot reste en erreur.

### Bug #5 — Idempotence content API

`launch_tts_for_all_days` créait des `cours_folders` sans vérifier s'il y en avait
déjà. Sur un restart en cours de génération, doublons. Fix : skip si folders
existent.

### Bug #6 — `segments_failed` ignoré par review

`run_content_review()` retournait succès même si certains segments avaient échoué
en interne. Fix : propagation explicite, l'auto-pilot lève une erreur si
`segments_failed > 0`.

### Bug #7 — `audio force_all=True`

L'étape audio re-générait tout depuis zéro à chaque relance. Fix : `force_all=False`
pour ne traiter que les folders avec `dirty=1`.

## Risques résiduels (cf. `02-problemes/pipeline-52-jours-risques-residuels.md`)

- Pas de **compteur max d'itérations** par étape : risque de boucle infinie si une
  étape réussit mais ne fait pas avancer l'état (bug logique).
- Boot recovery `eventlet.sleep(5)` peut être insuffisant si la DB n'est pas prête.
- Heartbeat 60 s peut être bloqué si une opération sync ne yield jamais à eventlet
  pendant > 60 s.

## Références code

- `backend/database/db.py` (~ligne 387) : 10 colonnes `auto_pilot_*` ajoutées via
  migration ALTER TABLE
- `backend/services/formation_pipeline_service.py` :
  - `update_job` / `get_job` étendus aux nouveaux champs
  - `get_auto_pilot_jobs_to_resume`
- `backend/routes/formation_routes.py` :
  - `_acquire_ap_lock` / `_release_ap_lock` / `_refresh_ap_lock`
  - `_determine_next_ap_step`
  - `_execute_ap_step`
  - `_tick_auto_pilot`
  - `resume_interrupted_auto_pilots`
- `backend/main_app.py` : `eventlet.spawn(resume_interrupted_auto_pilots)` au boot
- CHANGELOG 2026-04-30 : *"refactor: auto-pilot formation — state machine persistée
  en DB"*

## Leçons / Pour le mémoire

- **Toute pipeline > 30 min sur Azure App Service est potentiellement interrompue.**
  Concevoir dès le départ pour la reprise après crash, pas en bolt-on tardif.

- **In-memory state + restart automatique = perte silencieuse.** L'utilisateur ne
  voit rien, croit que ça marche, mais la prod est cassée. Persistance = visibilité.

- **Lock optimiste + heartbeat est plus simple qu'un broker** (Redis, etc.) pour ce
  cas d'usage. Mais le heartbeat doit yielder dans l'event loop, sinon le TTL
  expire pour rien.

- **Le runner court par étape est un pattern récurrent** pour les pipelines longues
  sur infra éphémère. Comparable aux *step functions* AWS, mais réalisable en pur
  SQL + greenlet.

- **L'idempotence est une feature de visibilité.** Permet de relancer manuellement
  une pipeline sans craindre les doublons. Donne aussi un moyen simple de "forcer
  une étape" : reset le flag en DB, relance.

- **Découvrir 7 bugs en implémentant le refactor** suggère que l'ancienne archi
  cachait des problèmes. Une refonte structurée force à faire face aux invariants
  qu'on présumait sans les vérifier.
