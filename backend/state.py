# state.py - Variables globales partagées de l'application

# Dictionnaire pour stocker les utilisateurs connectés (SocketIO)
# Format: {sid: username}
connected_users = {}

# Mapping sid → platform_id pour filtrer par plateforme
# Format: {sid: platform_id}
connected_users_platform = {}

# Tokens d'authentification pour navigation privée / cross-origin
# Format: {token_uuid: {nom, prenom, log_id, platform_id}}
user_tokens = {}

# Heure simulée par plateforme (debug/admin)
# Format: {platform_id: datetime_or_None}
simulated_time_offsets = {}

# Rétro-compatibilité : conservé pour les appels qui n'ont pas encore été migrés
simulated_time_offset = None

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
