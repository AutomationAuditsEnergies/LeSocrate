# Migration Azure → VPS (branche `staging`)

Ce document explique, simplement, comment fonctionne l'application aujourd'hui et comment la faire tourner sur un VPS à la place d'Azure.

---

## 1. C'est quoi la stack, en clair

L'application a 2 morceaux séparés qui se parlent par internet :

- **Le Backend** : un programme Python (Flask) qui gère toute la logique — les comptes, la génération des cours, la base de données, l'envoi des fichiers audio. C'est le "cerveau".
- **Le Frontend** : le site web que voient les utilisateurs (React), qui affiche les pages et appelle le Backend pour récupérer les données.

Le Backend utilise :
- **Flask** : le framework web Python.
- **eventlet** : une bibliothèque qui permet au serveur de gérer plusieurs utilisateurs en même temps sans bloquer.
- **SQLite** : la base de données. C'est **un simple fichier** sur le disque (pas un serveur de base de données séparé). Toutes les infos (élèves, cours, logs) sont dedans.
- **Claude / Fish Audio / Edge TTS** : les IA externes appelées pour générer le contenu des cours et la voix.

Le Frontend utilise **React + Vite**, un framework web moderne standard.

**Aujourd'hui il y a 4 "plateformes" (P1, P2, P3, P4)** — en fait, c'est la même application copiée 4 fois sur 4 serveurs Azure différents, chacune avec ses propres utilisateurs et sa propre base de données.

---

## 2. Comment ça marche aujourd'hui (avec Azure)

```
Utilisateur (navigateur)
        │
        ▼
  Frontend React  ──── hébergé sur "Azure Static Web Apps"
        │  (appelle des URLs comme /api/...)
        ▼
  Backend Flask   ──── hébergé sur "Azure App Service"
        │
        ├──► Fichier SQLite (stocké sur "Azure Files", un disque réseau)
        ├──► Fichiers audio/PDF ──► "Azure Blob Storage" (stockage de fichiers)
        └──► Appels API ──► Claude, Fish Audio, Azure OpenAI (services externes)
```

À chaque fois qu'on pousse du code sur la branche `staging` sur GitHub, un robot (GitHub Actions) reconstruit le Backend et le Frontend et les envoie automatiquement sur Azure. C'est pour ça qu'on ne voit jamais où est stocké le code "déployé" — c'est distant, sur les serveurs Azure.

