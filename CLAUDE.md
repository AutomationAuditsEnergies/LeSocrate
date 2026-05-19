# CLAUDE.md

Guide Claude Code pour **Le Socrate** — plateforme de formation en ligne (playlist MP3 horodatée + Q&A IA), multi-tenant (P1–P4), hébergée sur Azure.

> Les détails techniques vivent dans le vault Obsidian (pointeurs ci-dessous). Ce fichier garde l'identité + les règles critiques.

---

## Second Brain — vault couplé

Ce projet est couplé au Second Brain **`/Users/amelle/Downloads/kit-deuxieme-cerveau/`** (architecture Karpathy LLM Wiki : `raw/` humain + `wiki/` LLM + schema). Le vault contient la mémoire long-terme du projet : décisions, pièges, architecture, leçons de sessions passées.

### Workflow recommandé (depuis ce projet)

- **Début de session** : lance `/prime` pour charger `CLAUDE.md` du vault + l'index + la dernière daily note. Contexte chargé en ~3 lectures, pas besoin de re-scanner le wiki.
- **Pendant la session** : si tu as besoin d'une info précise (archi, décision passée, piège documenté), lance `/query "ma question"` — il va lire l'index puis les notes pertinentes.
- **Fin de session** : lance `/save` pour créer la daily note dans `vault/wiki/Daily/YYYY-MM-DD.md` (actions + décisions + prochaine étape). C'est ce que `/prime` relira au prochain démarrage.
- **Occasionnellement** : `/ingest` pour compiler des nouvelles sources raw/ (clippings, insights de session) en notes wiki structurées ; `/lint` 1×/semaine pour la santé du vault.

### Règles importantes (héritées du vault)

Les skills globaux `/prime`, `/save`, `/ingest`, `/query`, `/lint`, `/notebooklm` **ciblent toujours le chemin absolu** du vault, pas le CWD. Tu peux donc les lancer depuis ici sans souci. **Ne jamais résoudre `wiki/` ou `raw/` relativement à ce projet** — ces dossiers n'existent pas ici, ils vivent dans le vault.

Règles absolues du vault qui s'appliquent quand tu y écris :
1. **`raw/` est immutable** — espace humain, jamais modifier, renommer, déplacer un fichier dedans.
2. **`wiki/` est LLM** — tu peux y écrire, mais uniquement via un skill (`/ingest`, `/save`, `/notebooklm`).
3. **Pas de note orpheline** — chaque note wiki a au moins un `[[wiki link]]` entrant ou sortant.
4. **Pas d'information inventée** — si la donnée manque, le signaler plutôt que combler.

Détail complet : `/Users/amelle/Downloads/kit-deuxieme-cerveau/CLAUDE.md`.

---

## Principe architectural fondamental : 1 RNCP = 1 module durable

La pipeline formation (`/formation-pipeline`) est exécutée **une seule fois par RNCP**. Le résultat est un module audio complet et durable, **réutilisé tel quel pour toutes les promos** du même titre professionnel.

Implications :

- `nb_days` est intrinsèque au RNCP (dicté par le REAC), pas un paramètre par promo.
- Ne PAS concevoir d'optimisations "scaling par promo" ou "cache par RNCP" : la réutilisation est native.
- Coût Claude + TTS amorti sur toutes les promos — faire "une fois pour toutes, proprement" > "faire moins cher par promo".
- Promos = sessions utilisateurs distinctes (table `logs`), pas de modifications du module après génération.

Détails : `memoire/01-architecture/un-rncp-un-module-durable.md` et `/Users/amelle/Downloads/kit-deuxieme-cerveau/wiki/Intelligence/un-rncp-un-module-durable.md`.

---

## Stack

React 19 + Vite 7 (port 5173) · Flask + SocketIO + eventlet (port 5001) · SQLite · Fish Audio S2-Pro · Claude Sonnet 4 (génération contenu) · Azure OpenAI GPT-4 (chat/RAG) · OpenAI Whisper (transcription) · Azure (App Service, Static Web Apps, Blob, FrontDoor, AI Search).

Détails : `/Users/amelle/Downloads/kit-deuxieme-cerveau/wiki/Context/stack-technique.md`.

