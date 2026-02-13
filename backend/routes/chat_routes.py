import os
import re
import requests
from flask import Blueprint, request, jsonify

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME")

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


@chat_bp.route("", methods=["POST"])
def chat():
    data = request.get_json()
    question = data.get("question", "").strip()
    # historique = liste de {"role": "user"/"assistant", "content": "..."}
    # On garde uniquement les 10 derniers messages (trimming mémoire court terme)
    history = data.get("history", [])[-10:]

    if not question:
        return jsonify({"error": "Question manquante"}), 400

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
                    "index_name": AZURE_SEARCH_INDEX_NAME,
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

    response = requests.post(url, json=payload, headers=headers, timeout=30)

    if response.status_code != 200:
        return (
            jsonify({"error": "Erreur Azure", "details": response.text}),
            response.status_code,
        )

    result = response.json()
    answer = result["choices"][0]["message"]["content"]
    # Nettoyer les références [doc1][doc2] etc.
    answer = re.sub(r'\[doc\d+\]', '', answer).strip()

    return jsonify({"answer": answer})
