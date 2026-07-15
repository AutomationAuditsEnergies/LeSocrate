# Audit chronométré du pipeline de formation

**Date :** 15 juillet 2026

**Révision auditée :** `391321f` (`staging`)

**Périmètre :** pipeline texte, slides, fiabilité d'exécution et cycle de vie des professeurs IA.

**Méthode :** lecture du code et mesures en lecture seule sur PostgreSQL de `Formation3`. Aucun contenu utilisateur, secret ou mot de passe n'a été extrait.

## Conclusion exécutive

Le pipeline PostgreSQL durable est techniquement solide et un run récent utile termine le texte et les slides en **54 min 47 s**. Son principal poste de temps est la génération de contenu, surtout le calibrage de volume. Cependant, le parcours centre actuellement visible ne bénéficie pas encore de cette architecture :

- l'interface centre `thankful-wave-043aa3b03.4.azurestaticapps.net` est compilée avec `VITE_API_URL` vers **`socrate1`** ;
- `socrate1` est encore configuré en `hybrid`, avec une exécution pipeline `inline` implicite et un seul worker journée ;
- l'architecture mesurée et durable est configurée sur **`Formation3`** en PostgreSQL pur, file PostgreSQL, worker embarqué, leases et fencing.

**Décision recommandée avant toute optimisation :** désigner un backend PostgreSQL unique pour le SaaS centre, y faire pointer le frontend, puis verrouiller cette configuration dans le workflow de `staging`. Accélérer `Formation3` sans corriger ce routage n'accélérerait pas le vrai parcours utilisateur.

## 1. Cartographie du pipeline

La machine d'état choisit une seule prochaine étape à partir des données persistées. En mode file, chaque tick exécute une étape, journalise sa durée, puis crée atomiquement le tick suivant.

| Ordre | Étape technique | Résultat attendu | Durée run #13 | Part des étapes |
|---:|---|---|---:|---:|
| 1 | `reac` | Référentiel RNCP chargé | 6 s | 0,2 % |
| 2 | `kb` | Base de connaissances construite | 10 min 47 s | 19,8 % |
| 3 | `global` | Programme global produit | 1 min 38 s | 3,0 % |
| 4 | `daily` | Journées détaillées produites | 1 min 9 s | 2,1 % |
| 5 | `content` | Textes structurés générés et calibrés | 29 min 36 s | 54,2 % |
| 6 | `review` | Conformité locale des segments validée | 6 min 13 s | 11,4 % |
| 7 | `post_review_docs` | Document final réassemblé | 2 s | 0,1 % |
| 8 | `slides` | Slides ancrées sur le script | 5 min 5 s | 9,3 % |
| 9 | `audio` | Audio produit si demandé explicitement | non exécutée | — |

Sans audio automatique, la sortie normale est `text_ready`. L'audio doit ensuite être généré à la demande ou par la future planification J-1.

## 2. Mesures de référence

### Run récent complet

Le job #13, d'une journée de formation, fournit la référence la plus propre :

- première tentative jusqu'à la fin : **77 min 11 s** ;
- quatre échecs REAC ont consommé environ 22 minutes avant reprise ;
- reprise réussie jusqu'à `text_ready` : **54 min 47 s** ;
- somme des étapes chronométrées : **54 min 36 s** ;
- attente cumulée de file : négligeable, environ 0,04 à 0,06 s par tick.

La file PostgreSQL n'est donc pas le goulot d'étranglement. Le temps est consommé dans les traitements métier et les appels modèles.

### Détail de la génération de contenu

| Phase interne du job #13 | Durée | Part de `content` |
|---|---:|---:|
| Calibrage du budget de mots | 14 min 40 s | 49,6 % |
| Contrôle d'adhérence au plan | 5 min 18 s | 17,9 % |
| Génération des sections | 5 min 3 s | 17,1 % |
| Construction du plan JSON | 2 min 48 s | 9,5 % |
| Micro-revue éthique | 47 s | 2,6 % |
| Ouvertures tardives | 38 s | 2,1 % |
| Conclusions et résumés | 16 s | 0,9 % |
| Assemblage et persistance | 2 s | 0,1 % |

