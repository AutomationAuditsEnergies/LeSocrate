# db_safety.py - Sécurité de la base SQLite : intégrité, backups, restauration.
#
# Objectif : ne plus jamais perdre les données suite à une corruption SQLite
# (cf. incident "database disk image is malformed" — commit 5d9f00a).
#
# Au démarrage (appelé AVANT init_database dans main_app.py) :
#   1. PRAGMA integrity_check sur la base existante.
#   2. Si saine  → backup horodaté dans <dir>/backups/ + rotation.
#   3. Si corrompue → quarantaine, puis restauration automatique du dernier
#      backup sain. Sans backup sain, on repart sur une base neuve mais en
#      mode maintenance : l'API répond 503 jusqu'à intervention admin.
#
# L'état (notice de récupération, mode maintenance) est exposé via
# /api/admin/db/status pour ne plus jamais "repartir vide silencieusement".
import os
import shutil
import sqlite3
import threading
from datetime import datetime

from config import DB_PATH, FRANCE_TZ, SQLITE_SAFETY_STRICT, sqlite_runtime_enabled
from utils.logger import get_logger

logger = get_logger(__name__)

BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "backups")
BACKUP_PREFIX = os.path.splitext(os.path.basename(DB_PATH))[0]
MAX_BACKUPS = 15
MIN_AUTO_RESTORE_BYTES = 1024 * 1024

# État de santé partagé, consulté par le before_request de main_app et
# l'endpoint /api/admin/db/status. Protégé par _state_lock :
# threading.Lock est monkey-patché en lock green-thread).
_state_lock = threading.Lock()
db_health = {
    "maintenance": False,
    "maintenance_reason": None,
    # notice : None | 'restored_from_backup' | 'recreated_empty'
    "recovery_notice": None,
    "recovery_detail": None,
    "last_backup_at": None,
    "checked_at": None,
}


def _now_str():
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _timestamp():
    return datetime.now(FRANCE_TZ).strftime("%Y%m%d-%H%M%S")


def set_maintenance(enabled: bool, reason: str | None = None):
    with _state_lock:
        db_health["maintenance"] = enabled
        db_health["maintenance_reason"] = reason if enabled else None
    logger.warning("🚧 Mode maintenance DB: %s (%s)", "ON" if enabled else "OFF", reason)


def is_maintenance() -> bool:
    return db_health["maintenance"]


def maintenance_blocks_requests() -> bool:
    """SQLite recovery maintenance only applies when SQLite is authoritative."""
    return sqlite_runtime_enabled() and is_maintenance()


def check_integrity(db_path: str = DB_PATH) -> tuple[bool, str]:
    """Lance PRAGMA integrity_check. Retourne (ok, détail)."""
    if not os.path.exists(db_path):
        return True, "no database file (will be created)"
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
        detail = "; ".join(str(r[0]) for r in rows)
        return detail == "ok", detail
    except sqlite3.DatabaseError as e:
        return False, str(e)


def create_backup(db_path: str = DB_PATH, label: str = "auto") -> str | None:
    """Backup cohérent via l'API sqlite3 backup (sûr même avec WAL/écritures).

    Retourne le chemin du backup, ou None si la base n'existe pas encore.
    """
    if not os.path.exists(db_path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"{BACKUP_PREFIX}-{_timestamp()}-{label}.db"
    )
    source = sqlite3.connect(db_path, timeout=30)
    try:
        dest = sqlite3.connect(backup_path)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    with _state_lock:
        db_health["last_backup_at"] = _now_str()
    logger.info("💾 Backup DB créé: %s", backup_path)
    _rotate_backups()
    return backup_path


def _rotate_backups():
    backups = list_backups()
    for old in backups[MAX_BACKUPS:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old["name"]))
            logger.info("🧹 Backup DB supprimé (rotation): %s", old["name"])
        except OSError:
            pass


