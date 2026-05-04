# Coupure du MP3 cours en pleine phrase

**Date** : 2026-04-30
**Thématique** : problème
**Statut** : résolu (cf. solution `decoupage-blocs-cap-budget-cascade.md`)

---

## Contexte

La pipeline formation produit, pour chaque journée de cours, **7 blocs MP3** de durées
fixes (45 min / 45 min / 55 min / 45 min / 60 min / 60 min / 50 min). Le texte source
généré par le LLM (~60 000 mots/jour) est découpé en 7 morceaux proportionnels à ces
durées, puis chaque morceau est envoyé à Fish Audio S2-Pro pour synthèse.

L'enchaînement final dans la playlist horodatée est :
`cours_blocN.mp3 → qa_N.mp3 → pause_N.mp3 → cours_blocN+1.mp3`

Chaque MP3 est un fichier indépendant. La continuité pédagogique entre blocs repose
donc entièrement sur la propreté des fins de bloc côté audio, et sur la qualité des
transitions côté pauses.

## Problème

### Symptôme

Avec la calibration historique (Fish Audio à `speed=0.95`, marge de sécurité 30s sur
chaque bloc), un risque résiduel persistait : si le TTS générait l'audio plus lentement
que les 192 mots/min calibrés, le fichier dépassait la durée cible et le code de
post-traitement (`_pad_audio_to_duration`) **tronquait l'audio en pleine phrase**.

Concrètement, l'apprenant entendait : *"...et donc la méthode ABC per-"* puis silence
brutal, puis l'intro de pause statique : *"Vous avez maintenant quelques minutes de
pause."* — discontinuité auditive perceptible, perte de l'idée en cours.

### Cause racine — trois couches

**1. Calibration TTS approximative.** Les 192 mots/min étaient une moyenne empirique
sur un corpus restreint. La vitesse réelle de synthèse varie selon le passage : un
texte avec beaucoup de tags `[Slow]` Fish Audio, des termes techniques longs, ou des
ponctuations denses peut générer plus de secondes par mot que la moyenne.

**2. Marge de 30s insuffisante pour 192 wpm.** 30s à 192 wpm = ~96 mots de buffer.
Sur un bloc de 8 500 mots, c'est ~1.1% de marge. Une dérive TTS de 5% sur un passage
suffit à dépasser le buffer.

**3. Découpage du texte aveugle au budget.** La fonction `_choose_natural_boundary`
cherchait la fin de paragraphe la plus proche de la cible mots, dans une fenêtre
**symétrique** (`cible ± 700 mots`). Si la fin de paragraphe la plus proche se trouvait
700 mots **au-dessus** de la cible, le bloc finissait au-dessus du budget audio
estimé — et le pré-check Fish Audio ajouté plus tard rejetait le bloc.

### Pourquoi le problème explose à 52 jours

La pipeline auto-pilot doit produire une formation complète sur ~52 jours de cours,
soit **52 × 7 = 364 blocs**. Si UN seul bloc dépasse son budget et déclenche le
pré-check, la pipeline auto-pilot s'arrête en `auto_pilot_error`. Sans intervention
manuelle, la production reste bloquée.

Pour une probabilité d'échec par bloc de seulement 1%, la probabilité que **toute la
pipeline 52 jours réussisse** est `(1 - 0.01)^364 ≈ 2.6%`. Inacceptable.

## Options envisagées

### Option A — Réduire `speed` Fish Audio (palliatif)

Passer de `0.95` à `0.90` augmente la durée audio par mot de ~5%, donc plus de marge.
**Adopté** comme correction préliminaire (cf. CHANGELOG 2026-04-30, défaut
`FORMATION_TTS_SPEED=0.90`). Mais c'est un palliatif : ça déplace le problème, ça ne
le résout pas. Si un bloc continue à dépasser, on retombe sur la coupure mid-phrase.

### Option B — Speedup local x1.12 du MP3 (rejeté)

Première intuition : si l'audio est trop long, l'accélérer localement avec
`pydub.effects.speedup` jusqu'à x1.12 sans nouvel appel Fish Audio. Implémenté puis
**désactivé par défaut** (`FORMATION_TTS_LOCAL_MAX_SPEEDUP=1.0`) car :
- pydub change la pitch (voix plus aiguë et "Mickey Mouse")
- À x1.12 c'est subtil mais perceptible, et sur 52 jours × 7 blocs, l'effet cumulé serait pénible
- Cassait le ton "vrai prof" que les prompts cherchent à préserver

