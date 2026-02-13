# logger.py - Configuration centralisée des logs
import logging
import sys


def configure_logging():
    """Configure le système de logging pour l'application"""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/tmp/app.log", mode="a"),
        ],
    )


def get_logger(name):
    """Retourne un logger configuré pour le module donné"""
    return logging.getLogger(name)
