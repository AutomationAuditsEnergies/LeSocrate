# Feuille de route Cadrenza — version consolidée

Ce document remplace la version précédente (qui comparait encore plusieurs scénarios). **La décision est prise et confirmée par Mehdi Rousselle** : travail exclusif sur Cadrenza (branche `codex/current-saas-postgres-20260705`, plateforme P3). `staging`/P1/P2/P4 ("Le Socrate", usage interne quotidien) ne sont plus touchés. Ce document consolide toutes les découvertes et décisions prises depuis, jusqu'au 24/09/2026.

---

## Décisions actées (ne plus rediscuter)

| Sujet | Décision |
|---|---|
| Périmètre de travail | Exclusivement Cadrenza / P3 / `codex/current-saas-postgres-20260705` |
| P1, P2, P4 / staging | Ne pas toucher, laissés tels quels sur le même repo |
| Hébergement à court terme | Azure (le nouveau repo aussi, pour l'instant) |
| Migration VPS | Préparée séparément, plus tard, sans bloquer Cadrenza |
| Nouveau repo GitHub | Oui — démarre avec l'**historique Git complet** (pas tronqué) |
| Base de données | Postgres (confirmé, jamais SQLite en prod sur Cadrenza) |
| Sécurité | Corrections uniquement sur Cadrenza/P3, aucune intervention sur les autres plateformes |
| Workers Container Apps (IA/audio) | **Confirmé fonctionnels en production** — rien à faire |
| Nom de modèle DeepSeek | Déprioritisé — le modèle actuel fonctionne, à revoir plus tard (sujet microservice LLM) |
| Item 6 (auto-démarrage appareils) | Reporté par décision de Mehdi, hors périmètre actuel |
| Clonage de visage (item 8) | Nécessite validation juridique préalable avant tout développement |

---

## Découverte majeure qui change la priorité : plusieurs centres clients simultanés

Confirmé par l'utilisateur : le modèle commercial implique **plusieurs centres de formation clients en même temps**, chacun avec ses propres étudiants invités. Conséquence directe : l'isolation des données entre centres (aujourd'hui garantie uniquement par le code applicatif, sans filet au niveau base de données) devient **bloquante pour la Phase 2**, pas différable.

Bonne nouvelle en creusant : le mécanisme d'invitation étudiant lui-même est déjà bien conçu et correctement isolé par centre (vérifié dans `backend/routes/auth_routes.py` et `backend/utils/auth_tokens.py`). Le risque réel porte sur les centaines d'autres routes qui n'ont pas ce niveau de vérification systématique.

## Vérifié et résolu (24/09/2026) : la prod tourne bien sur Postgres

Doute levé : `DATABASE_BACKEND=postgres` est bien positionné manuellement sur l'App Service Formation3 (vérifié directement dans le portail Azure). La production n'a jamais tourné sur SQLite par défaut. **Décision prise** : ne pas entreprendre de retrait complet du code SQLite/hybride (25+ fichiers, dont un fichier central à 107 occurrences) — trop risqué pour le peu de bénéfice immédiat. On garde la structure actuelle et on corrige au fil de l'eau si un bug lié à ça apparaît. Aucune action de ce type dans le planning.

## Découverte du mémoire de Nassim ISSAD (`m_moire_de_fin_d_ann_e.md`) : le RAG est peut-être non branché

Ce document (mémoire de fin d'études EFREI, source de première main sur la conception du projet) révèle que le système de questions-réponses des élèves (RAG hybride, une des **deux fonctions centrales du produit** selon sa propre description) tourne sur Azure OpenAI + Azure Search. Or ces variables sont absentes de la configuration de déploiement actuelle de Cadrenza (`staging_formation3.yml`). **À vérifier en priorité en Phase 2** : ce n'est peut-être pas du code mort, mais une fonctionnalité centrale pas encore branchée sur le produit commercial.

---

## Planning en 4 phases (mis à jour)

### Phase 1 — Sécurité et remise en ordre (Cadrenza/P3 uniquement)
*Estimation : 1 à 1,5 semaine*

- Porter le correctif watchdog Edge TTS (bug de blocage confirmé sur la synthèse vocale)
- Ajouter une limitation de débit sur les pages de connexion/inscription
- Centraliser la gestion des erreurs (ne plus exposer de détails techniques aux utilisateurs)
- Corriger l'incohérence de nom de marque (`VITE_FORMATION_NAME` = "Le Socrate" au lieu de "Cadrenza")
- Préparer techniquement l'extraction vers le nouveau repo (historique complet conservé)
- Formaliser par écrit la cartographie branches / plateformes / ressources Azure

### Phase 2 — MVP commercialisable
*Estimation : 5 à 7 semaines*

- **Vérifier en premier si le RAG/chat élève fonctionne réellement sur Cadrenza** (cf. découverte ci-dessus) — si non, c'est un développement à part entière, pas une vérification de 5 minutes
- Audit systématique de l'isolation entre centres clients + tests automatisés d'accès croisé sur les routes sensibles (bloquant, cf. découverte ci-dessus)
- Tests réels : plusieurs générations de formations complètes avec configurations variées
- Connexion du vrai compte Stripe (délai partiellement hors de contrôle, dépend de la vérification côté Stripe)
- Tableau de bord coûts API / revenus, première version
- Réservation du nom de domaine

### Phase 3 — Mise en production et premiers clients
*Estimation : 1 à 2 semaines de préparation, puis suivi continu*

- Déploiement du nouveau repo (sur Azure)
- Accompagnement des premiers centres clients
- Suivi des coûts API réels vs facturation

### Phase 4 — Industrialisation
*Non bloquant pour la vente, au fil de l'eau*

- Renforcement de l'isolation entre centres au niveau base de données (vraies policies RLS, en couche supplémentaire)
- Modèle d'abonnement récurrent (aujourd'hui : paiement à l'acte)
- Upload de programme personnalisé par le client (au lieu du numéro RNCP)
- Migration VPS
- Personnalisation du PPT par le client (les 12 templates de slides existent déjà, personnalisation à définir — couleurs/logo simple vs réorganisation complète change le chiffrage)
- Pistes d'évolution notées par Nassim : réponses orales en direct, RAG conversationnel avec historique, suivi individualisé des élèves
- Sujets reportés comme convenu : démarrage automatique sur les appareils clients, clonage de visage (validation juridique préalable requise)

**Estimation totale pour une première version commercialisable (Phases 1+2) : 6 à 9 semaines**, avec une incertitude à la hausse si le RAG doit être développé plutôt que simplement reconnecté.

---

## Ce qui reste à demander à Mehdi

1. Accès direct en lecture à Azure (CLI ou portail), comme il l'a lui-même suggéré.
2. Confirmation sur l'état réel du RAG en prod (a-t-il été testé avec de vrais élèves depuis la rédaction du mémoire de Nassim ?).
