# state.py - Variables globales partagées de l'application

# Dictionnaire pour stocker les utilisateurs connectés (SocketIO)
# Format: {sid: username}
connected_users = {}

# Tokens d'authentification pour navigation privée / cross-origin
# Format: {token_uuid: {nom, prenom, log_id}}
user_tokens = {}

# Variable globale pour stocker l'heure simulée (debug/admin)
# None = utiliser l'heure réelle, datetime = heure simulée
simulated_time_offset = None

# État du job d'upload audio en arrière-plan
audio_upload_job = {
    "status": "idle",        # idle | saving | processing | completed | error
    "progress": 0,           # nombre de fichiers terminés
    "total": 0,              # nombre total de fichiers
    "current_file": "",      # gardé pour compatibilité
    "message": "",           # message humain
    "report": None,          # rapport final [{original, cleaned, converted, skipped}]
    "files_status": {},      # {cleaned_name: "pending"|"converting"|"uploading"|"done"|"error"}
}


def reset_audio_upload_job():
    """Remet le job d'upload audio à l'état initial"""
    audio_upload_job["status"] = "idle"
    audio_upload_job["progress"] = 0
    audio_upload_job["total"] = 0
    audio_upload_job["current_file"] = ""
    audio_upload_job["message"] = ""
    audio_upload_job["report"] = None
    audio_upload_job["files_status"] = {}


# État du job de backup-and-unlock par plateforme
# Format: { platform_id: { step, step_status, total, progress, error, archive_folder } }
backup_jobs = {}


def reset_backup_job(platform_id):
    """Remet le job de backup d'une plateforme à l'état initial"""
    backup_jobs[platform_id] = {
        "step": 0,          # 0=idle, 1=backup, 2=verify+delete, 3=done
        "step_status": "idle",   # idle | running | done | error
        "total": 0,
        "progress": 0,
        "archive_folder": "",
        "error": None,
    }
