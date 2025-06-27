# 👨‍🏫 Socrate

## 📘 Présentation

Le projet Socrate est une application web interactive destinée à la diffusion d’un cours audio synchronisé, avec une interface permettant aux utilisateurs de se connecter, d’écouter un fichier audio, et de poser des questions en temps réel via un chat assisté par un agent IA (microservice ElevenLabs). Une interface d’administration permet de consulter l’historique des connexions et durées de présence des utilisateurs.



## ⚙️ Technologies utilisées

- **Python 3** avec **Flask** pour le backend web  
- **Flask-SocketIO** pour la communication temps réel WebSocket  
- **Eventlet** pour la gestion asynchrone des websockets  
- **SQLite** comme base de données légère intégrée  
- **HTML / JS / CSS** pour les templates frontend  
- **Requests** pour communiquer avec le microservice IA ElevenLabs (API locale HTTP)  
- **Socket.IO** côté client pour le chat en temps réel  
- Fichiers audio statiques pour le cours (wav et mp4)  



## 📦 Installation et lancement

1. Cloner le dépôt  
2. Installer les dépendances Python :

   ```bash
   pip install -r requirements.txt
   ```
3. S’assurer que le microservice ElevenLabs est lancé localement sur le port 6000 (endpoint /ask)

4. Lancer le serveur avec :

    ```bash
    python run.py
    ```

5. Accéder à l’application via http://localhost:5000
