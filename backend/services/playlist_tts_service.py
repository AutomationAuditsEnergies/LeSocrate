"""
Pipeline TTS complète : PDFs d'un dossier → 19 fichiers MP3 conformes à la playlist.

Étapes :
1. Télécharger et concaténer tous les PDFs du dossier
2. Appeler Claude pour reformuler en 7 blocs cours (calibration 192 mots/min)
3. Générer les textes Q&A et pauses
4. TTS fish.audio pour chaque fichier
5. Ajuster la durée avec pydub (silence padding)
6. Upload Azure avec nommage strict
"""

import os
import io
import re
import anthropic
from pydub import AudioSegment
from utils.logger import get_logger
from services.tts_service import convert_to_speech, extract_text_from_pdf
from services.azure_blob_service import (
    upload_blob, download_blob, CONTAINER_DOCUMENTS, CONTAINER_AUDIOS,
    build_blob_path, delete_blobs_by_prefix,
)

logger = get_logger(__name__)

# ─── Constantes ──────────────────────────────────────────────────────────────

WORDS_PER_MINUTE = 192  # Calibré : 18473 mots = 1h36m19s à speed=0.95

# Les 19 fichiers de la playlist avec leurs durées en secondes
PLAYLIST_SPEC = [
    # (filename, duration_seconds, type, bloc_number)
    # === BLOC 1 ===
    ("cours_9h00_9h45.mp3",       2700, "cours", 1),
    ("qa_9h45_9h55.mp3",           600, "qa",    1),
    ("pause_9h55_10h05.mp3",       600, "pause", 1),
    # === BLOC 2 ===
    ("cours_10h05_10h50.mp3",     2700, "cours", 2),
    ("qa_10h50_11h00.mp3",         600, "qa",    2),
    ("pause_11h00_11h05.mp3",      300, "pause", 2),
    # === BLOC 3 ===
    ("cours_11h05_12h00.mp3",     3300, "cours", 3),
    ("qa_12h00_12h10.mp3",         600, "qa",    3),
    ("pause_12h10_12h20.mp3",      600, "pause", 3),
    # === BLOC 4 (nommage fixe, transitions neutres) ===
    ("pause_midi_13h15_14h45.mp3", 5400, "pause_midi", 4),
    ("cours_12h20_13h05.mp3",     2700, "cours", 4),
    ("qa_13h05_13h15.mp3",         600, "qa",    4),
    # === BLOC 5 ===
    ("cours_14h45_15h45.mp3",     3600, "cours", 5),
    ("qa_15h45_16h00.mp3",         900, "qa",    5),
    # === BLOC 6 ===
    ("cours_16h00_17h00.mp3",     3600, "cours", 6),
    ("qa_17h00_17h15.mp3",         900, "qa",    6),
    ("pause_17h15_17h25.mp3",      600, "pause", 6),
    # === BLOC 7 ===
    ("cours_17h25_18h15.mp3",     3000, "cours", 7),
    ("qa_18h15_18h30.mp3",         900, "qa",    7),
]

# Durées des 7 blocs cours en minutes
COURS_DURATIONS_MIN = {
    1: 45,
    2: 45,
    3: 55,
    4: 45,
    5: 60,
    6: 60,
    7: 50,
}

# Marge de sécurité : on vise 30s de moins que la durée max
MARGIN_SECONDS = 30


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _target_word_count(duration_minutes):
    """Nombre de mots cible pour une durée donnée (avec marge de 30s)."""
    effective_minutes = duration_minutes - (MARGIN_SECONDS / 60)
    return int(effective_minutes * WORDS_PER_MINUTE)


def _measure_duration_ms(audio_bytes):
    """Mesure la durée d'un MP3 en millisecondes via pydub."""
    audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
    return len(audio)


def _pad_audio_to_duration(audio_bytes, target_duration_seconds):
    """
    Ajuste un audio à la durée cible exacte :
    - 17s de silence au début (consigne des cours)
    - Si trop court → padding silence à la fin
    - Si trop long → truncate (le TTS a dépassé)
    """
    audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
    target_ms = target_duration_seconds * 1000

    # Silence de début (~17s comme demandé dans les consignes)
    start_silence = AudioSegment.silent(duration=17000)
    audio = start_silence + audio

    current_ms = len(audio)
    if current_ms < target_ms:
        # Trop court → ajouter du silence à la fin
        end_silence = AudioSegment.silent(duration=target_ms - current_ms)
        audio = audio + end_silence
    elif current_ms > target_ms:
        # Trop long → tronquer (le fichier ne doit JAMAIS dépasser la durée)
        logger.warning(f"   ⚠️ Audio trop long ({current_ms/1000:.1f}s > {target_duration_seconds}s), troncature")
        audio = audio[:target_ms]

    # Export MP3
    output = io.BytesIO()
    audio.export(output, format="mp3", bitrate="128k")
    return output.getvalue()


