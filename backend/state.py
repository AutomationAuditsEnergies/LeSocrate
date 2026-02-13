# state.py - Variables globales partagées de l'application

# Dictionnaire pour stocker les utilisateurs connectés (SocketIO)
# Format: {sid: username}
connected_users = {}

# Variable globale pour stocker l'heure simulée (debug/admin)
# None = utiliser l'heure réelle, datetime = heure simulée
simulated_time_offset = None

# État du job d'upload audio en arrière-plan
audio_upload_job = {
    "status": "idle",        # idle | saving | converting | uploading | completed | error
    "progress": 0,           # index du fichier en cours
    "total": 0,              # nombre total de fichiers
    "current_file": "",      # nom du fichier en cours
    "message": "",           # message humain
    "report": None,          # rapport final [{original, cleaned, converted, skipped}]
}


def reset_audio_upload_job():
    """Remet le job d'upload audio à l'état initial"""
    audio_upload_job["status"] = "idle"
    audio_upload_job["progress"] = 0
    audio_upload_job["total"] = 0
    audio_upload_job["current_file"] = ""
    audio_upload_job["message"] = ""
    audio_upload_job["report"] = None
