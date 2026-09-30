import azure.functions as func
import logging
import os
import requests

app = func.FunctionApp()


def _call_backend_endpoint(endpoint: str) -> None:
    api_url = os.environ["SOCRATE_API_URL"].rstrip("/")
    api_key = os.environ["PLATFORM_API_KEY"]
    url = f"{api_url}{endpoint}"
    headers = {"X-Platform-Key": api_key, "Content-Type": "application/json"}

    logging.info(f"Lancement automation -> {url}")
    resp = requests.post(url, headers=headers, json={}, timeout=30)
    result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"Erreur automation {endpoint}: {result}")
    logging.info(f"Automation OK {endpoint}: {len(result.get('results', []))} résultat(s)")


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
    """
    if myTimer.past_due:
        logging.warning("Le timer d'auto-planification est en retard !")

    _call_backend_endpoint("/api/internal/auto-schedule")