def _build_pause_audio(intro_text, outro_text, target_duration_seconds):
    """
    Construit un audio de pause/Q&A :
    intro TTS + silence + outro TTS, le tout padded à la durée cible.
    """
    intro_bytes = convert_to_speech(intro_text)
    outro_bytes = convert_to_speech(outro_text)

    intro_audio = AudioSegment.from_mp3(io.BytesIO(intro_bytes))
    outro_audio = AudioSegment.from_mp3(io.BytesIO(outro_bytes))

    target_ms = target_duration_seconds * 1000
    silence_ms = target_ms - len(intro_audio) - len(outro_audio) - 17000  # 17s début

    if silence_ms < 1000:
        silence_ms = 1000

    start_silence = AudioSegment.silent(duration=17000)
    mid_silence = AudioSegment.silent(duration=silence_ms)

    full_audio = start_silence + intro_audio + mid_silence + outro_audio

    # Si encore trop court, on pad
    if len(full_audio) < target_ms:
        full_audio = full_audio + AudioSegment.silent(duration=target_ms - len(full_audio))

    output = io.BytesIO()
    full_audio.export(output, format="mp3", bitrate="128k")
    return output.getvalue()


# ─── Claude API : reformulation bloc par bloc ───────────────────────────────

def _count_words_excluding_tags(text):
    """Compte les mots en excluant les tags [entre crochets] du décompte."""
    cleaned = re.sub(r'\[.*?\]', '', text)
    return len(cleaned.split())


def _call_claude_reformulate(course_text, progress_callback=None):
    """
    Appelle Claude pour reformuler le cours en 7 blocs avec les bons nombres de mots.
    Le texte est long (~68k mots en sortie), donc on fait un appel par bloc pour :
    - Rester dans les limites de tokens
    - Avoir un contrôle précis sur le word count de chaque bloc
    - Pouvoir retenter un bloc en cas d'erreur
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    word_targets = {i: _target_word_count(d) for i, d in COURS_DURATIONS_MIN.items()}
    total_target = sum(word_targets.values())

    logger.info(f"📝 Reformulation en 7 blocs ({total_target} mots cible total)")
    logger.info(f"   Texte source: {len(course_text.split())} mots")

    blocs = []

    for bloc_num in range(1, 8):
        target = word_targets[bloc_num]
        duration = COURS_DURATIONS_MIN[bloc_num]

        if progress_callback:
            progress_callback(f"Reformulation bloc {bloc_num}/7 ({target} mots, {duration}min)...")

        # Calculer la proportion du texte source pour ce bloc
        proportion = duration / sum(COURS_DURATIONS_MIN.values())
        words = course_text.split()
        total_words = len(words)
        start_idx = int(sum(COURS_DURATIONS_MIN[i] for i in range(1, bloc_num)) / sum(COURS_DURATIONS_MIN.values()) * total_words)
        end_idx = int(sum(COURS_DURATIONS_MIN[i] for i in range(1, bloc_num + 1)) / sum(COURS_DURATIONS_MIN.values()) * total_words)
        chunk = " ".join(words[start_idx:end_idx])

        # Contexte des blocs précédents (résumé)
        context_prev = ""
        if blocs:
            last_content = blocs[-1]["content"]
            last_sentences = last_content.replace("[", "").replace("]", "").split(".")[-3:]
            context_prev = f"\nLe bloc précédent se terminait par : \"{'.' .join(last_sentences).strip()}\"\nFais une reprise naturelle."

        bloc_prompt = f"""Tu es un professeur passionné qui donne un cours en présentiel à ses élèves.
Tu dois reformuler le contenu ci-dessous en un script oral pour TTS (fish.audio S2-Pro).

BLOC {bloc_num}/7 — {duration} minutes — EXACTEMENT {target} mots (hors tags entre crochets).
{context_prev}

