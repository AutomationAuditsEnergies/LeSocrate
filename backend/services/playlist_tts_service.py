"""
Pipeline TTS complète : PDFs d'un dossier → 19 fichiers MP3 conformes à la playlist.

Étapes :
1. Télécharger et concaténer tous les PDFs du dossier
2. Appeler Claude pour reformuler en 7 blocs cours (calibration 165,7 mots/min)
3. Générer les textes Q&A et pauses
4. TTS fish.audio pour chaque fichier
5. Ajuster la durée avec pydub (silence padding)
6. Upload Azure avec nommage strict
"""

import os
import io
import re
from pydub import AudioSegment
from utils.logger import get_logger
from utils.anthropic_client import default_model, post_message as _llm_post
from services.tts_service import convert_to_speech, extract_text_from_pdf, extract_text_from_file
from services.azure_blob_service import (
    upload_blob, download_blob, CONTAINER_DOCUMENTS, CONTAINER_AUDIOS,
    build_blob_path, delete_blobs_by_prefix,
)

logger = get_logger(__name__)
LLM_MODEL = default_model()

# ─── Constantes ──────────────────────────────────────────────────────────────

WORDS_PER_MINUTE = 165.7  # Fish Audio mesuré : 11 959 mots = 72,2 min à speed=0.90

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

# Mots nécessaires pour remplir une journée complète (7 blocs cours)
WORDS_NEEDED_PER_DAY = int(round(WORDS_PER_MINUTE * sum(COURS_DURATIONS_MIN.values())))  # 165.7 * 360 ≈ 59 652


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _target_word_count(duration_minutes):
    """Nombre de mots cible pour une durée donnée (avec marge de 30s)."""
    effective_minutes = duration_minutes - (MARGIN_SECONDS / 60)
    return int(effective_minutes * WORDS_PER_MINUTE)


def _measure_duration_ms(audio_bytes):
    """Mesure la durée d'un MP3 en millisecondes via pydub."""
    audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
    return len(audio)


