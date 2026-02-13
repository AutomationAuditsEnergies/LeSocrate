# slide_generation_service.py - Service de generation de slides a partir d'audio
# Version 3: Architecture hierarchique multi-pass avec event mapping et fusion
# Utilise requests directement pour eviter le conflit eventlet/trio avec le SDK OpenAI

import os
import io
import json
import time
import tempfile
import requests
from pydub import AudioSegment
from config import COURS_PLAYLIST
from utils.logger import get_logger

# Import des nouveaux services
from services.event_mapper import map_events, get_events_summary
from services.timeline_fusion import fuse_events, get_timeline_summary, validate_timeline
from services.slideshow_planner import plan_slideshow, build_final_slides

logger = get_logger(__name__)

# Configuration OpenAI
OPENAI_API_KEY = None

def get_api_key():
    """Recupere la cle API OpenAI"""
    global OPENAI_API_KEY
    if OPENAI_API_KEY is None:
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY non definie dans les variables d'environnement")
    return OPENAI_API_KEY


# Configuration
CHUNK_DURATION = 600  # 10 minutes par chunk (pour transcription)
MAX_DURATION = 300    # 5 minutes pour le test (premier audio seulement)
TRANSCRIPTION_MAX_RETRIES = 4


def _post_with_backoff(url, *, headers, files, data, timeout, max_retries=TRANSCRIPTION_MAX_RETRIES):
    """
    Effectue une requête POST avec backoff en cas de 429 ou d'erreurs serveur OpenAI.
    """
    last_exception = None
    last_response = None

    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=timeout
            )
            last_response = response

            if response.status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None
                wait_seconds = retry_after if retry_after is not None else min(30, 2 ** attempt)
                logger.warning(
                    f"Rate limit OpenAI (429) tentative {attempt + 1}/{max_retries}, "
                    f"nouvel essai dans {wait_seconds:.1f}s"
                )
                if attempt < max_retries - 1:
                    time.sleep(wait_seconds)
                    continue
                # Dernière tentative: laisser raise_for_status ci-dessous

            elif response.status_code >= 500:
                wait_seconds = min(30, 2 ** attempt)
                logger.warning(
                    f"Erreur serveur OpenAI {response.status_code} tentative {attempt + 1}/{max_retries}, "
                    f"nouvel essai dans {wait_seconds:.1f}s"
                )
                if attempt < max_retries - 1:
                    time.sleep(wait_seconds)
                    continue
                # Dernière tentative: laisser raise_for_status ci-dessous

            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as exc:
            last_exception = exc
            if attempt < max_retries - 1:
                wait_seconds = min(30, 2 ** attempt)
                logger.warning(
                    f"Erreur réseau OpenAI tentative {attempt + 1}/{max_retries}, "
                    f"nouvel essai dans {wait_seconds:.1f}s: {exc}"
                )
                time.sleep(wait_seconds)
                continue
            raise

    if last_response is not None:
        last_response.raise_for_status()
    if last_exception:
        raise last_exception
    raise RuntimeError("Echec inconnu lors de l'appel OpenAI")


def download_audio(url: str) -> bytes:
    """Telecharge l'audio depuis une URL (Azure CDN)"""
    logger.info(f"Telechargement de l'audio: {url[:50]}...")

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    logger.info(f"Audio telecharge: {len(response.content) / 1024 / 1024:.2f} MB")
    return response.content


def get_audio_duration(audio_bytes: bytes) -> float:
    """Retourne la duree totale de l'audio en secondes"""
    audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
    return len(audio) / 1000.0  # pydub retourne en millisecondes


