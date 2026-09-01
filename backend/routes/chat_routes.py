import os
import re
import requests
from flask import Blueprint, request
from routes.video_routes import (
    StudentCourseAccessError,
    _private_json,
    _student_access_error,
    _student_audio_info,
    _student_course_context,
)

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY")

SYSTEM_PROMPT = """
Tu es un assistant pédagogique intégré à une formation en direct.

CONTRAINTE ABSOLUE DE FORMAT :
- Réponds en 2 à 4 phrases MAXIMUM. Jamais plus.
- Va droit au but. Pas d'introduction, pas de récapitulatif.
- Si l'étudiant veut plus de détails, il reposera une question.

Règles :
1. Base-toi sur le contenu du cours fourni.
2. Si l'info n'est pas dans le cours, dis-le en une phrase puis donne une réponse courte.
3. Ne jamais inventer d'information présentée comme issue du cours.
4. Ton : direct, clair, pédagogique. Français courant.
"""


def _search_index_for_platform(platform_id):
    """Mirror the per-platform indexes provisioned by the HR ingestion route."""
    platform_id = int(platform_id)
    if platform_id == 1:
        return os.environ.get("AZURE_SEARCH_INDEX_NAME") or "rag-1770824229421"
    return (
        os.environ.get(f"PLATFORM_{platform_id}_AZURE_SEARCH_INDEX_NAME")
        or f"rag-p{platform_id}"
    )


@chat_bp.route("", methods=["POST"])
def chat():
    try:
        context = _student_course_context()
        audio_info, _offset, temps_restant = _student_audio_info(context)
    except StudentCourseAccessError as exc:
        return _student_access_error(exc)
    except Exception:
        return _private_json({"error": "Erreur serveur"}, 500)

    if not audio_info:
        if temps_restant > 0:
            return _private_json({"error": "Cours non démarré"}, 425)
        return _private_json({"error": "Cours terminé"}, 410)

    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    # historique = liste de {"role": "user"/"assistant", "content": "..."}
    # On garde uniquement les 10 derniers messages (trimming mémoire court terme)
    raw_history = data.get("history", [])
    history = []
    if isinstance(raw_history, list):
        for item in raw_history[-10:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            history.append({
                "role": item["role"],
                "content": str(item.get("content") or "")[:4000],
            })

    if not question:
        return _private_json({"error": "Question manquante"}, 400)
    if len(question) > 4000:
        return _private_json({"error": "Question trop longue"}, 400)

    url = (
        f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}"
        f"/chat/completions?api-version=2024-12-01-preview"
    )

    # On reconstruit les messages : system + historique + nouvelle question
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    payload = {
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.7,
        "data_sources": [
            {
                "type": "azure_search",
                "parameters": {
                    "endpoint": AZURE_SEARCH_ENDPOINT,
                    "index_name": _search_index_for_platform(context["platform_id"]),
                    "authentication": {
                        "type": "api_key",
                        "key": AZURE_SEARCH_API_KEY,
                    },
                    "query_type": "vector_simple_hybrid",
                    "embedding_dependency": {
                        "type": "deployment_name",
                        "deployment_name": os.getenv(
                            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
                        ),
                    },
                },
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException:
        return _private_json({"error": "Assistant indisponible"}, 502)

    if response.status_code != 200:
        return _private_json({"error": "Assistant indisponible"}, 502)

    try:
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, TypeError, ValueError, IndexError):
        return _private_json({"error": "Assistant indisponible"}, 502)
    # Nettoyer les références [doc1][doc2] etc.
    answer = re.sub(r'\[doc\d+\]', '', answer).strip()

    return _private_json({"answer": answer})
