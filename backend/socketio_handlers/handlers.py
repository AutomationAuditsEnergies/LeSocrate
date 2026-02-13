# handlers.py - Gestionnaires d'événements SocketIO
from flask_socketio import emit
from flask import request
import state
from services.rag_service import call_rag_service
from services.time_service import get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)


def register_socketio_handlers(socketio):
    """Enregistre tous les gestionnaires d'événements SocketIO"""

    @socketio.on("connect")
    def handle_connect():
        """Gestion de la connexion d'un client"""
        try:
            logger.info(f"🔌 Nouvelle connexion WebSocket: {request.sid}")
            # Broadcast du nombre de participants à tous les clients
            nb_participants = len(state.connected_users)
            emit("participants_update", {"count": nb_participants}, broadcast=True)
            logger.debug(f"📢 Participants update broadcast: {nb_participants}")
        except Exception as e:
            logger.error(f"❌ Erreur handle_connect: {e}")

    @socketio.on("disconnect")
    def handle_disconnect():
        """Gestion de la déconnexion d'un client"""
        try:
            sid = request.sid
            logger.info(f"🔌 Déconnexion WebSocket: {sid}")

            # Retirer l'utilisateur de la liste si présent
            if sid in state.connected_users:
                username = state.connected_users.pop(sid)
                logger.info(f"👋 Utilisateur {username} retiré des connectés")

            # Broadcast du nouveau nombre de participants
            nb_participants = len(state.connected_users)
            emit("participants_update", {"count": nb_participants}, broadcast=True)
            logger.debug(f"📢 Participants update broadcast: {nb_participants}")
        except Exception as e:
            logger.error(f"❌ Erreur handle_disconnect: {e}")

    @socketio.on("user_connected")
    def handle_user_connected(data):
        """Gestion de l'enregistrement d'un utilisateur connecté"""
        try:
            username = data.get("username", "Anonyme")
            sid = request.sid
            logger.info(f"👤 Utilisateur connecté: {username} (sid: {sid})")

            # Vérifier si cet utilisateur était déjà connecté avec un autre SID
            old_sids = [s for s, u in state.connected_users.items() if u == username]
            for old_sid in old_sids:
                logger.warning(
                    f"⚠️ Utilisateur {username} déjà connecté avec SID {old_sid}, nettoyage"
                )
                state.connected_users.pop(old_sid, None)

            # Enregistrer le nouvel utilisateur
            state.connected_users[sid] = username

            # Broadcast du nouveau nombre de participants
            nb_participants = len(state.connected_users)
            emit("participants_update", {"count": nb_participants}, broadcast=True)
            logger.info(
                f"✅ Utilisateur {username} enregistré, total: {nb_participants}"
            )
        except Exception as e:
            logger.error(f"❌ Erreur handle_user_connected: {e}")

    @socketio.on("get_participants")
    def handle_get_participants():
        """Retourne la liste des participants connectés"""
        try:
            logger.debug("📊 Demande liste participants")
            participants = list(state.connected_users.values())
            emit("participants_list", {"participants": participants})
            logger.debug(f"📊 {len(participants)} participants retournés")
        except Exception as e:
            logger.error(f"❌ Erreur handle_get_participants: {e}")

    @socketio.on("send_question")
    def handle_send_question(data):
        """Gestion d'une question envoyée par un utilisateur"""
        try:
            question = data.get("question", "").strip()
            username = data.get("username", "Anonyme")
            timestamp = get_current_simulated_time().strftime("%H:%M:%S")

            logger.info(f"❓ Question reçue de {username}: {question[:50]}...")

            if not question:
                logger.warning("⚠️ Question vide reçue")
                return

            # Broadcast de la question à tous les clients
            emit(
                "new_message",
                {
                    "username": username,
                    "message": question,
                    "timestamp": timestamp,
                    "type": "question",
                },
                broadcast=True,
            )
            logger.debug(f"📢 Question broadcast à tous les clients")

            # Appeler le service RAG
            logger.info(f"🤖 Appel RAG pour la question: {question[:50]}...")
            answer = call_rag_service(question)
            answer_timestamp = get_current_simulated_time().strftime("%H:%M:%S")

            logger.info(f"🤖 Réponse RAG reçue: {answer[:100]}...")

            # Broadcast de la réponse à tous les clients
            emit(
                "new_message",
                {
                    "username": "Professeur",
                    "message": answer,
                    "timestamp": answer_timestamp,
                    "type": "answer",
                },
                broadcast=True,
            )
            logger.debug(f"📢 Réponse RAG broadcast à tous les clients")

        except Exception as e:
            logger.error(f"❌ Erreur handle_send_question: {e}")
            # Envoyer un message d'erreur à l'utilisateur
            emit(
                "new_message",
                {
                    "username": "Système",
                    "message": "Désolé, une erreur est survenue lors du traitement de votre question.",
                    "timestamp": get_current_simulated_time().strftime("%H:%M:%S"),
                    "type": "error",
                },
            )

    logger.info("✅ Gestionnaires SocketIO enregistrés")