def _pad_audio_to_duration(audio_bytes, target_duration_seconds, truncate_overflow=True):
    """
    Ajuste un audio à la durée cible exacte :
    - 17s de silence au début (consigne des cours)
    - Si trop court → padding silence à la fin
    - Si trop long → truncate si autorisé, sinon erreur explicite
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
        if not truncate_overflow:
            raise ValueError(
                f"Audio trop long ({current_ms/1000:.1f}s > {target_duration_seconds}s) "
                "et troncature interdite"
            )
        # Trop long → tronquer (ancien comportement conservé pour les appels legacy)
        logger.warning(f"   ⚠️ Audio trop long ({current_ms/1000:.1f}s > {target_duration_seconds}s), troncature")
        audio = audio[:target_ms]

    # Export MP3
    output = io.BytesIO()
    audio.export(output, format="mp3", bitrate="128k")
    return output.getvalue()


def _build_pause_audio(intro_text, outro_text, target_duration_seconds, convert_func=None):
    """
    Construit un audio de pause/Q&A :
    intro TTS optionnelle + silence + outro TTS, le tout padded à la durée cible.
    """
    tts = convert_func or convert_to_speech
    intro_text = (intro_text or "").strip()
    outro_text = (outro_text or "").strip()
    if not intro_text and not outro_text:
        raise ValueError("Pause/Q&A vide")

    intro_audio = AudioSegment.empty()
    if intro_text:
        intro_audio = AudioSegment.from_mp3(io.BytesIO(tts(intro_text)))

    outro_audio = AudioSegment.empty()
    if outro_text:
        outro_audio = AudioSegment.from_mp3(io.BytesIO(tts(outro_text)))

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
    Appelle Claude pour reformuler le cours en 7 blocs.

    Logique :
    - On avance dans le texte source séquentiellement
    - Claude reformule fidèlement le contenu, il ne DOIT PAS inventer ou étirer
    - Si le contenu s'épuise avant le bloc 7, les blocs restants sont vides
    - Si du contenu reste après le bloc 7, on le signale dans le résultat
    """
    word_targets = {i: _target_word_count(d) for i, d in COURS_DURATIONS_MIN.items()}

    source_words = course_text.split()
    total_source_words = len(source_words)
    logger.info(f"📝 Texte source: {total_source_words} mots")

    # On découpe le source en 7 parts proportionnelles aux durées
    # Mais c'est juste une SUGGESTION — Claude utilise ce qu'il y a, pas plus
    total_duration = sum(COURS_DURATIONS_MIN.values())
    cursor = 0  # position dans le texte source

    blocs = []

    for bloc_num in range(1, 8):
        target = word_targets[bloc_num]
        duration = COURS_DURATIONS_MIN[bloc_num]

        if progress_callback:
            progress_callback(f"Reformulation bloc {bloc_num}/7 — cible : {duration} min audio...")

        # Calculer combien de mots source donner à ce bloc (proportionnel à la durée)
        proportion = duration / total_duration
        chunk_size = int(total_source_words * proportion)
        chunk_end = min(cursor + chunk_size, total_source_words)
        chunk = " ".join(source_words[cursor:chunk_end])
        cursor = chunk_end

        # Si plus de contenu source → bloc vide
        if not chunk.strip():
            logger.info(f"   ⏭️ Bloc {bloc_num}: plus de contenu source, bloc vide")
            blocs.append({
                "bloc_number": bloc_num,
                "content": "",
                "word_count": 0,
                "target_words": target,
                "skipped": True,
            })
            continue

        # Contexte des blocs précédents
        context_prev = ""
        if blocs and blocs[-1].get("content"):
            last_content = blocs[-1]["content"]
            last_sentences = re.sub(r'\[.*?\]', '', last_content).split(".")[-3:]
            context_prev = f"\nLe bloc précédent se terminait par : \"{'. '.join(s.strip() for s in last_sentences if s.strip())}\"\nFais une reprise naturelle."

        bloc_prompt = f"""Tu es un professeur passionné qui donne un cours en présentiel à ses élèves.
Reformule le contenu ci-dessous en un script oral pour TTS (fish.audio S2-Pro).

BLOC {bloc_num}/7 — durée max : {duration} minutes — vise environ {target} mots (hors tags entre crochets).
{context_prev}

RÈGLE ABSOLUE : REFORMULE FIDÈLEMENT LE CONTENU SOURCE CI-DESSOUS.
- N'invente RIEN. Ne rajoute RIEN qui ne soit pas dans le contenu source.
- Si le contenu source est court, le bloc sera court. C'est NORMAL. Ne rallonge pas artificiellement.
- Tu peux reformuler, illustrer avec des exemples issus du texte, expliquer autrement, mais
  le fond doit rester fidèle au contenu fourni.

TON ET POSTURE — Tu es un VRAI prof devant sa classe :
- Tu T'ADRESSES DIRECTEMENT aux élèves : "vous voyez ?", "c'est clair pour tout le monde ?",
  "imaginez que...", "regardez bien ce point", "est-ce que ça vous parle ?",
  "je vais vous donner un exemple concret", "retenez bien ceci"
- Tu ILLUSTRES avec des exemples concrets, des analogies du quotidien tirées du contenu
- Tu REFORMULES les concepts difficiles : "autrement dit...", "pour simplifier...",
  "concrètement ça veut dire que..."
- Tu fais des TRANSITIONS pédagogiques entre les idées
- Tu INSISTES sur les points importants : "attention, ça c'est fondamental"
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
Les tags ne comptent PAS dans le nombre de mots.

Réponds UNIQUEMENT avec le texte du bloc (pas de JSON, pas d'explication, juste le script oral avec tags).

CONTENU SOURCE POUR CE BLOC :

{chunk[:30000]}"""

        try:
            content = _llm_post(
                messages=[{"role": "user", "content": bloc_prompt}],
                max_tokens=32000,
                model=LLM_MODEL,
                timeout=300,
            ).strip()
            actual_words = _count_words_excluding_tags(content)

            blocs.append({
                "bloc_number": bloc_num,
                "content": content,
                "word_count": actual_words,
                "target_words": target,
            })
            logger.info(f"   ✅ Bloc {bloc_num}: {actual_words} mots (cible: {target})")

        except Exception as e:
            logger.error(f"   ❌ Bloc {bloc_num}: {e}")
            raise ValueError(f"Échec reformulation bloc {bloc_num}: {e}")

    # Contenu source restant non traité
    remaining_words = total_source_words - cursor
    if remaining_words > 50:
        logger.warning(f"⚠️ {remaining_words} mots de contenu source non utilisés (surplus)")

    return blocs, remaining_words


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


def _get_recycled_qa_pause(filename):
    """
    Télécharge un fichier Q&A ou pause depuis le container audioqapause (Azure).
    Ces fichiers sont permanents et réutilisés pour toutes les journées.
    """
    conn_str = os.getenv("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_AUDIO_STORAGE_CONNECTION_STRING non définie dans .env")
    from azure.storage.blob import BlobServiceClient as _BSC
    bsc = _BSC.from_connection_string(conn_str)
    blob_client = bsc.get_blob_client(container="audioqapause", blob=filename)
    return blob_client.download_blob().readall()