TON ET POSTURE — Tu es un VRAI prof devant sa classe :
- Tu T'ADRESSES DIRECTEMENT aux élèves : "vous voyez ?", "c'est clair pour tout le monde ?",
  "imaginez que...", "regardez bien ce point", "est-ce que ça vous parle ?",
  "je vais vous donner un exemple concret", "retenez bien ceci"
- Tu ILLUSTRES avec des exemples concrets, des anecdotes, des analogies du quotidien
- Tu REFORMULES les concepts difficiles : "autrement dit...", "pour simplifier...",
  "concrètement ça veut dire que..."
- Tu fais des TRANSITIONS pédagogiques : "maintenant qu'on a vu ça, on va passer à...",
  "vous vous souvenez de ce qu'on a dit sur... ? Eh bien..."
- Tu INSISTES sur les points importants : "attention, ça c'est fondamental",
  "je veux que vous reteniez une chose de cette partie..."
- Tu rends le cours VIVANT : tu poses des questions rhétoriques, tu anticipes les
  incompréhensions, tu fais des parallèles avec la vie réelle
- NE LIS PAS un texte — ENSEIGNE. Le résultat doit sonner comme un cours filmé, pas un livre audio

RÈGLES :
- NE MENTIONNE JAMAIS les horaires
{"- TRANSITIONS NEUTRES : pas de référence à la pause déjeuner / l'heure. Ex: 'Très bien, on reprend.'" if bloc_num == 4 else ""}
{"- Commence directement par le contenu (pas de 'Bonjour')" if bloc_num == 1 else "- Commence par une reprise naturelle"}
{"- Termine par une conclusion naturelle du cours entier" if bloc_num == 7 else "- Termine par une phrase de clôture : 'On va s'arrêter ici pour le moment.' ou similaire"}

TAGS FISH.AUDIO S2-PRO — [CROCHETS] UNIQUEMENT (jamais de parenthèses) :
Place des tags en langage naturel libre dans le texte pour le rendre vivant :
- Rythme : [pause] (15-20x), [long pause] (4-6x), [breath] (5-8x)
- Émotions : [excited], [calm], [serious], [warm], [whisper], etc.
- Descriptions libres : [slightly amused], [speak with conviction], [building anticipation], etc.
- Sons : [sigh], [laugh], [gasp] (ponctuellement)
Les tags ne comptent PAS dans les {target} mots.

