# export_service.py - Service d'export Excel
from collections import defaultdict
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import tempfile
from utils.logger import get_logger

logger = get_logger(__name__)


def _format_seconds(total_seconds):
    """Formate un nombre de secondes en 'Xh Ymin Zsec' ou 'Xmin Zsec'"""
    total_seconds = int(total_seconds)
    heures = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secondes = total_seconds % 60
    if heures > 0:
        return f"{heures}h {minutes}min {secondes}sec"
    return f"{minutes}min {secondes}sec"


def generate_excel_export(logs_data):
    """
    Génère un fichier Excel à partir des données de logs.
    Colonnes A-F : détail des sessions
    Colonnes H-J : récapitulatif temps total par utilisateur

    Args:
        logs_data: Liste de tuples (id, nom, prenom, arrivee, depart)

    Returns:
        Chemin du fichier temporaire Excel généré
    """
    try:
        logger.info(f"📊 Génération export Excel pour {len(logs_data)} lignes")

        wb = Workbook()
        ws = wb.active
        ws.title = "Logs"

        # --- En-têtes détail (A-F) ---
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        summary_fill = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")

        for col, title in enumerate(["ID", "Nom", "Prénom", "Arrivée", "Départ", "Durée session"], start=1):
            cell = ws.cell(row=1, column=col, value=title)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # --- Données détail + calcul totaux par utilisateur ---
        totaux_par_user = defaultdict(int)   # clé: (nom, prenom) → secondes totales

        now = datetime.now()

        for row in logs_data:
            id_, nom, prenom, arrivee, depart = row
            dt1 = datetime.strptime(arrivee, "%Y-%m-%d %H:%M:%S")
            if depart:
                dt2 = datetime.strptime(depart, "%Y-%m-%d %H:%M:%S")
                seconds = (dt2 - dt1).total_seconds()
                minutes = int(seconds // 60)
                secondes = int(seconds % 60)
                duree = f"{minutes}min {secondes}sec"
            else:
                seconds = (now - dt1).total_seconds()
                minutes = int(seconds // 60)
                secondes = int(seconds % 60)
                duree = f"{minutes}min {secondes}sec (en cours)"
            totaux_par_user[(nom, prenom)] += seconds
            ws.append([id_, nom, prenom, arrivee, depart or "", duree])

        # --- En-têtes récapitulatif (colonnes H=8, I=9, J=10) ---
        for col, title in enumerate(["Nom", "Prénom", "Temps total de connexion"], start=8):
            cell = ws.cell(row=1, column=col, value=title)
            cell.font = header_font
            cell.fill = summary_fill
            cell.alignment = Alignment(horizontal="center")

        # --- Données récapitulatif, triées par nom ---
        for i, ((nom, prenom), total_sec) in enumerate(
            sorted(totaux_par_user.items(), key=lambda x: (x[0][0], x[0][1])),
            start=2
        ):
            ws.cell(row=i, column=8, value=nom)
            ws.cell(row=i, column=9, value=prenom)
            ws.cell(row=i, column=10, value=_format_seconds(total_sec))

        # --- Largeurs de colonnes ---
        column_widths = {1: 6, 2: 18, 3: 18, 4: 20, 5: 20, 6: 16, 8: 18, 9: 18, 10: 28}
        for col, width in column_widths.items():
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = width

        # --- Date d'export en bas du tableau principal ---
        last_row = ws.max_row + 2
        date_cell = ws.cell(row=last_row, column=1, value=f"Exporté le {datetime.now().strftime('%d/%m/%Y')}")
        date_cell.font = Font(italic=True, color="888888")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        wb.save(tmp.name)
        tmp.seek(0)

        logger.info("✅ Export Excel généré avec succès")
        return tmp.name

    except Exception as e:
        logger.error(f"❌ Erreur génération Excel: {e}")
        raise