def _playlist_items_for_platform(platform_id):
    """Retourne la playlist effective de la plateforme au format PLAYLIST_SPEC."""
    bloc_by_filename = {spec[0]: spec[3] for spec in PLAYLIST_SPEC}

    try:
        from services.audio_service import get_playlist
        playlist = get_playlist(platform_id)
    except Exception as e:
        logger.warning(f"⚠️ Playlist plateforme indisponible, fallback PLAYLIST_SPEC : {e}")
        return list(PLAYLIST_SPEC)

    items = []
    for item in playlist:
        filename = os.path.basename((item.get("filename") or "").split("?", 1)[0])
        file_type = item.get("type")
        duration = int(item.get("duration") or 0)
        bloc_num = bloc_by_filename.get(filename, 1)
        items.append((filename, duration, file_type, bloc_num))
    return items or list(PLAYLIST_SPEC)


def _build_contextual_break_audio(
    filename,
    duration_sec,
    file_type,
    bloc_num,
    item_idx,
    playlist_items,
    blocs_by_number,
):
    from services.break_transition_service import build_break_transition_texts

    intro, outro = build_break_transition_texts(
        filename=filename,
        duration_sec=duration_sec,
        break_type=file_type,
        bloc_num=bloc_num,
        item_idx=item_idx,
        playlist_items=playlist_items,
        get_bloc_text=lambda n: blocs_by_number.get(n, ""),
    )
    try:
        return _build_pause_audio(intro, outro, duration_sec)
    except Exception as e:
        logger.warning(f"⚠️ Q&A/Pause contextuel échoué pour {filename}: {e}; fallback audioqapause")
        return _get_recycled_qa_pause(filename)


def count_words_in_folder(platform_id, folder_id):
    """
    Compte les mots de tous les PDFs d'un dossier.
    Retourne un dict avec total_words, days_coverable, sufficient, words_missing.
    """
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
        return {"total_words": 0, "days_coverable": 0, "sufficient": False, "words_missing": WORDS_NEEDED_PER_DAY, "documents": []}

    doc_details = []
    total_words = 0
    for doc_id, filename, original_name in documents:
        try:
            file_bytes = download_blob(CONTAINER_DOCUMENTS, filename)
            text = extract_text_from_file(file_bytes, original_name)
            word_count = len(text.split()) if text and text.strip() else 0
            total_words += word_count
            doc_details.append({"name": original_name, "words": word_count})
        except Exception as e:
            logger.warning(f"   ⚠️ Impossible de lire {original_name}: {e}")
            doc_details.append({"name": original_name, "words": 0, "error": str(e)})

    days_coverable = round(total_words / WORDS_NEEDED_PER_DAY, 2)
    sufficient = total_words >= WORDS_NEEDED_PER_DAY
    words_missing = max(0, WORDS_NEEDED_PER_DAY - total_words)
    surplus_words = max(0, total_words - WORDS_NEEDED_PER_DAY)

    return {
        "total_words": total_words,
        "words_needed_per_day": WORDS_NEEDED_PER_DAY,
        "days_coverable": days_coverable,
        "sufficient": sufficient,
        "words_missing": words_missing,
        "surplus_words": surplus_words,
        "documents": doc_details,
    }


# ─── Pipeline principale ────────────────────────────────────────────────────

def _generate_mock_blocs():
    """Retourne 7 blocs courts factices (aucun appel Claude) pour les tests."""
    mock_topics = [
        "l'introduction du cours", "les fondamentaux", "les méthodes pratiques",
        "les études de cas", "la réglementation", "l'évaluation", "la conclusion",
    ]
    blocs = []
    for i in range(1, 8):
        target = _target_word_count(COURS_DURATIONS_MIN[i])
        text = (
            f"[MOCK BLOC {i}] Bienvenue dans cette partie consacrée à {mock_topics[i-1]}. "
            f"Ce bloc couvre les points essentiels du programme. "
            f"Prenez le temps d'assimiler chaque notion. "
            f"[pause] On continue avec le contenu principal. "
            f"[warm] Voilà pour ce bloc numéro {i}. "
            f"[pause] Passons à la suite." * 3
        )
        blocs.append({
            "bloc_number": i,
            "content": text,
            "word_count": len(text.split()),
            "target_words": target,
            "skipped": False,
        })
    return blocs