def extract_audio_segment(audio_bytes: bytes, start_seconds: int = 0, duration_seconds: int = CHUNK_DURATION) -> bytes:
    """
    Extrait un segment d'un fichier audio.

    Args:
        audio_bytes: Audio complet en bytes
        start_seconds: Position de debut (offset)
        duration_seconds: Duree du segment a extraire

    Returns:
        Bytes du segment audio en MP3
    """
    logger.info(f"Extraction segment: {start_seconds}s -> {start_seconds + duration_seconds}s")

    # Charger l'audio avec pydub
    audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))

    # Convertir en millisecondes
    start_ms = start_seconds * 1000
    end_ms = (start_seconds + duration_seconds) * 1000

    # Extraire le segment
    segment = audio[start_ms:end_ms]

    # Exporter en MP3
    output = io.BytesIO()
    segment.export(output, format="mp3", bitrate="128k")
    output.seek(0)

    result = output.read()
    actual_duration = len(segment) / 1000.0
    logger.info(f"Segment extrait: {len(result) / 1024 / 1024:.2f} MB ({actual_duration:.1f}s)")

    return result


def transcribe_chunk(audio_bytes: bytes, chunk_offset: int = 0) -> dict:
    """
    Transcrit un chunk audio avec OpenAI Whisper API.

    Args:
        audio_bytes: Bytes du chunk audio
        chunk_offset: Offset temporel du chunk (pour ajuster les timecodes)

    Returns:
        Dict avec text, segments (avec timecodes absolus), duration
    """
    logger.info(f"Transcription chunk (offset: {chunk_offset}s)...")

    api_key = get_api_key()

    # Sauvegarder temporairement l'audio
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_path = tmp_file.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = _post_with_backoff(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={
                    "Authorization": f"Bearer {api_key}"
                },
                files={
                    "file": ("audio.mp3", audio_file, "audio/mpeg")
                },
                data={
                    "model": "whisper-1",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment"
                },
                timeout=300
            )

        transcription = response.json()

        # Convertir les segments avec timecodes absolus
        segments = []
        for segment in transcription.get("segments", []):
            segments.append({
                "start": segment["start"] + chunk_offset,  # Timecode absolu
                "end": segment["end"] + chunk_offset,
                "text": segment["text"]
            })

        duration = transcription.get("duration", 0)
        logger.info(f"Transcription: {len(transcription.get('text', ''))} chars, {len(segments)} segments")

        return {
            "text": transcription.get("text", ""),
            "segments": segments,
            "duration": duration,
            "chunk_offset": chunk_offset
        }

    finally:
        os.unlink(tmp_path)


