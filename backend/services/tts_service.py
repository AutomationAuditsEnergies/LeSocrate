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


def extract_text_from_file(file_bytes, original_name):
    """
    Extrait le texte d'un fichier selon son extension.
    Supporte : .pdf, .txt, .md

    Args:
        file_bytes: bytes du fichier
        original_name: nom original du fichier (pour détecter le type)

    Returns:
        Texte extrait
    """
    ext = original_name.lower().rsplit(".", 1)[-1] if "." in original_name else ""

    if ext == "pdf":
        return extract_text_from_pdf(file_bytes)

    elif ext in ("txt", "md"):
        # Décode en UTF-8 (fallback latin-1 si nécessaire)
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        # Pour le markdown : supprimer les balises de formatage basiques (#, **, __, `)
        if ext == "md":
            import re
            text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # titres
            text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)          # gras/italique
            text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)             # soulignement
            text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)                # code inline/bloc
            text = re.sub(r"!\[.*?\]\(.*?\)", "", text)                   # images
            text = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", text)              # liens
            text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)    # listes
            text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)    # listes numérotées
        return text

    else:
        raise ValueError(f"Format non supporté : .{ext} — utilisez .pdf, .txt ou .md")


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
