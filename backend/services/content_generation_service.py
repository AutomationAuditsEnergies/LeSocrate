"""
Service de génération de contenu TTS-direct.

Pipeline par dossier (= 1 journée de formation) :
  1. Extraction automatique de 6 sous-parties depuis le programme (1 appel Claude)
  2. Pour chaque sous-partie : Passe 1 → Passe 2 → Passe 3 (~5 100 mots chacune)
  3. Total ~92 000 mots TTS-ready → sauvegardé comme document .txt dans le dossier

Checkpointing : chaque segment complété est sauvegardé en DB immédiatement.
En cas d'interruption, la génération reprend au segment suivant non complété.
"""

import os
import re
import json
import time
import uuid as uuid_mod

import requests as _http

from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"
NUM_SUB_PARTS = 6

# ─── Texte mock pour les tests ───────────────────────────────────────────────

_MOCK_PASSE_LABELS = ["fondation", "expansion", "enrichissement"]
_MOCK_PHRASES = [
    "Ce module aborde les fondamentaux essentiels de cette thématique.",
    "Chaque notion est construite progressivement pour faciliter l'assimilation.",
    "Les exemples concrets viennent illustrer la théorie à chaque étape.",
    "Le formateur insiste sur les points clés à retenir pour la pratique professionnelle.",
    "Des mises en situation permettront de consolider les apprentissages.",
    "Il est important de bien comprendre le contexte avant d'aller plus loin.",
    "Les compétences acquises ici seront réutilisées tout au long de la formation.",
    "Prenez le temps d'assimiler chaque notion avant de passer à la suivante.",
]

def _generate_mock_text(passe, sub_part_name, sub_idx):
    """Génère ~220 mots de texte factice structuré pour les tests (sans appel Claude)."""
    label = _MOCK_PASSE_LABELS[passe - 1]
    lines = [
        f"Bonjour et bienvenue dans cette partie consacrée à {sub_part_name}.",
        f"Nous abordons ici la {label} de ce module. [MODE TEST — Passe {passe}/3 — Sous-partie {sub_idx + 1}]",
        "",
    ]
    # Répéter les phrases pour atteindre ~200 mots
    for i, phrase in enumerate(_MOCK_PHRASES * 3):
        lines.append(f"{phrase} ({sub_part_name}, itération {i + 1}.)")
    lines += [
        "",
        f"Voilà pour cette passe {passe} dédiée à {sub_part_name}.",
        f"Nous avons couvert l'essentiel de la {label}. Passons à la suite.",
    ]
    return "\n".join(lines)

# Chemins vers les fichiers de prompts
_PROMPT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "prompt-generation-tts-direct.md"
)
_PROMPT_FILE_SCRATCH = os.path.join(
    os.path.dirname(__file__), "..", "..", "prompt-generation-tts-scratch.md"
)

# Cache des prompts invalidé sur mtime du fichier source — permet d'éditer
# les prompts .md sans redémarrer le backend (watchmedo ne watch que *.py).
# Structure : (prompts_list, mtime) ou None.
_PASSE_PROMPTS = None           # mode expansion
_PASSE_PROMPTS_SCRATCH = None   # mode from_scratch


