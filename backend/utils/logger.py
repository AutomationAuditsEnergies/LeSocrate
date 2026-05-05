# logger.py - Configuration centralisée des logs
import logging
import os
import sys


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


def configure_logging():
    """Configure le système de logging pour l'application.

    Niveau root pilotable via la variable d'env `LOG_LEVEL` (défaut `INFO`).
    Les SDK Azure / urllib3 / openai / httpx sont forcés à `WARNING` pour
    laisser respirer les logs métier (préfixes `PIPELINE_*`).
    """
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/tmp/app.log", mode="a"),
        ],
        force=True,
    )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name):
    """Retourne un logger configuré pour le module donné"""
    return logging.getLogger(name)
