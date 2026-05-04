# Ratio de dilution REAC → formation TTS

**Date** : 2026-04-17
**Thématique** : problème architectural
**Statut** : identifié, résolution en cours (Couche 1)

## Contexte

Le pipeline produit un programme de formation audio à partir d'un REAC. La durée de la formation est paramétrée (N jours × 7h/jour). À 192 mots/min en TTS, on génère ~46 000 mots de contenu parlé par jour (6h audio utile net des pauses).

## Problème / Question

Que se passe-t-il quand on demande une formation de 14 jours à partir d'un REAC de 15 000 mots ?

**Calcul du ratio :**
- Input : REAC ≈ 15 000 mots
- Output : 14 jours × 46 000 mots = **644 000 mots**
- **Ratio de dilution = 43:1** (pour 1 mot REAC, on génère 43 mots de cours)

Au-delà d'un certain ratio, Claude ne peut plus "expliquer" le REAC : il doit **broder, répéter, digresser** pour remplir le temps. Risque pédagogique : perte de densité informationnelle, répétitions non pédagogiques, contenu hors-sujet.

## Diagnostic

L'utilisateur a exprimé cette inquiétude : *"je ne veux pas me retrouver s'il y a par exemple 14 journées de cours avec un programme de formation qui est mal fait au point que [...] on va devoir parler dans le vide."*

C'est la formulation intuitive du problème de dilution. Mesurable, quantifiable.

## Ordres de grandeur

| Nombre de jours | Mots output | Ratio dilution | Risque |
|-----------------|-------------|----------------|--------|
| 2 | 92 000 | 6:1 | Faible |
| 5 | 230 000 | 15:1 | Modéré |
| 7 | 322 000 | 21:1 | Modéré |
| 10 | 460 000 | 30:1 | Élevé |
| 14 | 644 000 | 43:1 | Très élevé |
| 20 | 920 000 | 61:1 | Critique |

Seuil empirique proposé : **au-delà de 20:1**, enrichissement obligatoire.

## Options envisagées

1. **Limiter le nombre de jours** — Contrainte utilisateur, pas acceptable (certains TP font 280h officiellement).
2. **Demander à Claude de broder** (status quo) — Risque qualité confirmé.
3. **Enrichir la matière source avant génération** (retenu — Couche 1) — Passer le REAC de 15k à 120-150k mots exploitables via expansion structurée.
4. **RAG sur corpus externe** (Couche 4 future) — Manuels de formation, articles métier, pour métiers sous-documentés.

## Décision finale

Implémenter la **Couche 1 (enrichissement structuré)** : transformer le REAC en base de connaissances dense avant la génération du programme, pour faire chuter le ratio effectif.

**Effet attendu** : passer d'un REAC 15k → knowledge base 120k → ratio effectif divisé par 8. Une formation 14 jours passe de 43:1 à ~5:1, dans la zone sûre.

Ajouter également l'**alerte densité** (Couche 2) : afficher le ratio dans l'UI avant lancement pour que l'utilisateur arbitre.

## Rationale technique

- **La qualité d'une génération longue est d'abord une question de matière source**, pas de sophistication du modèle. Un prompt parfait sur 15k mots ne peut pas produire 600k mots de qualité constante.
- **L'enrichissement est paramétrable** : plus on demande de profondeur à la Couche 1 (études de cas, pièges, vocabulaire...), plus on baisse le ratio.
- **Pas une solution universelle** : pour certains RNCP très spécialisés, même enrichi, il faudra Couche 4 (RAG externe).

## Références code

- `backend/services/formation_pipeline_service.py:556` — `build_daily_programs` (point d'injection futur KB)
- `backend/services/content_generation_service.py` — 3 passes TTS (consommatrices de matière)
- À créer : `backend/services/knowledge_base_service.py`

## Leçons / Pour le mémoire

- **Quantifier avant d'architecturer** : le ratio 43:1 a transformé un ressenti flou ("le programme sera pas top") en métrique actionable.
- **Le "garbage in, garbage out" a une version moderne** : "sparse in, dilute out". Fournir trop peu de matière à un LLM génératif produit du contenu dilué, même avec le meilleur modèle.
- **Les contraintes de forme externes** (durée fixe, format audio) transforment les besoins en architecture : sans la contrainte TTS 192 mots/min × 6h, ce problème n'existerait pas.