def list_backups() -> list[dict]:
    """Backups disponibles, du plus récent au plus ancien."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    items = []
    for name in os.listdir(BACKUP_DIR):
        if not (name.startswith(BACKUP_PREFIX) and name.endswith(".db")):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append({
            "name": name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, FRANCE_TZ).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        })
    items.sort(key=lambda b: b["name"], reverse=True)
    return items


def quarantine_database(db_path: str = DB_PATH) -> str:
    """Met de côté une base corrompue (et ses fichiers -wal/-shm)."""
    quarantine_path = f"{db_path}.corrupt-{_timestamp()}"
    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        if not os.path.exists(path):
            continue
        target = f"{quarantine_path}{path[len(db_path):]}"
        try:
            os.replace(path, target)
        except OSError:
            shutil.copy2(path, target)
            os.remove(path)
        logger.error("🧯 Base SQLite corrompue mise de côté: %s -> %s", path, target)
    return quarantine_path


def restore_backup(backup_name: str, db_path: str = DB_PATH) -> bool:
    """Restaure un backup nommé. Vérifie son intégrité avant de remplacer.

    La base courante (si présente) est d'abord sauvegardée avec le label
    'pre-restore' pour que l'opération soit réversible.
    """
    backup_path = os.path.join(BACKUP_DIR, os.path.basename(backup_name))
    if not os.path.exists(backup_path):
        logger.error("❌ Backup introuvable: %s", backup_path)
        return False
    ok, detail = check_integrity(backup_path)
    if not ok:
        logger.error("❌ Backup corrompu, restauration refusée: %s (%s)", backup_name, detail)
        return False
    if os.path.exists(db_path):
        create_backup(db_path, label="pre-restore")
    # Supprimer les restes WAL/SHM de l'ancienne base avant remplacement
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(f"{db_path}{suffix}")
        except OSError:
            pass
    shutil.copy2(backup_path, db_path)
    logger.warning("♻️ Base restaurée depuis le backup: %s", backup_name)
    return True


def _restore_latest_healthy_backup(db_path: str = DB_PATH) -> str | None:
    """Tente les backups du plus récent au plus ancien, retourne le nom utilisé."""
    for backup in list_backups():
        if backup.get("size_bytes", 0) < MIN_AUTO_RESTORE_BYTES:
            logger.error(
                "⚠️ Backup %s ignoré pour restauration auto (taille anormale: %s octets)",
                backup["name"],
                backup.get("size_bytes", 0),
            )
            continue
        ok, detail = check_integrity(os.path.join(BACKUP_DIR, backup["name"]))
        if not ok:
            logger.error("⚠️ Backup %s lui-même corrompu (%s), on passe au suivant", backup["name"], detail)
            continue
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(f"{db_path}{suffix}")
            except OSError:
                pass
        shutil.copy2(os.path.join(BACKUP_DIR, backup["name"]), db_path)
        return backup["name"]
    return None


def enable_wal(db_path: str = DB_PATH):
    """Active le mode WAL (persistant : survit aux connexions suivantes).

    ATTENTION : jamais sur Azure App Service — /home est un partage réseau
    (Azure Files/CIFS) et SQLite documente le WAL comme non fiable sur les
    filesystems réseau (le -shm est mmappé). On garde le rollback journal
    par défaut là-bas ; le timeout=30 des connexions gère la concurrence.
    """
    if os.getenv("WEBSITE_SITE_NAME"):
        logger.info("ℹ️ WAL non activé (Azure App Service : /home est un partage réseau)")
        return
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        finally:
            conn.close()
        logger.info("✅ SQLite journal_mode=%s", mode)
    except sqlite3.DatabaseError as e:
        logger.error("⚠️ Impossible d'activer WAL: %s", e)


def startup_check():
    """Séquence de sécurité au boot. À appeler AVANT init_database()."""
    with _state_lock:
        db_health["checked_at"] = _now_str()

    db_exists = os.path.exists(DB_PATH)
    db_size = os.path.getsize(DB_PATH) if db_exists else 0
    if (not db_exists or db_size < MIN_AUTO_RESTORE_BYTES) and list_backups():
        logger.error(
            "🚨 Base SQLite absente ou anormalement petite au démarrage: %s octets",
            db_size,
        )
        restored = _restore_latest_healthy_backup()
        if restored:
            enable_wal()
            with _state_lock:
                db_health["recovery_notice"] = "restored_from_backup"
                db_health["recovery_detail"] = (
                    f"Base absente ou anormalement petite ({db_size} octets). "
                    f"Restaurée depuis le backup {restored}."
                )
            logger.warning("♻️ Récupération automatique réussie depuis %s", restored)
            return
        if db_exists and SQLITE_SAFETY_STRICT:
            set_maintenance(
                True,
                "Base de données anormalement petite et aucun backup complet sain disponible.",
            )
        elif db_exists:
            logger.warning(
                "⚠️ Base SQLite anormalement petite (%s octets), mais "
                "SQLITE_SAFETY_STRICT=0 : démarrage autorisé.",
                db_size,
            )

    ok, detail = check_integrity()
    if ok:
        logger.info("✅ Intégrité SQLite vérifiée (%s)", detail)
        enable_wal()
        try:
            create_backup(label="boot")
        except Exception as e:
            # Un échec de backup ne doit pas empêcher l'app de démarrer
            logger.error("⚠️ Backup au démarrage impossible: %s", e)
        return

    logger.error("🚨 Base SQLite corrompue au démarrage: %s", detail)
    quarantine_path = quarantine_database()

    restored = _restore_latest_healthy_backup()
    if restored:
        enable_wal()
        with _state_lock:
            db_health["recovery_notice"] = "restored_from_backup"
            db_health["recovery_detail"] = (
                f"Base corrompue ({detail}) mise en quarantaine sous {quarantine_path}. "
                f"Restaurée depuis le backup {restored}."
            )
        logger.warning("♻️ Récupération automatique réussie depuis %s", restored)
        return

    # Aucun backup sain : on repart sur une base neuve mais on NE fait PAS
    # comme si de rien n'était — mode maintenance jusqu'à décision admin.
    with _state_lock:
        db_health["recovery_notice"] = "recreated_empty"
        db_health["recovery_detail"] = (
            f"Base corrompue ({detail}) mise en quarantaine sous {quarantine_path}. "
            "Aucun backup sain disponible : base recréée vide."
        )
    set_maintenance(
        True,
        "Base de données corrompue et aucun backup sain disponible. "
        "Restauration manuelle requise (POST /api/admin/db/restore ou "
        "désactivation via POST /api/admin/db/maintenance).",
    )


def periodic_backup_loop(sleep_fn, interval_seconds: int = 6 * 3600):
    """Boucle de backup périodique avec une fonction de sommeil injectable."""
    while True:
        sleep_fn(interval_seconds)
        try:
            create_backup(label="periodic")
        except Exception as e:
            logger.error("⚠️ Backup périodique en échec: %s", e)
