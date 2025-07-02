# main_app.py - Version Azure avec logs détaillés
import pytz
import os
import logging
import sys

# Configuration des logs détaillés
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/app.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# Fuseau horaire français
FRANCE_TZ = pytz.timezone("Europe/Paris")
logger.info(f"🌍 Fuseau horaire configuré: {FRANCE_TZ}")

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    flash,
    jsonify,
)
from flask_socketio import SocketIO, emit
from datetime import datetime
import sqlite3
import requests
from flask import Response
import csv
import io
from flask import send_file
from openpyxl import Workbook
import tempfile
import threading
import time

logger.info("📦 Importation des modules terminée")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_secret_key_for_dev")
logger.info(f"🔐 Secret key configuré: {'***' if app.secret_key else 'MANQUANT'}")

# ✅ Configuration Azure - URL du service RAG
RAG_SERVICE_URL = os.getenv(
    "RAG_SERVICE_URL", "https://rag-b0fndpa9fycaafcr.francecentral-01.azurewebsites.net"
)
logger.info(f"🔗 RAG Service URL: {RAG_SERVICE_URL}")

# ✅ Base de données - SQLite local en dev, Azure SQL en prod
if os.getenv("AZURE_SQL_CONNECTION_STRING"):
    # TODO: Configuration Azure SQL Database
    logger.info("🗄️ Mode Azure SQL Database")
    DB_PATH = "/tmp/database.db"
else:
    logger.info("🗄️ Mode SQLite local (développement)")
    DB_PATH = "/tmp/database.db"

logger.info(f"🗄️ Chemin base de données: {DB_PATH}")

# SocketIO configuration
try:
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")
    logger.info("🔌 SocketIO configuré avec succès")
except Exception as e:
    logger.error(f"❌ Erreur configuration SocketIO: {e}")
    raise

# Configuration du cours - PLAYLIST DES AUDIOS
# Configuration du cours - PLAYLIST DES AUDIOS (Azure Storage)
COURS_PLAYLIST = [
    # === BLOC 1 : 9h00 - 10h05 ===
    {
        "id": 1,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_9h00_9h45.mp3",
        "duration": 2700,
        "title": "Cours - Bloc 1 (9h00-9h45)",
        "type": "cours",
    },
    {
        "id": 2,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_9h45_9h55.wav",
        "duration": 600,
        "title": "Questions-Réponses IA (9h45-9h55)",
        "type": "qa",
    },
    {
        "id": 3,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_9h55_10h05.wav",
        "duration": 600,
        "title": "Pause (9h55-10h05)",
        "type": "pause",
    },
    # === BLOC 2 : 10h05 - 11h05 ===
    {
        "id": 4,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_10h05_10h50.wav",
        "duration": 2862,
        "title": "Cours - Bloc 2 (10h05-10h50)",
        "type": "cours",
    },
    {
        "id": 5,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_10h50_11h00.wav",
        "duration": 600,
        "title": "Questions-Réponses IA (10h50-11h00)",
        "type": "qa",
    },
    {
        "id": 6,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_11h00_11h05.wav",
        "duration": 300,
        "title": "Pause (11h00-11h05)",
        "type": "pause",
    },
    # === BLOC 3 : 11h05 - 12h20 ===
    {
        "id": 7,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_11h05_12h00.wav",
        "duration": 3300,
        "title": "Cours - Bloc 3 (11h05-12h00)",
        "type": "cours",
    },
    {
        "id": 8,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_12h00_12h10.wav",
        "duration": 600,
        "title": "Questions-Réponses IA (12h00-12h10)",
        "type": "qa",
    },
    {
        "id": 9,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_12h10_12h20.wav",
        "duration": 600,
        "title": "Pause (12h10-12h20)",
        "type": "pause",
    },
    # === BLOC 4 : 12h20 - 14h45 ===
    {
        "id": 10,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_12h20_13h05.wav",
        "duration": 2700,
        "title": "Cours - Bloc 4 (12h20-13h05)",
        "type": "cours",
    },
    {
        "id": 11,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_13h05_13h15.wav",
        "duration": 600,
        "title": "Questions-Réponses IA (13h05-13h15)",
        "type": "qa",
    },
    {
        "id": 12,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_midi_13h15_14h45.wav",
        "duration": 5400,
        "title": "Pause déjeuner (13h15-14h45)",
        "type": "pause_midi",
    },
    # === BLOC 5 : 14h45 - 16h00 ===
    {
        "id": 13,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_14h45_15h45.wav",
        "duration": 3640,
        "title": "Cours - Bloc 5 (14h45-15h45)",
        "type": "cours",
    },
    {
        "id": 14,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_15h45_16h00.wav",
        "duration": 900,
        "title": "Questions-Réponses IA (15h45-16h00)",
        "type": "qa",
    },
    # === BLOC 6 : 16h00 - 17h25 ===
    {
        "id": 15,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_16h00_17h00.wav",
        "duration": 3600,
        "title": "Cours - Bloc 6 (16h00-17h00)",
        "type": "cours",
    },
    {
        "id": 16,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_17h00_17h15.wav",
        "duration": 900,
        "title": "Questions-Réponses IA (17h00-17h15)",
        "type": "qa",
    },
    {
        "id": 17,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_17h15_17h25.wav",
        "duration": 600,
        "title": "Pause (17h15-17h25)",
        "type": "pause",
    },
    # === BLOC 7 : 17h25 - 18h30 ===
    {
        "id": 18,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_17h25_18h15.wav",
        "duration": 3023,
        "title": "Cours - Bloc 7 (17h25-18h15)",
        "type": "cours",
    },
    {
        "id": 19,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_18h15_18h30.wav",
        "duration": 900,
        "title": "Questions-Réponses IA (18h15-18h30)",
        "type": "qa",
    },
]

