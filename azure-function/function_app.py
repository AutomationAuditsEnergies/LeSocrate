import azure.functions as func
import logging
import os
import requests

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def course_automation_tick(myTimer: func.TimerRequest) -> None:
    """
    Timer Trigger : s'exécute toutes les 5 minutes.
    - /api/internal/auto-schedule maintient cours_config sur la séance active
      ou la prochaine séance planifiée.
    - /api/internal/reminders/tick envoie les rappels dus.
    """
    if myTimer.past_due:
        logging.warning("Le timer est en retard !")

    api_url = os.environ["SOCRATE_API_URL"].rstrip("/")
    api_key = os.environ["PLATFORM_API_KEY"]

    headers = {"X-Platform-Key": api_key, "Content-Type": "application/json"}

    for endpoint in ("/api/internal/auto-schedule", "/api/internal/reminders/tick"):
        url = f"{api_url}{endpoint}"
        logging.info(f"Lancement automation -> {url}")

        try:
            resp = requests.post(url, headers=headers, json={}, timeout=30)
            result = resp.json()

            if result.get("success"):
                logging.info(f"Automation OK {endpoint}: {len(result.get('results', []))} résultat(s)")
            else:
                logging.error(f"Erreur automation {endpoint}: {result}")

        except Exception as e:
            logging.error(f"Impossible d'appeler {endpoint}: {e}")
            raise
