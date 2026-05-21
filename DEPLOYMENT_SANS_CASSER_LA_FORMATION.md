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

## Procédure exacte qui a fonctionné le 2026-05-20

Cette section documente le cas réel du repo, avec les pièges qu'on a
effectivement rencontrés.

### Ce qui a marché

Pour publier la vraie prod Socrate1 sans casser le flux :

1. pousser le code sur `staging`
2. vérifier que le frontend staging et le backend staging passent
3. mettre `main` au même niveau que `staging`
4. lancer le frontend production
5. lancer le backend production

Les runs GitHub qui ont finalement réussi étaient :

- frontend production : `Deploy Frontend - Socrate1`, run `26151742977`
- backend production : `Deploy Backend - socrate1`, run `26151743040`

### Règle critique pour le backend production

Le backend production Socrate1 doit être déclenché depuis la ref `staging`,
pas depuis `main`, même quand `target=production`.

Pourquoi :

- l'auth Azure OIDC du workflow backend Socrate1 est actuellement liée à la
  branche `staging`
- si on lance `staging_socrate1.yml` depuis `main`, Azure refuse avec :

```text
AADSTS700213: No matching federated identity record found for presented assertion subject 'repo:AutomationAuditsEnergies/LeSocrate:ref:refs/heads/main'
```

Donc :

- frontend production : peut être lancé depuis `main` ou `staging`
- backend production : doit être lancé depuis `staging`

### Ancien workflow à ne pas utiliser

Il existe un ancien workflow backend :

```text
.github/workflows/main_socrate-backend-v.yml
```

Ce n'est pas le backend Socrate1 en production.

Symptômes typiques :

- il se lance sur `main`
- il cherche `requirements.txt` à la racine
- il échoue avec :

```text
Could not open requirements file: [Errno 2] No such file or directory: 'requirements.txt'
```

Ce workflow legacy a été neutralisé pour éviter les faux positifs dans l'onglet
Actions.

## Règles de push

### 1. Toujours partir d'un arbre propre

Avant de pousser :

- vérifier `git status`
- ne pas embarquer `venv/`, `frontend/.vite/`, exports audio locaux, caches
- ne pas embarquer de fichiers de debug si on ne veut pas les publier

Commande minimale :

```bash
git status
```

### 2. Test normal = `staging`

Pour toute correction ou feature :

```bash
git checkout staging
git pull origin staging
git merge ta-branche
git push origin staging
```

Effet attendu :

- frontend Socrate1 staging
- backend Socrate1 slot `staging`
- base staging uniquement

### 3. Production = validation préalable sur staging

Ne pas envoyer en prod tant que :

- la page staging n'est pas bonne
- le backend staging n'est pas bon
- le cas utilisateur n'a pas été retesté

### 4. Synchroniser `main` sans croire que ça déploie

Une fois staging validé :

```bash
git checkout main
git pull origin main
git merge staging
git push origin main
```

Important :

- ce push ne doit pas être considéré comme le déploiement prod
- il met seulement `main` à jour

### 5. Déployer la prod dans le bon ordre

Ordre recommandé :

1. frontend production
2. backend production

Déclenchement GitHub :

- workflow `Deploy Frontend - Socrate1`
- workflow `Deploy Backend - socrate1`

Paramètre :

```text
target=production
```

Règle de ref :

- frontend : OK depuis `main` ou `staging`
- backend : lancer depuis `staging`

### 6. Si un run backend prod échoue avec OIDC

Si tu vois :

```text
AADSTS700213
```

ça veut dire en pratique :

- le workflow a été lancé depuis la mauvaise branche
- il faut le relancer depuis `staging`

### 7. Si un run backend staging échoue avec `409 Conflict`

Si tu vois :

```text
Conflict (CODE: 409)
```

ça signifie généralement :

- un autre déploiement App Service est déjà en cours
- il faut attendre la fin du run concurrent puis relancer

## Checklist courte

Avant push :

- `git status` propre
- pas d'artefacts locaux indésirables
- bonne branche

Pour tester :

- push sur `staging`
- vérifier frontend staging
- vérifier backend staging

Pour prod :

- merge `staging` -> `main`
- lancer `Deploy Frontend - Socrate1` avec `target=production`
- lancer `Deploy Backend - socrate1` avec `target=production` depuis `staging`
- vérifier la vraie URL :

```text
https://thankful-wave-043aa3b03.4.azurestaticapps.net/hr-dashboard
```

## Procédure urgente pendant une formation

Si une formation est en cours :

1. Ne pousse pas sur `main`.
2. Pousse sur `staging`.
3. Teste l'URL staging.
4. Ne merge vers `main` que quand la correction est validée.