logger.info(f"📋 Playlist configurée avec {len(COURS_PLAYLIST)} éléments")

# Création de la BDD si elle n'existe pas
logger.info("🗄️ Initialisation de la base de données...")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    logger.info("✅ Connexion à la base de données réussie")

    # Table des logs existante
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT,
        prenom TEXT,
        arrivee TEXT,
        depart TEXT
    )
    """
    )
    logger.info("✅ Table logs créée/vérifiée")

    # Table pour suivre les visites de /video
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER,
            timestamp TEXT
        )
        """
    )
    logger.info("✅ Table video_visits créée/vérifiée")

    # Table pour stocker l'heure de début du cours
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cours_config (
            id INTEGER PRIMARY KEY,
            heure_debut TEXT NOT NULL
        )
        """
    )
    logger.info("✅ Table cours_config créée/vérifiée")

    # Insérer une heure par défaut si la table est vide
    cursor.execute("SELECT COUNT(*) FROM cours_config")
    count = cursor.fetchone()[0]
    logger.info(f"📊 Nombre d'entrées dans cours_config: {count}")

    if count == 0:
        # Heure par défaut en heure française
        heure_defaut_naive = datetime(2025, 5, 28, 16, 35, 0)
        heure_defaut = FRANCE_TZ.localize(heure_defaut_naive).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cursor.execute(
            "INSERT INTO cours_config (id, heure_debut) VALUES (1, ?)", (heure_defaut,)
        )
        logger.info(f"✅ Heure par défaut insérée: {heure_defaut}")
    else:
        logger.info("ℹ️ Configuration cours déjà présente")

    conn.commit()
    conn.close()
    logger.info("✅ Base de données initialisée avec succès")

except Exception as e:
    logger.error(f"❌ Erreur lors de l'initialisation de la base: {e}")
    raise

# Dictionnaire pour stocker les utilisateurs connectés
connected_users = {}
logger.info("👥 Dictionnaire utilisateurs connectés initialisé")

# Variable globale pour stocker l'heure simulée
simulated_time_offset = None
logger.info("⏰ Variable simulation temps initialisée")


def get_current_simulated_time():
    """Retourne l'heure actuelle ou l'heure simulée EN HEURE FRANÇAISE"""
    try:
        if simulated_time_offset is not None:
            logger.debug(f"⏰ Utilisation temps simulé: {simulated_time_offset}")
            # S'assurer que la simulation a un timezone français
            if simulated_time_offset.tzinfo is None:
                result = FRANCE_TZ.localize(simulated_time_offset)
                logger.debug(f"⏰ Timezone ajouté au temps simulé: {result}")
                return result
            result = simulated_time_offset.astimezone(FRANCE_TZ)
            logger.debug(f"⏰ Temps simulé converti: {result}")
            return result

        # Heure actuelle en France
        result = datetime.now(FRANCE_TZ)
        logger.debug(f"⏰ Heure réelle française: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur get_current_simulated_time: {e}")
        return datetime.now(FRANCE_TZ)


def set_heure_debut_cours(nouvelle_heure):
    """Met à jour l'heure de début du cours dans la base de données"""
    try:
        logger.info(f"⏰ Mise à jour heure début cours: {nouvelle_heure}")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Si l'heure n'a pas de timezone, la considérer comme française
        if nouvelle_heure.tzinfo is None:
            nouvelle_heure = FRANCE_TZ.localize(nouvelle_heure)
            logger.debug(f"⏰ Timezone ajouté: {nouvelle_heure}")

        # Stocker en format string (sans timezone pour simplicité)
        heure_str = nouvelle_heure.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE cours_config SET heure_debut = ? WHERE id = 1", (heure_str,)
        )
        conn.commit()
        conn.close()
        logger.info(f"✅ Heure début cours mise à jour: {heure_str}")
    except Exception as e:
        logger.error(f"❌ Erreur set_heure_debut_cours: {e}")
        raise


def get_heure_debut_cours():
    """Récupère l'heure de début du cours EN HEURE FRANÇAISE"""
    try:
        logger.debug("🔍 Récupération heure début cours")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
        result = cursor.fetchone()
        conn.close()

        if result:
            # Interpréter l'heure stockée comme heure française
            dt_naive = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
            dt_fr = FRANCE_TZ.localize(dt_naive)
            logger.debug(f"✅ Heure début cours récupérée: {dt_fr}")
            return dt_fr
        else:
            # Fallback par défaut en heure française
            dt_naive = datetime(2025, 5, 28, 16, 35, 0)
            dt_fr = FRANCE_TZ.localize(dt_naive)
            logger.warning(f"⚠️ Utilisation heure par défaut: {dt_fr}")
            return dt_fr
    except Exception as e:
        logger.error(f"❌ Erreur get_heure_debut_cours: {e}")
        dt_naive = datetime(2025, 5, 28, 16, 35, 0)
        return FRANCE_TZ.localize(dt_naive)