Réponds UNIQUEMENT avec le texte du bloc (pas de JSON, pas d'explication, juste le script oral avec tags).

CONTENU SOURCE POUR CE BLOC :

{chunk[:30000]}"""

        # Appel API avec retry
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=32000,
                    messages=[{"role": "user", "content": bloc_prompt}],
                )
                content = response.content[0].text.strip()

                actual_words = _count_words_excluding_tags(content)
                tolerance = 0.15  # 15% de tolérance
                if actual_words < target * (1 - tolerance) or actual_words > target * (1 + tolerance):
                    logger.warning(
                        f"   ⚠️ Bloc {bloc_num} attempt {attempt+1}: {actual_words} mots "
                        f"(cible {target}, tolérance ±{int(tolerance*100)}%)"
                    )
                    if attempt < 2:
                        continue  # Retenter

                blocs.append({
                    "bloc_number": bloc_num,
                    "content": content,
                    "word_count": actual_words,
                    "target_words": target,
                })
                logger.info(f"   ✅ Bloc {bloc_num}: {actual_words} mots (cible: {target})")
                break

            except Exception as e:
                logger.error(f"   ❌ Bloc {bloc_num} attempt {attempt+1}: {e}")
                if attempt == 2:
                    raise ValueError(f"Échec reformulation bloc {bloc_num} après 3 tentatives: {e}")

    return blocs


# ─── Textes Q&A et Pauses ───────────────────────────────────────────────────

_QA_VARIANTS = [
    (
        "C'est le moment pour vos questions. "
        "Je vous laisse les poser dans le chat, je serai ravi d'y répondre.",
        "Très bien, on clôture cette session de questions. "
        "Merci pour vos questions, on continue."
    ),
    (
        "On passe maintenant aux questions-réponses. "
        "N'hésitez pas à poser vos questions dans le chat.",
        "Merci pour ces échanges. "
        "On reprend la suite du programme."
    ),
    (
        "C'est votre moment, posez toutes vos questions dans le chat. "
        "Je suis là pour y répondre.",
        "Très bien, merci pour vos questions. "
        "On passe à la suite."
    ),
    (
        "Je vous laisse quelques minutes pour vos questions. "
        "Écrivez-les dans le chat, je les prends dans l'ordre.",
        "Parfait, on a fait le tour. "
        "Merci, on continue."
    ),
    (
        "On fait une petite session questions-réponses. "
        "Le chat est ouvert, allez-y.",
        "On a bien avancé sur vos questions. "
        "Allez, on reprend."
    ),
    (
        "C'est le moment de vos questions. "
        "Envoyez-les dans le chat, je vous réponds.",
        "Merci pour toutes ces questions. "
        "On va reprendre le cours."
    ),
    (
        "Je vous propose une session de questions-réponses. "
        "Posez-les dans le chat, je suis à votre écoute.",
        "Très bien, merci pour ces échanges. "
        "On continue ensemble."
    ),
]

_PAUSE_VARIANTS = [
    (
        "Vous avez maintenant quelques minutes de pause, "
        "profitez-en pour vous détendre.",
        "La pause est terminée, nous allons maintenant reprendre le cours."
    ),
    (
        "On fait une petite pause. "
        "Étirez-vous, prenez un verre d'eau.",
        "C'est reparti, on reprend."
    ),
    (
        "Petite pause bien méritée. "
        "Soufflez un peu, on se retrouve dans quelques minutes.",
        "Allez, on y retourne. On reprend le cours."
    ),
    (
        "On s'accorde une petite coupure. "
        "Profitez-en pour faire une pause.",
        "La pause est finie, on reprend là où on en était."
    ),
]

# Pause midi : transitions neutres (fonctionnent été comme hiver)
_PAUSE_MIDI_INTRO = (
    "Vous avez maintenant une pause. "
    "Profitez-en pour vous reposer et souffler un peu."
)
_PAUSE_MIDI_OUTRO = "La pause est terminée, on reprend."


def _get_qa_text(bloc_number):
    """Retourne le texte d'intro et outro pour un Q&A (varié par bloc)."""
    idx = (bloc_number - 1) % len(_QA_VARIANTS)
    return _QA_VARIANTS[idx]


def _get_pause_text(bloc_number):
    """Retourne le texte d'intro et outro pour une pause courte (varié par bloc)."""
    idx = (bloc_number - 1) % len(_PAUSE_VARIANTS)
    return _PAUSE_VARIANTS[idx]


def _get_pause_midi_text():
    """Retourne le texte d'intro et outro pour la pause déjeuner (neutre)."""
    return _PAUSE_MIDI_INTRO, _PAUSE_MIDI_OUTRO


# ─── Pipeline principale ────────────────────────────────────────────────────

def generate_playlist_for_folder(platform_id, folder_id, progress_callback=None):
    """
    Pipeline complète : génère les 19 fichiers MP3 pour un dossier de cours.

    Args:
        platform_id: ID de la plateforme
        folder_id: ID du dossier de cours
        progress_callback: fonction(step, total, message) pour suivre la progression

    Returns:
        dict avec le statut et les fichiers générés
    """
    def progress(step, total, message):
        logger.info(f"📊 [{step}/{total}] {message}")
        if progress_callback:
            progress_callback(step, total, message)

    total_steps = 5 + 19  # 5 étapes prep + 19 fichiers TTS

    # ── Étape 1 : récupérer les documents du dossier ──
    progress(1, total_steps, "Récupération des documents du dossier...")

    from database.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filename, original_name FROM cours_documents WHERE folder_id = ? ORDER BY id",
        (folder_id,)
    )
    documents = cursor.fetchall()
    conn.close()

    if not documents:
        raise ValueError("Aucun document dans ce dossier")

    logger.info(f"📂 {len(documents)} document(s) trouvé(s) dans le dossier {folder_id}")

    # ── Étape 2 : télécharger et concaténer les PDFs ──
    progress(2, total_steps, f"Extraction du texte de {len(documents)} PDF(s)...")

    all_text = []
    for doc_id, filename, original_name in documents:
        blob_path = build_blob_path(platform_id, folder_id, filename)
        try:
            pdf_bytes = download_blob(CONTAINER_DOCUMENTS, blob_path)
            text = extract_text_from_pdf(pdf_bytes)
            if text and text.strip():
                all_text.append(text)
                logger.info(f"   ✅ {original_name}: {len(text.split())} mots extraits")
            else:
                logger.warning(f"   ⚠️ {original_name}: texte vide")
        except Exception as e:
            logger.error(f"   ❌ {original_name}: {e}")

    if not all_text:
        raise ValueError("Aucun texte extractible des PDFs")

    course_text = "\n\n---\n\n".join(all_text)
    total_words = len(course_text.split())
    logger.info(f"📝 Texte total: {total_words} mots")

    # ── Étape 3 : reformulation via Claude (bloc par bloc) ──
    progress(3, total_steps, f"Reformulation du cours en 7 blocs via Claude ({total_words} mots)...")

    def claude_progress(message):
        progress(3, total_steps, message)

    blocs = _call_claude_reformulate(course_text, progress_callback=claude_progress)

    # Mapper les blocs par numéro
    blocs_by_number = {b["bloc_number"]: b["content"] for b in blocs}

    # Log résumé
    total_generated_words = sum(b["word_count"] for b in blocs)
    total_target_words = sum(_target_word_count(d) for d in COURS_DURATIONS_MIN.values())
    logger.info(f"📝 Total reformulé: {total_generated_words} mots (cible: {total_target_words})")

    # ── Étape 4 : préparer le prefix Azure ──
    progress(4, total_steps, "Préparation de l'upload Azure...")
    azure_prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"

    # Nettoyer les anciens fichiers playlist
    delete_blobs_by_prefix(CONTAINER_AUDIOS, azure_prefix)

    # ── Étape 5 : générer les 19 fichiers ──
    progress(5, total_steps, "Début de la génération TTS des 19 fichiers...")

    generated_files = []
    errors = []

    for i, (filename, duration_sec, file_type, bloc_num) in enumerate(PLAYLIST_SPEC):
        step = 6 + i
        progress(step, total_steps, f"Génération {filename} ({file_type}, bloc {bloc_num})...")

        try:
            if file_type == "cours":
                # Générer le TTS du bloc cours
                bloc_text = blocs_by_number.get(bloc_num)
                if not bloc_text:
                    raise ValueError(f"Bloc {bloc_num} manquant dans la reformulation")

                # Les tags fish.audio sont déjà intégrés par Claude dans la reformulation
                audio_bytes = convert_to_speech(bloc_text)
                duration_ms = _measure_duration_ms(audio_bytes)
                logger.info(f"   TTS brut: {duration_ms/1000:.1f}s (cible: {duration_sec}s)")

                # Padder à la durée cible
                final_bytes = _pad_audio_to_duration(audio_bytes, duration_sec)

            elif file_type == "qa":
                intro, outro = _get_qa_text(bloc_num)
                final_bytes = _build_pause_audio(intro, outro, duration_sec)

            elif file_type == "pause":
                intro, outro = _get_pause_text(bloc_num)
                final_bytes = _build_pause_audio(intro, outro, duration_sec)

            elif file_type == "pause_midi":
                intro, outro = _get_pause_midi_text()
                final_bytes = _build_pause_audio(intro, outro, duration_sec)

            else:
                raise ValueError(f"Type inconnu: {file_type}")

            # Upload vers Azure
            blob_path = f"{azure_prefix}{filename}"
            upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)

            final_duration = _measure_duration_ms(final_bytes) / 1000
            generated_files.append({
                "filename": filename,
                "type": file_type,
                "bloc": bloc_num,
                "duration": final_duration,
                "target_duration": duration_sec,
                "size_bytes": len(final_bytes),
            })
            logger.info(f"   ✅ {filename}: {final_duration:.1f}s uploadé")

        except Exception as e:
            logger.error(f"   ❌ {filename}: {e}")
            errors.append({"filename": filename, "error": str(e)})

    # ── Résultat ──
    total_duration = sum(f["duration"] for f in generated_files)
    total_size = sum(f["size_bytes"] for f in generated_files)
    result = {
        "status": "completed" if not errors else "partial",
        "total_files": 19,
        "generated": len(generated_files),
        "errors": len(errors),
        "files": generated_files,
        "error_details": errors,
        "azure_prefix": azure_prefix,
        "total_duration_hours": round(total_duration / 3600, 1),
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "word_counts": {b["bloc_number"]: b["word_count"] for b in blocs},
    }

    logger.info(f"🏁 Pipeline terminée: {len(generated_files)}/19 fichiers générés, {len(errors)} erreur(s)")
    return result