def generate_slides_v3(audio_id: int = 1, max_duration: int = MAX_DURATION) -> dict:
    """
    Pipeline v3: Generation de slides avec architecture hierarchique multi-pass.

    Etapes:
    1. Telecharger l'audio
    2. Transcrire en chunks de 10 minutes
    3. Event mapping sur chaque chunk
    4. Fusion inter-blocs
    5. Construction du plan de slides
    6. Generation du contenu minimal

    Args:
        audio_id: ID de l'audio dans COURS_PLAYLIST (1-based)
        max_duration: Duree max a traiter (secondes) - pour les tests

    Returns:
        Dict avec slides, timeline, stats
    """
    logger.info(f"=== Pipeline v3: Generation slides pour audio #{audio_id} ===")

    # 1. Recuperer l'URL de l'audio
    if audio_id < 1 or audio_id > len(COURS_PLAYLIST):
        raise ValueError(f"Audio ID invalide: {audio_id}")

    audio_info = COURS_PLAYLIST[audio_id - 1]
    audio_url = audio_info["filename"]
    logger.info(f"Audio selectionne: {audio_info['title']}")

    # 2. Telecharger l'audio
    audio_bytes = download_audio(audio_url)
    total_duration = min(get_audio_duration(audio_bytes), max_duration)
    logger.info(f"Duree a traiter: {total_duration:.1f}s (max: {max_duration}s)")

    # 3. Transcrire en chunks
    chunks_transcriptions = []
    offset = 0

    while offset < total_duration:
        chunk_duration = min(CHUNK_DURATION, total_duration - offset)
        logger.info(f"Chunk {len(chunks_transcriptions)}: {offset}s -> {offset + chunk_duration}s")

        # Extraire le chunk audio
        chunk_audio = extract_audio_segment(audio_bytes, start_seconds=offset, duration_seconds=chunk_duration)

        # Transcrire avec offset pour timecodes absolus
        transcription = transcribe_chunk(chunk_audio, chunk_offset=offset)
        chunks_transcriptions.append(transcription)

        offset += chunk_duration

    logger.info(f"Transcription complete: {len(chunks_transcriptions)} chunks")

    # 4. Event mapping sur chaque chunk
    logger.info("=== Event Mapping ===")
    all_events = []

    for i, chunk_trans in enumerate(chunks_transcriptions):
        events = map_events(chunk_trans, chunk_index=i, chunk_offset=chunk_trans["chunk_offset"])
        all_events.append(events)
        logger.debug(get_events_summary(events))

    # Compter les evenements
    total_events = sum(len(chunk) for chunk in all_events)
    logger.info(f"Total evenements detectes: {total_events}")

    # 5. Fusion inter-blocs
    logger.info("=== Fusion Inter-Blocs ===")
    merged_timeline = fuse_events(all_events)
    logger.info(get_timeline_summary(merged_timeline))

    # Validation
    validation = validate_timeline(merged_timeline)
    if not validation["valid"]:
        logger.warning(f"Timeline invalide: {validation['issues']}")

    # 6. Construction du plan
    logger.info("=== Construction du Plan ===")
    slide_plan = plan_slideshow(merged_timeline)
    logger.info(f"Plan: {len(slide_plan)} slides decidees")

    # 7. Generation du contenu
    logger.info("=== Generation du Contenu ===")
    slides = build_final_slides(merged_timeline, slide_plan)

    logger.info(f"=== Pipeline termine: {len(slides)} slides generees ===")

    # Flatten all_events pour le debug (liste de tous les evenements par chunk)
    raw_events_flat = []
    for chunk_idx, chunk_events in enumerate(all_events):
        for event in chunk_events:
            raw_events_flat.append({
                **event,
                "chunk_index": chunk_idx
            })

    # Retourner les resultats avec stats ET donnees intermediaires
    return {
        "slides": slides,
        "timeline": merged_timeline,
        "stats": {
            "audio_duration": total_duration,
            "chunks_processed": len(chunks_transcriptions),
            "events_detected": total_events,
            "events_after_fusion": len(merged_timeline),
            "slides_generated": len(slides),
            "slides_planned": len(slide_plan)
        },
        "transcription_full": " ".join([c["text"] for c in chunks_transcriptions]),
        # Donnees intermediaires pour debug/visualisation
        "pipeline_debug": {
            "raw_events": raw_events_flat,  # Evenements bruts avant fusion
            "slide_plan": slide_plan,        # Plan de slides (avant generation contenu)
        }
    }


# ========== Legacy v1 (conserve pour compatibilite) ==========

SEGMENT_DURATION = 150  # 2 minutes 30 secondes

TEMPLATE_MAPPING = [
    {"type": "casestudy", "name": "CaseStudyTemplate"},
    {"type": "reflection", "name": "ReflectionTemplate"},
]

PROMPTS = {
    "casestudy": """Tu es un expert en creation de contenu pedagogique.
Analyse le texte suivant issu d'une formation et extrais exactement 3 idees principales.

Pour chaque idee, fournis:
- title: un titre court et percutant (3-5 mots maximum)
- desc: une description claire en 1-2 phrases

Le titre general de la slide doit resumer le theme aborde.

Texte de la formation:
{segment_text}

Reponds UNIQUEMENT en JSON valide avec ce format exact:
{{"title": "Titre de la slide", "cases": [{{"title": "Idee 1", "desc": "Description..."}}, {{"title": "Idee 2", "desc": "Description..."}}, {{"title": "Idee 3", "desc": "Description..."}}]}}""",

    "reflection": """Tu es un expert en creation de contenu pedagogique.
Analyse le texte suivant et cree une reflexion synthetique pour une slide de formation.

Fournis:
- title: le concept principal ou la question cle (3-6 mots)
- text: un paragraphe de synthese reflexive (3-4 phrases) qui invite a la reflexion

Texte de la formation:
{segment_text}

Reponds UNIQUEMENT en JSON valide avec ce format exact:
{{"title": "Titre reflexif", "text": "Paragraphe de synthese..."}}"""
}


