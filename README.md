# Socrate

Application de formation audio synchronisee, avec backend Flask/Gunicorn,
frontend React/Vite, pipeline de generation de contenus pedagogiques et outils
TTS.

## Structure

- `backend/` : API Flask, routes, services, PostgreSQL production / SQLite local, prompts backend.
- `frontend/` : application React/Vite, tests Playwright.
- `azure-function/` : fonction Azure separee.
- `cours/` : documents source lourds ou bureautiques (`.docx`, `.pdf`).
- `courstxt/` : textes de cours et versions TTS-ready.
- `docs/` : documentation projet, audits, deployment, design, references.
- `memoire/` : notes d'architecture, decisions, problemes et solutions.
- `tools/` : scripts ponctuels hors runtime applicatif.
  - `tools/tts/` : generation/calibration/debug audio.
  - `tools/dev/` : scripts de developpement local.
  - `tools/content/` : scripts de correction/nettoyage de contenu.

La racine doit rester limitee aux fichiers de pilotage du repo : README,
changelog, configuration Git et dossiers principaux.

## Installation

Backend :

```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
python backend/run.py
```

Frontend :

```bash
cd frontend
npm install
npm run dev
```

Les fichiers locaux sensibles ou generes (`backend/.env`, bases `.db`,
`node_modules`, sorties audio, caches, builds) sont ignores par Git.

Architecture et cutover de la pipeline :
[PostgreSQL + Azure Blob + file durable](docs/architecture/PIPELINE_PRODUCTION_POSTGRES_AZURE.md).