**Point important sur Supabase** : Il y a des bouts de code qui font référence à Supabase (un service d'authentification), mais après vérification :
- Côté site web (Frontend), ce code **n'est utilisé nulle part** — c'est du code laissé de côté, inactif.
- Côté Backend, Supabase sert juste à une fonction annexe de gestion de comptes admin, pas à la connexion des élèves.
- **La vraie connexion des élèves utilise déjà un système correct** : un mot de passe stocké de façon sécurisée (haché) dans la base SQLite. Pas besoin de "migrer Supabase" — ce n'est pas vraiment utilisé aujourd'hui.

---

## 3. Le plan pour passer sur un VPS

Un **VPS**, c'est un serveur loué (chez Hetzner, OVH, Scaleway...) sur lequel on installe et gère tout nous-mêmes, contrairement à Azure qui gère une partie à notre place. Ça coûte moins cher, mais on doit s'occuper de plus de choses.

### Étape 0 — Sécuriser AVANT de bouger quoi que ce soit
Il y a des failles de sécurité connues dans le code actuel qu'il faut corriger avant d'exposer l'app sur un nouveau serveur :
1. Le mot de passe admin est écrit en clair dans le code (`admin` / `secret123`) → à remplacer par un vrai mot de passe secret.
2. Certaines routes qui suppriment ou ajoutent des fichiers audio ne vérifient pas qui appelle → à protéger.
3. Une variable `SECRET_KEY` doit être obligatoire au démarrage (aujourd'hui elle a une valeur de secours visible dans le code).

**Pourquoi avant tout le reste ?** Azure protège un peu par défaut (réseau fermé). Un VPS tout neuf est ouvert sur internet dès le premier jour — si on n'a pas corrigé ça, on expose ces failles à tout le monde.

### Étape 1 — Préparer le VPS
1. Louer un VPS chez un hébergeur européen (Hetzner, OVH ou Scaleway conviennent, prix ~15-40€/mois).
2. Installer **Docker** dessus (un outil qui permet de faire tourner l'appli dans une "boîte" isolée et reproductible).
3. Installer **Caddy** (un petit serveur qui gère automatiquement le HTTPS/cadenas vert du navigateur).
4. Pointer un nom de domaine vers l'adresse IP du VPS.

### Étape 2 — Mettre le code dans une "boîte" Docker
1. Écrire un `Dockerfile` : la recette qui dit "installe Python, installe les dépendances du projet, lance `python run.py`".
2. Construire le Frontend (React) et le servir directement en fichiers statiques via Caddy.
3. Faire pointer la base SQLite vers un vrai dossier sur le disque du VPS (pas sur un disque réseau comme sur Azure — ça va même améliorer les performances de la base).

### Étape 3 — S'occuper de la base de données (Postgres)
Tu as choisi de passer à **Postgres** (une vraie base de données serveur, plus robuste que SQLite pour plusieurs utilisateurs en même temps). Il existe déjà un schéma Postgres tout prêt sur une autre branche du projet (`codex/current-saas-postgres-20260705`, fichier `postgres_schema.sql`) — on part de ça plutôt que d'inventer un nouveau schéma.

⚠️ **Attention, ce n'est pas juste "changer d'endroit"** : le code actuel de `staging` parle à SQLite avec une syntaxe légèrement différente de Postgres. Il faudra adapter la façon dont le code interroge la base (mais pas réécrire toute la logique métier).

### Étape 4 — Remplacer les autres services Azure

| Ce qu'Azure fait aujourd'hui | Comment on le remplace sur le VPS |
|---|---|
| Stocke les fichiers audio/PDF (Azure Blob) | Un espace de stockage compatible ("S3") chez un hébergeur, ou un disque dédié |
| Le "CDN" qui accélère les téléchargements audio (Front Door) | Cloudflare (gratuit) |
| Le robot hebdomadaire qui planifie les cours (Function App) | Une simple tâche automatique programmée (`cron`) sur le VPS |
| Le chat IA (Azure OpenAI) | Appeler directement Claude à la place, pour n'avoir qu'un seul fournisseur d'IA à gérer |

### Étape 5 — Tester avant de tout couper
**Ne pas résilier Azure tout de suite.** On fait tourner le VPS et Azure **en même temps** pendant 2 à 4 semaines, on vérifie que tout marche pareil, puis on bascule progressivement (une plateforme à la fois si possible), et seulement après on arrête Azure.

---

## 4. Où trouver les mots de passe et clés actuels

Ces informations sont dans le **Portail Azure** (le site web de gestion Azure), pas dans le code (normal, ce sont des secrets) :

1. Va sur le portail Azure → cherche l'App Service (ex. `socrate1`) → section **"Variables d'environnement"** (ou "Configuration").
2. Clique sur **"Afficher les valeurs"** pour voir les clés en clair.
3. Note toutes celles qui commencent par : `AZURE_`, `ANTHROPIC_API_KEY`, `FISH_AUDIO_`, `PLATFORM_API_KEY`, `SECRET_KEY`.
4. Fais ça pour chacune des 4 App Services (les valeurs peuvent différer d'une plateforme à l'autre).

Ces clés serviront à configurer le nouveau serveur — tu les recopieras dans un fichier de configuration sur le VPS (jamais dans le code lui-même).

---

## 5. Résumé en une phrase par étape

1. On corrige les failles de sécurité connues.
2. On loue et on prépare un VPS.
3. On met le code actuel dedans, sans le réécrire.
4. On bascule la base de données vers Postgres.
5. On remplace les autres services Azure un par un.
6. On teste en parallèle plusieurs semaines.
7. Seulement à la fin, on résilie Azure.
