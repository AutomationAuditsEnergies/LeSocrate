# export_service.py - Service d'export Excel
from datetime import datetime
from openpyxl import Workbook
import tempfile
from utils.logger import get_logger

logger = get_logger(__name__)


def generate_excel_export(logs_data):
    """
    Génère un fichier Excel à partir des données de logs

    Args:
        logs_data: Liste de tuples (id, nom, prenom, arrivee, depart)

    Returns:
        Chemin du fichier temporaire Excel généré
    """
    try:
        logger.info(f"📊 Génération export Excel pour {len(logs_data)} lignes")

        wb = Workbook()
        ws = wb.active
        ws.append(["ID", "Nom", "Prénom", "Arrivée", "Départ", "Durée"])

        for row in logs_data:
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
        return tmp.name

    except Exception as e:
        logger.error(f"❌ Erreur génération Excel: {e}")
        raise