def get_current_audio_info():
    """
    Détermine quel fichier audio doit être joué et à quelle position
    """
    try:
        logger.debug("🎵 Calcul info audio actuel")
        heure_debut_cours = get_heure_debut_cours()
        now = get_current_simulated_time()

        logger.debug(f"🎵 Heure début: {heure_debut_cours}")
        logger.debug(f"🎵 Heure actuelle: {now}")

        # S'assurer que les deux ont le même timezone
        if now.tzinfo is None:
            now = FRANCE_TZ.localize(now)
        if heure_debut_cours.tzinfo is None:
            heure_debut_cours = FRANCE_TZ.localize(heure_debut_cours)

        # Si le cours n'a pas encore commencé
        if now < heure_debut_cours:
            temps_restant = int((heure_debut_cours - now).total_seconds())
            logger.debug(
                f"🎵 Cours pas encore commencé, temps restant: {temps_restant}s"
            )
            return None, 0, temps_restant

        # Calculer le temps écoulé depuis le début du cours
        temps_ecoule = int((now - heure_debut_cours).total_seconds())
        logger.debug(f"🎵 Temps écoulé depuis début: {temps_ecoule}s")

        # Parcourir la playlist pour trouver l'audio actuel
        temps_cumule = 0
        for i, audio in enumerate(COURS_PLAYLIST):
            if temps_cumule + audio["duration"] > temps_ecoule:
                # C'est l'audio actuel
                offset_dans_audio = temps_ecoule - temps_cumule
                logger.info(
                    f"🎵 Audio actuel: {audio['title']} (ID: {audio['id']}) - Offset: {offset_dans_audio}s"
                )
                return audio, offset_dans_audio, 0
            temps_cumule += audio["duration"]
            logger.debug(f"🎵 Audio {i+1} passé, temps cumulé: {temps_cumule}s")

        # Si on a dépassé tous les audios, le cours est terminé
        logger.info("🎵 Cours terminé - tous les audios ont été joués")
        return None, 0, 0

    except Exception as e:
        logger.error(f"❌ Erreur dans get_current_audio_info: {e}")
        return None, 0, 0


# ========== AJOUTER CES LIGNES APRÈS LA DÉFINITION DE sync_all_clients_periodically() ==========
# ========== ET AVANT LES HANDLERS @socketio.on ==========


# ✅ ÉTAT GLOBAL CENTRALISÉ pour éviter les race conditions
class AudioSyncState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_audio = None
        self.current_offset = 0
        self.last_update_time = None
        self.pending_clients = set()  # Clients qui attendent une sync

    def update_state(self, audio_info, offset):
        """Met à jour l'état global de manière thread-safe"""
        with self.lock:
            old_audio_id = self.current_audio["id"] if self.current_audio else None
            new_audio_id = audio_info["id"] if audio_info else None

            # Détection changement de bloc
            audio_changed = old_audio_id != new_audio_id

            self.current_audio = audio_info
            self.current_offset = offset
            self.last_update_time = datetime.now(FRANCE_TZ)

            logger.info(
                f"🔄 État audio mis à jour - ID: {new_audio_id}, Offset: {offset}s"
            )

            return audio_changed

    def get_current_state(self):
        """Récupère l'état actuel de manière thread-safe"""
        with self.lock:
            if self.current_audio is None:
                return None, 0, False

            # Recalcul de l'offset basé sur le temps écoulé
            if self.last_update_time:
                elapsed = (
                    datetime.now(FRANCE_TZ) - self.last_update_time
                ).total_seconds()
                adjusted_offset = self.current_offset + int(elapsed)

                # Vérifier si on a dépassé la durée de l'audio actuel
                if adjusted_offset >= self.current_audio["duration"]:
                    logger.info(f"🔄 Audio terminé, recalcul nécessaire")
                    return None, 0, True  # Nécessite recalcul complet

                return self.current_audio, adjusted_offset, False

            return self.current_audio, self.current_offset, False


# Instance globale
audio_sync_state = AudioSyncState()


def smart_sync_clients(force_recalculate=False, target_client_sid=None):
    """
    Synchronise les clients de manière intelligente
    - force_recalculate: Force un nouveau calcul depuis get_current_audio_info()
    - target_client_sid: Synchronise seulement un client spécifique
    """
    try:
        logger.debug(
            f"🔄 Smart sync - Force recalc: {force_recalculate}, Target: {target_client_sid}"
        )

        if force_recalculate or audio_sync_state.current_audio is None:
            # Recalcul complet depuis la playlist
            audio_info, offset, _ = (
                get_current_audio_info()
            )  # ✅ _ au lieu de temps_restant
            audio_changed = audio_sync_state.update_state(audio_info, offset)
        else:
            # Utilisation de l'état existant avec ajustement temporel
            audio_info, offset, needs_recalc = audio_sync_state.get_current_state()
            audio_changed = False

            if needs_recalc:
                # Recalcul nécessaire (audio probablement terminé)
                audio_info, offset, _ = (
                    get_current_audio_info()
                )  # ✅ _ au lieu de temps_restant
                audio_changed = audio_sync_state.update_state(audio_info, offset)

        # Préparation du message de sync
        if audio_info:
            sync_message = {
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "offset": offset,
                "audio_changed": audio_changed,  # ✅ Info importante pour le frontend
            }

            if target_client_sid:
                # Sync d'un client spécifique
                socketio.emit("sync_audio", sync_message, room=target_client_sid)
                logger.info(
                    f"🎯 Sync client spécifique {target_client_sid} - Audio ID: {audio_info['id']}"
                )
            else:
                # Broadcast à tous les clients
                socketio.emit("sync_audio", sync_message)
                logger.info(
                    f"📡 Sync broadcast - Audio ID: {audio_info['id']}, Clients: {len(connected_users)}"
                )

                # ✅ Log détaillé pour débugger
                if audio_changed:
                    logger.warning(
                        f"🔄 CHANGEMENT AUDIO DÉTECTÉ ET DIFFUSÉ - Audio ID: {audio_info['id']}"
                    )
        else:
            # Cours pas commencé ou terminé
            if target_client_sid:
                socketio.emit(
                    "cours_not_started_or_finished", {}, room=target_client_sid
                )
            else:
                socketio.emit("cours_not_started_or_finished", {})
            logger.debug("🔄 Sync: Cours pas commencé ou terminé")

    except Exception as e:
        logger.error(f"❌ Erreur smart_sync_clients: {e}")


