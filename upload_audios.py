# Upload d'un seul fichier vers Azure Storage
import os
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

# Configuration Azure Storage
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = "audios"


def upload_single_file():
    """Upload uniquement le fichier cours_10h05_10h50.wav"""

    if not AZURE_STORAGE_CONNECTION_STRING:
        print("❌ AZURE_STORAGE_CONNECTION_STRING manquante dans .env")
        return False

    try:
        # Connexion au service Blob
        blob_service_client = BlobServiceClient.from_connection_string(
            AZURE_STORAGE_CONNECTION_STRING
        )

        # Vérifier le container
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        # Fichier à uploader
        filename = "cours_10h05_10h50.wav"
        local_path = os.path.join("audios", filename)

        # Vérifier que le fichier existe
        if not os.path.exists(local_path):
            print(f"❌ Fichier '{local_path}' introuvable")
            return False

        file_size = os.path.getsize(local_path)
        print(f"📤 Upload {filename} ({file_size / 1024 / 1024:.1f} MB)...")

        # Supprimer l'ancien blob s'il existe
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME, blob=filename
        )

        try:
            blob_client.delete_blob()
            print(f"🗑️ Ancien fichier supprimé")
        except Exception:
            print(f"ℹ️ Aucun ancien fichier à supprimer")

        # Upload le nouveau fichier
        with open(local_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)

        # URL publique du fichier
        blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{filename}"

        print(f"✅ {filename} uploadé avec succès !")
        print(f"🔗 URL: {blob_url}")

        return True

    except Exception as e:
        print(f"❌ Erreur upload: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Upload du fichier cours_10h05_10h50.wav...")
    success = upload_single_file()

    if success:
        print("\n✅ Upload terminé !")
    else:
        print("\n❌ Échec de l'upload")
