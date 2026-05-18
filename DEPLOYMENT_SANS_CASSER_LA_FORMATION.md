# Déploiement sans casser la formation live

Objectif : pouvoir tester une version web Azure sans écraser la version utilisée
en formation.

## Règle simple

- `main` = code validé pour production, mais **ne déploie pas automatiquement**.
- `staging` = test.
- Les branches de travail passent par Pull Request.

Avant cette correction, `staging` déployait directement :

- le frontend live `thankful-wave-043aa3b03`
- le backend live `socrate1`

Donc un push de test sur `staging` pouvait casser la formation en cours.

## Ce qui est maintenant codé

### Frontend Socrate1

Workflow :

```text
.github/workflows/azure-static-web-apps-thankful-wave-043aa3b03.yml
```

Comportement :

- push sur `main` -> aucun déploiement automatique
- push sur `staging` -> environnement Static Web Apps nommé `staging`
- Pull Request vers `main` -> preview PR Azure, sans toucher la production
- déploiement production -> manuel via `workflow_dispatch`

### Backend Socrate1

Workflow :

```text
.github/workflows/staging_socrate1.yml
```

Comportement :

- push sur `main` -> aucun déploiement automatique
- push sur `staging` -> slot `staging`
- déploiement production -> manuel via `workflow_dispatch`

Si le slot backend `staging` n'existe pas encore, le workflow échouera au lieu
d'écraser la production. C'est volontaire.

## À faire une seule fois dans Azure

### 1. Créer le slot backend

Azure Portal :

1. App Services
2. `socrate1`
3. Deployment slots
4. Add slot
5. Name : `staging`
6. Clone settings from : `socrate1`
7. Create

### 2. Isoler la base SQLite du slot staging

Le workflow backend le fait maintenant automatiquement au prochain déploiement
staging :

```text
DB_PATH=/home/database-staging.db
SCM_DO_BUILD_DURING_DEPLOYMENT=true
ENABLE_ORYX_BUILD=true
```

Si tu dois le faire à la main dans Azure, va dans le slot `socrate1/staging` :

1. Configuration
2. Application settings
3. Ajouter ou vérifier :

```text
DB_PATH=/home/database-staging.db
SCM_DO_BUILD_DURING_DEPLOYMENT=true
ENABLE_ORYX_BUILD=true
```

Dans la prod, ne mets rien : elle garde `/home/database.db`.

### 2 bis. Corriger l'erreur "Application Error" du slot staging

Cette erreur arrive quand le slot démarre avant d'avoir installé les dépendances
Python. Les logs typiques sont :

```text
ModuleNotFoundError: No module named 'eventlet'
WARNING: Could not find virtual environment directory /home/site/wwwroot/antenv
```

Correction attendue :

1. Déployer le backend vers `staging` avec le workflow GitHub `Deploy Backend - socrate1`.
2. Le workflow force le build Oryx et installe `backend/requirements.txt`.
3. Le workflow remet la commande de démarrage :

```text
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8000 --timeout 120 run:app
```

### 3. Donner au frontend staging l'URL exacte du backend staging

Après création du slot, récupère son URL Azure. Elle ressemble souvent à :

```text
https://socrate1-staging.azurewebsites.net
```

ou, selon Azure :

```text
https://socrate1-staging-xxxxx.francecentral-01.azurewebsites.net
```

Dans GitHub :

1. Settings
2. Secrets and variables
3. Actions
4. Variables
5. New repository variable

Nom :

```text
SOCRATE1_STAGING_API_URL
```

Valeur :

```text
https://socrate1-staging-f4hnc2hbbwc8faen.francecentral-01.azurewebsites.net
```

## Workflow au quotidien

Pour tester :

```bash
git checkout staging
git merge ta-branche
git push origin staging
```

Ça déploie uniquement :

- frontend staging
- backend slot staging
- base `/home/database-staging.db`

Pour préparer le code production :

```bash
git checkout main
git merge staging
git push origin main
```

Ça ne déploie rien automatiquement. Pour mettre en production, déclenche
manuellement les deux workflows GitHub avec `target=production` :

- frontend production
- backend production
- base `/home/database.db`

## Procédure urgente pendant une formation

Si une formation est en cours :

1. Ne pousse pas sur `main`.
2. Pousse sur `staging`.
3. Teste l'URL staging.
4. Ne merge vers `main` que quand la correction est validée.
