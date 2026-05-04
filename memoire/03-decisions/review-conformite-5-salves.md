# Décision : révision de conformité en 5 salves thématiques (anti-dilution attention)

**Date** : 2026-04-30
**Statut** : appliqué
**Fichiers impactés** : `backend/services/content_generation_service.py`, `backend/services/claude_code_mission_service.py`

---

## Contexte

Après la génération du contenu (~60 000 mots/jour, 18 segments par journée),
chaque segment doit passer par une **révision de conformité** sur 27 règles couvrant
l'éthique culturelle, l'éthique commerciale, le légal, l'anti-hallucination et le
style oral TTS.

Le code initial faisait **un seul appel API** par segment, en passant les 27 règles
en une fois au LLM (Claude Sonnet via API ou DeepSeek-v4-pro). La sortie attendue était
une liste JSON de patches `[{rule_number, original, patched, reason}, ...]` à appliquer
au texte.

## Problème

### Dilution d'attention sur les règles

Quand on passe 27 règles en un seul prompt, le LLM en oublie systématiquement
plusieurs. Observation empirique sur ~50 segments traités en mode test :
- Règles #9 (humour), #10 (cohérence), #14 (respect des tiers) : **jamais** détectées
- Règles #21–#27 (style oral) : sporadiquement appliquées
- Règles #1–#5 (les premières du prompt) : appliquées le plus souvent

Le pattern correspond exactement à la **dilution d'attention** documentée dans la
littérature LLM : sur un input long, les premiers éléments sont sur-pondérés
(*primacy effect*), les derniers parfois aussi (*recency effect*), mais le milieu
reçoit moins d'attention.

27 règles = trop pour qu'aucune ne soit "noyée".

### Pourquoi c'est critique pour Le Socrate

Les règles oubliées ne sont pas mineures :
- #9 (humour proscrit) → blagues de mauvais goût qui passent en prod
- #10 (cohérence interne) → contradictions logiques entre passages d'un même cours
- #14 (respect des tiers) → mention nominale d'entreprises concurrentes
- #21–#27 → ponctuation TTS cassée (guillemets directs, parenthèses lues à l'oral)

Sur 52 jours × 18 segments × ~5 000 mots, un taux d'oubli de 30 % par règle critique
= des centaines de violations non corrigées en prod.

## Options envisagées

### Option A — Augmenter `max_tokens` du prompt (rejeté)

Aucun effet : le problème n'est pas le budget de sortie, c'est l'attention sur l'input.
Le LLM a la place pour répondre correctement, il *décide* d'ignorer certaines règles.

### Option B — Numérotation explicite + récap final (testé, insuffisant)

Ajouter en fin de prompt *"Liste explicitement les 27 règles que tu as vérifiées"*.
Le LLM répond bien, mais soit il ment (dit avoir vérifié sans avoir détecté), soit
il liste 5–6 règles puis abandonne. Symptomatique de la dilution.

### Option C — 5 salves thématiques (retenu)

Découper les 27 règles en **5 groupes sémantiquement cohérents** et faire **5 appels
API séquentiels** par segment. Chaque appel ne traite qu'un focus.

| Groupe | Règles | Thème |
|---|---|---|
| Éthique culturelle | #1, #2, #3, #9, #14 | Spirituel, alcool/musique, humour, respect des tiers |
| Éthique commerciale | #4, #5, #6, #7, #8 | Manipulation, closing, flirt, chance, célébrités |
| Légal et intégrité | #10, #11, #12, #13, #15, #16 | Cohérence, discrimination, RGPD, promesses irréalistes |
| Anti-hallucination | #17, #18, #19, #20 | Exemples fictifs, chiffres non sourcés, prudence |
| Style oral TTS | #21–#27 | Fusion syntaxique, guillemets, posture, oral |

Le découpage est **sémantique**, pas arithmétique : les règles d'un groupe se
renforcent mutuellement (par ex. #4-#8 sont toutes des dérives commerciales). Le LLM
peut "rester en tête" sur une thématique pendant tout l'appel.

## Décision finale

Option C retenue. Implémentée via :

- `_REVIEW_RULE_GROUPS` : constante partagée entre `content_generation_service.py` et
  `claude_code_mission_service.py` (cohérence API/CC).
- `_extract_rules_for_group(full_rules_text, rule_numbers)` : extrait les règles
  demandées du prompt complet via regex sur les en-têtes `RÈGLE #\d+`.
- `_build_review_prompt_focused(...)` : prompt focalisé qui annonce explicitement le
  scope au LLM (*"Tu n'audites QUE ces règles, ignore les autres."*).
- Les patches s'**accumulent** sur `current_text` : la salve N voit le résultat
  patché de la salve N-1. Permet à une salve "style" de ne pas réintroduire un
  problème "éthique" déjà corrigé.
- Marqueur `reviewed=1` posé seulement si **les 5 salves réussissent**. Une seule
  salve en erreur ⇒ `review_error`, segment non marqué reviewed.

## Trade-offs

### Coût × 5

5 appels API au lieu d'1. Sur 52 jours × 18 segments = 936 segments × 5 = 4 680 appels
de révision au lieu de 936. Coût absorbé par le fait que la pipeline est exécutée
**une seule fois par RNCP** (cf. `01-architecture/un-rncp-un-module-durable.md`) : le
coût est amorti sur toutes les promos.

### Latence × 5

5 appels séquentiels par segment ⇒ ~3-5 minutes par segment au lieu de ~1 min. Sur
52 jours, c'est plusieurs heures de plus. Acceptable car la pipeline tourne en
auto-pilot, pas en interaction utilisateur.

### Risque sur les patches

Les patches s'appliquent par recherche verbatim de `original` → `patched`. Si une
salve modifie un passage que la salve suivante voulait modifier, la deuxième
recherche échoue (texte original introuvable). Atténué par :
- Anchoring strict (`original` doit apparaître **exactement une fois**)
- Salves ordonnées : éthique avant style, donc les corrections substantielles
  d'abord, les corrections cosmétiques ensuite

## Leçons / Pour le mémoire

- **La dilution d'attention LLM est réelle, mesurable, et combat-able par découpage
  sémantique.** Pas besoin de doubler la taille du modèle ni de raffiner le prompt :
  passer de 27 → 5×6 règles change radicalement la détection.

- **Les groupes doivent être sémantiquement cohérents, pas arithmétiquement égaux.**
  L'ergonomie cognitive du LLM (et humaine) bénéficie d'une catégorisation par thème.

- **L'accumulation de patches inter-salves crée une dépendance d'ordre.** Documenter
  l'ordre des salves est aussi important que documenter la liste. Ici : éthique →
  intégrité → hallucination → style. L'éthique d'abord parce que c'est le plus
  invasif.

- **Le marqueur `reviewed=1` doit être atomique.** Si 4 salves sur 5 réussissent,
  poser `reviewed=1` masquerait l'échec partiel. Le tout-ou-rien est plus honnête,
  même au prix de re-faire 4 salves au prochain run.

## Références code

- `backend/services/content_generation_service.py` :
  - `_REVIEW_RULE_GROUPS` (constante, ~ligne 1223)
  - `_extract_rules_for_group`, `_build_review_prompt_focused`
  - `run_content_review` (boucle externe sur les 5 groupes)
- `backend/services/claude_code_mission_service.py` : même `_REVIEW_RULE_GROUPS`
  partagée (mode Claude Code local)
- CHANGELOG 2026-04-30 : *"feat: révision conformité en 5 salves ciblées
  (anti-dilution attention)"*
