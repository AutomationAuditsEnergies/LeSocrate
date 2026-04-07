# handlers.py - Gestionnaires d'événements SocketIO
from flask_socketio import emit, join_room, leave_room
from flask import request
import state
from services.rag_service import call_rag_service
from services.time_service import get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_room(sid):
    """Retourne le nom de la room pour un SID donné"""
    pid = state.connected_users_platform.get(sid, 1)
    return f"platform_{pid}"


def _count_platform_users(platform_id):
    """Compte les utilisateurs connectés sur une plateforme"""
    return sum(1 for pid in state.connected_users_platform.values() if pid == platform_id)


def register_socketio_handlers(socketio):
    """Enregistre tous les gestionnaires d'événements SocketIO"""

    @socketio.on("connect")
    def handle_connect():
        """Gestion de la connexion d'un client"""
        try:
            logger.info(f"🔌 Nouvelle connexion WebSocket: {request.sid}")
            # Le count sera mis à jour quand user_connected sera reçu
            nb_participants = len(state.connected_users)
            emit("participants_update", {"count": nb_participants}, broadcast=True)
        except Exception as e:
            logger.error(f"❌ Erreur handle_connect: {e}")

    @socketio.on("disconnect")
    def handle_disconnect():
        """Gestion de la déconnexion d'un client"""
        try:
            sid = request.sid
            logger.info(f"🔌 Déconnexion WebSocket: {sid}")

            platform_id = state.connected_users_platform.pop(sid, 1)
            room = f"platform_{platform_id}"

            if sid in state.connected_users:
                username = state.connected_users.pop(sid)
                logger.info(f"👋 Utilisateur {username} retiré (P{platform_id})")

            nb_participants = _count_platform_users(platform_id)
            emit("participants_update", {"count": nb_participants}, to=room)
        except Exception as e:
            logger.error(f"❌ Erreur handle_disconnect: {e}")

    @socketio.on("user_connected")
    def handle_user_connected(data):
        """Gestion de l'enregistrement d'un utilisateur connecté"""
        try:
            username = data.get("username", "Anonyme")
            platform_id = data.get("platform_id", 1)
            sid = request.sid
            room = f"platform_{platform_id}"

            logger.info(f"👤 Utilisateur connecté: {username} P{platform_id} (sid: {sid})")

            # Nettoyage des anciennes connexions du même utilisateur
            old_sids = [s for s, u in state.connected_users.items() if u == username]
            for old_sid in old_sids:
                state.connected_users.pop(old_sid, None)
                state.connected_users_platform.pop(old_sid, None)

            # Enregistrer
            state.connected_users[sid] = username
            state.connected_users_platform[sid] = platform_id
            join_room(room)

            nb_participants = _count_platform_users(platform_id)
            emit("participants_update", {"count": nb_participants}, to=room)
            logger.info(f"✅ {username} enregistré P{platform_id}, total room: {nb_participants}")
        except Exception as e:
            logger.error(f"❌ Erreur handle_user_connected: {e}")

    @socketio.on("get_participants")
    def handle_get_participants():
        """Retourne la liste des participants connectés sur la même plateforme"""
        try:
            sid = request.sid
            platform_id = state.connected_users_platform.get(sid, 1)

            participants = [
                state.connected_users[s]
                for s, pid in state.connected_users_platform.items()
                if pid == platform_id and s in state.connected_users
            ]
            emit("participants_list", {"participants": participants})
        except Exception as e:
            logger.error(f"❌ Erreur handle_get_participants: {e}")

    @socketio.on("send_question")
    def handle_send_question(data):
        """Gestion d'une question envoyée par un utilisateur"""
        try:
            question = data.get("question", "").strip()
            username = data.get("username", "Anonyme")
            sid = request.sid
            platform_id = state.connected_users_platform.get(sid, 1)
            room = f"platform_{platform_id}"
            timestamp = get_current_simulated_time(platform_id).strftime("%H:%M:%S")

            logger.info(f"❓ Question de {username} P{platform_id}: {question[:50]}...")

            if not question:
                return

            # Broadcast de la question à la room de la plateforme
            emit(
                "new_message",
                {
                    "username": username,
                    "message": question,
                    "timestamp": timestamp,
                    "type": "question",
                },
                to=room,
            )

            # Appeler le service RAG
            answer = call_rag_service(question)
            answer_timestamp = get_current_simulated_time(platform_id).strftime("%H:%M:%S")

            emit(
                "new_message",
                {
                    "username": "Professeur",
                    "message": answer,
                    "timestamp": answer_timestamp,
                    "type": "answer",
                },
                to=room,
            )

        except Exception as e:
            logger.error(f"❌ Erreur handle_send_question: {e}")
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
