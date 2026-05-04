# RC et ROME indisponibles pour RNCP 35304

**Date** : 2026-04-17
**Thématique** : problème rencontré
**Statut** : résolu (par abandon)

## Contexte

Le pipeline formation tentait de télécharger 3 sources en parallèle depuis internet :
- **REAC** (Référentiel Emploi Activités Compétences) — PDF officiel France Compétences
- **RC** (Référentiel de Certification) — PDF complémentaire, critères d'évaluation
- **ROME** (Répertoire Opérationnel des Métiers) — fiches métier France Travail

Ces 3 sources alimentaient ensuite Claude pour générer le programme de formation.

## Problème / Question

Sur le cas test RNCP 35304 (TP Conseiller Relation Client à Distance), seul le REAC s'est téléchargé correctement (95 509 caractères). RC et ROME sont restés vides, affichés en gris dans l'UI comme s'il y avait un bug.

## Diagnostic (via logs backend)

```
2026-04-17 09:48:47 - download_rc_text - WARNING - ⚠️ RC introuvable pour RNCP 35304
2026-04-17 09:48:47 - _get_rome_codes - INFO - 📋 Codes ROME trouvés pour RNCP 35304 : ['D1408', 'M1401']
2026-04-17 09:48:47 - fetch_rome_data - WARNING - ⚠️ Scraping ROME D1408 : 404
2026-04-17 09:48:47 - fetch_rome_data - WARNING - ⚠️ Scraping ROME M1401 : 404
```

**RC** : France Compétences n'expose **pas de RC public** pour ce RNCP. Les 4 patterns regex testés (`/wp-json/api/v1/evaluation/export/`, `/wp-json/api/v1/certification/export/`, URLs PDF avec "RC" ou "referentiel-certification" dans le nom) retournent tous vide.

**ROME** : L'ancienne URL `https://candidat.francetravail.fr/metierform/accueil?codeRome=D1408` retourne **404**. France Travail a changé son URL publique. La nouvelle URL (`metierscope/fiche-metier/{code}`) existe mais est rendue en JavaScript (SPA) — non scrapable en HTTP brut.

## Options envisagées

1. **Ajouter upload manuel** de PDFs RC et ROME via UI — Permet fallback humain mais incompatible avec l'objectif d'automatisation totale du pipeline.
2. **Obtenir des credentials France Travail API** pour ROME — Gratuit, 2 jours d'attente pour validation. Mais ne règle pas le problème RC (inexistant).
3. **Corriger l'URL scraping ROME** vers la nouvelle (`metierscope`) — Nécessite rendu JS (Playwright/Puppeteer). Coût infrastructure élevé pour bénéfice marginal.
4. **Abandonner RC/ROME** (retenu) — Le REAC seul suffit pour la génération de programme.

## Décision finale

**Abandon de RC et ROME dans l'UI**. Le backend garde le code (les 3 threads parallèles tournent toujours), mais :
- Les badges gris RC / ROME sont supprimés de l'étape "Téléchargement REAC" dans l'UI
- Seul REAC est affiché
- Le job passe en `reac_ready` avec REAC uniquement

## Rationale technique

**Densité du REAC** : 95 509 caractères = ~66 pages PDF = toutes les compétences + savoirs + savoirs-faire + savoirs-être détaillés. C'est déjà très dense pour alimenter Claude.

**Gain marginal de RC/ROME** :
- RC : critères d'évaluation (utile pour la partie examen/QCM, peu pour le cours)
- ROME : contexte métier terrain (définition, synonymes). Déjà partiellement présent dans le REAC.

**Trade-off** : complexité maintenance (scraping fragile, URLs qui changent) > bénéfice qualité (quelques % en plus).

**Impact sur Couche 1 (enrichissement)** : la Couche 1 (cf. [architecture 4 couches](../01-architecture/architecture-4-couches-qualite-programme.md)) rendra le REAC encore plus exploitable sans dépendre de sources externes fragiles.

## Références code

- `backend/services/formation_pipeline_service.py:277-323` — `download_rc_text`
- `backend/services/formation_pipeline_service.py:372-433` — `fetch_rome_data`
- `backend/routes/formation_routes.py:194-266` — `fetch_reac` (orchestration 3 threads parallèles)
- `frontend/src/pages/FormationPipeline.jsx:740-756` — badges UI (RC/ROME retirés)
- `CHANGELOG.md` 2026-04-17 — entrées "Clarification RC/ROME optionnels" et "Décision RC/ROME retirés UI"

## Leçons / Pour le mémoire

- **Les APIs publiques gouvernementales sont fragiles** : URLs qui changent, absence de versioning, documentation inexistante. Toute dépendance doit prévoir la panne.
- **Le scraping HTTP brut ne suffit plus** sur les sites modernes (SPA JavaScript). Alternatives : API officielles (avec auth souvent), rendu headless (coûteux), ou abandon.
- **Savoir renoncer proprement à une feature** est un acte d'ingénierie mature : ici, 3 heures investies pour 5% de gain qualité potentiel → meilleur investissement ailleurs.
- **Le pattern "silent failure + UI clean"** (backend tente, frontend masque l'échec) est valable seulement si la feature est vraiment optionnelle. Ici c'est le cas.
