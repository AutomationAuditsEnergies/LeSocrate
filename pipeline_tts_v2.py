"""
Pipeline TTS v2 : PDF → Reformulation Claude → TTS Fish Audio → 7 fichiers cours MP3

Usage :
    python pipeline_tts_v2.py "Module1_formation_VCB (1) (1) (1).pdf" --output-dir output_cours

Étapes :
    1. Extraire le texte du PDF
    2. Reformuler tout le texte avec Claude (prompt-tts-reformulation.md)
    3. Pour chaque slot (7 blocs cours) :
       a. Générer intro TTS
       b. Avancer paragraphe par paragraphe dans le texte reformulé
       c. Générer TTS, mesurer la durée audio réelle
       d. Quand on approche la durée cible → générer conclusion TTS
       e. Assembler avec silences, fade-out, padding
       f. Exporter MP3
"""

import argparse
import io
import os
import re
import sys
import json
import time

import anthropic
import requests
from dotenv import load_dotenv
from pydub import AudioSegment

import tts_pipeline_state as state

load_dotenv("backend/.env")

# ─── Config ──────────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-20250514"
FISH_API_URL = "https://api.fish.audio/v1/tts"
FISH_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
FISH_VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Paramètres TTS validés par tests
TTS_PARAMS = {
    "temperature": 0.9,
    "top_p": 0.7,
    "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True},
    "chunk_length": 300,
    "normalize": False,
    "format": "mp3",
    "mp3_bitrate": 128,
    "latency": "normal",
}

# Paramètres audio
SILENCE_BETWEEN_PARAGRAPHS_MS = 500
SILENCE_AFTER_QUESTION_MS = 400
FADE_OUT_MS = 150
START_SILENCE_MS = 17000
MARGIN_SECONDS = 120  # 2 min de marge avant la durée max

# Playlist des 7 blocs cours avec durées en secondes
COURS_SLOTS = [
    {"filename": "cours_9h00_9h45.mp3", "duration": 2700, "bloc": 1},
    {"filename": "cours_10h05_10h50.mp3", "duration": 2700, "bloc": 2},
    {"filename": "cours_11h05_12h00.mp3", "duration": 3300, "bloc": 3},
    {"filename": "cours_12h20_13h05.mp3", "duration": 2700, "bloc": 4},
    {"filename": "cours_14h45_15h45.mp3", "duration": 3600, "bloc": 5},
    {"filename": "cours_16h00_17h00.mp3", "duration": 3600, "bloc": 6},
    {"filename": "cours_17h25_18h15.mp3", "duration": 3000, "bloc": 7},
]


# ─── Étape 1 : Extraction PDF ────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path):
    """Extrait le texte d'un fichier PDF, page par page."""
    import PyPDF2
    pages = []
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
    return pages


def chunk_pages(pages, pages_per_chunk=4):
    """Découpe les pages en chunks de N pages."""
    chunks = []
    for i in range(0, len(pages), pages_per_chunk):
        chunk_text = "\n\n".join(pages[i:i + pages_per_chunk])
        chunks.append(chunk_text)
    return chunks


# ─── Étape 2 : Reformulation Claude ──────────────────────────────────────────

