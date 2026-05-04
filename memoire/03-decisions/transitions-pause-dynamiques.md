# Décision : transitions de pauses dynamiques contextuelles (4 pauses courtes)

**Date** : 2026-04-30
**Statut** : implémenté sous une forme élargie — remplacé par les transitions
contextuelles Q&A/pauses (cf.
`memoire/04-solutions/break-transitions-contextuelles.md`)
**Fichiers cibles historiques** : `backend/services/playlist_tts_service.py` +
nouveau service `backend/services/pause_transition_service.py`
**Fichiers implémentés** : `backend/services/break_transition_service.py`,
`backend/services/content_generation_service.py`,
`backend/services/playlist_tts_service.py`, `backend/routes/hr_routes.py`

> **Note de mise à jour 2026-05-04** : cette décision est maintenant dépassée par
> l'implémentation `break_transition_service.py`. Le périmètre a été élargi :
> non seulement les pauses courtes, mais aussi les Q&A et la pause déjeuner peuvent
> recevoir une intro/outro contextuelle. Le closing du cours reste une clôture
> pédagogique douce et n'annonce plus directement `questions`, `pause` ou `chat`.
> `audioqapause` est conservé comme fallback, pas comme source principale quand le
> dossier contient ses propres fichiers contextualisés.

> **Note historique 2026-04-30** : avec le closing contextuel maintenant intégré
> à la fin du fichier cours, la discontinuité auditive entre cours et pause était
> largement atténuée. Cette analyse reste utile pour comprendre l'origine de la
> solution, mais le statut "non implémenté" n'est plus vrai.

---

## Contexte

La playlist horodatée d'une journée contient 19 fichiers MP3 :

```
cours_blocN.mp3 → qa_N.mp3 → pause_N.mp3 → cours_blocN+1.mp3 → ...
```

Les **pauses courtes** (4 sur la journée, après les blocs 1, 2, 3, 6) servent de
sas entre deux blocs de cours. Elles contiennent de la musique d'ambiance + une
voix qui annonce la pause et la reprise.

Architecture actuelle : les MP3 de pause sont **téléchargés depuis Azure Blob**
(container `audioqapause`), pas régénérés par dossier. Les textes intro/outro sont
en dur dans le code (`_PAUSE_VARIANTS`, 4 variantes statiques) :

```python
_PAUSE_VARIANTS = [
    ("Vous avez maintenant quelques minutes de pause...", "La pause est terminée..."),
    ("On fait une petite pause. Étirez-vous...", "C'est reparti, on reprend."),
    ...
]
```

Sélection : `idx = (bloc_number - 1) % 4`. Cycle de 4 textes neutres, génériques.

## Problème

### Discontinuité auditive entre cours et pause

À la fin d'un bloc cours, l'apprenant entend par exemple : *"...et c'est ce qui
explique l'efficacité des techniques de fidélisation client par les avantages
exclusifs."*

Puis sans transition contextuelle : *"On fait une petite pause. Étirez-vous, prenez
un verre d'eau."*

La rupture est nette. Aucune référence à ce qui vient d'être enseigné, aucune
amorce de ce qui va suivre. C'est une coupe **mécanique**, pas une transition
**pédagogique** comme un vrai prof ferait : *"Voilà, on a posé les fondamentaux de
la fidélisation. Prenez 10 minutes, on continuera avec la mise en pratique."*

### Faiblesse pédagogique