Le premier candidat d'optimisation est clairement le **calibrage du budget**, suivi de l'adhérence au plan. Toute modification devra conserver exactement les garde-fous de volume, de conformité et de synchronisation des slides.

### Échantillon historique indicatif

Les mesures disponibles sur plusieurs runs donnent les ordres de grandeur suivants. Les échantillons sont petits et les anciennes exécutions comportent des interruptions ; ils ne constituent pas encore un benchmark statistique stable.

| Étape | Médiane observée | P95 indicatif | Échantillon |
|---|---:|---:|---:|
| `content` | 41 min 9 s | 1 h 13 min 38 s | 6 |
| `kb` | 11 min 53 s | 18 min 28 s | 10 |
| `daily` | 1 min 15 s | 19 min 7 s | 11 |
| `slides` | 2 min 15 s | 4 min 28 s | 6 |
| `global` | 1 min 38 s | 4 min 51 s | 11 |

La revue globale est volontairement exclue de ce tableau : un ancien défaut de boucle a pollué sa télémétrie.

## 3. Ce qui est déjà robuste

- PostgreSQL est la source de vérité des jobs, contenus, événements, slides et états sur `Formation3`.
- La file persistante utilise déduplication, unicité des travaux actifs, leases, heartbeat et fencing.
- Chaque étape est redéterminée depuis l'état persistant : un tick obsolète est ignoré puis réconcilié.
- Les reprises utilisent une temporisation croissante avec jitter ; `Formation3` borne chaque travail à cinq tentatives avant dead-letter.
- Les artefacts principaux sont stockés dans Azure Blob avec écritures idempotentes et tentatives bornées.
- Les temps d'étapes et les erreurs sont journalisés sans pouvoir faire échouer un traitement terminé.
- La concurrence du contenu est bornée par configuration ; elle n'est pas laissée sans limite.

## 4. Risques et corrections prioritaires

### P0 — Le vrai frontend centre n'utilise pas le backend durable audité

Le workflow du frontend `staging` cible `socrate1`, alors que la configuration durable PostgreSQL est portée par le workflow `Formation3`, déclenché sur une autre branche. En production actuelle, les deux chemins peuvent donc produire des comportements et des performances différents.

**Correction proposée :** choisir l'autorité SaaS, vérifier la propriété des comptes et données, puis soit faire pointer le frontend vers `Formation3`, soit porter la configuration PostgreSQL durable complète dans `socrate1`. Le choix doit être unique et couvert par un test de déploiement.

### P1 — Le cycle de vie produit n'a pas encore de modèle autoritaire

Les modules utilisent principalement `draft` et `validated`; `archived` est filtré mais n'est pas alimenté automatiquement. Les notions produit « en préparation », « actif », « terminé » et « ancien professeur réutilisable » ne sont pas représentées par une seule machine d'état fiable.

**Modèle cible proposé :**

```text
preparing -> ready -> active -> completed -> archived
     |
     +-> failed -> preparing (reprise)
```

- `preparing` : pipeline texte/slides en cours ;
- `ready` : professeur prêt, planning modifiable selon la règle J-2/J-3 ;
- `active` : formation dans sa période de diffusion ;
- `completed` : dernière séance passée ;
- `archived` : visible dans « Réutiliser un ancien professeur IA » ;
- `failed` : préparation interrompue, relançable sans doublon.

Le paiement (`payment_pending`, `paid`, remboursement) doit rester dans un état de commande séparé, puis autoriser la transition vers `preparing`.

### P1 — Une ancienne boucle de revue a saturé l'observabilité

