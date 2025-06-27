# main_app.py - Version Azure
import pytz
import os

# Fuseau horaire français
FRANCE_TZ = pytz.timezone("Europe/Paris")

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

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_secret_key_for_dev")

# ✅ Configuration Azure - URL du service RAG
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://127.0.0.1:7000")
print(f"🔗 RAG Service URL: {RAG_SERVICE_URL}")

# ✅ Base de données - SQLite local en dev, Azure SQL en prod
if os.getenv("AZURE_SQL_CONNECTION_STRING"):
    # TODO: Configuration Azure SQL Database
    print("🗄️ Mode Azure SQL Database")
    DB_PATH = "/tmp/database.db"
else:
    print("🗄️ Mode SQLite local (développement)")
    DB_PATH = "/tmp/database.db"

# SocketIO configuration
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Configuration du cours - PLAYLIST DES AUDIOS
# Configuration du cours - PLAYLIST DES AUDIOS (Azure Storage)
COURS_PLAYLIST = [
    # === BLOC 1 : 9h00 - 10h05 ===
    {
        "id": 1,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_9h00_9h45.wav",
        "duration": 2700,  # 45 minutes (9h00 à 9h45)
        "title": "Cours - Bloc 1 (9h00-9h45)",
        "type": "cours",
    },
    {
        "id": 2,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_9h45_9h55.wav",
        "duration": 600,  # 10 minutes (9h45 à 9h55)
        "title": "Questions-Réponses IA (9h45-9h55)",
        "type": "qa",
    },
    {
        "id": 3,
        "filename": "https://formationaudios.blob.core.windows.net/audios/pause_9h55_10h05.wav",
        "duration": 600,  # 10 minutes (9h55 à 10h05)
        "title": "Pause (9h55-10h05)",
        "type": "pause",
    },
    # === BLOC 2 : 10h05 - 11h05 ===
    {
        "id": 4,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_10h05_10h50.wav",
        "duration": 2862,  # 45 minutes (10h05 à 10h50)
        "title": "Cours - Bloc 2 (10h05-10h50)",
        "type": "cours",
    },
    {
        "id": 5,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_10h50_11h00.wav",
        "duration": 600,  # 10 minutes (10h50 à 11h00)
        "title": "Questions-Réponses IA (10h50-11h00)",
        "type": "qa",
    },
    {
        "id": 6,
        "filename": "https://formationaudios.blob.core.windows.net/audios/pause_11h00_11h05.wav",
        "duration": 300,  # 5 minutes (11h00 à 11h05)
        "title": "Pause (11h00-11h05)",
        "type": "pause",
    },
    # === BLOC 3 : 11h05 - 12h20 ===
    {
        "id": 7,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_11h05_12h00.wav",
        "duration": 3300,  # 55 minutes (11h05 à 12h00)
        "title": "Cours - Bloc 3 (11h05-12h00)",
        "type": "cours",
    },
    {
        "id": 8,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_12h00_12h10.wav",
        "duration": 600,  # 10 minutes (12h00 à 12h10)
        "title": "Questions-Réponses IA (12h00-12h10)",
        "type": "qa",
    },
    {
        "id": 9,
        "filename": "https://formationaudios.blob.core.windows.net/audios/pause_12h10_12h20.wav",
        "duration": 600,  # 10 minutes (12h10 à 12h20)
        "title": "Pause (12h10-12h20)",
        "type": "pause",
    },
    # === BLOC 4 : 12h20 - 14h45 ===
    {
        "id": 10,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_12h20_13h05.wav",
        "duration": 2700,  # 45 minutes (12h20 à 13h05)
        "title": "Cours - Bloc 4 (12h20-13h05)",
        "type": "cours",
    },
    {
        "id": 11,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_13h05_13h15.wav",
        "duration": 600,  # 10 minutes (13h05 à 13h15)
        "title": "Questions-Réponses IA (13h05-13h15)",
        "type": "qa",
    },
    {
        "id": 12,
        "filename": "https://formationaudios.blob.core.windows.net/audios/pause_midi_13h15_14h45.wav",
        "duration": 5400,  # 90 minutes (13h15 à 14h45)
        "title": "Pause déjeuner (13h15-14h45)",
        "type": "pause_midi",
    },
    # === BLOC 5 : 14h45 - 16h00 ===
    {
        "id": 13,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_14h45_15h45.wav",
        "duration": 3640,  # 60 minutes (14h45 à 15h45)
        "title": "Cours - Bloc 5 (14h45-15h45)",
        "type": "cours",
    },
    {
        "id": 14,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_15h45_16h00.wav",
        "duration": 900,  # 15 minutes (15h45 à 16h00)
        "title": "Questions-Réponses IA (15h45-16h00)",
        "type": "qa",
    },
    # === BLOC 6 : 16h00 - 17h25 ===
    {
        "id": 15,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_16h00_17h00.wav",
        "duration": 3600,  # 60 minutes (16h00 à 17h00)
        "title": "Cours - Bloc 6 (16h00-17h00)",
        "type": "cours",
    },
    {
        "id": 16,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_17h00_17h15.wav",
        "duration": 900,  # 15 minutes (17h00 à 17h15)
        "title": "Questions-Réponses IA (17h00-17h15)",
        "type": "qa",
    },
    {
        "id": 17,
        "filename": "https://formationaudios.blob.core.windows.net/audios/pause_17h15_17h25.wav",
        "duration": 600,  # 10 minutes (17h15 à 17h25)
        "title": "Pause (17h15-17h25)",
        "type": "pause",
    },
    # === BLOC 7 : 17h25 - 18h30 ===
    {
        "id": 18,
        "filename": "https://formationaudios.blob.core.windows.net/audios/cours_17h25_18h15.wav",
        "duration": 3023,  # 50 minutes (17h25 à 18h15)
        "title": "Cours - Bloc 7 (17h25-18h15)",
        "type": "cours",
    },
    {
        "id": 19,
        "filename": "https://formationaudios.blob.core.windows.net/audios/qa_18h15_18h30.wav",
        "duration": 900,  # 15 minutes (18h15 à 18h30)
        "title": "Questions-Réponses IA (18h15-18h30)",
        "type": "qa",
    },
]

