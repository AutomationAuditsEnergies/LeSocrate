import os
import logging
import requests
import azure.functions as func

logger = logging.getLogger(__name__)


def main(mytimer: func.TimerRequest) -> None:
    """
    Timer Trigger : s'exécute chaque samedi à 8h00 (heure de Paris).
    Appelle /api/internal/auto-schedule sur le backend P1 pour programmer
    les cours de la semaine suivante.
    """
    if mytimer.past_due:
        logger.warning("Le timer est en retard !")

    api_url = os.environ["SOCRATE_API_URL"].rstrip("/")
    api_key = os.environ["PLATFORM_API_KEY"]

    url = f"{api_url}/api/internal/auto-schedule"
    logger.info(f"📅 Lancement auto-schedule → {url}")

    try:
        resp = requests.post(
            url,
            headers={"X-Platform-Key": api_key, "Content-Type": "application/json"},
            json={},  # utilise le schedule par défaut (P1=vendredi, P2=lundi, P3=mercredi)
            timeout=30,
        )
        result = resp.json()

        if result.get("success"):
            for r in result.get("results", []):
                status = "✅" if r["success"] else "❌"
                msg = r.get("scheduled") or r.get("error", "?")
                logger.info(f"  {status} P{r['platform_id']} : {msg}")
        else:
            logger.error(f"❌ Erreur auto-schedule : {result}")

    except Exception as e:
        logger.error(f"❌ Impossible d'appeler auto-schedule : {e}")
        raise