def _parse_passe_prompts_from_file(path: str) -> list:
    """Extrait les 3 blocs ``` ``` sous les titres ## PASSE N du fichier."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"## PASSE \d[^`]*```(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)
    if len(matches) < 3:
        raise ValueError(f"Impossible de trouver les 3 prompts dans {path} ({len(matches)} trouvés)")
    return [m.strip() for m in matches[:3]]


def _get_passe_prompts(from_scratch=False):
    """
    Retourne les 3 prompts (Passe 1/2/3) depuis le bon fichier .md.
    Recharge automatiquement si le fichier a été modifié depuis la dernière lecture.
    """
    global _PASSE_PROMPTS, _PASSE_PROMPTS_SCRATCH
    path = _PROMPT_FILE_SCRATCH if from_scratch else _PROMPT_FILE
    mtime = os.path.getmtime(path)

    cached = _PASSE_PROMPTS_SCRATCH if from_scratch else _PASSE_PROMPTS
    if cached is not None and cached[1] == mtime:
        return cached[0]

    prompts = _parse_passe_prompts_from_file(path)
    if from_scratch:
        _PASSE_PROMPTS_SCRATCH = (prompts, mtime)
    else:
        _PASSE_PROMPTS = (prompts, mtime)
    logger.info(f"📖 Prompts rechargés depuis {os.path.basename(path)}")
    return prompts


# ─── Extraction des sous-parties ─────────────────────────────────────────────

_EXTRACT_PROMPT = """Tu analyses un programme de formation professionnelle.
Ton rôle : identifier exactement 6 sous-parties distinctes qui couvriront une journée complète de formation.

Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après :
{{
  "title": "Nom exact du titre professionnel préparé",
  "sub_parts": [
    "Nom précis de la sous-partie 1",
    "Nom précis de la sous-partie 2",
    "Nom précis de la sous-partie 3",
    "Nom précis de la sous-partie 4",
    "Nom précis de la sous-partie 5",
    "Nom précis de la sous-partie 6"
  ]
}}

Règles :
- Exactement 6 sous-parties (ni plus ni moins)
- Chaque nom doit être suffisamment précis pour orienter la génération de 15 000 mots de cours oral
- Couvrir l'essentiel du programme sans répétition entre sous-parties
- Si le programme couvre 2 journées, prendre uniquement les sous-parties de la première moitié

PROGRAMME :
{program_text}"""


def _anthropic_post(messages, max_tokens, model=None):
    """Appel direct à l'API Anthropic via requests (évite le conflit trio/eventlet)."""
    resp = _http.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model or CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def extract_sub_parts(program_text):
    """
    Appelle Claude pour extraire 6 sous-parties depuis le programme.
    Synchrone — retourne {"title": str, "sub_parts": [str×6]} ou lève une exception.
    """
    prompt = _EXTRACT_PROMPT.replace("{program_text}", program_text[:15000])

    logger.info("🔍 Extraction des sous-parties avec Claude...")

    for attempt in range(3):
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            ).strip()

            # Nettoyer au cas où Claude ajoute du texte avant/après le JSON
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                raise ValueError("Pas de JSON valide dans la réponse")

            data = json.loads(json_match.group())
            if "sub_parts" not in data or len(data["sub_parts"]) < 1:
                raise ValueError(f"Format incorrect : {list(data.keys())}")

            # Forcer exactement 6 sous-parties
            sub_parts = data["sub_parts"][:NUM_SUB_PARTS]
            while len(sub_parts) < NUM_SUB_PARTS:
                sub_parts.append(f"Sous-partie {len(sub_parts) + 1}")

            result = {"title": data.get("title", "Formation professionnelle"), "sub_parts": sub_parts}
            logger.info(f"✅ {len(result['sub_parts'])} sous-parties extraites pour : {result['title']}")
            return result

        except Exception as e:
            if attempt < 2:
                logger.warning(f"⚠️ Tentative extraction {attempt+1}/3 échouée : {e}, retry...")
                time.sleep(3)
            else:
                raise ValueError(f"Extraction échouée après 3 tentatives : {e}")


# ─── Génération d'un segment (une passe) ─────────────────────────────────────