def segment_transcription(transcription: dict, segment_duration: int = SEGMENT_DURATION) -> list:
    """Legacy: Decoupe la transcription en segments de duree fixe."""
    segments = transcription["segments"]
    result = []

    current_segment_start = 0
    current_segment_texts = []

    for seg in segments:
        segment_index = int(seg["start"] // segment_duration)
        expected_start = segment_index * segment_duration

        if expected_start > current_segment_start and current_segment_texts:
            result.append({
                "segment_id": len(result) + 1,
                "start": current_segment_start,
                "end": current_segment_start + segment_duration,
                "text": " ".join(current_segment_texts).strip()
            })
            current_segment_start = expected_start
            current_segment_texts = []

        current_segment_texts.append(seg["text"])

    if current_segment_texts:
        result.append({
            "segment_id": len(result) + 1,
            "start": current_segment_start,
            "end": min(current_segment_start + segment_duration, transcription["duration"]),
            "text": " ".join(current_segment_texts).strip()
        })

    return result


def analyze_segment_with_requests(text: str, template_type: str) -> dict:
    """Legacy: Analyse un segment de texte avec GPT-4."""
    api_key = get_api_key()

    prompt = PROMPTS.get(template_type)
    if not prompt:
        raise ValueError(f"Template non supporte: {template_type}")

    formatted_prompt = prompt.format(segment_text=text)

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "Tu es un assistant qui repond uniquement en JSON valide."},
                {"role": "user", "content": formatted_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        },
        timeout=60
    )

    response.raise_for_status()
    result = response.json()

    content = result["choices"][0]["message"]["content"].strip()

    try:
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        data = json.loads(content)
        return data

    except json.JSONDecodeError:
        if template_type == "casestudy":
            return {
                "title": "Analyse en cours",
                "cases": [
                    {"title": "Point 1", "desc": "Contenu a analyser"},
                    {"title": "Point 2", "desc": "Contenu a analyser"},
                    {"title": "Point 3", "desc": "Contenu a analyser"}
                ]
            }
        else:
            return {
                "title": "Reflexion",
                "text": "Le contenu necessite une analyse plus approfondie."
            }


def generate_slides(audio_id: int = 1) -> list:
    """
    Legacy v1: Generation de slides avec segmentation temporelle fixe.
    Conserve pour compatibilite.
    """
    logger.info(f"=== Legacy v1: Generation slides pour audio #{audio_id} ===")

    if audio_id < 1 or audio_id > len(COURS_PLAYLIST):
        raise ValueError(f"Audio ID invalide: {audio_id}")

    audio_info = COURS_PLAYLIST[audio_id - 1]
    audio_url = audio_info["filename"]

    audio_bytes = download_audio(audio_url)

    # Extraire seulement les 5 premieres minutes
    trimmed_audio = extract_audio_segment(audio_bytes, start_seconds=0, duration_seconds=MAX_DURATION)
    transcription = transcribe_chunk(trimmed_audio, chunk_offset=0)
    transcription["duration"] = MAX_DURATION

    segments = segment_transcription(transcription, segment_duration=SEGMENT_DURATION)

    slides = []
    for i, segment in enumerate(segments):
        template_info = TEMPLATE_MAPPING[i % len(TEMPLATE_MAPPING)]
        template_type = template_info["type"]

        slide_data = analyze_segment_with_requests(segment["text"], template_type)

        slide = {
            "segment_id": segment["segment_id"],
            "start_time": segment["start"],
            "end_time": segment["end"],
            "template_type": template_type,
            "data": slide_data,
            "source_text": segment["text"]
        }

        slides.append(slide)

    return slides


def get_generation_status() -> dict:
    """Retourne le statut du service"""
    return {
        "status": "ready",
        "message": "Service pret (v3 avec architecture hierarchique)",
        "version": "3.0"
    }
