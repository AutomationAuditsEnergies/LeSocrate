# Slides — JSON maître et stratégie anchor-first

**Date** : 2026-05-25
**Thématique** : décision | slides | pédagogie
**Statut** : actif

## Contexte

La question posée était : comment créer des PowerPoint vraiment alignés avec le
texte produit ?

Deux intuitions existaient :

1. générer le texte, puis analyser ce qui revient le plus souvent ;
2. demander au JSON de décider les moments pédagogiques à visualiser, puis générer
   texte et slides autour de ces moments.

Le besoin final n'est pas seulement de produire des slides jolies. Les slides doivent
accompagner le raisonnement pédagogique.

## Problème / Question

Si les slides sont générées après coup par analyse du texte, elles risquent de
montrer :

- les mots les plus fréquents ;
- les paragraphes les plus longs ;
- les thèmes les plus faciles à résumer.

Mais ce ne sont pas forcément les meilleurs moments à visualiser.

Un exemple court, un piège métier, une checklist ou une comparaison peuvent être
pédagogiquement cruciaux même s'ils n'apparaissent qu'une seule fois dans le script.

## Options envisagées

### Option A — Text mining après génération

Principe : générer tout le texte, puis demander au modèle de repérer les points
dominants.

Avantage :

- simple à ajouter ;
- ne contraint pas la génération du texte.

Limites :

- alignement incertain ;
- risque de slides génériques ;
- difficulté à garantir une diversité de templates ;
- les moments pédagogiques importants mais courts peuvent être oubliés.

### Option B — Forcer le texte à produire des zones prédéfinies

Principe : imposer dans chaque chapitre des zones comme exemple, conseil, piège,
checklist, etc.

Avantage :

- slides plus faciles à mapper ;
- structure très contrôlée.

Limites :

- risque de rigidifier le cours ;
- tous les thèmes ne nécessitent pas les mêmes moments ;
- la narration peut devenir mécanique.

### Option C — JSON maître avec `teaching_beats` et `slide_anchor`

Principe : pendant la planification, le JSON choisit les moments pédagogiques à
visualiser parmi un catalogue de possibilités. Ensuite :

- le texte couvre ces moments naturellement ;
- les slides sont générées depuis les anchors validés ;
- le formateur ne parle jamais de template ou de slide.

Décision retenue : option C.

## Décision finale

Le JSON devient maître des moments visualisables.

Il peut prévoir des `teaching_beats` de types variés :

- définition ;
- exemple ;
- conseil ;
- piège ;
- checklist ;
- comparaison ;
- schéma en étapes ;
- méthode ;
- histoire courte ;
- cas pratique ;
- synthèse.

Chaque beat peut être associé à un `slide_anchor` :

- type de template ;
- intention pédagogique ;
- niveau de priorité ;
- contenu attendu ;
- moment du cours.

## Rationale technique

Cette stratégie évite deux extrêmes :

- ne rien contrôler et produire les slides après coup ;
- tout rigidifier avec des zones obligatoires identiques partout.

Le plan décide, mais il décide intelligemment selon le contenu du chapitre. Le texte
reste naturel, et les slides restent alignées.

Le catalogue de templates devient un outil pédagogique, pas seulement graphique.

## Règles importantes

- Le texte doit couvrir les teaching beats.
- Le texte ne doit jamais nommer les beats, anchors, templates ou slides.
- Une slide doit correspondre à une intention pédagogique claire.
- Tous les chapitres n'ont pas besoin du même nombre de slides.
- Le modèle doit choisir le bon type de visualisation selon le thème.
- L'analyse du texte final peut servir de vérification, pas de moteur principal.

## Références code

- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/slides/README.md`
- `backend/prompts/slides/template-catalog.json`
- `backend/services/script_slide_generation_service.py`
- `backend/services/content_pipeline/validators.py`
- `frontend/src/pages/FormationPipeline.jsx`
- Commit lié :
  - `822b9e8` — Expose full content pipeline roadmap

## Leçons / Pour le mémoire

Les slides IA ne doivent pas être pensées comme un résumé automatique. Elles doivent
être pensées comme une couche visuelle d'une intention pédagogique déjà planifiée.

Le JSON maître devient donc l'outil d'orchestration entre texte, pédagogie, contrôle
qualité et support visuel.
