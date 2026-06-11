# iIMPORTANT: eventlet.monkey_patch() DOIT etre appele EN PREMIER
import eventlet

eventlet.monkey_patch()

# Maintenant on peut importer le reste
from dotenv import load_dotenv

load_dotenv()  # Charge le fichier .env

from main_app import app, socketio

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5001
    print(
        f"🚀 Serveur lance sur http://127.0.0.1:{port} (localhost) et http://{host}:{port} (sur le reseau)"
    )
    socketio.run(app, host=host, port=port, debug=True, use_reloader=False)