### Option C — Pré-check avant TTS (adopté pour partie)

`_synthesize_course_audio_to_fit` calcule un budget mots prudent
(`_estimated_words_budget_for_course`) et **refuse l'appel Fish Audio** si le bloc
dépasse. Économise les coûts TTS inutiles. Mais ne résout pas le problème : le bloc
échoue tout de même, l'auto-pilot s'arrête.

### Option D — LLM raccourcit le bloc en débord (rejeté)

Si un bloc dépasse, envoyer le texte au LLM avec consigne *"réduis de 20% en gardant
les idées importantes"*. Rejeté pour quatre raisons :
- **Coût** : un appel LLM par bloc en débord, sur potentiellement plusieurs blocs/jour.
- **Risque sur le contenu** : le LLM peut couper une notion clé en la jugeant secondaire.
- **Non-déterminisme** : deux retries peuvent produire des versions différentes.
- **Complexité** : ajoute une boucle de correction réactive, plus de cas d'erreur à gérer.

### Option E — Cascade des paragraphes en surplus vers le bloc suivant (retenu)

Au lieu de raccourcir le texte d'un bloc qui déborde, **déplacer les derniers
paragraphes complets vers le bloc suivant**. Le bloc N finit naturellement sur une fin
d'idée (en-deçà du budget), et le bloc N+1 hérite du surplus, qui à son tour cascade
si nécessaire.

Cette approche est :
- **Gratuite** : aucun appel LLM additionnel.
- **Déterministe** : algorithme pur sur les positions de mots et paragraphes.
- **Préserve verbatim** les unités d'idée pédagogiques (les paragraphes ne sont pas
  réécrits, juste re-attribués).
- **Naturelle** : exploite le fait que le texte est déjà découpé en paragraphes par
  le LLM (séparateurs `\n\n`), donc les unités d'idée existent gratuitement.

## Décision

Implémenter l'option E (cascade paragraphes), avec un cap budget calculé par bloc
intégré directement à `_choose_natural_boundary`. Détails dans
`memoire/04-solutions/decoupage-blocs-cap-budget-cascade.md`.

## Leçons / Pour le mémoire

- **Une calibration empirique d'un modèle externe (TTS) est toujours fragile.** On ne
  contrôle pas la vitesse réelle de synthèse. Il faut concevoir le système comme s'il
  pouvait dériver de ±10% à tout moment, pas seulement de ±1%.

- **Les fenêtres symétriques sont dangereuses quand l'écart en surplus a un coût
  asymétrique.** Ici, dépasser de 700 mots casse la pipeline ; rester 700 mots
  en-dessous ne casse rien. La fenêtre devait être **asymétrique** (ou avec un hard cap
  côté débord).

- **Une approche déterministe simple bat souvent une approche LLM réactive.** L'instinct
  était d'invoquer le LLM pour "réparer" le bloc trop long. Le vrai fix tenait en 30
  lignes d'algorithme déterministe sur les frontières de paragraphes.

- **Le cascade naturel est sous-utilisé en pratique.** Quand on découpe une séquence
  ordonnée en N segments avec contraintes par segment, faire cascader le surplus est
  presque toujours plus robuste que d'essayer d'optimiser chaque segment isolément.

- **Sur une pipeline à N étapes, la robustesse multiplie.** À 1% d'échec/étape sur 364
  étapes, le succès end-to-end est de 2.6%. Toute correction qui passe l'échec/étape de
  1% à 0.1% transforme le succès end-to-end de 2.6% à 70%. La marge entre "bug rare" et
  "production qui marche" est exponentielle.

## Références code

- `backend/services/content_generation_service.py` :
  - `_choose_natural_boundary` (paramètre `word_budget_max`)
  - `_build_course_blocs_from_segments` (calcul du budget par bloc, log enrichi)
  - `_synthesize_course_audio_to_fit` (pré-check, plus de speedup local par défaut)
  - `_estimated_words_budget_for_course` (budget mots prudent par durée)
- CHANGELOG 2026-04-30 : entrée *"fix: découpage TTS — cap budget par bloc, cascade
  des paragraphes en surplus"*