def load_prompt():
    """Charge le prompt de reformulation depuis le fichier md."""
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt-tts-reformulation.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Extraire le contenu entre les balises ```
    match = re.search(r"## Le Prompt\s*```(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError("Impossible de trouver le prompt dans prompt-tts-reformulation.md")


def reformulate_text(source_text, progress_cb=None):
    """
    Reformule le texte source via Claude Sonnet 4 (streaming).
    Retourne le texte reformulé complet.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt_template = load_prompt()

    # Remplacer le placeholder par le texte source
    prompt = prompt_template.replace("{COLLER_LE_TEXTE_ICI}", source_text[:80000])

    if progress_cb:
        progress_cb("Reformulation du texte avec Claude Sonnet 4...")

    print(f"  Envoi à Claude ({CLAUDE_MODEL}) en streaming... ({len(source_text)} caractères)")

    reformulated = ""
    input_tokens = 0
    output_tokens = 0

    for attempt in range(5):
        try:
            reformulated = ""
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=32000,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    reformulated += text
                    if len(reformulated) % 2000 < len(text):
                        print(f"    ... {len(reformulated)} caractères générés", end="\r")

                response = stream.get_final_message()
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens

            reformulated = reformulated.strip()
            print()
            break
        except Exception as e:
            if attempt < 4:
                wait = 10 * (attempt + 1)
                print(f"\n    ⚠️ Erreur Claude ({e}), retry dans {wait}s...")
                time.sleep(wait)
                reformulated = ""
            else:
                raise

    # Coût Sonnet 4 ($3/MTok in, $15/MTok out)
    cost_input = input_tokens / 1_000_000 * 3
    cost_output = output_tokens / 1_000_000 * 15
    total_cost = cost_input + cost_output

    print(f"  ✅ Reformulation terminée ({len(reformulated)} caractères)")
    print(f"  📊 Tokens: {input_tokens} in / {output_tokens} out")
    print(f"  💰 Coût estimé: ${total_cost:.4f}")

    return reformulated


# ─── Étape 3 : TTS Fish Audio ─────────────────────────────────────────────────

def tts_text(text):
    """Convertit un texte en audio via Fish Audio S2-Pro. Retourne les bytes MP3."""
    payload = {
        "text": text,
        "reference_id": FISH_VOICE_ID,
        **TTS_PARAMS,
    }
    headers = {
        "model": "s2-pro",
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = requests.post(FISH_API_URL, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Erreur Fish Audio ({resp.status_code}): {resp.text[:300]}")
    return resp.content


def audio_from_bytes(mp3_bytes):
    """Convertit des bytes MP3 en AudioSegment."""
    return AudioSegment.from_mp3(io.BytesIO(mp3_bytes))


def split_on_questions(text):
    """Découpe un texte en morceaux : chaque '?' marque une coupure."""
    parts = re.split(r'(\?)', text)
    chunks = []
    current = ""
    for part in parts:
        current += part
        if part == "?":
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def generate_paragraph_audio(paragraph):
    """
    Génère l'audio d'un paragraphe complet, avec :
    - Découpage sur les '?' pour insérer des silences après les questions
    - Fade-out de 150ms sur chaque segment
    """
    silence_question = AudioSegment.silent(duration=SILENCE_AFTER_QUESTION_MS)
    question_chunks = split_on_questions(paragraph)

    para_audio = AudioSegment.empty()

    for j, chunk in enumerate(question_chunks):
        if not chunk.strip():
            continue

        audio_bytes = tts_text(chunk)
        segment = audio_from_bytes(audio_bytes)
        segment = segment.fade_out(FADE_OUT_MS)

        para_audio = para_audio + segment

        if chunk.strip().endswith("?") and j < len(question_chunks) - 1:
            para_audio = para_audio + silence_question

    return para_audio


# ─── Étape 4 : Assemblage d'un slot ──────────────────────────────────────────

def generate_intro(subject_hint):
    """Génère une intro TTS pour un bloc cours."""
    intro_text = (
        f"Alors, dans ce cours on va aborder une notion importante : "
        f"{subject_hint}."
    )
    return intro_text


def generate_conclusion():
    """Génère une conclusion TTS pour un bloc cours."""
    conclusion_text = (
        "Voilà, on a bien avancé sur cette notion. "
        "On a vu les points essentiels, et on aura l'occasion "
        "d'aller plus loin par la suite."
    )
    return conclusion_text


def tts_with_retry(text, max_retries=5):
    """Appel TTS avec retry, backoff et rate-limit handling."""
    for attempt in range(max_retries):
        try:
            result = tts_text(text)
            time.sleep(0.5)  # Rate limit : 0.5s entre chaque requête
            return result
        except Exception as e:
            if "429" in str(e):
                wait = 3 * (attempt + 1)  # 3s, 6s, 9s, 12s, 15s
                print(f"    ⏳ Rate limit, attente {wait}s...")
                time.sleep(wait)
            elif attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    ⚠️ Retry {attempt+1}/{max_retries} dans {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


def generate_all_tts_parallel(paragraphs, job_id, done_set, max_workers=3):
    """
    Génère le TTS des paragraphes manquants, upload chaque segment vers Azure
    immédiatement et enregistre l'état en BDD.

    Les paragraphes déjà dans done_set sont skippés (ils sont déjà en Azure).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    todo = [(i, p) for i, p in enumerate(paragraphs) if i not in done_set]
    failed = []

    if not todo:
        print(f"  ✅ Tous les paragraphes sont déjà en cache Azure, rien à générer")
        return

    def process_paragraph(idx, para):
        """TTS d'un paragraphe → upload Azure → mark done en BDD."""
        try:
            silence_question = AudioSegment.silent(duration=SILENCE_AFTER_QUESTION_MS)
            question_chunks = split_on_questions(para)
            para_audio = AudioSegment.empty()

            for j, chunk in enumerate(question_chunks):
                if not chunk.strip():
                    continue
                audio_bytes = tts_with_retry(chunk)
                segment = audio_from_bytes(audio_bytes)
                segment = segment.fade_out(FADE_OUT_MS)
                para_audio = para_audio + segment

                if chunk.strip().endswith("?") and j < len(question_chunks) - 1:
                    para_audio = para_audio + silence_question

            # Sérialiser en MP3 et upload Azure
            buf = io.BytesIO()
            para_audio.export(buf, format="mp3", bitrate="128k")
            audio_bytes = buf.getvalue()
            azure_path = state.azure_upload_segment(job_id, idx, audio_bytes)
            state.mark_segment_done(job_id, idx, azure_path, len(para_audio))

            return idx, True, None
        except Exception as e:
            state.mark_segment_failed(job_id, idx)
            return idx, False, str(e)

    print(f"  🚀 Génération de {len(todo)} paragraphes manquants ({max_workers} workers, upload Azure live)")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_paragraph, idx, para): idx
            for idx, para in todo
        }

        done_count = 0
        total = len(todo)
        for future in as_completed(futures):
            idx, ok, err = future.result()
            done_count += 1
            if ok:
                if done_count % 10 == 0 or done_count == total:
                    print(f"    ✅ {done_count}/{total} générés et uploadés Azure")
            else:
                failed.append(idx)
                print(f"    ❌ Paragraphe {idx+1} échoué: {err}")

    if failed:
        print(f"  ⚠️ {len(failed)} paragraphes échoués (relance la pipeline pour réessayer)")