logger.info("✅ Système de synchronisation intelligent initialisé")


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


@app.route("/")
def index():
    logger.info("🏠 Accès page d'accueil")
    try:
        return render_template("index.html")
    except Exception as e:
        logger.error(f"❌ Erreur page d'accueil: {e}")
        return "Erreur lors du chargement de la page", 500


@app.route("/", methods=["POST"])
def index_post():
    try:
        nom = request.form.get("nom", "").strip()
        prenom = request.form.get("prenom", "").strip()

        logger.info(f"👤 Tentative connexion: {nom} {prenom}")

        if not nom or not prenom:
            logger.warning("⚠️ Nom ou prénom manquant")
            flash("Nom et prénom requis", "error")
            return render_template("index.html")

        session["nom"] = nom
        session["prenom"] = prenom
        # Enregistrement en heure française
        arrivee_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
        session["arrivee"] = arrivee_time

        logger.info(f"👤 Session créée pour {nom} {prenom} à {arrivee_time}")

        # Enregistrement arrivée
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (nom, prenom, arrivee) VALUES (?, ?, ?)",
            (nom, prenom, arrivee_time),
        )
        log_id = cursor.lastrowid
        session["log_id"] = log_id
        conn.commit()
        conn.close()

        logger.info(f"✅ Utilisateur enregistré en base avec ID: {log_id}")

        return redirect("/video")

    except Exception as e:
        logger.error(f"❌ Erreur connexion utilisateur: {e}")
        flash("Erreur lors de la connexion", "error")
        return render_template("index.html")


@app.route("/video")
def video():
    try:
        if "nom" not in session:
            logger.warning("⚠️ Accès /video sans session")
            return redirect("/")

        nom = session.get("nom")
        prenom = session.get("prenom")
        logger.info(f"🎥 Accès page vidéo par {nom} {prenom}")

        # ✅ NOUVEAU : Utiliser l'état global au lieu de recalculer
        audio_info, offset, needs_recalc = audio_sync_state.get_current_state()

        # Si recalcul nécessaire ou pas d'état, calculer
        if needs_recalc or audio_info is None:
            audio_info, offset, temps_restant = get_current_audio_info()
            if audio_info:
                audio_sync_state.update_state(audio_info, offset)
        else:
            # Pour les cas d'attente, on a besoin de temps_restant
            _, _, temps_restant = get_current_audio_info()

        logger.debug(
            f"🎥 Info audio: {audio_info['title'] if audio_info else 'None'}, offset: {offset}, temps_restant: {temps_restant if 'temps_restant' in locals() else 0}"
        )

        # Si le cours n'a pas encore commencé
        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours()
            heure_actuelle_simulee = get_current_simulated_time()

            logger.info(f"⏳ Cours pas encore commencé, attente de {temps_restant}s")

            return render_template(
                "attente.html",
                nom=nom,
                prenom=prenom,
                heure_debut=heure_debut_cours,
                temps_restant=temps_restant,
                heure_actuelle_simulee=heure_actuelle_simulee,
            )

        # Si le cours est terminé
        if audio_info is None:
            logger.info("🏁 Cours terminé")
            return render_template(
                "video.html",
                nom=nom,
                prenom=prenom,
                audio_filename="",
                audio_title="Cours terminé",
                offset=0,
                audio_id=0,
                temps_restant=0,
                cours_termine=True,
            )

        # Le cours est en cours
        logger.info(f"▶️ Cours en cours: {audio_info['title']}")
        return render_template(
            "video.html",
            nom=nom,
            prenom=prenom,
            audio_filename=audio_info["filename"],
            audio_title=audio_info["title"],
            offset=offset,
            audio_id=audio_info["id"],
            temps_restant=0,
            cours_termine=False,
        )

    except Exception as e:
        logger.error(f"❌ Erreur page vidéo: {e}")
        return "Erreur lors du chargement de la page vidéo", 500


@app.route("/api/cours-status")
def cours_status():
    """API endpoint pour obtenir l'état actuel du cours - Version thread-safe"""
    try:
        logger.debug("📊 Demande statut cours (via état global)")

        # ✅ NOUVEAU : Utiliser l'état global au lieu de recalculer
        audio_info, offset, needs_recalc = audio_sync_state.get_current_state()

        if needs_recalc or audio_info is None:
            # Recalcul si nécessaire
            audio_info, offset, temps_restant = get_current_audio_info()
            if audio_info:
                audio_sync_state.update_state(audio_info, offset)
        else:
            # Pour déterminer waiting vs finished, on a besoin de temps_restant
            _, _, temps_restant = get_current_audio_info()

        if audio_info is None and temps_restant > 0:
            result = {"status": "waiting", "temps_restant": temps_restant}
        elif audio_info is None:
            result = {"status": "finished"}
        else:
            result = {
                "status": "playing",
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "audio_title": audio_info["title"],
                "offset": offset,
            }

        logger.debug(f"📊 Statut cours: {result['status']}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Erreur API cours-status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/intro")