---

## Commandes dev

```bash
# Frontend
cd frontend && npm install && npm run dev   # 5173

# Backend (toujours run.py — eventlet requis ; jamais flask run)
cd backend && pip install -r requirements.txt
python run.py                               # 5001

# Backend avec auto-reload sur changement .py (watchdog)
# Installation : ./venv/bin/pip install watchdog
cd backend && watchmedo auto-restart -d . -p '*.py' -R -- python run.py
```

Proxy Vite : `/api` et `/socket.io` → `http://localhost:5001`.

---

## Pointeurs vault (pour les détails)

Avant de refactorer/étendre un service ou de prendre une décision d'archi, consulter :

- **Vue d'ensemble projet** → `wiki/Context/projet-le-socrate.md`
- **Multi-tenant (P1–P4)** → `wiki/Context/architecture-multi-tenant.md`
- **Pipeline TTS 19 MP3** (flux complet, tags Fish Audio, calibration 165,7 mots/min, playlist blocs) → `wiki/Intelligence/pipeline-tts-19-mp3.md`
- **Infra Azure 3 comptes Blob** (piège des connection strings) → `wiki/Intelligence/infra-azure-3-comptes-blob.md`
- **Décisions persistance SQLite** → `wiki/Intelligence/decisions-persistance-sqlite.md`
- **Conventions repo** → `wiki/Resources/conventions-repo.md`

Chemins absolus : préfixer par `/Users/amelle/Downloads/kit-deuxieme-cerveau/`.

---

## Règles critiques (ne jamais enfreindre)

1. **Backend** : `python run.py`, jamais `flask run`. Port **5001** en dev.
2. **3 comptes Azure Storage** distincts — ne jamais mélanger les connection strings :
   - `formationdocuments` → PDFs (`AZURE_STORAGE_CONNECTION_STRING`)
   - `formationaudios` → MP3 cours (`AZURE_AUDIO_STORAGE_CONNECTION_STRING`)
   - `documentstts` → MP3 TTS Fish Audio (`AZURE_TTS_STORAGE_CONNECTION_STRING`)
3. **Container audios TTS = `audiostts`** dans `documentstts` (pas `audiotts`, pas `formationaudios`).
4. **SAS URLs audios** via `AZURE_TTS_STORAGE_CONNECTION_STRING` dans `hr_routes.py`.
5. **Pas de SDK OpenAI/Fish Audio** (conflits eventlet) → `requests` HTTP direct.
6. **Timezone** Europe/Paris · format `YYYY-MM-DD HH:MM:SS`.
7. **Auth** : sessions Flask + fallback `X-Auth-Token` (localStorage) + header `X-Platform-Id`.
8. **CHANGELOG.md** : une entrée à chaque modification ou décision (cf. règle détaillée dans `.claude/CLAUDE.md`).

---

## Multi-tenant (rappel)

4 plateformes (P1 = référence/staging, P2/P3/P4 = prod). `platform_id` dans toutes les tables et appels API. Rooms SocketIO : `platform_{platform_id}`. HR Dashboard (P1) pilote P2/P3 via `PLATFORM_{id}_BACKEND_URL`.

Playlist mode (configurable `/schedule-config` par plateforme) :

- `hiver` : Pause midi → Cours bloc 4 → Q&A
- `ete` : Cours bloc 4 → Q&A → Pause midi

---

## CI/CD

Push sur `staging` → 10 workflows GitHub Actions parallèles (3 backends App Service, 3 frontends Static Web Apps, + P4 et Function App). Login OIDC (pas de secrets exposés), `azure/webapps-deploy@v3`.
Branche prod : `main` · staging/dev : `staging`.

---

## Styling (règles UI)

Tailwind v4 (global via Vite) · CSS par fichier pour templates slides · Material Icons self-hostés (fonts locales dans `frontend/public/`) · Poppins/Fredoka/Fira Code · dark theme `#0f172a` / `#1e293b` + accent violet `#8B5CF6`.

Pour les aesthetics frontend (éviter le "AI slop") et le workflow MCP Gemini Design obligatoire, voir `.claude/CLAUDE.md`.