def generate_bloc_intro(bloc_num, last_paragraph_text=""):
    """Génère une intro pour un bloc cours (sauf le bloc 1)."""
    if bloc_num == 1:
        return None

    if last_paragraph_text:
        # Extraire les 2 premières phrases du dernier paragraphe pour contexte
        sentences = re.split(r'[.!?]', re.sub(r'\[.*?\]', '', last_paragraph_text))
        context = sentences[0].strip() if sentences else ""
        intro = (
            f"Alors, on reprend là où on s'était arrêté. "
            f"Juste avant, on parlait de {context.lower() if context else 'la notion précédente'}. "
            f"On va continuer sur cette lancée."
        )
    else:
        intro = (
            "Très bien, on reprend. "
            "On va continuer avec la suite du cours."
        )
    return intro


def _load_segment_from_azure(job_id, idx):
    """Télécharge un segment depuis Azure et retourne l'AudioSegment."""
    azure_path = state.get_segment_azure_path(job_id, idx)
    if not azure_path:
        return None
    audio_bytes = state.azure_download_segment(azure_path)
    return audio_from_bytes(audio_bytes)


def assemble_slots(paragraphs, job_id, output_dir):
    """
    Assemble les segments (téléchargés depuis Azure à la demande) en slots
    de la playlist. Mémoire-friendly : un segment à la fois en RAM.
    """
    silence_para = AudioSegment.silent(duration=SILENCE_BETWEEN_PARAGRAPHS_MS)
    start_silence = AudioSegment.silent(duration=START_SILENCE_MS)

    total_stats = []
    seg_cursor = 0
    last_paragraph_text = ""
    n_paragraphs = len(paragraphs)

    os.makedirs(output_dir, exist_ok=True)

    for slot in COURS_SLOTS:
        if seg_cursor >= n_paragraphs:
            print(f"\n  ⏭️ Bloc {slot['bloc']} : plus de contenu, fichier silencieux")
            silence = AudioSegment.silent(duration=slot["duration"] * 1000)
            out = io.BytesIO()
            silence.export(out, format="mp3", bitrate="128k")
            filepath = os.path.join(output_dir, slot["filename"])
            with open(filepath, "wb") as f:
                f.write(out.getvalue())
            # Upload final vers Azure
            try:
                state.azure_upload_final(job_id, slot["filename"], out.getvalue())
            except Exception as e:
                print(f"    ⚠️ Upload Azure final échoué: {e}")
            total_stats.append({
                "bloc": slot["bloc"], "filename": slot["filename"],
                "paragraphs_used": 0, "content_duration_s": 0,
                "total_duration_s": slot["duration"], "skipped": True,
            })
            continue

        target_ms = (slot["duration"] - MARGIN_SECONDS) * 1000
        duration_min = slot["duration"] / 60
        target_min = (slot["duration"] - MARGIN_SECONDS) / 60

        print(f"\n  ── Bloc {slot['bloc']} : {slot['filename']} ({duration_min:.0f}min, cible {target_min:.0f}min) ──")

        full_audio = start_silence
        content_audio_ms = 0
        paragraphs_used = 0

        # Intro de reprise (sauf bloc 1)
        intro_text = generate_bloc_intro(slot["bloc"], last_paragraph_text)
        if intro_text:
            try:
                print(f"    🎤 Intro : \"{intro_text[:60]}...\"")
                intro_bytes = tts_with_retry(intro_text)
                intro_audio = audio_from_bytes(intro_bytes).fade_out(FADE_OUT_MS)
                full_audio = full_audio + intro_audio + silence_para
                content_audio_ms += len(intro_audio)
            except Exception as e:
                print(f"    ⚠️ Erreur intro: {e}")

        while seg_cursor < n_paragraphs:
            seg = _load_segment_from_azure(job_id, seg_cursor)
            if seg is None:
                # Segment manquant en BDD/Azure (failed) → on saute
                print(f"    ⚠️ Segment {seg_cursor} manquant en Azure, ignoré")
                seg_cursor += 1
                continue

            projected = len(full_audio) + len(seg) + SILENCE_BETWEEN_PARAGRAPHS_MS
            if projected > target_ms and paragraphs_used > 0:
                print(f"    ⏱️ Cible atteinte ({content_audio_ms/1000:.0f}s de contenu)")
                break

            if paragraphs_used > 0:
                full_audio = full_audio + silence_para
            full_audio = full_audio + seg
            content_audio_ms += len(seg)

            last_paragraph_text = paragraphs[seg_cursor]
            seg_cursor += 1
            paragraphs_used += 1

        # Conclusion
        try:
            conclusion_text = generate_conclusion()
            conclusion_bytes = tts_with_retry(conclusion_text)
            conclusion_audio = audio_from_bytes(conclusion_bytes).fade_out(FADE_OUT_MS)
            full_audio = full_audio + silence_para + conclusion_audio
            content_audio_ms += len(conclusion_audio)
        except Exception as e:
            print(f"    ⚠️ Erreur conclusion: {e}")

        # Padding
        target_total_ms = slot["duration"] * 1000
        if len(full_audio) < target_total_ms:
            full_audio = full_audio + AudioSegment.silent(duration=target_total_ms - len(full_audio))
        elif len(full_audio) > target_total_ms:
            print(f"    ⚠️ Troncature ({len(full_audio)/1000:.1f}s > {slot['duration']}s)")
            full_audio = full_audio[:target_total_ms]

        # Export local
        out = io.BytesIO()
        full_audio.export(out, format="mp3", bitrate="128k")
        filepath = os.path.join(output_dir, slot["filename"])
        with open(filepath, "wb") as f:
            f.write(out.getvalue())

        # Upload final vers Azure
        try:
            azure_url = state.azure_upload_final(job_id, slot["filename"], out.getvalue())
            print(f"    ☁️ Uploadé Azure : {azure_url}")
        except Exception as e:
            print(f"    ⚠️ Upload Azure final échoué: {e}")

        content_s = content_audio_ms / 1000
        stats = {
            "bloc": slot["bloc"], "filename": slot["filename"],
            "paragraphs_used": paragraphs_used,
            "content_duration_s": content_s,
            "total_duration_s": len(full_audio) / 1000,
            "skipped": False,
        }
        total_stats.append(stats)
        print(f"    ✅ {slot['filename']} : {content_s:.0f}s contenu réel, {paragraphs_used} §")

    return total_stats