# Création de la BDD si elle n'existe pas
# os.makedirs("data", exist_ok=True)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

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

# Table pour stocker l'heure de début du cours
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS cours_config (
        id INTEGER PRIMARY KEY,
        heure_debut TEXT NOT NULL
    )
    """
)

# Insérer une heure par défaut si la table est vide
cursor.execute("SELECT COUNT(*) FROM cours_config")
if cursor.fetchone()[0] == 0:
    # Heure par défaut en heure française
    heure_defaut_naive = datetime(2025, 5, 28, 16, 35, 0)
    heure_defaut = FRANCE_TZ.localize(heure_defaut_naive).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO cours_config (id, heure_debut) VALUES (1, ?)", (heure_defaut,)
    )

conn.commit()
conn.close()

# Dictionnaire pour stocker les utilisateurs connectés
connected_users = {}

# Variable globale pour stocker l'heure simulée
simulated_time_offset = None


def get_current_simulated_time():
    """Retourne l'heure actuelle ou l'heure simulée EN HEURE FRANÇAISE"""
    if simulated_time_offset is not None:
        # S'assurer que la simulation a un timezone français
        if simulated_time_offset.tzinfo is None:
            return FRANCE_TZ.localize(simulated_time_offset)
        return simulated_time_offset.astimezone(FRANCE_TZ)

    # Heure actuelle en France
    return datetime.now(FRANCE_TZ)


def set_heure_debut_cours(nouvelle_heure):
    """Met à jour l'heure de début du cours dans la base de données"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Si l'heure n'a pas de timezone, la considérer comme française
    if nouvelle_heure.tzinfo is None:
        nouvelle_heure = FRANCE_TZ.localize(nouvelle_heure)

    # Stocker en format string (sans timezone pour simplicité)
    heure_str = nouvelle_heure.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE cours_config SET heure_debut = ? WHERE id = 1", (heure_str,))
    conn.commit()
    conn.close()