def _generate_segment_text(passe, sub_part_name, program_title, program_text, prev_text,
                           from_scratch=False, module_content="", model=None):
    """
    Génère le texte d'un segment via Claude.
    passe : 1, 2 ou 3

    Mode expansion (from_scratch=False) — comportement historique :
      - prev_text : texte passe 1 pour passe 2, texte passe 1+2 pour passe 3

    Mode from_scratch (from_scratch=True) — nouveau pipeline formation :
      - Chaque passe génère depuis module_content (pas du texte précédent)
      - Passe 1 = Fondation, Passe 2 = Pratique, Passe 3 = Maîtrise

    Retourne le texte généré (~5 000 mots).
    """
    prompts = _get_passe_prompts(from_scratch=from_scratch)
    template = prompts[passe - 1]

    if from_scratch:
        # Mode from_scratch : toutes les passes reçoivent le contenu du module
        prompt = template
        prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
        prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
        prompt = prompt.replace("{CONTENU_DU_MODULE}", (module_content or program_text)[:15000])
    else:
        # Mode expansion (comportement historique)
        if passe == 1:
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_PROGRAMME_ICI}", program_text[:12000])
        elif passe == 2:
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_TEXTE_DE_LA_PASSE_1}", prev_text[:40000])
        else:  # passe 3
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_TEXTE_COMPLET_PASSE_1_ET_2}", prev_text[:60000])

    mode_label = "from_scratch" if from_scratch else "expansion"
    logger.info(f"  📝 Génération passe {passe} [{mode_label}] pour '{sub_part_name}'...")

    for attempt in range(3):
        try:
            generated = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=16000,
                model=model,
            )
            words = len(generated.split())
            logger.info(f"  ✅ Passe {passe} terminée : {words} mots")
            return generated.strip()

        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                logger.warning(f"  ⚠️ Retry {attempt+1}/3 dans {wait}s : {e}")
                time.sleep(wait)
            else:
                raise


# ─── Helpers DB ──────────────────────────────────────────────────────────────

def start_generation_job(folder_id: int, platform_id: int, program_text: str,
                         program_title: str, sub_parts_override: list = None,
                         module_contents: dict = None, from_scratch: bool = False,
                         model: str = None):
    """
    Crée le job DB et lance la génération en background thread.
    Utilisé par le pipeline formation automatisé.

    sub_parts_override : liste de noms de sous-parties (bypass extraction Claude)
    module_contents    : dict {sub_part_name: contenu_module} pour le mode from_scratch
    from_scratch       : True = passes indépendantes depuis module_content (nouveau paradigme)
    """
    import threading

    # Extraction des sous-parties si pas fournie
    if sub_parts_override:
        sub_parts = sub_parts_override[:NUM_SUB_PARTS]
        while len(sub_parts) < NUM_SUB_PARTS:
            sub_parts.append(f"Sous-partie {len(sub_parts) + 1}")
        title = program_title
    else:
        extracted = extract_sub_parts(program_text)
        sub_parts = extracted["sub_parts"]
        title = extracted.get("title", program_title) or program_title

    conn = get_db_connection()
    cursor = conn.cursor()
    # Supprimer anciens segments si réinitialisation
    cursor.execute("""
        DELETE FROM content_generation_segments WHERE job_id IN (
            SELECT id FROM content_generation_jobs WHERE folder_id = ?
        )
    """, (folder_id,))
    cursor.execute("""
        INSERT OR REPLACE INTO content_generation_jobs
            (folder_id, platform_id, program_text, program_title, sub_parts,
             from_scratch, module_contents,
             status, current_sub_part, current_passe, total_words, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'idle', 0, 1, 0, NULL)
    """, (
        folder_id, platform_id, program_text, title,
        json.dumps(sub_parts, ensure_ascii=False),
        1 if from_scratch else 0,
        json.dumps(module_contents or {}, ensure_ascii=False),
    ))
    conn.commit()
    conn.close()

    # Lancer génération en background
    def _run():
        try:
            run_content_generation(folder_id, mode="normal", model=model)
        except Exception as e:
            logger.error(f"❌ Génération background dossier {folder_id} : {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"🚀 Génération lancée en background pour dossier {folder_id} (from_scratch={from_scratch})")


def get_job_from_db(folder_id):
    """Retourne le job DB pour un dossier, ou None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, platform_id, program_text, program_title, sub_parts, status,
               current_sub_part, current_passe, total_words, error_message,
               from_scratch, module_contents
        FROM content_generation_jobs WHERE folder_id = ?
    """, (folder_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "platform_id": row[1], "program_text": row[2],
        "program_title": row[3], "sub_parts": json.loads(row[4] or "[]"),
        "status": row[5], "current_sub_part": row[6], "current_passe": row[7],
        "total_words": row[8], "error_message": row[9],
        "from_scratch": bool(row[10]),
        "module_contents": json.loads(row[11] or "{}"),
    }


def get_segments_status(job_id):
    """Retourne la liste des segments avec leur statut."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, sub_part_name, passe, status, word_count
        FROM content_generation_segments
        WHERE job_id = ?
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"sub_part_index": r[0], "sub_part_name": r[1], "passe": r[2],
         "status": r[3], "word_count": r[4]}
        for r in rows
    ]


def _update_job_db(job_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE content_generation_jobs SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def _get_completed_segments(job_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
    """, (job_id,))
    done = set((r[0], r[1]) for r in cursor.fetchall())
    conn.close()
    return done