Une transition contextuelle sert à :
1. **Signaler la fin d'un thème** (clôture cognitive)
2. **Anticiper la suite** (amorce, maintient l'engagement)
3. **Donner le sentiment d'un humain au bout** (vs un système automatique)

Le cycle de 4 textes statiques manque les 3 fonctions.

## Options envisagées

### Option A — Statu quo (rejeté)

Garder les 4 textes statiques. Pro : zéro complexité ajoutée. Contra : laisse une
faiblesse pédagogique critique.

### Option B — Élargir le pool de textes statiques (rejeté)

Passer de 4 à 20 variantes statiques pour réduire la répétition. Ne résout PAS le
problème de contextualisation — toujours pas de référence au contenu effectif du
cours.

### Option C — LLM génère les transitions par dossier (retenu)

Pour chaque pause courte (4 par jour), appeler le LLM avec :
- Les ~200 derniers mots du bloc cours qui précède
- Les ~200 premiers mots du bloc cours qui suit
- Consigne : générer un intro (clôture du bloc) + outro (relance vers la suite)

Format JSON `{intro: "...", outro: "..."}`. Coût marginal : 4 appels LLM par jour de
cours, soit ~200 sur 52 jours.

**Gain** : transitions vraiment contextuelles. Le ton "vrai prof" est préservé.

## Cas particulier : la pause midi (`pause_midi`)

La playlist a un fichier spécifique `pause_midi_13h15_14h45.mp3` (90 min). Sa
position dans la playlist **change selon la saison** :

- **Hiver** : `[fin bloc 3]` → pause_midi → `[cours bloc 4]`
- **Été** : `[Q&A bloc 4]` → pause_midi → `[cours bloc 5]`

Configurable par plateforme via `/schedule-config` (mode `hiver` ou `ete`).

**Impact sur les transitions** : on ne sait pas, au moment de la génération du dossier,
dans quel ordre la pause_midi sera diffusée. Les MP3 sont produits une seule fois
(principe "1 RNCP = 1 module durable"), mais consommés selon le mode actif au moment
de la lecture.

→ **Décision** : la pause_midi garde des textes intro/outro **neutres et statiques**
(`_PAUSE_MIDI_INTRO/OUTRO`). Pas de contextualisation possible sans dupliquer le
fichier (été et hiver), ce qui casse l'architecture "1 module durable".

Les **4 pauses courtes** restent contextualisables car leur position est fixe :
- Pause après bloc 1 → toujours entre bloc 1 et bloc 2
- Pause après bloc 2 → toujours entre bloc 2 et bloc 3
- Pause après bloc 3 → toujours entre bloc 3 et bloc 4 (été) OU bloc 3 et pause_midi (hiver)
- Pause après bloc 6 → toujours entre bloc 6 et bloc 7

(Note : la pause après bloc 3 a deux modes possibles. Si on contextualise, il faut
choisir : on la rend contextuelle au bloc 3 et au bloc 4 du jour, ce qui est juste
en hiver mais légèrement off en été où la pause_midi vient ensuite. Pour V1,
ignorer ce détail.)

## Architecture cible historique (remplacée)

Cette section décrit l'ancien design envisagé. L'implémentation effective utilise
`break_transition_service.py`, couvre `qa`, `pause` et `pause_midi`, et se câble
dans les deux chemins audio (`generate_audio_from_script` et
`generate_playlist_for_folder`). Voir la note solution :
`memoire/04-solutions/break-transitions-contextuelles.md`.

### Nouveau service `pause_transition_service.py`

```python
def generate_pause_transition(folder_id, after_bloc_num, pause_duration_sec):
    """
    Génère intro+outro contextuels pour la pause après bloc after_bloc_num.
    Cache en DB (table pause_transitions). Fallback statique en cas d'erreur LLM.
    """
    # Cache check
    if cached: return cached.intro, cached.outro

    # Récupérer textes adjacents
    prev_text = get_bloc_text(folder_id, after_bloc_num)
    next_text = get_bloc_text(folder_id, after_bloc_num + 1)

    # Extraits
    prev_excerpt = " ".join(prev_text.split()[-200:])
    next_excerpt = " ".join(next_text.split()[:200])

    # Prompt LLM
    intro, outro = _generate_via_llm(prev_excerpt, next_excerpt, pause_duration_sec)

    # Cache
    save_to_db(folder_id, after_bloc_num, intro, outro)
    return intro, outro
```

### Nouvelle table DB `pause_transitions`

```sql
CREATE TABLE pause_transitions (
    folder_id INTEGER NOT NULL,
    after_bloc_num INTEGER NOT NULL,
    intro_text TEXT NOT NULL,
    outro_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (folder_id, after_bloc_num)
)
```

Cache nécessaire : éviter de re-appeler le LLM si on relance la génération TTS.

### Helper `get_bloc_text(folder_id, bloc_num)` dans `playlist_tts_service`

```python
def get_bloc_text(folder_id, bloc_num):
    """Lit script.json depuis Azure Blob et retourne le texte du bloc demandé."""
    platform_id = _query_platform_id(folder_id)
    blob_path = f"platform-{platform_id}/folder-{folder_id}/playlist/script.json"
    script = json.loads(download_blob(CONTAINER_AUDIOS, blob_path))
    for bloc in script["blocs"]:
        if bloc["bloc_number"] == bloc_num:
            return bloc.get("content", "")
    return ""
```

### Wire-in dans `playlist_tts_service.generate_playlist_for_folder`

Remplacer pour les 4 pauses courtes :
```python
# Avant
final_bytes = _get_recycled_qa_pause(filename)

# Après
intro, outro = generate_pause_transition(folder_id, bloc_num, duration_sec)
final_bytes = _build_pause_audio(intro, outro, duration_sec)
```

`_build_pause_audio` existe déjà dans `playlist_tts_service` mais n'était pas
utilisé en production : on l'active.

## Pourquoi l'implémentation avait été différée

À la date de cette décision (2026-04-30), la priorité absolue est la stabilisation
de la pipeline TTS pour la prod 52 jours :
- Cap budget cascade (fait)
- Calibration empirique 0.90 à valider
- Compteur max anti-boucle auto-pilot (à faire)
- Boot recovery robuste (à faire)

Les transitions dynamiques étaient un *enhancement qualitatif*, pas un *blocker*
prod. Elles ont ensuite été implémentées dans une forme plus large avec
`break_transition_service.py`.

## Bénéfices attendus à l'implémentation

- **Continuité auditive** : plus de rupture mécanique entre cours et pause.
- **Engagement** : les apprenants restent connectés mentalement entre les blocs.
- **Différenciation** : Le Socrate sonne plus comme un vrai prof qu'un système
  automatique générique.
- **Coût marginal acceptable** : ~200 appels LLM/RNCP, amortis sur toutes les promos
  qui consomment ce module.

## Risques identifiés à l'implémentation

- **Latence ajoutée** : 4 appels LLM par dossier × 52 dossiers = 208 appels. À
  paralléliser via GreenPile (~2 concurrent) pour ne pas allonger drastiquement
  la pipeline.
- **Cohérence du ton** : si une pause sonne "robotique" ou hors-ton, ça contrastera
  *plus* avec le cours qu'une pause neutre. Le prompt LLM doit être strict sur le
  ton "vrai prof".
- **Cache invalidation** : si le contenu du bloc N change (re-génération), il faut
  invalider la transition après bloc N et celle après bloc N-1 (qui amorce le bloc N).

## Références code (cible)

- À créer : `backend/services/pause_transition_service.py`
- À modifier : `backend/services/playlist_tts_service.py` (`get_bloc_text` helper +
  branche pause dans `generate_playlist_for_folder`)
- À migrer : `backend/database/db.py` (table `pause_transitions`)

## Leçons / Pour le mémoire

- **Une fonctionnalité "qualitative" peut nécessiter plus d'archi qu'une fonctionnalité
  "fonctionnelle".** Rendre une pause contextuelle implique : nouvelle table DB,
  nouveau service, helper de lecture cross-service, cache invalidation. Le poids
  pédagogique justifie le poids architectural — mais à ne pas sous-estimer en
  estimation de charge.

- **Les contraintes saisonnières (pause_midi) limitent ce qu'on peut contextualiser.**
  Tout ce qui change selon le mode de diffusion ne peut pas être "calé sur le contenu
  qui suit" si ce contenu varie. Conserver le neutre dans ces cas est la seule option
  saine sans dupliquer les fichiers.

- **Différer une feature qualitative pour stabiliser la prod est sain.** La tentation
  est forte d'empiler les améliorations. Discipline : finir la pipeline robuste avant
  d'embellir les transitions.

- **Le cache DB avec invalidation cross-blocs est non-trivial.** Une transition après
  bloc N dépend du contenu **des deux blocs adjacents**. Toute modif d'un bloc invalide
  *deux* transitions. À documenter explicitement à l'implémentation.