def intro():
    try:
        if "nom" not in session:
            logger.warning("⚠️ Accès /intro sans session")
            return redirect("/")

        nom = session.get("nom")
        prenom = session.get("prenom")
        logger.info(f"📺 Accès page intro par {nom} {prenom}")

        return render_template(
            "video2.html",
            nom=nom,
            prenom=prenom,
        )
    except Exception as e:
        logger.error(f"❌ Erreur page intro: {e}")
        return "Erreur lors du chargement de la page intro", 500


@app.route("/logout")
def logout():
    try:
        nom = session.get("nom", "Inconnu")
        prenom = session.get("prenom", "")
        logger.info(f"👋 Déconnexion {nom} {prenom}")

        if "log_id" in session:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            # Départ en heure française
            depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE logs SET depart=? WHERE id=?", (depart, session["log_id"])
            )
            conn.commit()
            conn.close()
            logger.info(f"✅ Départ enregistré: {depart}")

        session.clear()
        return redirect("/")

    except Exception as e:
        logger.error(f"❌ Erreur déconnexion: {e}")
        session.clear()
        return redirect("/")


@app.route("/deconnexion-auto", methods=["POST"])
def deconnexion_auto():
    try:
        nom = session.get("nom", "Inconnu")
        logger.info(f"🔄 Déconnexion automatique {nom}")

        if "log_id" in session:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE logs SET depart=? WHERE id=?",
                    (depart, session["log_id"]),
                )
                conn.commit()
                logger.info(f"✅ Déconnexion auto enregistrée: {depart}")

        return "", 204

    except Exception as e:
        logger.error(f"❌ Erreur déconnexion auto: {e}")
        return "", 500