Deux anciens jobs ont produit **427 920 événements** de démarrage/fin de revue, soit environ **99,6 %** des 429 595 événements présents. La table et ses index occupent environ **100 Mo**. Les jobs récents ne reproduisent plus cette boucle, mais aucune politique de rétention ne protège encore la base.

**Correction proposée :** ajouter un invariant empêchant de recommencer une étape déjà validée sans changement d'état, un identifiant de tentative exploitable, une alerte de cardinalité et une politique de rétention/archivage des événements.

### P1 — Les échecs REAC peuvent encore nécessiter une intervention

Le run #13 a épuisé quatre tentatives REAC avant une reprise manuelle. La file et ses délais fonctionnent, mais le défaut externe ou de parsing à l'origine de ces échecs reste un risque d'exploitation.

**Correction proposée :** classifier les erreurs REAC, conserver un diagnostic sans donnée sensible, rendre les erreurs transitoires relançables et les erreurs permanentes immédiatement explicites dans l'interface.

### P2 — La concurrence doit être mesurée, pas simplement augmentée

`Formation3` autorise trois journées en parallèle et sept cours structurés par journée, soit jusqu'à 21 appels imbriqués dans certaines phases. Augmenter encore ces valeurs peut provoquer quotas, ralentissements et reprises coûteuses.

**Correction proposée :** mesurer latence, taux 429 et débit par modèle, puis appliquer un budget global de concurrence partagé. Les slides disposent déjà de parallélisme ; leur priorité est la stabilité, pas une hausse aveugle des workers.

### P2 — L'audio ne dispose pas encore d'un benchmark fiable

L'historique contient un succès audio et 21 erreurs regroupées sur un même ancien job. Cet échantillon ne permet pas de promettre une durée ni de dimensionner proprement la génération J-1.

**Correction proposée :** instrumenter séparément synthèse, stockage, assemblage et retry, puis lancer un benchmark représentatif avant d'activer la planification automatique.

## 5. Plan d'amélioration sans perte de qualité

1. **Unifier le backend de l'espace centre.** Même base, même file durable, même worker et même workflow de déploiement pour le parcours réellement utilisé.
2. **Implémenter la machine d'état professeur IA.** Transitions transactionnelles, historique, reprise idempotente, règles d'accès par centre et tests de chaque transition.
3. **Assainir l'observabilité.** Tentatives explicites, seuils d'alerte, invariant anti-boucle, rétention et tableau de bord de durée par étape.
4. **Optimiser le calibrage de volume.** Instrumenter chaque passe, éviter les analyses répétées, arrêter dès que la cible est atteinte et paralléliser uniquement les unités réellement indépendantes.
5. **Mettre en cache la KB RNCP.** Clé comprenant RNCP, empreinte REAC, version de prompt et modèle ; réutilisation sûre entre professeurs partageant le même référentiel.
6. **Auditer et fiabiliser l'audio J-1.** File durable, déduplication par journée/version, observabilité et reprise après redémarrage.
7. **Ajouter un benchmark de non-régression.** Même entrée et même configuration avant/après, avec critères qualité bloquants.

## 6. Critères obligatoires avant d'accepter un gain de vitesse

Une optimisation ne sera validée que si elle respecte simultanément :

- budget de mots et durée cible sans régression ;
- couverture du plan et ordre pédagogique conservés ;
- contrôles éthiques et de conformité au moins équivalents ;
- ancres et synchronisation slides/script au moins équivalentes ;
- aucun doublon après retry, redémarrage ou double clic ;
- reprise automatique depuis chaque frontière d'étape ;
- baisse mesurée de la médiane et du P95 sur plusieurs runs représentatifs ;
- absence de hausse des erreurs fournisseur et des dead-letters.

## Prochaine tâche recommandée

Traiter **P0** en premier : établir l'autorité de données entre `socrate1` et `Formation3`, puis faire exécuter le parcours centre sur la pile PostgreSQL durable. Ce chantier doit être validé avant modification, car il touche le routage de production et la base contenant les comptes centres.
