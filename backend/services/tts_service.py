import os
import io
import requests as http_requests
from utils.logger import get_logger

logger = get_logger(__name__)

API_KEY = os.getenv("FISH_AUDIO_API_KEY")
API_URL = "https://api.fish.audio/v1/tts"
DEFAULT_VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")


def extract_text_from_pdf(pdf_data):
    """
    Extrait le texte d'un PDF à partir de bytes.

    Args:
        pdf_data: bytes du fichier PDF

    Returns:
        Texte extrait du PDF
    """
    try:
        import PyPDF2

        text = []
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)

        return "\n\n".join(text)
    except Exception as e:
        logger.error(f"❌ Erreur extraction PDF: {e}")
        raise


def add_pedagogical_tags(text):
    """
    Améliore le texte pour une lecture pédagogique avec fish.audio S2-Pro.
    Utilise les tags en [crochets] supportés par S2-Pro (PAS du SSML).
    """
    text = text.replace(". ", ". [pause] ")
    text = text.replace("\n\n", "\n\n[long pause] ")
    text = text.replace(": ", ": [short pause] ")
    return text


def convert_to_speech(
    text,
    voice_id=None,
    model="s2-pro",
    speed=0.95,
    temperature=0.7,
    top_p=0.7
):
    """
    Convertit un texte en audio via fish.audio API.

    Returns:
        bytes du fichier MP3
    """
    if not voice_id:
        voice_id = DEFAULT_VOICE_ID

    api_key = os.getenv("FISH_AUDIO_API_KEY") or API_KEY
    if not api_key:
        raise ValueError("FISH_AUDIO_API_KEY non définie dans l'environnement")

    payload = {
        "text": text,
        "reference_id": voice_id,
        "temperature": temperature,
        "top_p": top_p,
        "prosody": {
            "speed": speed,
            "volume": 0,
            "normalize_loudness": True
        },
        "chunk_length": 300,
        "normalize": False,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "balanced"
    }

    headers = {
        "model": model,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"⏳ Envoi à l'API fish.audio... ({len(text)} caractères)")

    response = http_requests.post(API_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Erreur API fish.audio ({response.status_code}): {response.text}")

    logger.info(f"✅ Audio généré: {len(response.content)} bytes")
    return response.content


def process_document_to_audio(pdf_data, voice_id=None, model="s2-pro", speed=0.95):
    """
    Pipeline complète: PDF bytes → tags pédagogiques → TTS → MP3 bytes

    Args:
        pdf_data: bytes du fichier PDF

    Returns:
        bytes du fichier MP3
    """
    text = extract_text_from_pdf(pdf_data)

    if not text or len(text.strip()) < 10:
        raise ValueError("Texte extrait vide ou trop court")

    text_with_tags = add_pedagogical_tags(text)

    return convert_to_speech(text_with_tags, voice_id, model, speed)