def get_heure_debut_cours():
    """Récupère l'heure de début du cours EN HEURE FRANÇAISE"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
    result = cursor.fetchone()
    conn.close()

    if result:
        # Interpréter l'heure stockée comme heure française
        dt_naive = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        return FRANCE_TZ.localize(dt_naive)
    else:
        # Fallback par défaut en heure française
        dt_naive = datetime(2025, 5, 28, 16, 35, 0)
        return FRANCE_TZ.localize(dt_naive)


def get_current_audio_info():
    """
    Détermine quel fichier audio doit être joué et à quelle position
    """
    try:
        heure_debut_cours = get_heure_debut_cours()
        now = get_current_simulated_time()

        # S'assurer que les deux ont le même timezone
        if now.tzinfo is None:
            now = FRANCE_TZ.localize(now)
        if heure_debut_cours.tzinfo is None:
            heure_debut_cours = FRANCE_TZ.localize(heure_debut_cours)

        # Si le cours n'a pas encore commencé
        if now < heure_debut_cours:
            return None, 0, int((heure_debut_cours - now).total_seconds())

        # Calculer le temps écoulé depuis le début du cours
        temps_ecoule = int((now - heure_debut_cours).total_seconds())

        # Parcourir la playlist pour trouver l'audio actuel
        temps_cumule = 0
        for audio in COURS_PLAYLIST:
            if temps_cumule + audio["duration"] > temps_ecoule:
                # C'est l'audio actuel
                offset_dans_audio = temps_ecoule - temps_cumule
                return audio, offset_dans_audio, 0
            temps_cumule += audio["duration"]

        # Si on a dépassé tous les audios, le cours est terminé
        return None, 0, 0

    except Exception as e:
        print(f"Erreur dans get_current_audio_info: {e}")
        return None, 0, 0


def sync_all_clients_periodically():
    """Fonction qui synchronise tous les clients toutes les 10 secondes"""
    while True:
        try:
            if connected_users:  # Seulement s'il y a des utilisateurs connectés
                audio_info, offset, _ = get_current_audio_info()

                if audio_info:
                    socketio.emit(
                        "sync_audio",
                        {
                            "audio_id": audio_info["id"],
                            "audio_filename": audio_info["filename"],
                            "offset": offset,
                        },
                    )
                    print(
                        f"Synchronisation automatique - Audio ID: {audio_info['id']}, Offset: {offset}s"
                    )

        except Exception as e:
            print(f"Erreur lors de la synchronisation automatique: {e}")

        time.sleep(10)  # Attendre 10 secondes


def call_rag_service(question):
    """Appel au service RAG externe"""
    try:
        print(f"🔍 Appel au service RAG: {question}")
        response = requests.post(
            f"{RAG_SERVICE_URL}/ask", json={"question": question}, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        return data.get("answer_text", "Désolé, je n'ai pas pu obtenir de réponse.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur service RAG: {e}")
        return "Désolé, le service de réponse est temporairement indisponible."
    except Exception as e:
        print(f"❌ Erreur inattendue RAG: {e}")
        return "Désolé, une erreur est survenue."


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/", methods=["POST"])
def index_post():
    nom = request.form["nom"]
    prenom = request.form["prenom"]
    session["nom"] = nom
    session["prenom"] = prenom
    # Enregistrement en heure française
    session["arrivee"] = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # Enregistrement arrivée
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (nom, prenom, arrivee) VALUES (?, ?, ?)",
        (nom, prenom, session["arrivee"]),
    )
    session["log_id"] = cursor.lastrowid
    conn.commit()
    conn.close()

    return redirect("/video")


@app.route("/video")
def video():
    if "nom" not in session:
        return redirect("/")

    audio_info, offset, temps_restant = get_current_audio_info()

    # Si le cours n'a pas encore commencé
    if audio_info is None and temps_restant > 0:
        heure_debut_cours = get_heure_debut_cours()
        heure_actuelle_simulee = get_current_simulated_time()

        return render_template(
            "attente.html",
            nom=session["nom"],
            prenom=session["prenom"],
            heure_debut=heure_debut_cours,
            temps_restant=temps_restant,
            heure_actuelle_simulee=heure_actuelle_simulee,
        )

    # Si le cours est terminé
    if audio_info is None:
        return render_template(
            "video.html",
            nom=session["nom"],
            prenom=session["prenom"],
            audio_filename="",
            audio_title="Cours terminé",
            offset=0,
            audio_id=0,
            temps_restant=0,
            cours_termine=True,
        )

    # Le cours est en cours
    return render_template(
        "video.html",
        nom=session["nom"],
        prenom=session["prenom"],
        audio_filename=audio_info["filename"],
        audio_title=audio_info["title"],
        offset=offset,
        audio_id=audio_info["id"],
        temps_restant=0,
        cours_termine=False,
    )


@app.route("/api/cours-status")
def cours_status():
    """API endpoint pour obtenir l'état actuel du cours"""
    audio_info, offset, temps_restant = get_current_audio_info()

    if audio_info is None and temps_restant > 0:
        return jsonify({"status": "waiting", "temps_restant": temps_restant})
    elif audio_info is None:
        return jsonify({"status": "finished"})
    else:
        return jsonify(
            {
                "status": "playing",
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "audio_title": audio_info["title"],
                "offset": offset,
            }
        )


@app.route("/intro")
def intro():
    if "nom" not in session:
        return redirect("/")

    return render_template(
        "video2.html",
        nom=session["nom"],
        prenom=session["prenom"],
    )


@app.route("/logout")
def logout():
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
    session.clear()
    return redirect("/")


