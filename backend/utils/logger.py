# logger.py - Configuration centralisée des logs
import logging
import os
import sys
import tempfile


# Loggers tiers très verbeux qui noient les logs métier en DEBUG/INFO
# (chaque requête HTTP Azure Blob = ~30 lignes de headers + corps).
# On les muselle à WARNING : ils ne parlent que sur problème réel.
_NOISY_LOGGERS = (
    "azure",
    "azure.core",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.storage",
    "azure.identity",
    "urllib3",
    "urllib3.connectionpool",
    "msrest",
    "msal",
    "openai",
    "httpx",
)


def log_file_path():
    """Fichier de logs : `LOG_FILE` si défini, sinon `app.log` dans le dossier
    temporaire du système (`/tmp/app.log` sous Linux et sur Azure)."""
    return os.getenv("LOG_FILE") or os.path.join(tempfile.gettempdir(), "app.log")


def configure_logging():
    """Configure le système de logging pour l'application.

    Niveau root pilotable via la variable d'env `LOG_LEVEL` (défaut `INFO`).
    Les SDK Azure / urllib3 / openai / httpx sont forcés à `WARNING` pour
    laisser respirer les logs métier (préfixes `PIPELINE_*`).
    Si le fichier de logs ne peut pas être ouvert, seule la console est gardée.
    """
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = log_file_path()
    handlers = [logging.StreamHandler(sys.stdout)]
    file_error = None
    try:
        handlers.append(logging.FileHandler(log_path, mode="a"))
    except OSError as exc:
        file_error = exc

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        handlers=handlers,
        force=True,
    )
    if file_error is not None:
        logging.getLogger("socrate.boot").warning(
            "LOG_FILE_UNAVAILABLE path=%s error=%s : logs sur la console uniquement",
            log_path,
            file_error,
        )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Marqueur de démarrage : permet de vérifier dans les logs Azure que
    # cette version de configure_logging() tourne bien. Si ce marqueur
    # n'apparaît pas après redéploiement, le worker tourne encore sur
    # l'ancien code (cache .pyc, restart partiel).
    boot_logger = logging.getLogger("socrate.boot")
    effective_levels = {
        n: logging.getLevelName(logging.getLogger(n).getEffectiveLevel())
        for n in _NOISY_LOGGERS
    }
    boot_logger.warning(
        "LOGGING_BOOT v2 — root=%s, noisy_muted=%s",
        level_name,
        effective_levels,
    )


def get_logger(name):
    """Retourne un logger configuré pour le module donné"""
    return logging.getLogger(name)
