import os
import io
import base64
import json
import requests as http_requests
from utils.logger import get_logger

logger = get_logger(__name__)

API_KEY = os.getenv("FISH_AUDIO_API_KEY")
API_URL = "https://api.fish.audio/v1/tts"
TIMESTAMP_API_URL = "https://api.fish.audio/v1/tts/stream/with-timestamp"
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


def _build_tts_payload(
    text,
    voice_id=None,
    speed=0.95,
    temperature=0.7,
    top_p=0.7,
    format="mp3",
):
    if not voice_id:
        voice_id = DEFAULT_VOICE_ID

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
        "format": format,
        "latency": "balanced"
    }
    if format == "mp3":
        payload["mp3_bitrate"] = 128
    elif format == "opus":
        payload["sample_rate"] = 48000
    return payload


def _global_timeline_from_alignment(alignment_by_chunk):
    timeline = []
    for chunk_seq, item in sorted(alignment_by_chunk.items()):
        offset = float(item.get("offset") or 0.0)
        alignment = item.get("alignment") or {}
        for segment in alignment.get("segments") or []:
            timeline.append({
                "text": segment.get("text") or "",
                "start": round(float(segment.get("start") or 0.0) + offset, 3),
                "end": round(float(segment.get("end") or 0.0) + offset, 3),
                "chunk_seq": int(chunk_seq),
            })
    return timeline


def convert_to_speech_with_timestamps(
    text,
    voice_id=None,
    model="s2-pro",
    speed=0.95,
    temperature=0.7,
    top_p=0.7,
    format="mp3",
):
    """
    Convertit un texte via Fish Audio en conservant l'alignement timestampé.

    Returns:
        (audio_bytes, metadata)
    """
    api_key = os.getenv("FISH_AUDIO_API_KEY") or API_KEY
    if not api_key:
        raise ValueError("FISH_AUDIO_API_KEY non définie dans l'environnement")

    payload = _build_tts_payload(
        text,
        voice_id=voice_id,
        speed=speed,
        temperature=temperature,
        top_p=top_p,
        format=format,
    )
    headers = {
        "model": model,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"⏳ Envoi à l'API fish.audio timestamp... ({len(text)} caractères)")
    response = http_requests.post(
        TIMESTAMP_API_URL,
        json=payload,
        headers=headers,
        stream=True,
        timeout=(30, 900),
    )

    if response.status_code != 200:
        raise Exception(f"Erreur API fish.audio timestamp ({response.status_code}): {response.text[:500]}")

    audio_chunks = []
    alignment_by_chunk = {}
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        if event.get("audio_base64"):
            audio_chunks.append(base64.b64decode(event["audio_base64"]))
        if event.get("alignment") is not None:
            alignment_by_chunk[event["chunk_seq"]] = {
                "content": event.get("content") or "",
                "offset": event.get("chunk_audio_offset_sec") or 0.0,
                "alignment": event["alignment"],
            }

    audio = b"".join(audio_chunks)
    timeline = _global_timeline_from_alignment(alignment_by_chunk)
    audio_duration = 0.0
    if timeline:
        audio_duration = max(float(segment["end"]) for segment in timeline)
    elif alignment_by_chunk:
        audio_duration = max(
            float(item.get("offset") or 0.0)
            + float((item.get("alignment") or {}).get("audio_duration") or 0.0)
            for item in alignment_by_chunk.values()
        )

    spoken_words = len([segment for segment in timeline if (segment.get("text") or "").strip()])
    wpm = spoken_words / (audio_duration / 60.0) if audio_duration > 0 else 0.0
    metadata = {
        "provider": "fish_audio",
        "endpoint": "stream_with_timestamp",
        "model": model,
        "format": format,
        "speed": speed,
        "audio_duration_sec": round(audio_duration, 3),
        "spoken_word_count": spoken_words,
        "words_per_minute": round(wpm, 3),
        "text_read": " ".join(
            segment["text"].strip()
            for segment in timeline
            if (segment.get("text") or "").strip()
        ),
        "timeline": timeline,
        "chunks": [
            {
                "chunk_seq": int(chunk_seq),
                "content": item.get("content") or "",
                "offset": round(float(item.get("offset") or 0.0), 3),
                "audio_duration_sec": round(float((item.get("alignment") or {}).get("audio_duration") or 0.0), 3),
                "segment_count": len((item.get("alignment") or {}).get("segments") or []),
            }
            for chunk_seq, item in sorted(alignment_by_chunk.items())
        ],
    }
    logger.info(
        "✅ Audio timestamp généré: %s bytes, %.1fs, %s mots, %.1f mots/min",
        len(audio),
        metadata["audio_duration_sec"],
        metadata["spoken_word_count"],
        metadata["words_per_minute"],
    )
    return audio, metadata


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