_SILENCE_1S_MP3_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "silence_1s.mp3")
_SILENCE_1S_CACHE = None


def _generate_silence_mp3(duration_sec=1):
    """Retourne un MP3 de silence pour les tests (mode mock TTS).

    N'utilise PAS pydub.AudioSegment.silent().export() parce que cette méthode
    requiert ffmpeg au runtime, et Azure App Service Linux n'a pas ffmpeg
    installé par défaut (cf. "Couldn't find ffmpeg or avconv" dans les logs).
    À la place, on lit un MP3 1s pré-généré stocké dans backend/assets/.
    Pour des durées > 1s, on concatène en bytes (MP3 est un format frame-based,
    la concaténation naïve marche pour des MP3 générés avec les mêmes params).
    """
    global _SILENCE_1S_CACHE
    if _SILENCE_1S_CACHE is None:
        with open(_SILENCE_1S_MP3_PATH, "rb") as f:
            _SILENCE_1S_CACHE = f.read()
    # Pour mock: on retourne juste 1s (les callers passent tous 1 pour l'instant)
    # Si besoin d'étendre: concaténer N copies pour obtenir N secondes
    if duration_sec <= 1:
        return _SILENCE_1S_CACHE
    return _SILENCE_1S_CACHE * int(duration_sec)