@app.route("/deconnexion-auto", methods=["POST"])
def deconnexion_auto():
    if "log_id" in session:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE logs SET depart=? WHERE id=?",
                (
                    datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    session["log_id"],
                ),
            )
            conn.commit()
    return "", 204


@app.route("/admin", methods=["GET", "POST"])
def admin():
    # Vérification d'authentification ADMIN
    if not session.get("is_admin"):
        return redirect("/login_admin")

    prenom_recherche = request.args.get("prenom", "")

    # Récupération de l'heure actuelle du cours
    heure_debut_cours = get_heure_debut_cours()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if prenom_recherche:
        cursor.execute(
            "SELECT * FROM logs WHERE prenom LIKE ?", ("%" + prenom_recherche + "%",)
        )
    else:
        cursor.execute("SELECT * FROM logs")

    logs = cursor.fetchall()
    conn.close()

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

    return render_template(
        "admin.html",
        logs=logs_with_duration,
        prenom_recherche=prenom_recherche,
        temps_total=temps_total_format,
        heure_debut_cours=heure_debut_cours,
    )


@app.route("/admin/config_cours", methods=["POST"])
def config_cours():
    if not session.get("is_admin"):
        return redirect("/login_admin")

    try:
        date_str = request.form.get("date_cours")
        heure_str = request.form.get("heure_cours")

        if not date_str or not heure_str:
            flash("Veuillez renseigner la date et l'heure.", "error")
            return redirect("/admin")

        datetime_str = f"{date_str} {heure_str}:00"
        nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)

        # Sauvegarder en base
        set_heure_debut_cours(nouvelle_heure_fr)

        flash(
            f"Heure de début du cours mise à jour : {nouvelle_heure_fr.strftime('%d/%m/%Y à %H:%M')} (heure française)",
            "success",
        )

    except ValueError as e:
        flash("Format de date/heure invalide.", "error")
    except Exception as e:
        flash(f"Erreur lors de la mise à jour : {str(e)}", "error")

    return redirect("/admin")


@app.route("/export_excel")
def export_excel():
    prenom = request.args.get("prenom", "")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if prenom:
        cursor.execute("SELECT * FROM logs WHERE prenom LIKE ?", ("%" + prenom + "%",))
    else:
        cursor.execute("SELECT * FROM logs")

    rows = cursor.fetchall()
    conn.close()

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

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name="historique.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/login_admin", methods=["GET", "POST"])
def login_admin():
    if session.get("is_admin"):
        return redirect("/admin")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == "admin" and password == "secret123":
            session["is_admin"] = True
            session.permanent = True
            flash("Connexion admin réussie !", "success")
            return redirect("/admin")
        else:
            flash("Identifiant ou mot de passe incorrect.", "error")

    return render_template("login_admin.html")


@app.route("/logout_admin")
def logout_admin():
    session.pop("is_admin", None)
    return redirect("/login_admin")


@app.route("/admin/simulate-current-time", methods=["POST"])
def simulate_current_time():
    """Simule l'heure actuelle pour le debug"""
    global simulated_time_offset

    if not session.get("is_admin"):
        return jsonify({"success": False, "error": "Accès refusé"}), 403

    try:
        data = request.get_json()
        simulated_time_str = data.get("simulated_current_time")

        if not simulated_time_str:
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

        print(f"Heure actuelle simulée définie: {simulated_time_offset}")

        return jsonify(
            {
                "success": True,
                "message": f"Heure actuelle simulée: {simulated_time_offset.strftime('%Y-%m-%d %H:%M:%S')} (heure française)",
            }
        )

    except Exception as e:
        print(f"Erreur simulation heure actuelle: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/reset-simulation", methods=["POST"])
def reset_simulation():
    """Remet l'heure réelle"""
    global simulated_time_offset

    if not session.get("is_admin"):
        return jsonify({"success": False, "error": "Accès refusé"}), 403

    simulated_time_offset = None
    return jsonify(
        {"success": True, "message": "Simulation désactivée, heure réelle restaurée"}
    )


@app.route("/debug/cours-info")
def debug_cours_info():
    """Route de debug pour voir l'état actuel du cours"""
    if not session.get("is_admin"):
        return "Accès refusé - Connectez-vous d'abord en tant qu'admin", 403

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


# ========== GESTION DES WEBSOCKETS POUR LA SYNCHRONISATION ==========


@socketio.on("connect")
def handle_connect():
    print(f"🔌 Client connecté: {request.sid}")
    emit("participants_update", {"count": len(connected_users)})