@app.route("/admin", methods=["GET", "POST"])
def admin():
    try:
        # Vérification d'authentification ADMIN
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative accès admin sans authentification")
            return redirect("/login_admin")

        logger.info("👑 Accès page admin")
        prenom_recherche = request.args.get("prenom", "")

        if prenom_recherche:
            logger.debug(f"🔍 Recherche admin par prénom: {prenom_recherche}")

        # Récupération de l'heure actuelle du cours
        heure_debut_cours = get_heure_debut_cours()
        logger.debug(f"⏰ Heure début cours admin: {heure_debut_cours}")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        if prenom_recherche:
            cursor.execute(
                "SELECT * FROM logs WHERE prenom LIKE ?",
                ("%" + prenom_recherche + "%",),
            )
        else:
            cursor.execute("SELECT * FROM logs")

        logs = cursor.fetchall()
        conn.close()

        logger.debug(f"📊 {len(logs)} logs récupérés")

        total_seconds = 0
        logs_with_duration = []

        for log in logs:
            id_, nom, prenom, arrivee, depart = log
            if depart:
                dt_arrivee = datetime.strptime(arrivee, "%Y-%m-%d %H:%M:%S")
                dt_depart = datetime.strptime(depart, "%Y-%m-%d %H:%M:%S")
                duration = dt_depart - dt_arrivee
                seconds = duration.total_seconds()
                total_seconds += seconds

                minutes = int(seconds // 60)
                secondes = int(seconds % 60)
                duree = f"{minutes} min {secondes} sec"
            else:
                duree = "En cours..."
            logs_with_duration.append((id_, nom, prenom, arrivee, depart, duree))

        # Calcul du temps total cumulé en h/min/sec
        total_minutes = int(total_seconds // 60)
        total_heures = total_minutes // 60
        total_minutes_restant = total_minutes % 60
        total_secondes = int(total_seconds % 60)
        temps_total_format = (
            f"{total_heures} h {total_minutes_restant} min {total_secondes} sec"
        )

        logger.debug(f"📊 Temps total calculé: {temps_total_format}")

        return render_template(
            "admin.html",
            logs=logs_with_duration,
            prenom_recherche=prenom_recherche,
            temps_total=temps_total_format,
            heure_debut_cours=heure_debut_cours,
        )

    except Exception as e:
        logger.error(f"❌ Erreur page admin: {e}")
        return "Erreur lors du chargement de la page admin", 500


@app.route("/admin/config_cours", methods=["POST"])
def config_cours():
    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative config cours sans authentification admin")
            return redirect("/login_admin")

        logger.info("⚙️ Configuration cours demandée")

        date_str = request.form.get("date_cours", "").strip()
        heure_str = request.form.get("heure_cours", "").strip()

        logger.debug(f"⚙️ Données reçues - Date: {date_str}, Heure: {heure_str}")

        if not date_str or not heure_str:
            logger.warning("⚠️ Date ou heure manquante")
            flash("Veuillez renseigner la date et l'heure.", "error")
            return redirect("/admin")

        datetime_str = f"{date_str} {heure_str}:00"
        logger.debug(f"⚙️ DateTime string: {datetime_str}")

        nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)

        logger.info(f"⚙️ Nouvelle heure calculée: {nouvelle_heure_fr}")

        # Sauvegarder en base
        set_heure_debut_cours(nouvelle_heure_fr)

        flash(
            f"Heure de début du cours mise à jour : {nouvelle_heure_fr.strftime('%d/%m/%Y à %H:%M')} (heure française)",
            "success",
        )
        logger.info("✅ Configuration cours mise à jour avec succès")

    except ValueError as e:
        logger.error(f"❌ Format date/heure invalide: {e}")
        flash("Format de date/heure invalide.", "error")
    except Exception as e:
        logger.error(f"❌ Erreur configuration cours: {e}")
        flash(f"Erreur lors de la mise à jour : {str(e)}", "error")

    return redirect("/admin")


@app.route("/export_excel")
def export_excel():
    try:
        logger.info("📊 Export Excel demandé")
        prenom = request.args.get("prenom", "")

        if prenom:
            logger.debug(f"📊 Export filtré par prénom: {prenom}")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        if prenom:
            cursor.execute(
                "SELECT * FROM logs WHERE prenom LIKE ?", ("%" + prenom + "%",)
            )
        else:
            cursor.execute("SELECT * FROM logs")

        rows = cursor.fetchall()
        conn.close()

        logger.debug(f"📊 {len(rows)} lignes à exporter")

        wb = Workbook()
        ws = wb.active
        ws.append(["ID", "Nom", "Prénom", "Arrivée", "Départ", "Durée"])

        for row in rows:
            id_, nom, prenom, arrivee, depart = row
            if depart:
                dt1 = datetime.strptime(arrivee, "%Y-%m-%d %H:%M:%S")
                dt2 = datetime.strptime(depart, "%Y-%m-%d %H:%M:%S")
                duration = dt2 - dt1
                minutes = int(duration.total_seconds() // 60)
                secondes = int(duration.total_seconds() % 60)
                duree = f"{minutes} min {secondes} sec"
            else:
                duree = "En cours..."
            ws.append([id_, nom, prenom, arrivee, depart or "", duree])

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        wb.save(tmp.name)
        tmp.seek(0)

        logger.info("✅ Export Excel généré avec succès")

        return send_file(
            tmp.name,
            as_attachment=True,
            download_name="historique.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        logger.error(f"❌ Erreur export Excel: {e}")
        return "Erreur lors de l'export", 500


@app.route("/login_admin", methods=["GET", "POST"])
def login_admin():
    try:
        if session.get("is_admin"):
            logger.info("👑 Admin déjà connecté, redirection")
            return redirect("/admin")

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()

            logger.info(f"🔐 Tentative connexion admin: {username}")

            if username == "admin" and password == "secret123":
                session["is_admin"] = True
                session.permanent = True
                flash("Connexion admin réussie !", "success")
                logger.info("✅ Connexion admin réussie")
                return redirect("/admin")
            else:
                logger.warning("❌ Échec connexion admin - identifiants incorrects")
                flash("Identifiant ou mot de passe incorrect.", "error")

        return render_template("login_admin.html")

    except Exception as e:
        logger.error(f"❌ Erreur login admin: {e}")
        return "Erreur lors de la connexion admin", 500


@app.route("/logout_admin")
def logout_admin():
    try:
        logger.info("👑 Déconnexion admin")
        session.pop("is_admin", None)
        return redirect("/login_admin")
    except Exception as e:
        logger.error(f"❌ Erreur logout admin: {e}")
        return redirect("/login_admin")


@app.route("/admin/simulate-current-time", methods=["POST"])
def simulate_current_time():
    """Simule l'heure actuelle pour le debug"""
    global simulated_time_offset

    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative simulation temps sans authentification admin")
            return jsonify({"success": False, "error": "Accès refusé"}), 403

        logger.info("⏰ Simulation temps demandée")

        data = request.get_json()
        simulated_time_str = data.get("simulated_current_time", "").strip()

        logger.debug(f"⏰ Temps reçu pour simulation: {simulated_time_str}")

        if not simulated_time_str:
            logger.warning("⚠️ Heure manquante pour simulation")
            return jsonify({"success": False, "error": "Heure manquante"}), 400

        try:
            simulated_time_naive = datetime.strptime(
                simulated_time_str, "%Y-%m-%dT%H:%M:%S"
            )
        except ValueError:
            try:
                simulated_time_naive = datetime.strptime(
                    simulated_time_str, "%Y-%m-%dT%H:%M"
                )
            except ValueError:
                logger.error(f"❌ Format date invalide: {simulated_time_str}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Format de date invalide: {simulated_time_str}",
                        }
                    ),
                    400,
                )

        simulated_time_offset = FRANCE_TZ.localize(simulated_time_naive)

        logger.info(f"✅ Heure actuelle simulée définie: {simulated_time_offset}")

        return jsonify(
            {
                "success": True,
                "message": f"Heure actuelle simulée: {simulated_time_offset.strftime('%Y-%m-%d %H:%M:%S')} (heure française)",
            }
        )

    except Exception as e:
        logger.error(f"❌ Erreur simulation heure actuelle: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/reset-simulation", methods=["POST"])
def reset_simulation():
    """Remet l'heure réelle"""
    global simulated_time_offset

    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative reset simulation sans authentification admin")
            return jsonify({"success": False, "error": "Accès refusé"}), 403

        logger.info("⏰ Reset simulation demandé")
        simulated_time_offset = None
        logger.info("✅ Simulation désactivée, heure réelle restaurée")

        return jsonify(
            {
                "success": True,
                "message": "Simulation désactivée, heure réelle restaurée",
            }
        )

    except Exception as e:
        logger.error(f"❌ Erreur reset simulation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/debug/cours-info")
def debug_cours_info():
    """Route de debug pour voir l'état actuel du cours"""
    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative accès debug sans authentification admin")
            return "Accès refusé - Connectez-vous d'abord en tant qu'admin", 403

        logger.info("🐛 Accès page debug cours")

        audio_info, offset, temps_restant = get_current_audio_info()
        heure_debut = get_heure_debut_cours()
        heure_actuelle = get_current_simulated_time()

        # Calculer des statistiques supplémentaires
        total_duration = sum(item["duration"] for item in COURS_PLAYLIST)
        elapsed_time = max(0, int((heure_actuelle - heure_debut).total_seconds()))

        # Déterminer le statut
        if audio_info is None and temps_restant > 0:
            status = "waiting"
        elif audio_info is None:
            status = "finished"
        else:
            status = "playing"

        # Calculer le pourcentage de progression
        progress_percent = 0
        if audio_info and audio_info["duration"] > 0:
            progress_percent = (offset / audio_info["duration"]) * 100

        logger.debug(f"🐛 Debug info - Status: {status}, Users: {len(connected_users)}")

        return render_template(
            "debug_cours.html",
            heure_debut=heure_debut.strftime("%Y-%m-%d %H:%M:%S"),
            heure_actuelle=heure_actuelle.strftime("%Y-%m-%d %H:%M:%S"),
            audio_info=audio_info,
            offset=offset,
            temps_restant=temps_restant,
            users_count=len(connected_users),
            users_list=list(connected_users.values()),
            playlist=COURS_PLAYLIST,
            status=status,
            total_duration=total_duration,
            elapsed_time=elapsed_time,
            progress_percent=round(progress_percent, 1),
        )

    except Exception as e:
        logger.error(f"❌ Erreur page debug: {e}")
        return "Erreur lors du chargement du debug", 500


# ========== GESTION DES WEBSOCKETS POUR LA SYNCHRONISATION ==========


@socketio.on("connect")
def handle_connect():
    try:
        logger.info(f"🔌 Client connecté: {request.sid}")
        emit("participants_update", {"count": len(connected_users)})
    except Exception as e:
        logger.error(f"❌ Erreur connect handler: {e}")


@socketio.on("disconnect")
def handle_disconnect():
    try:
        logger.info(f"🔌 Client déconnecté: {request.sid}")
        username = connected_users.pop(request.sid, None)

        # ✅ AJOUT: Nettoyage des pending clients dans l'état global
        audio_sync_state.pending_clients.discard(request.sid)

        if username:
            logger.info(f"👤 Utilisateur {username} déconnecté")
            socketio.emit("user_disconnected", {"username": username})

        socketio.emit("participants_update", {"count": len(connected_users)})
        logger.debug(f"📊 Utilisateurs restants: {list(connected_users.values())}")

    except Exception as e:
        logger.error(f"❌ Erreur disconnect handler: {e}")


@socketio.on("user_connected")
def handle_user_connected(data):
    try:
        username = data.get("username", "Anonyme")

        logger.info(f"🎯 Événement user_connected reçu pour: {username}")
        logger.debug(f"🆔 SID: {request.sid}")

        # Nettoyer les anciennes connexions de cet utilisateur
        old_sids = [sid for sid, user in connected_users.items() if user == username]
        for old_sid in old_sids:
            connected_users.pop(old_sid, None)
            logger.debug(f"🧹 Nettoyage ancienne connexion: {old_sid}")

        # Ajouter la nouvelle connexion
        connected_users[request.sid] = username
        logger.info(f"✅ Utilisateur {username} ajouté avec SID: {request.sid}")
        logger.debug(f"📊 Total utilisateurs connectés: {len(connected_users)}")
        logger.debug(f"👥 Liste: {list(connected_users.values())}")

        socketio.emit("participants_update", {"count": len(connected_users)})

        # ✅ NOUVEAU: Synchronisation via smart_sync au lieu de recalcul direct
        # Cette fonction utilise l'état global et force un recalcul seulement pour ce client
        smart_sync_clients(force_recalculate=True, target_client_sid=request.sid)

        logger.info(f"🎵 Synchronisation immédiate demandée pour {username}")

    except Exception as e:
        logger.error(f"❌ Erreur user_connected handler: {e}")


@socketio.on("get_participants")
def handle_get_participants():
    try:
        participants_list = list(connected_users.values())
        logger.debug(
            f"👥 Liste participants demandée: {len(participants_list)} utilisateurs"
        )
        emit(
            "participants_list",
            {"count": len(participants_list), "users": participants_list},
        )
    except Exception as e:
        logger.error(f"❌ Erreur get_participants handler: {e}")


@socketio.on("sync_request")
def handle_sync_request():
    """Synchronise l'audio pour un client qui en fait la demande"""
    try:
        username = connected_users.get(request.sid, "Inconnu")
        logger.info(f"🔄 Demande sync de {username} (SID: {request.sid})")

        # ✅ NOUVEAU: Sync intelligente pour ce client seulement
        smart_sync_clients(force_recalculate=False, target_client_sid=request.sid)

    except Exception as e:
        logger.error(f"❌ Erreur sync_request handler: {e}")


@socketio.on("cours_finished_check")
def handle_cours_finished_check():
    """Vérifie si le cours est terminé"""
    try:
        username = connected_users.get(request.sid, "Inconnu")
        logger.debug(f"🏁 Vérification fin de cours par {username}")

        # ✅ NOUVEAU: Utilise l'état global au lieu de recalculer
        audio_info, _, needs_recalc = audio_sync_state.get_current_state()

        # Si recalcul nécessaire, on vérifie vraiment
        if needs_recalc or audio_info is None:
            audio_info, _, _ = get_current_audio_info()
            if audio_info:
                audio_sync_state.update_state(audio_info, 0)

        if audio_info is None:
            emit("cours_finished", {})
            logger.debug(f"🏁 Cours confirmé terminé pour {username}")
        else:
            logger.debug(
                f"🏁 Cours encore en cours pour {username} - Audio: {audio_info['title']}"
            )

    except Exception as e:
        logger.error(f"❌ Erreur cours_finished_check handler: {e}")


@socketio.on("send_question")
def handle_send_question(data):
    try:
        username = data.get("username", "Anonyme")
        question = data.get("question", "").strip()

        logger.info(f"❓ Question reçue de {username}: {question[:50]}...")

        if not question:
            logger.warning("⚠️ Question vide reçue")
            return

        # Timestamp en heure française
        timestamp = datetime.now(FRANCE_TZ).strftime("%H:%M:%S")

        # Diffuser la question de l'utilisateur à tous les clients
        socketio.emit(
            "receive_question",
            {"username": username, "question": question, "timestamp": timestamp},
        )
        logger.debug(f"📢 Question diffusée à tous les clients")

        # ✅ Appel au service RAG externe
        try:
            logger.info(f"🤖 Appel au service RAG externe pour: {question[:30]}...")

            response_text = call_rag_service(question)

            logger.info(f"✅ RAG Response reçue: {response_text[:50]}...")

            # Diffuser la réponse textuelle de l'agent
            socketio.emit(
                "receive_question",
                {
                    "username": "Professeur",
                    "question": response_text,
                    "timestamp": datetime.now(FRANCE_TZ).strftime("%H:%M:%S"),
                },
            )
            logger.debug("📢 Réponse RAG diffusée à tous les clients")

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'appel RAG externe: {e}")
            socketio.emit(
                "receive_question",
                {
                    "username": "Alain",
                    "question": "Désolé, une erreur est survenue avec le système de réponse.",
                    "timestamp": datetime.now(FRANCE_TZ).strftime("%H:%M:%S"),
                },
            )

    except Exception as e:
        logger.error(f"❌ Erreur send_question handler: {e}")


# ❌ SUPPRIMER CES LIGNES (l'ancien thread problématique) :
# try:
#     sync_thread = threading.Thread(target=sync_all_clients_periodically, daemon=True)
#     sync_thread.start()
#     logger.info("🔄 Thread synchronisation automatique démarré")
# except Exception as e:
#     logger.error(f"❌ Erreur démarrage thread synchronisation: {e}")


# ✅ REMPLACER PAR CES LIGNES (nouveau thread intelligent) :
def intelligent_audio_monitor():
    """Thread qui surveille les changements d'audio et synchronise uniquement quand nécessaire"""
    logger.info("🔄 Démarrage moniteur audio intelligent")
    last_audio_id = None

    while True:
        try:
            if connected_users:  # Seulement si des clients sont connectés
                # Vérification légère de l'état actuel
                current_audio, _, needs_recalc = audio_sync_state.get_current_state()

                if needs_recalc or current_audio is None:
                    # Recalcul nécessaire
                    audio_info, offset, _ = get_current_audio_info()
                    current_audio_id = audio_info["id"] if audio_info else None

                    # Détection changement de bloc
                    if last_audio_id != current_audio_id:
                        logger.warning(
                            f"🚨 CHANGEMENT AUDIO DÉTECTÉ: {last_audio_id} → {current_audio_id}"
                        )
                        smart_sync_clients(force_recalculate=True)  # Broadcast à tous
                        last_audio_id = current_audio_id
                    elif needs_recalc:
                        # Mise à jour de l'état sans changement d'audio
                        audio_sync_state.update_state(audio_info, offset)
                else:
                    # État stable, vérifier juste l'ID pour les changements
                    current_audio_id = current_audio["id"] if current_audio else None
                    if last_audio_id != current_audio_id:
                        logger.warning(
                            f"🚨 CHANGEMENT AUDIO DÉTECTÉ (état stable): {last_audio_id} → {current_audio_id}"
                        )
                        smart_sync_clients(force_recalculate=True)  # Broadcast à tous
                        last_audio_id = current_audio_id

            time.sleep(5)  # Vérification toutes les 5 secondes

        except Exception as e:
            logger.error(f"❌ Erreur moniteur audio intelligent: {e}")
            time.sleep(5)


# Démarrer le nouveau moniteur intelligent
try:
    intelligent_monitor_thread = threading.Thread(
        target=intelligent_audio_monitor, daemon=True
    )
    intelligent_monitor_thread.start()
    logger.info("🔄 Thread moniteur audio intelligent démarré")
except Exception as e:
    logger.error(f"❌ Erreur démarrage moniteur intelligent: {e}")


# ✅ Configuration pour Azure App Service
if __name__ == "__main__":
    try:
        # Port fourni par Azure (ou local)
        port = int(os.environ.get("PORT", 5000))

        # Détecter si on est en production via une variable d'environnement
        is_production = os.environ.get(
            "WEBSITE_SITE_NAME"
        )  # Variable Azure automatique

        logger.info(f"🚀 Démarrage sur le port {port}")
        logger.info(f"🏭 Mode: {'Production' if is_production else 'Développement'}")
        logger.info(
            f"🌐 Variables d'environnement Azure détectées: {bool(is_production)}"
        )

        # Log des variables d'environnement importantes (sans révéler les valeurs sensibles)
        env_vars = [
            "WEBSITE_SITE_NAME",
            "PORT",
            "RAG_SERVICE_URL",
            "AZURE_SQL_CONNECTION_STRING",
        ]
        for var in env_vars:
            value = os.environ.get(var)
            if value:
                if "CONNECTION_STRING" in var or "SECRET" in var:
                    logger.info(f"🔧 {var}: ***[MASQUÉ]***")
                else:
                    logger.info(f"🔧 {var}: {value}")
            else:
                logger.info(f"🔧 {var}: NON DÉFINI")

        # SocketIO avec Eventlet
        logger.info("🚀 Lancement de l'application avec SocketIO...")
        socketio.run(
            app,
            host="0.0.0.0",
            port=port,
            debug=not is_production,  # Debug OFF en production
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )

    except Exception as e:
        logger.error(f"❌ Erreur critique au démarrage: {e}")
        raise
