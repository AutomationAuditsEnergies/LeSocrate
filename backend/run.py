import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))  # Charge backend/.env quel que soit le dossier de lancement

from main_app import app

if __name__ == "__main__":
    host = "0.0.0.0"
    default_port = 8000 if os.getenv("WEBSITE_SITE_NAME") else 5001
    port = int(os.getenv("PORT") or os.getenv("WEBSITES_PORT") or default_port)
    print(
        f"🚀 Serveur lance sur http://127.0.0.1:{port} (localhost) et http://{host}:{port} (sur le reseau)"
    )
    app.run(
        host=host,
        port=port,
        debug=not bool(os.getenv("WEBSITE_SITE_NAME")),
        threaded=True,
        use_reloader=False,
    )