def generate_playlist_for_folder(platform_id, folder_id, progress_callback=None, mock=False):
    """
    Pipeline complète : génère les 19 fichiers MP3 pour un dossier de cours.

    Args:
        platform_id: ID de la plateforme
        folder_id: ID du dossier de cours
        progress_callback: fonction(step, total, message) pour suivre la progression
        mock: si True, utilise des blocs factices et du silence 1s au lieu du vrai TTS (tests)

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
        try:
            file_bytes = download_blob(CONTAINER_DOCUMENTS, filename)
            text = extract_text_from_file(file_bytes, original_name)
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

    # ── Étape 3 : reformulation via Claude (ou mock) ──
    if mock:
        progress(3, total_steps, "[MOCK] Génération de blocs factices (0 appel Claude)...")
        blocs = _generate_mock_blocs()
        remaining_source_words = 0
        logger.info("🧪 MODE MOCK playlist — blocs factices générés")
    else:
        progress(3, total_steps, f"Reformulation du cours en 7 blocs via Claude ({total_words} mots source)...")

        def claude_progress(msg):
            # Reformatter le message pour ne pas afficher "(45min)" qui prête à confusion
            progress(3, total_steps, msg)

        blocs, remaining_source_words = _call_claude_reformulate(course_text, progress_callback=claude_progress)

    # Mapper les blocs par numéro (exclure les blocs vides)
    blocs_by_number = {b["bloc_number"]: b["content"] for b in blocs if b.get("content")}

    # Log résumé
    total_generated_words = sum(b["word_count"] for b in blocs)
    filled_blocs = len(blocs_by_number)
    logger.info(f"📝 Total reformulé: {total_generated_words} mots, {filled_blocs}/7 blocs remplis")
    if remaining_source_words > 50:
        logger.warning(f"⚠️ {remaining_source_words} mots source non utilisés (surplus)")

    # ── Étape 4 : préparer le prefix Azure + sauvegarder le script ──
    progress(4, total_steps, "Sauvegarde du script et préparation Azure...")
    azure_prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"

    # Sauvegarder le script reformulé en JSON pour consultation ultérieure
    import json as _json
    script_data = {
        "folder_id": folder_id,
        "platform_id": platform_id,
        "source_words": total_words,
        "filled_blocs": filled_blocs,
        "remaining_source_words": remaining_source_words,
        "blocs": [
            {
                "bloc_number": b["bloc_number"],
                "content": b.get("content", ""),
                "word_count": b.get("word_count", 0),
                "target_words": b.get("target_words", 0),
                "skipped": b.get("skipped", False),
            }
            for b in blocs
        ]
    }
    script_bytes = _json.dumps(script_data, ensure_ascii=False, indent=2).encode("utf-8")
    upload_blob(CONTAINER_AUDIOS, f"{azure_prefix}script.json", script_bytes)
    logger.info(f"📄 Script reformulé sauvegardé dans {azure_prefix}script.json")

    # Nettoyer les anciens fichiers MP3 playlist (mais pas le script)
    existing_blobs = []
    try:
        from azure.storage.blob import BlobServiceClient
        conn_str = os.getenv("AZURE_TTS_STORAGE_CONNECTION_STRING")
        if conn_str:
            bsc = BlobServiceClient.from_connection_string(conn_str)
            cc = bsc.get_container_client(CONTAINER_AUDIOS)
            for blob in cc.list_blobs(name_starts_with=azure_prefix):
                if blob.name.endswith(".mp3"):
                    cc.delete_blob(blob.name)
    except Exception as e:
        logger.warning(f"⚠️ Nettoyage anciens MP3: {e}")

    # ── Étape 5 : générer les 19 fichiers ──
    progress(5, total_steps, "Début de la génération TTS des 19 fichiers...")

    generated_files = []
    errors = []

    playlist_items = _playlist_items_for_platform(platform_id)
    for i, (filename, duration_sec, file_type, bloc_num) in enumerate(playlist_items):
        step = 6 + i
        progress(step, total_steps, f"Génération {filename} ({file_type}, bloc {bloc_num})...")

        try:
            if mock:
                if file_type != "cours":
                    # En mock, on ne génère pas les Q&A et pauses :
                    # ils viennent toujours d'audioqapause, inutile de les uploader ici
                    logger.info(f"   🧪 [MOCK] {filename}: skip (Q&A/pause vient d'audioqapause)")
                    continue
                # Mode mock cours : 1 seconde de silence
                final_bytes = _generate_silence_mp3(1)
                logger.info(f"   🧪 [MOCK] {filename}: silence 1s")

            elif file_type == "cours":
                # Générer le TTS du bloc cours
                bloc_text = blocs_by_number.get(bloc_num)
                if not bloc_text:
                    logger.info(f"   ⏭️ {filename}: bloc {bloc_num} vide, skip")
                    continue

                audio_bytes = convert_to_speech(bloc_text)
                duration_ms = _measure_duration_ms(audio_bytes)
                logger.info(f"   TTS brut: {duration_ms/1000:.1f}s (cible: {duration_sec}s)")
                final_bytes = _pad_audio_to_duration(audio_bytes, duration_sec)

            elif file_type == "qa":
                if bloc_num not in blocs_by_number:
                    logger.info(f"   ⏭️ {filename}: bloc {bloc_num} vide, skip Q&A")
                    continue
                final_bytes = _build_contextual_break_audio(
                    filename, duration_sec, file_type, bloc_num, i,
                    playlist_items, blocs_by_number,
                )
                logger.info(f"   🧩 {filename}: Q&A contextuel généré")

            elif file_type == "pause":
                from services.break_transition_service import nearest_course_bloc

                prev_course = nearest_course_bloc(playlist_items, i, -1) or bloc_num
                next_course = nearest_course_bloc(playlist_items, i, 1)
                if prev_course not in blocs_by_number and next_course not in blocs_by_number:
                    logger.info(f"   ⏭️ {filename}: blocs voisins vides, skip pause")
                    continue
                final_bytes = _build_contextual_break_audio(
                    filename, duration_sec, file_type, bloc_num, i,
                    playlist_items, blocs_by_number,
                )
                logger.info(f"   🧩 {filename}: pause contextuelle générée")

            elif file_type == "pause_midi":
                final_bytes = _build_contextual_break_audio(
                    filename, duration_sec, file_type, bloc_num, i,
                    playlist_items, blocs_by_number,
                )
                logger.info(f"   🧩 {filename}: pause midi contextuelle générée")

            else:
                raise ValueError(f"Type inconnu: {file_type}")

            # Upload vers Azure
            blob_path = f"{azure_prefix}{filename}"
            upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)

            if mock:
                final_duration = 1.0
            else:
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
    skipped_blocs = [b["bloc_number"] for b in blocs if b.get("skipped")]
    result = {
        "status": "completed" if not errors else "partial",
        "total_files": 19,
        "generated": len(generated_files),
        "skipped": 19 - len(generated_files) - len(errors),
        "errors": len(errors),
        "files": generated_files,
        "error_details": errors,
        "azure_prefix": azure_prefix,
        "total_duration_hours": round(total_duration / 3600, 1),
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "word_counts": {b["bloc_number"]: b["word_count"] for b in blocs},
        "filled_blocs": filled_blocs,
        "skipped_blocs": skipped_blocs,
        "remaining_source_words": remaining_source_words,
    }

    logger.info(f"🏁 Pipeline terminée: {len(generated_files)}/19 fichiers générés, {len(errors)} erreur(s)")
    return result