# ─── Pipeline principale ─────────────────────────────────────────────────────

def run_pipeline(pdf_paths, output_dir="output_cours", from_text=None, job_id=None):
    """Exécute la pipeline complète : PDFs → 7 fichiers cours MP3.

    Args:
        pdf_paths: chemin unique (str) ou liste de chemins vers les PDFs
                   (ignoré si from_text est fourni)
        output_dir: dossier de sortie
        from_text: chemin vers un fichier .txt déjà TTS-ready (bypass
                   extraction PDF + reformulation Claude)
        job_id: identifiant du job (ex: 'jour1') pour reprise + persistance
                Azure. Si None, dérivé du nom de output_dir.
    """
    if job_id is None:
        job_id = os.path.basename(os.path.normpath(output_dir))
    print("=" * 60)
    if from_text:
        print("  PIPELINE TTS v2 — Texte TTS-ready → 7 fichiers cours MP3")
    else:
        print("  PIPELINE TTS v2 — PDFs → 7 fichiers cours MP3")
    print("=" * 60)

    os.makedirs(output_dir, exist_ok=True)

    cache_path = os.path.join(output_dir, "reformulated_text.txt")

    # ── Mode texte direct (bypass PDF + reformulation) ───────────────────
    if from_text:
        print(f"\n📄 Texte TTS-ready fourni directement : {from_text}")
        with open(from_text, "r", encoding="utf-8") as f:
            reformulated = f.read()
        words = len(reformulated.split())
        print(f"  ✅ {words} mots chargés (reformulation ignorée)")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(reformulated)

    else:
        if isinstance(pdf_paths, str):
            pdf_paths = [pdf_paths]

        # ── Étape 1 : Extraction PDFs ────────────────────────────────────
        all_pages = []
        for pdf_path in pdf_paths:
            print(f"\n📄 Extraction : {pdf_path}")
            pages = extract_text_from_pdf(pdf_path)
            words = sum(len(p.split()) for p in pages)
            print(f"  ✅ {len(pages)} pages, {words} mots")
            all_pages.extend(pages)

        total_words = sum(len(p.split()) for p in all_pages)
        print(f"\n  📊 Total : {len(all_pages)} pages, {total_words} mots")
        pages = all_pages

        # ── Étape 2 : Reformulation par chunks ───────────────────────────
        print(f"\n🔄 Étape 2 : Reformulation avec Claude (par chunks de 4 pages)")

        if os.path.exists(cache_path):
            print(f"  ♻️ Reformulation trouvée en cache ({cache_path})")
            with open(cache_path, "r", encoding="utf-8") as f:
                reformulated = f.read()
        else:
            chunks = chunk_pages(pages, pages_per_chunk=4)
            print(f"  📦 {len(chunks)} chunks à reformuler")

            all_reformulated = []
            total_cost = 0

            for i, chunk in enumerate(chunks):
                print(f"\n  ── Chunk {i+1}/{len(chunks)} ──")
                chunk_result = reformulate_text(chunk, progress_cb=print)
                all_reformulated.append(chunk_result)

            reformulated = "\n\n".join(all_reformulated)

            # Sauvegarder le cache
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(reformulated)
            print(f"\n  💾 Cache sauvegardé dans {cache_path}")

    # Découper en paragraphes
    paragraphs = [p.strip() for p in reformulated.split("\n\n") if p.strip()]
    print(f"  📊 {len(paragraphs)} paragraphes détectés")

    # ── Job & reprise depuis BDD ──────────────────────────────────────────
    print(f"\n🗄️ Job '{job_id}' (BDD locale + Azure container '{state.AZURE_CONTAINER}')")
    source_for_job = from_text or (pdf_paths[0] if pdf_paths else "")
    done_set = state.create_or_resume_job(
        job_id, source_for_job, output_dir, len(paragraphs)
    )

    # ── Étape 3 : TTS des paragraphes manquants → upload Azure live ──────
    print(f"\n🎙️ Étape 3 : Génération TTS + upload Azure")
    try:
        generate_all_tts_parallel(paragraphs, job_id, done_set, max_workers=3)
    except Exception as e:
        state.mark_job_failed(job_id, e)
        raise

    # ── Étape 4 : Assemblage en slots (lecture depuis Azure) ─────────────
    print(f"\n📦 Étape 4 : Assemblage en 7 blocs cours (download depuis Azure)")

    try:
        total_stats = assemble_slots(paragraphs, job_id, output_dir)
    except Exception as e:
        state.mark_job_failed(job_id, e)
        raise

    state.mark_job_completed(job_id)

    # ── Résumé ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RÉSUMÉ")
    print("=" * 60)

    for s in total_stats:
        status = "⏭️ vide" if s.get("skipped") else f"✅ {s['content_duration_s']:.0f}s contenu, {s['paragraphs_used']} §"
        print(f"  Bloc {s['bloc']} ({s['filename']}): {status}")

    print(f"\n  Fichiers générés dans : {output_dir}/")
    print("=" * 60)

    # Sauvegarder les stats
    stats_path = os.path.join(output_dir, "pipeline_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(total_stats, f, indent=2, ensure_ascii=False)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline TTS v2 : PDFs → 7 fichiers cours MP3")
    parser.add_argument("pdfs", nargs="*", help="Chemins vers les fichiers PDF (ignoré si --from-text)")
    parser.add_argument("--output-dir", "-o", default="output_cours", help="Dossier de sortie")
    parser.add_argument(
        "--from-text", "-t",
        metavar="FICHIER_TXT",
        help="Fichier .txt déjà TTS-ready : bypass extraction PDF + reformulation Claude",
    )
    parser.add_argument(
        "--job-id", "-j",
        help="Identifiant du job pour reprise + persistance Azure (défaut: nom du output-dir)",
    )
    args = parser.parse_args()

    if args.from_text:
        if not os.path.exists(args.from_text):
            print(f"❌ Fichier introuvable : {args.from_text}")
            sys.exit(1)
        run_pipeline([], args.output_dir, from_text=args.from_text, job_id=args.job_id)
    else:
        if not args.pdfs:
            parser.error("Fournir au moins un PDF, ou utiliser --from-text <fichier.txt>")
        for pdf in args.pdfs:
            if not os.path.exists(pdf):
                print(f"❌ Fichier introuvable : {pdf}")
                sys.exit(1)
        run_pipeline(args.pdfs, args.output_dir, job_id=args.job_id)
    sys.exit(0)