def _save_segment_db(job_id, sub_idx, sub_part_name, passe, text):
    word_count = len(text.split())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO content_generation_segments
            (job_id, sub_part_index, sub_part_name, passe, status, text_content, word_count)
        VALUES (?, ?, ?, ?, 'completed', ?, ?)
    """, (job_id, sub_idx, sub_part_name, passe, text, word_count))
    conn.commit()
    conn.close()
    logger.info(f"  💾 Checkpoint : sous-partie {sub_idx+1}, passe {passe} ({word_count} mots)")


def _get_segment_text(job_id, sub_idx, passe):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT text_content FROM content_generation_segments
        WHERE job_id = ? AND sub_part_index = ? AND passe = ?
    """, (job_id, sub_idx, passe))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""


# ─── Assemblage final ─────────────────────────────────────────────────────────

def _assemble_and_upload(folder_id, platform_id, job_id):
    """
    Concatène tous les segments complétés et uploade le texte final
    vers Azure comme document .txt dans le dossier.
    Retourne le nombre total de mots.
    """
    from services.azure_blob_service import upload_blob, CONTAINER_DOCUMENTS

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, text_content
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()

    # Assembler dans l'ordre sous-partie → passe
    parts_by_idx = {}
    for sub_idx, passe, text in rows:
        parts_by_idx.setdefault(sub_idx, {})[passe] = text

    final_parts = []
    for sub_idx in sorted(parts_by_idx.keys()):
        for passe in sorted(parts_by_idx[sub_idx].keys()):
            final_parts.append(parts_by_idx[sub_idx][passe])

    full_text = "\n\n".join(final_parts)
    total_words = len(full_text.split())

    # Chemin blob unique
    file_uuid = uuid_mod.uuid4()
    blob_path = f"platform-{platform_id}/folder-{folder_id}/{file_uuid}.txt"
    original_name = f"cours_genere_{uuid_mod.uuid4().hex[:6]}.txt"

    upload_blob(CONTAINER_DOCUMENTS, blob_path, full_text.encode("utf-8"))

    # Enregistrer comme document dans la DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cours_documents (folder_id, filename, original_name, status)
        VALUES (?, ?, ?, 'uploaded')
    """, (folder_id, blob_path, original_name))
    conn.commit()
    conn.close()

    logger.info(f"✅ Texte final : {total_words} mots → {blob_path}")
    return total_words, original_name


# ─── Pipeline principale ──────────────────────────────────────────────────────

def run_content_generation(folder_id, on_progress=None, mode="normal", model=None):
    """
    Lance ou reprend la génération de contenu pour un dossier.
    Doit être appelé dans un greenlet eventlet (non-bloquant).

    on_progress(sub_idx, total_sub_parts, passe, total_words, message) — callback optionnel.

    mode :
      "normal" — génération complète via Claude (~92 000 mots)
      "mock"   — texte factice instantané, 0 appel Claude (pour tests)
      "mini"   — 1 seule sous-partie × 1 seule passe, max_tokens 300 (~0.02€)
    """

    def _progress(sub_idx, passe, total_words, message):
        if on_progress:
            on_progress(sub_idx, NUM_SUB_PARTS, passe, total_words, message)

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun job trouvé pour le dossier {folder_id}")

    job_id = job["id"]
    platform_id = job["platform_id"]
    program_text = job["program_text"]
    program_title = job["program_title"]
    sub_parts = job["sub_parts"]
    from_scratch = job.get("from_scratch", False)
    module_contents = job.get("module_contents", {})

    is_mock = mode == "mock"
    is_mini = mode == "mini"

    if is_mock:
        logger.info(f"🧪 MODE MOCK — génération factice pour dossier {folder_id}")
    elif is_mini:
        logger.info(f"🧪 MODE MINI — 1 sous-partie × 1 passe, 300 tokens")

    _update_job_db(job_id, status="running", error_message=None)

    try:
        done_set = _get_completed_segments(job_id)
        total_words = job["total_words"] or 0

        # En mode mini : seulement la première sous-partie, passe 1
        sub_parts_to_run = [sub_parts[0]] if is_mini else sub_parts
        passes_to_run = [1] if is_mini else [1, 2, 3]

        for sub_idx, sub_part_name in enumerate(sub_parts_to_run):
            passe1_text = _get_segment_text(job_id, sub_idx, 1) if (sub_idx, 1) in done_set else ""
            passe1_2_text = (
                passe1_text + "\n\n" + _get_segment_text(job_id, sub_idx, 2)
                if (sub_idx, 2) in done_set else ""
            )

            for passe in passes_to_run:
                if (sub_idx, passe) in done_set:
                    logger.info(f"  ♻️ Sous-partie {sub_idx+1}, passe {passe} : déjà fait, skip")
                    continue

                msg = f"Sous-partie {sub_idx + 1}/{NUM_SUB_PARTS} · Passe {passe}/3 — {sub_part_name}"
                if is_mock:
                    msg = f"[MOCK] {msg}"
                _progress(sub_idx, passe, total_words, msg)
                _update_job_db(job_id, current_sub_part=sub_idx, current_passe=passe)

                if is_mock:
                    time.sleep(0.8)  # Simule un délai réaliste
                    text = _generate_mock_text(passe, sub_part_name, sub_idx)
                elif is_mini:
                    text = _generate_segment_mini(sub_part_name, program_title, program_text)
                elif from_scratch:
                    # Mode from_scratch : chaque passe génère depuis le contenu du module
                    module_content = module_contents.get(sub_part_name, "")
                    text = _generate_segment_text(
                        passe, sub_part_name, program_title, program_text,
                        prev_text="", from_scratch=True, module_content=module_content,
                        model=model,
                    )
                else:
                    prev = "" if passe == 1 else (passe1_text if passe == 2 else passe1_2_text)
                    text = _generate_segment_text(passe, sub_part_name, program_title, program_text, prev, model=model)

                _save_segment_db(job_id, sub_idx, sub_part_name, passe, text)
                words_added = len(text.split())
                total_words += words_added
                _update_job_db(job_id, total_words=total_words)

                if passe == 1:
                    passe1_text = text
                elif passe == 2:
                    passe1_2_text = passe1_text + "\n\n" + text

        # En mode mini : marquer completed sans upload (pas de texte complet)
        if is_mini:
            _update_job_db(job_id, status="completed", total_words=total_words)
            _progress(1, 1, total_words, f"✅ [MINI] 1 segment généré ({total_words} mots) — pas d'upload Azure")
            logger.info(f"✅ [MINI] Génération terminée pour dossier {folder_id} : {total_words} mots")
            return

        # Assemblage + upload
        _progress(NUM_SUB_PARTS, 3, total_words, "Assemblage et upload du texte final...")
        final_words, filename = _assemble_and_upload(folder_id, platform_id, job_id)

        _update_job_db(job_id, status="completed", total_words=final_words)
        _progress(NUM_SUB_PARTS, 3, final_words, f"✅ Terminé : {final_words} mots — fichier {filename} ajouté aux sources")
        logger.info(f"✅ Génération terminée pour dossier {folder_id} : {final_words} mots")

    except Exception as e:
        logger.error(f"❌ Erreur génération contenu dossier {folder_id} : {e}")
        _update_job_db(job_id, status="error", error_message=str(e))
        raise


def generate_audio_from_script(folder_id, on_progress=None, force_all=False, mock=False):
    """
    Génère (ou régénère) les 7 fichiers MP3 cours à partir du script TTS stocké en DB.

    Logique de régénération sélective :
    - Assemble les segments en ordre (sub_part × passe)
    - Découpe le texte total en 7 blocs proportionnels aux durées de la playlist
    - Pour chaque bloc, vérifie si au moins un segment contributeur est dirty=1
    - Si dirty (ou force_all=True) → génère le TTS + upload Azure
    - Si propre → conserve l'ancien MP3

    Après génération réussie d'un bloc : marque ses segments dirty=0.
    """
    from services.playlist_tts_service import (
        COURS_DURATIONS_MIN, PLAYLIST_SPEC, _pad_audio_to_duration, _measure_duration_ms
    )
    from services.tts_service import convert_to_speech
    from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS

    def _progress(step, total, msg):
        if on_progress:
            on_progress(step, total, msg)

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun script TTS pour le dossier {folder_id}")

    platform_id = job["platform_id"]
    job_id = job["id"]

    # ── 1. Charger tous les segments complétés dans l'ordre ──
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, text_content, word_count, dirty
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise ValueError("Aucun segment généré — lancez d'abord la génération du script")

    # Construire la liste ordonnée des segments avec leur index global
    segments = [
        {"sub_idx": r[0], "passe": r[1], "text": r[2], "word_count": r[3], "dirty": bool(r[4])}
        for r in rows
    ]

    # ── 2. Assembler le texte complet et mapper chaque mot → segment index ──
    full_words = []
    word_to_seg_idx = []  # pour chaque position mot, l'index du segment

    for seg_idx, seg in enumerate(segments):
        words = seg["text"].split()
        full_words.extend(words)
        word_to_seg_idx.extend([seg_idx] * len(words))

    total_words = len(full_words)
    logger.info(f"📝 Script total : {total_words} mots, {len(segments)} segments")

    # ── 3. Découper en 7 blocs proportionnels aux durées ──
    total_duration = sum(COURS_DURATIONS_MIN.values())
    blocs = []
    cursor_w = 0

    for bloc_num in range(1, 8):
        duration = COURS_DURATIONS_MIN[bloc_num]
        proportion = duration / total_duration
        bloc_words_count = round(total_words * proportion)
        end_w = min(cursor_w + bloc_words_count, total_words)

        # Texte de ce bloc
        bloc_text = " ".join(full_words[cursor_w:end_w])

        # Segments qui contribuent à ce bloc
        contributing_seg_indices = set(word_to_seg_idx[cursor_w:end_w])

        # Ce bloc est dirty si au moins un de ses segments a été modifié
        is_dirty = force_all or any(segments[i]["dirty"] for i in contributing_seg_indices)

        # Durée cible en secondes (depuis PLAYLIST_SPEC)
        target_sec = next(
            (spec[1] for spec in PLAYLIST_SPEC if spec[3] == bloc_num and spec[2] == "cours"),
            duration * 60
        )

        blocs.append({
            "bloc_number": bloc_num,
            "text": bloc_text,
            "contributing_seg_indices": contributing_seg_indices,
            "dirty": is_dirty,
            "target_sec": target_sec,
            "filename": next(
                (spec[0] for spec in PLAYLIST_SPEC if spec[3] == bloc_num and spec[2] == "cours"),
                f"cours_bloc{bloc_num}.mp3"
            ),
        })
        cursor_w = end_w

    dirty_count = sum(1 for b in blocs if b["dirty"])
    clean_count = 7 - dirty_count
    logger.info(f"🎯 {dirty_count}/7 blocs à régénérer, {clean_count}/7 conservés")

    _progress(0, 7, f"{dirty_count}/7 blocs à régénérer ({clean_count} conservés)...")

    # ── 4. Générer le TTS uniquement pour les blocs dirty ──
    azure_prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"
    generated = []
    skipped = []

    for i, bloc in enumerate(blocs):
        step = i + 1
        filename = bloc["filename"]
        target_sec = bloc["target_sec"]

        if not bloc["dirty"]:
            logger.info(f"   ⏭️ Bloc {bloc['bloc_number']} ({filename}) : non modifié, conservé")
            _progress(step, 7, f"Bloc {bloc['bloc_number']}/7 — conservé (non modifié)")
            skipped.append(filename)
            continue

        if not bloc["text"].strip():
            logger.info(f"   ⏭️ Bloc {bloc['bloc_number']} : texte vide, skip")
            skipped.append(filename)
            continue

        if mock:
            _progress(step, 7, f"[MOCK] Bloc {bloc['bloc_number']}/7 — silence 1s...")
            logger.info(f"   🧪 [MOCK] Bloc {bloc['bloc_number']} ({filename}) — silence 1s")
            from services.playlist_tts_service import _generate_silence_mp3
            final_bytes = _generate_silence_mp3(1)
        else:
            _progress(step, 7, f"Bloc {bloc['bloc_number']}/7 — génération TTS ({len(bloc['text'].split())} mots)...")
            logger.info(f"   🎙️ Bloc {bloc['bloc_number']} ({filename}) — TTS en cours...")
            audio_bytes = convert_to_speech(bloc["text"])
            raw_duration = _measure_duration_ms(audio_bytes) / 1000
            logger.info(f"   TTS brut : {raw_duration:.1f}s (cible : {target_sec}s)")
            final_bytes = _pad_audio_to_duration(audio_bytes, target_sec)
        blob_path = f"{azure_prefix}{filename}"
        upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)

        final_duration = _measure_duration_ms(final_bytes) / 1000
        logger.info(f"   ✅ {filename} : {final_duration:.1f}s uploadé")
        generated.append(filename)

        # Marquer les segments contributeurs comme propres (dirty=0)
        seg_keys = [
            (segments[i]["sub_idx"], segments[i]["passe"])
            for i in bloc["contributing_seg_indices"]
            if segments[i]["dirty"]
        ]
        if seg_keys:
            conn = get_db_connection()
            cur2 = conn.cursor()
            for sub_idx, passe in seg_keys:
                cur2.execute("""
                    UPDATE content_generation_segments
                    SET dirty = 0
                    WHERE job_id = ? AND sub_part_index = ? AND passe = ?
                """, (job_id, sub_idx, passe))
            conn.commit()
            conn.close()

    _progress(7, 7, f"✅ Terminé — {len(generated)} régénérés, {len(skipped)} conservés")
    logger.info(f"✅ generate_audio_from_script : {len(generated)} régénérés, {len(skipped)} conservés")

    return {"generated": len(generated), "skipped": len(skipped), "files": generated}


def get_script_dirty_blocs(folder_id):
    """
    Retourne le nombre de blocs cours qui seraient régénérés si on lance la génération audio.
    Utilisé par le frontend pour afficher un indicateur.
    """
    from services.playlist_tts_service import COURS_DURATIONS_MIN

    job = get_job_from_db(folder_id)
    if not job:
        return {"dirty_blocs": 0, "total_blocs": 7, "has_script": False}

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, word_count, dirty
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job["id"],))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"dirty_blocs": 0, "total_blocs": 7, "has_script": True}

    segments = [{"sub_idx": r[0], "passe": r[1], "wc": r[2], "dirty": bool(r[3])} for r in rows]
    total_words = sum(s["wc"] for s in segments)

    word_to_seg_idx = []
    for si, seg in enumerate(segments):
        word_to_seg_idx.extend([si] * seg["wc"])

    total_duration = sum(COURS_DURATIONS_MIN.values())
    dirty_blocs = 0
    cursor_w = 0

    for bloc_num in range(1, 8):
        proportion = COURS_DURATIONS_MIN[bloc_num] / total_duration
        end_w = min(cursor_w + round(total_words * proportion), total_words)
        contributing = set(word_to_seg_idx[cursor_w:end_w])
        if any(segments[i]["dirty"] for i in contributing):
            dirty_blocs += 1
        cursor_w = end_w

    return {"dirty_blocs": dirty_blocs, "total_blocs": 7, "has_script": True}


def _generate_segment_mini(sub_part_name, program_title, program_text):
    """Génère un court segment via Claude (300 tokens max) pour tester l'intégration."""
    prompts = _get_passe_prompts()
    prompt = prompts[0]  # Passe 1
    prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
    prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
    prompt = prompt.replace("{COLLER_LE_PROGRAMME_ICI}", program_text[:3000])
    prompt += "\n\nIMPORTANT : génère SEULEMENT une introduction de 150 mots maximum, c'est un test."
    return _anthropic_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
    ).strip()
