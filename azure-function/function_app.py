import azure.functions as func
import logging
import os
import requests

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 0 7 * * 6",
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def auto_schedule(myTimer: func.TimerRequest) -> None:
    """
    Timer Trigger : s'exécute chaque samedi à 7h UTC (= 8h/9h Paris).
    Appelle /api/internal/auto-schedule sur le backend P1 pour programmer
    les cours de la semaine suivante (P1=vendredi, P2=lundi, P3=mercredi).
    """
    if myTimer.past_due:
        logging.warning("Le timer est en retard !")

    api_url = os.environ["SOCRATE_API_URL"].rstrip("/")
    api_key = os.environ["PLATFORM_API_KEY"]

    url = f"{api_url}/api/internal/auto-schedule"
    logging.info(f"Lancement auto-schedule -> {url}")

    try:
        resp = requests.post(
            url,
            headers={"X-Platform-Key": api_key, "Content-Type": "application/json"},
            json={},
            timeout=30,
        )
        result = resp.json()

        if result.get("success"):
            for r in result.get("results", []):
                status = "OK" if r["success"] else "ERREUR"
                msg = r.get("scheduled") or r.get("error", "?")
                logging.info(f"  [{status}] P{r['platform_id']} : {msg}")
        else:
            logging.error(f"Erreur auto-schedule : {result}")

    except Exception as e:
        logging.error(f"Impossible d'appeler auto-schedule : {e}")
        raise
