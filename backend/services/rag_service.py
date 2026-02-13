# rag_service.py - Service d'appel au RAG externe
import requests
from config import RAG_SERVICE_URL
from utils.logger import get_logger

logger = get_logger(__name__)


def call_rag_service(question):
    """Appel au service RAG externe"""
    try:
        logger.info(f"🔍 Appel au service RAG: {question[:50]}...")
        logger.debug(f"🔍 URL RAG: {RAG_SERVICE_URL}")

        response = requests.post(
            f"{RAG_SERVICE_URL}/ask", json={"question": question}, timeout=30
        )
        logger.debug(f"🔍 Code réponse RAG: {response.status_code}")

        response.raise_for_status()
        data = response.json()
        answer = data.get("answer_text", "Désolé, je n'ai pas pu obtenir de réponse.")

        logger.info(f"✅ Réponse RAG reçue: {answer[:100]}...")
        return answer

    except requests.exceptions.Timeout as e:
        logger.error(f"⏰ Timeout service RAG: {e}")
        return "Désolé, le service de réponse met trop de temps à répondre."
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 Erreur connexion service RAG: {e}")
        return "Désolé, impossible de se connecter au service de réponse."
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Erreur service RAG: {e}")
        return "Désolé, le service de réponse est temporairement indisponible."
    except Exception as e:
        logger.error(f"❌ Erreur inattendue RAG: {e}")
        return "Désolé, une erreur est survenue."
