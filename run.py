import eventlet
from main_app import app, socketio

eventlet.monkey_patch()

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5000
    print(
        f"🚀 Serveur lancé sur http://127.0.0.1:{port} (localhost) et http://{host}:{port} (sur le réseau)"
    )
    socketio.run(app, host=host, port=port, debug=True, use_reloader=False)
