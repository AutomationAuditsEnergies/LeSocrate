# Un RNCP = un module durable (pas un job par promo)

**Date** : 2026-04-17
**Thématique** : architecture — principe structurant
**Statut** : clarification fondamentale

## Contexte

En travaillant sur l'architecture qualité programme (Couche 1 — enrichissement REAC), j'envisageais des optimisations du type "scaler l'enrichissement par nombre de jours" ou "cacher la KB par RNCP pour éviter de re-enrichir à chaque promo". Ces idées présupposaient (à tort) que le pipeline serait relancé pour chaque nouvelle promo.

## Clarification utilisateur

**Le modèle réel du projet** :

1. **1 RNCP = 1 pipeline exécuté UNE SEULE FOIS**
2. Cette exécution crée **1 plateforme Azure** (avec ses containers blob dédiés) — cf. [multi-tenant-plateforme-par-pipeline.md](./multi-tenant-plateforme-par-pipeline.md)
3. Le résultat = **1 module audio complet et durable** avec tous les `cours_folders` jour1 / jour2 / ... jourN correspondant à la durée officielle du titre professionnel
4. Ce module est ensuite **réutilisé tel quel pour toutes les promos** du même TP — sans rejouer la pipeline

**Exemple concret** :
- TP CRCD : durée officielle = X jours. On lance la pipeline UNE fois. On obtient une plateforme "Module CRCD" avec X dossiers de cours audio.
- Promo CRCD Septembre 2026, Promo CRCD Janvier 2027, Promo CRCD Mars 2027 — toutes utilisent **le même module**, pas de régénération.

## Conséquences architecturales

### La durée de formation n'est pas un paramètre de promo

`nb_days` n'est pas un choix "combien de temps pour cette formation" — c'est une **propriété intrinsèque du RNCP** (déterminée par le REAC officiel). Scaler l'enrichissement KB par `nb_days` n'a donc pas de sens à l'échelle promo : `nb_days` est fixe pour un RNCP donné.

### La réutilisation est native, pas à optimiser

Mon idée de "cache KB par RNCP" (option C dans l'audit d'architecture) était redondante avec le modèle natif : la KB existe naturellement une seule fois, attachée à sa plateforme/module, qui est elle-même réutilisée pour toutes les promos.

### Le coût du pipeline est amorti sur toutes les promos

Si un module CRCD sert 10 promos sur 3 ans, le coût de la pipeline (Claude enrichissement + TTS Fish Audio) est divisé par 10. L'économie à optimiser n'est **pas** "faire moins cher par promo" mais "faire une fois pour toutes, proprement".

### Les promos ne polluent pas le module

Chaque promo = un logs utilisateurs distinct dans la table `logs`, mais **pas** de modification du module audio. Le module est en lecture seule après génération.

## Ce que ça change dans les futures couches

### Couche 2 (alerte densité UI)

Sans objet de "scaler par promo". Le ratio de densité est **fixe par RNCP** : on l'affiche au moment de créer la pipeline pour alerter si le REAC est trop pauvre par rapport à la durée officielle. Une fois validé, c'est OK pour toujours.

### Couche 3 (squelette pédagogique)

Même logique : le squelette pédagogique se construit selon `nb_days` intrinsèque du RNCP, une fois pour toutes.

### Couche 4 (RAG Obsidian)

Prend d'autant plus de sens : un corpus externe maintenu par RNCP dans Obsidian → enrichit la pipeline une fois par RNCP → amorti sur toutes les promos.

## Références code

- `backend/routes/formation_routes.py` — `init_formation` crée UNE plateforme par pipeline (déjà aligné avec ce principe)
- `backend/database/db.py` — table `platform_config` : 1 ligne = 1 module durable
- `backend/database/db.py` — table `cours_folders` + `cours_documents` : structure du module audio, lecture seule après génération
- `backend/database/db.py` — table `logs` : sessions utilisateurs distinctes par promo, référençant le même `platform_id`

## Leçons / Pour le mémoire

- **Le bon modèle mental** : pipeline formation = *création d'un produit durable* (un module audio), pas *exécution d'un batch par promo*. Cette distinction change complètement les optimisations qui font sens vs celles qui sont hors sujet.
- **Les propriétés intrinsèques vs paramètres variables** : `nb_days` est intrinsèque au RNCP, pas un paramètre de configuration par job. Un bon design distingue les deux explicitement et évite d'inventer de la flexibilité là où il n'y en a pas.
- **Réutilisation par nature, pas par cache** : quand la réutilisation est native à l'architecture (1 RNCP → 1 module), pas besoin d'une couche cache. Le cache est une optimisation pour récupérer de la réutilisation perdue — si elle est native, rien à récupérer.
- **Demander l'architecture métier avant de proposer** : j'ai failli proposer 2 couches d'optimisation (cache par RNCP, scaling par nb_days) qui n'avaient pas lieu d'être car j'avais mal compris le modèle d'usage réel. À retenir : toujours confirmer le pattern d'utilisation avant de concevoir des optimisations.