@socketio.on("disconnect")
def handle_disconnect():
    print(f"🔌 Client déconnecté: {request.sid}")
    username = connected_users.pop(request.sid, None)
    if username:
        print(f"👤 Utilisateur {username} déconnecté")
        socketio.emit("user_disconnected", {"username": username})

    socketio.emit("participants_update", {"count": len(connected_users)})
    print(f"📊 Utilisateurs restants: {list(connected_users.values())}")


@socketio.on("user_connected")
def handle_user_connected(data):
    username = data.get("username", "Anonyme")

    print(f"🎯 Événement user_connected reçu pour: {username}")
    print(f"🆔 SID: {request.sid}")

    # Nettoyer les anciennes connexions de cet utilisateur
    old_sids = [sid for sid, user in connected_users.items() if user == username]
    for old_sid in old_sids:
        connected_users.pop(old_sid, None)
        print(f"🧹 Nettoyage ancienne connexion: {old_sid}")

    # Ajouter la nouvelle connexion
    connected_users[request.sid] = username
    print(f"✅ Utilisateur {username} ajouté avec SID: {request.sid}")
    print(f"📊 Total utilisateurs connectés: {len(connected_users)}")
    print(f"👥 Liste: {list(connected_users.values())}")

    socketio.emit("participants_update", {"count": len(connected_users)})

    # Synchroniser immédiatement le nouvel utilisateur
    audio_info, offset, _ = get_current_audio_info()
    if audio_info:
        emit(
            "sync_audio",
            {
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "offset": offset,
            },
        )
        print(
            f"🎵 Synchronisation immédiate pour {username} - Audio ID: {audio_info['id']}"
        )


@socketio.on("get_participants")
def handle_get_participants():
    participants_list = list(connected_users.values())
    emit(
        "participants_list",
        {"count": len(participants_list), "users": participants_list},
    )


@socketio.on("sync_request")
def handle_sync_request():
    """Synchronise l'audio pour un client qui en fait la demande"""
    audio_info, offset, temps_restant = get_current_audio_info()

    if audio_info:
        emit(
            "sync_audio",
            {
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "offset": offset,
            },
        )
        print(
            f"Synchronisation demandée - Audio ID: {audio_info['id']}, Offset: {offset}s"
        )
    elif temps_restant > 0:
        emit("cours_not_started", {"temps_restant": temps_restant})
    else:
        emit("cours_finished", {})


@socketio.on("cours_finished_check")
def handle_cours_finished_check():
    """Vérifie si le cours est terminé"""
    audio_info, _, _ = get_current_audio_info()

    if audio_info is None:
        emit("cours_finished", {})


@socketio.on("send_question")
def handle_send_question(data):
    username = data.get("username", "Anonyme")
    question = data.get("question", "").strip()

    if not question:
        return

    # Timestamp en heure française
    timestamp = datetime.now(FRANCE_TZ).strftime("%H:%M:%S")

    # Diffuser la question de l'utilisateur à tous les clients
    socketio.emit(
        "receive_question",
        {"username": username, "question": question, "timestamp": timestamp},
    )

    # ✅ Appel au service RAG externe
    try:
        print(f"🤖 Appel au service RAG externe pour: {question}")

        response_text = call_rag_service(question)

        print(f"✅ RAG Response: {response_text[:100]}...")

        # Diffuser la réponse textuelle de l'agent
        socketio.emit(
            "receive_question",
            {
                "username": "Alain",
                "question": response_text,
                "timestamp": datetime.now(FRANCE_TZ).strftime("%H:%M:%S"),
            },
        )

    except Exception as e:
        print(f"❌ Erreur lors de l'appel RAG externe: {e}")
        socketio.emit(
            "receive_question",
            {
                "username": "Alain",
                "question": "Désolé, une erreur est survenue avec le système de réponse.",
                "timestamp": datetime.now(FRANCE_TZ).strftime("%H:%M:%S"),
            },
        )


# Démarrer la synchronisation automatique en arrière-plan
sync_thread = threading.Thread(target=sync_all_clients_periodically, daemon=True)
sync_thread.start()


# ✅ Configuration pour Azure App Service
if __name__ == "__main__":
    # Port fourni par Azure (ou local)
    port = int(os.environ.get("PORT", 5000))

    # Détecter si on est en production via une variable d'environnement
    is_production = os.environ.get("WEBSITE_SITE_NAME")  # Variable Azure automatique

    print(f"🚀 Démarrage sur le port {port}")
    print(f"🏭 Mode: {'Production' if is_production else 'Développement'}")

    # SocketIO avec Eventlet
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=not is_production,  # Debug OFF en production
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
