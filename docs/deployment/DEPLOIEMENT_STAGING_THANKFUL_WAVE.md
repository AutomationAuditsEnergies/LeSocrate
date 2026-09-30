# Déploiement staging vers l'URL principale thankful-wave

## Objectif

Quand on pousse sur la branche `staging`, le frontend Socrate1 doit mettre à jour cette URL :

https://thankful-wave-043aa3b03.4.azurestaticapps.net/

Il ne faut pas utiliser l'URL avec `-staging` dans le lien.

## Ce qui a été corrigé

Le workflow GitHub Actions concerné est :

`.github/workflows/azure-static-web-apps-thankful-wave-043aa3b03.yml`

Avant, le workflow contenait une logique avec plusieurs environnements :

- `production`
- `staging`
- `deployment_environment: "staging"`
- déploiements via `workflow_dispatch`
- previews de pull requests

Le point important : dans Azure Static Web Apps, `deployment_environment: "staging"` crée une URL d'environnement nommée, donc une URL avec `-staging`.

Ce n'est pas ce qu'on veut ici.

## Comportement voulu maintenant

Le workflow fait seulement :

```bash
push sur staging -> déploiement sur l'URL principale thankful-wave
```

La config importante est :

```yaml
on:
  push:
    branches:
      - staging

with:
  production_branch: "staging"
```

Cela signifie que la branche `staging` est traitée comme la branche principale de déploiement pour cette Static Web App.

## Commandes à utiliser

Depuis le repo `LeSocrate` :

```bash
git add .
git commit -m "message clair"
git push origin staging
```

Après le push, GitHub Actions doit lancer le workflow :

`Deploy Frontend - Socrate1`

Si tout se passe bien, le log affiche :

```text
Visit your site at: https://thankful-wave-043aa3b03.4.azurestaticapps.net
```

## Vérification faite

Le déploiement a été vérifié le 20 mai 2026.

Résultat :

- `Deploy Frontend - Socrate1` : succès
- URL publiée : `https://thankful-wave-043aa3b03.4.azurestaticapps.net`
- l'URL répond en `HTTP 200`

## À retenir

Ne pas remettre `deployment_environment: "staging"` dans ce workflow si l'objectif est de publier sur l'URL principale.

Pour publier sur `thankful-wave`, il faut garder :

```yaml
production_branch: "staging"
```
