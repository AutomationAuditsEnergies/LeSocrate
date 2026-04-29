"""
Service pipeline formation automatisé.

Flux complet :
  1. Recherche RNCP sur France Compétences à partir du nom TP
  2. Téléchargement + extraction texte du REAC PDF
  3. Génération programme global (Claude) → validation humaine
  4. Découpage programme par journée (Claude) → validation humaine
  5. Lancement génération TTS pour chaque journée (pipeline existant)
"""

import io
import os
import re
import math
import json
import time
import threading
from urllib.parse import quote

import requests as _http

from database.db import get_db_connection
from utils.anthropic_client import (
    AnthropicRateLimitError,
    default_model,
    post_message as _anthropic_post,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Modèle utilisé pour la génération du pipeline formation.
# Configure `FORMATION_LLM_MODEL=deepseek-v4-flash` ou `deepseek-v4-pro`
# pour passer par DeepSeek. `FORMATION_CLAUDE_MODEL` reste supporté.
CLAUDE_MODEL = default_model()
HOURS_PER_DAY = 7

# ─── Prompts Claude ───────────────────────────────────────────────────────────

_GLOBAL_PROGRAM_PROMPT = """Tu es un expert en ingénierie pédagogique spécialisé dans les titres professionnels du Ministère du Travail.

Tu vas créer un programme de formation complet et structuré pour le titre professionnel suivant :

TITRE PROFESSIONNEL : {TP_NAME}
DURÉE TOTALE : {TOTAL_HOURS} heures ({NB_DAYS} journées de 7h)

RÉFÉRENTIEL REAC :
{REAC_TEXT}

CONSIGNE :
Crée un programme de formation détaillé et pédagogiquement structuré, orienté cours magistral TTS.
Le programme doit couvrir 100% des compétences du REAC.

STRUCTURE ATTENDUE (suis ce format précisément) :

# PROGRAMME DE FORMATION — {TP_NAME}
Durée totale : {TOTAL_HOURS} heures | {NB_DAYS} journées

## OBJECTIF GLOBAL
[2-3 phrases décrivant ce que le stagiaire saura faire à l'issue de la formation]

## TABLE DES MATIÈRES
[Liste des blocs et modules avec durées en heures]

## BLOC 1 : [Nom du bloc — reprend le premier bloc de compétences du REAC]
Durée : Xh | Compétences REAC couvertes : CP1, CP2...

### MODULE 1.1 : [Nom précis du module] (Xh)
**Compétences visées :**
- [Compétence 1]
- [Compétence 2]

**Contenu théorique :**
1. [Section 1 — titre précis]
   - [Sous-thème A]
   - [Sous-thème B]
2. [Section 2 — titre précis]
   - [Sous-thème A]
   - [Sous-thème B]
[... autant de sections que nécessaire]

**Cas pratiques suggérés :**
- [Cas pratique 1]
- [Cas pratique 2]

[Répéter pour chaque module et chaque bloc]

## MODULES TRANSVERSAUX
[Communication professionnelle, outils numériques, etc.]

## PRÉPARATION À LA CERTIFICATION [hors TTS]
[Méthodologie examen, entraînements, dossier professionnel]

RÈGLES :
- Chaque module doit avoir une durée réaliste (entre 5h et 25h maximum)
- La somme des durées hors [hors TTS] doit être égale à {TOTAL_HOURS}h
- Chaque sous-thème doit être assez précis pour générer 15 minutes de cours oral
- Évite les répétitions entre modules
- Intègre les savoir-faire et savoirs du REAC dans les sous-thèmes"""

_DAILY_SPLIT_PROMPT = """Tu es un expert en ingénierie pédagogique.

Tu vas découper ce programme de formation en fiches journée pour les jours {DAY_START} à {DAY_END} (sur {NB_DAYS} journées au total).

TITRE PROFESSIONNEL : {TP_NAME}
JOURNÉES À GÉNÉRER : jours {DAY_START} à {DAY_END}

PROGRAMME GLOBAL :
{GLOBAL_PROGRAM}

CONSIGNE :
Génère uniquement les journées {DAY_START} à {DAY_END}, en répartissant le programme de façon cohérente.

RÈGLES :
- Chaque journée = exactement 7 heures de contenu
- Chaque journée a EXACTEMENT 6 sous-parties dans "sub_parts"
- Ne coupe pas un module au milieu sauf si sa durée dépasse 7h
- Jour 1 : pas de rappel. Autres jours : bref rappel de la séance précédente.
- "day_recap" : commence par "Lors de la dernière séance, nous avons vu…" (sauf jour 1)
- "day_transition" : commence par "À la prochaine séance, nous aborderons…" (jamais "demain" ni "la semaine prochaine")
- "module_content" : 5-6 phrases détaillées (100-150 mots) : compétences visées, notions clés, exemples concrets, points de vigilance. Ce contenu sera la base directe de la génération TTS.

FORMAT DE SORTIE : JSON valide uniquement, sans texte avant ni après.

{{
  "days": [
    {{
      "day_number": {DAY_START},
      "title": "Titre descriptif de la journée",
      "hours": 7,
      "modules_covered": ["MODULE 1.1 : Nom"],
      "sub_parts": [
        {{
          "name": "Nom précis de la sous-partie",
          "module_content": "2-3 phrases décrivant les compétences et contenus clés de cette sous-partie."
        }}
      ],
      "day_recap": "Rappel de la veille (vide pour le jour 1)",
      "day_transition": "Annonce de la prochaine journée"
    }}
  ]
}}"""


# ─── France Compétences ───────────────────────────────────────────────────────

_FC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def search_rncp(query: str) -> list:
    """
    Recherche des titres RNCP via l'API officielle France Compétences.
    Retourne une liste de dicts : [{rncp_code, title}]
    """
    # API officielle — renvoie du JSON, pas de scraping HTML
    api_url = (
        "https://www.francecompetences.fr/wp-json/fc/v1/certifications"
        f"?search={quote(query)}&type=RNCP&active=true&per_page=8"
    )
    try:
        resp = _http.get(api_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        results = []
        items = data if isinstance(data, list) else data.get("items", data.get("results", []))
        for item in items[:8]:
            # Différents formats possibles selon la version de l'API
            code = (
                item.get("numero_fiche") or
                item.get("rncp_code") or
                item.get("code") or
                str(item.get("id", ""))
            )
            # Supprimer le préfixe "RNCP" si présent
            code = re.sub(r'^RNCP', '', str(code)).strip()
            title = (
                item.get("intitule") or
                item.get("titre") or
                item.get("title") or
                item.get("label") or
                f"RNCP {code}"
            )
            if code:
                results.append({"rncp_code": code, "title": title})

        if not results:
            logger.warning(f"⚠️ API France Compétences : aucun résultat pour '{query}' — fallback scraping HTML")
            return _search_rncp_html_fallback(query)

        return results

    except Exception as e:
        logger.warning(f"⚠️ API France Compétences échouée ({e}) — fallback scraping HTML")
        return _search_rncp_html_fallback(query)


def _search_rncp_html_fallback(query: str) -> list:
    """
    Fallback : scrape la page de résultats HTML de France Compétences.
    Utilisé si l'API JSON échoue ou retourne vide.
    """
    # Essayer plusieurs URL patterns
    urls_to_try = [
        f"https://www.francecompetences.fr/recherche-resultats/?types=certification&search={quote(query)}&pageType=certification&active=1",
        f"https://www.francecompetences.fr/recherche/?search={quote(query)}&type=RNCP",
    ]
    for url in urls_to_try:
        try:
            resp = _http.get(url, headers=_FC_HEADERS, timeout=20)
            resp.raise_for_status()
            codes = re.findall(r'/recherche/rncp/(\d+)/', resp.text)
            codes = list(dict.fromkeys(codes))[:8]
            if not codes:
                continue
            results = []
            for code in codes:
                pattern = rf'href="[^"]*rncp/{code}/[^"]*"[^>]*>([^<]+)</a>'
                match = re.search(pattern, resp.text)
                title = match.group(1).strip() if match else f"RNCP {code}"
                title = title.replace("&amp;", "&").replace("&#039;", "'").replace("&eacute;", "é")
                results.append({"rncp_code": code, "title": title})
            if results:
                return results
        except Exception as e:
            logger.warning(f"⚠️ Fallback HTML échoué pour {url} : {e}")
            continue
    return []


def get_reac_export_url(rncp_code: str) -> str:
    """
    Récupère l'URL d'export REAC PDF depuis la page d'une fiche RNCP.
    """
    page_url = f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/"
    try:
        resp = _http.get(page_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()

        # L'URL d'export a la forme /wp-json/api/v1/activity/export/XXXXX/YYYYY
        match = re.search(r'/wp-json/api/v1/activity/export/(\d+)/(\d+)', resp.text)
        if not match:
            raise ValueError(f"URL export REAC introuvable pour RNCP {rncp_code}")

        return f"https://www.francecompetences.fr/wp-json/api/v1/activity/export/{match.group(1)}/{match.group(2)}"

    except Exception as e:
        logger.error(f"❌ Erreur récupération URL REAC pour RNCP {rncp_code} : {e}")
        raise


def download_reac_text(rncp_code: str) -> str:
    """
    Télécharge le REAC PDF et en extrait le texte brut.
    """
    import PyPDF2

    reac_url = get_reac_export_url(rncp_code)
    logger.info(f"📥 Téléchargement REAC depuis {reac_url}")

    resp = _http.get(reac_url, timeout=60)
    resp.raise_for_status()

    reader = PyPDF2.PdfReader(io.BytesIO(resp.content))
    pages_text = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            pages_text.append(txt)

    full_text = "\n".join(pages_text)
    logger.info(f"✅ REAC extrait : {len(full_text)} caractères ({len(reader.pages)} pages)")
    return full_text


# ─── Référentiel de Certification (RC) ───────────────────────────────────────

def download_rc_text(rncp_code: str) -> str:
    """
    Télécharge le RC (Référentiel de Certification) PDF depuis France Compétences.
    Le RC est le document complémentaire au REAC : critères d'évaluation, modalités d'examen.
    """
    import PyPDF2
    page_url = f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/"
    try:
        resp = _http.get(page_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()

        # Le RC a un pattern différent du REAC dans les URLs
        rc_patterns = [
            r'/wp-json/api/v1/evaluation/export/(\d+)/(\d+)',
            r'/wp-json/api/v1/certification/export/(\d+)/(\d+)',
            r'href="([^"]+/RC[^"]*\.pdf)"',
            r'href="([^"]+referentiel[^"]*certification[^"]*\.pdf)"',
        ]
        rc_url = None
        for pattern in rc_patterns:
            match = re.search(pattern, resp.text, re.IGNORECASE)
            if match:
                if match.lastindex == 2:
                    rc_url = f"https://www.francecompetences.fr/wp-json/api/v1/evaluation/export/{match.group(1)}/{match.group(2)}"
                else:
                    rc_url = match.group(1)
                    if not rc_url.startswith('http'):
                        rc_url = f"https://www.francecompetences.fr{rc_url}"
                break

        if not rc_url:
            logger.warning(f"⚠️ RC introuvable pour RNCP {rncp_code}")
            return ""

        logger.info(f"📥 Téléchargement RC depuis {rc_url}")
        rc_resp = _http.get(rc_url, timeout=60)
        rc_resp.raise_for_status()

        reader = PyPDF2.PdfReader(io.BytesIO(rc_resp.content))
        pages_text = [p.extract_text() for p in reader.pages if p.extract_text()]
        text = "\n".join(pages_text)
        logger.info(f"✅ RC extrait : {len(text)} caractères")
        return text

    except Exception as e:
        logger.warning(f"⚠️ RC non disponible pour RNCP {rncp_code} : {e}")
        return ""


# ─── Données ROME (France Travail) ───────────────────────────────────────────

def _get_france_travail_token() -> str:
    """Obtient un token OAuth2 France Travail (nécessite FRANCE_TRAVAIL_CLIENT_ID + SECRET)."""
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        return ""
    try:
        resp = _http.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
            "?realm=%2Fpartenaire",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "api_rome-metiersv1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", "")
    except Exception as e:
        logger.warning(f"⚠️ Token France Travail impossible : {e}")
        return ""


def _get_rome_codes_from_rncp_page(rncp_code: str) -> list:
    """Extrait les codes ROME associés à une fiche RNCP."""
    try:
        resp = _http.get(
            f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/",
            headers=_FC_HEADERS, timeout=20
        )
        resp.raise_for_status()
        # Codes ROME = lettre + 4 chiffres (ex: D1408, E1206)
        codes = re.findall(r'\b([A-Z]\d{4})\b', resp.text)
        # Filtrer les faux positifs (garder seulement les codes ROME valides A-Z + 4 chiffres)
        valid = [c for c in dict.fromkeys(codes) if c[0].isalpha()][:5]
        logger.info(f"📋 Codes ROME trouvés pour RNCP {rncp_code} : {valid}")
        return valid
    except Exception as e:
        logger.warning(f"⚠️ Codes ROME introuvables : {e}")
        return []


def fetch_rome_data(rncp_code: str) -> str:
    """
    Récupère les fiches ROME associées au titre RNCP.
    Utilise l'API France Travail si les credentials sont disponibles,
    sinon tente un scraping de la page candidat.
    """
    rome_codes = _get_rome_codes_from_rncp_page(rncp_code)
    if not rome_codes:
        return ""

    token = _get_france_travail_token()
    results = []

    for rome_code in rome_codes[:3]:  # Max 3 codes ROME
        text = ""

        # Tentative 1 : API officielle France Travail
        if token:
            try:
                resp = _http.get(
                    f"https://api.francetravail.io/partenaire/rome-metiers/v1/metiers/metier/{rome_code}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=15,
                )
                if resp.ok:
                    data = resp.json()
                    parts = []
                    if data.get("libelle"):
                        parts.append(f"Métier : {data['libelle']}")
                    if data.get("definition"):
                        parts.append(f"Définition : {data['definition']}")
                    for cat in ["savoirs", "savoirsFaire", "savoirsEtre"]:
                        items = data.get(cat, [])
                        if items:
                            parts.append(f"{cat} : " + ", ".join(i.get("libelle", "") for i in items[:15]))
                    text = "\n".join(parts)
                    logger.info(f"✅ ROME {rome_code} récupéré via API")
            except Exception as e:
                logger.warning(f"⚠️ API ROME {rome_code} : {e}")

        # Tentative 2 : scraping page candidat France Travail
        if not text:
            try:
                resp = _http.get(
                    f"https://candidat.francetravail.fr/metierform/accueil?codeRome={rome_code}",
                    headers=_FC_HEADERS, timeout=15,
                )
                if resp.ok and len(resp.text) > 500:
                    # Extraire le texte brut (la page peut être partiellement rendue)
                    clean = re.sub(r'<[^>]+>', ' ', resp.text)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    text = clean[:3000]
                    logger.info(f"✅ ROME {rome_code} scraping page candidat")
            except Exception as e:
                logger.warning(f"⚠️ Scraping ROME {rome_code} : {e}")

        if text:
            results.append(f"=== FICHE ROME {rome_code} ===\n{text}")

    combined = "\n\n".join(results)
    logger.info(f"✅ Données ROME : {len(combined)} caractères pour {len(results)} code(s)")
    return combined


# ─── Appel Claude ─────────────────────────────────────────────────────────────

def _claude_post(messages, max_tokens=16000, model=None):
    """Wrapper local qui injecte le modèle par défaut du service pipeline."""
    return _anthropic_post(messages, max_tokens=max_tokens, model=model or CLAUDE_MODEL)


# ─── Génération programme global ──────────────────────────────────────────────

def _generate_global_program_thread(job_id: int, model: str = None):
    """Thread : génère le programme global et met à jour le job."""
    try:
        job = get_job(job_id)
        if not job:
            return

        update_job(job_id, status="global_generating")
        used_model = model or CLAUDE_MODEL
        logger.info(f"🔄 Job {job_id} : génération programme global (modèle: {used_model})...")

        nb_days = job["nb_days"]

        # ── Couche 1 : prioriser la Knowledge Base enrichie si dispo ──
        # Si l'utilisateur a lancé l'enrichissement (status kb_ready), on
        # injecte la KB dense (~120-150k mots structurés) plutôt que le REAC
        # brut (15k). Réduit le ratio de dilution sur formations longues.
        from services.knowledge_base_service import build_kb_context
        kb_context = build_kb_context(job_id)

        if kb_context:
            sources = (
                f"=== SOURCE PRIMAIRE : Base de connaissances pédagogique enrichie ===\n"
                f"(Extraite du REAC officiel puis expansée : définitions, études de cas, "
                f"pièges, vocabulaire métier, contexte terrain pour chaque compétence)\n\n"
                f"{kb_context}\n\n"
                f"=== SOURCE SECONDAIRE : REAC brut (référence) ===\n"
                f"{job['reac_text'][:8000]}"
            )
            logger.info(f"📚 Job {job_id} : programme global généré depuis KB enrichie ({len(kb_context)} chars)")
        else:
            # Fallback REAC brut (anciens jobs ou KB non construite)
            sources = f"=== REAC (Référentiel Emploi Activités Compétences) ===\n{job['reac_text'][:15000]}"
            if job.get("rc_text"):
                sources += f"\n\n=== RC (Référentiel de Certification) ===\n{job['rc_text'][:8000]}"
            if job.get("rome_text"):
                sources += f"\n\n=== FICHES ROME (France Travail) ===\n{job['rome_text'][:5000]}"
            logger.info(f"📄 Job {job_id} : programme global généré depuis REAC brut (KB non disponible)")

        prompt = (
            _GLOBAL_PROGRAM_PROMPT
            .replace("{TP_NAME}", job["tp_name"])
            .replace("{TOTAL_HOURS}", str(job["total_hours"]))
            .replace("{NB_DAYS}", str(nb_days))
            .replace("{REAC_TEXT}", sources)
        )

        for attempt in range(5):
            try:
                program = _claude_post(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=16000,
                    model=used_model,
                )
                update_job(
                    job_id,
                    status="global_ready",
                    global_program=program,
                    global_program_generated_via="api",
                )
                logger.info(f"✅ Job {job_id} : programme global généré ({len(program)} chars)")
                return
            except AnthropicRateLimitError as e:
                if attempt < 4:
                    logger.warning(f"⏳ Retry {attempt+1}/5 génération global (429, sleep {e.wait_seconds:.0f}s)")
                    time.sleep(e.wait_seconds)
                else:
                    raise
            except Exception as e:
                if attempt < 4:
                    logger.warning(f"⚠️ Retry {attempt+1}/5 génération global : {e}")
                    time.sleep(15)
                else:
                    raise

    except Exception as e:
        logger.error(f"❌ Job {job_id} génération global échouée : {e}")
        update_job(job_id, status="error", error_message=str(e))


def launch_global_program_generation(job_id: int, model: str = None):
    """Lance la génération du programme global dans un thread."""
    thread = threading.Thread(
        target=_generate_global_program_thread,
        args=(job_id, model),
        daemon=True,
    )
    thread.start()
    logger.info(f"🚀 Job {job_id} : thread génération programme global démarré")


# ─── Découpage en journées ────────────────────────────────────────────────────

BATCH_SIZE = 5  # jours par appel Claude


def _clean_json(raw: str) -> str:
    """Nettoie une réponse Claude pour extraire du JSON valide."""
    # Supprimer les blocs markdown ```json ... ```
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
    # Extraire le premier objet JSON { ... }
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        raise ValueError("Pas de JSON valide dans la réponse")
    text = match.group()
    # Tenter de réparer un JSON tronqué en fermant les structures ouvertes
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Compter les accolades/crochets ouverts pour tenter une réparation
        opens = text.count('{') - text.count('}')
        arr_opens = text.count('[') - text.count(']')
        # Fermer proprement en remontant jusqu'au dernier objet complet
        # Trouver la dernière virgule + objet complet avant la troncature
        last_complete = text.rfind('},')
        if last_complete > 0:
            text = text[:last_complete + 1]
            # Refermer les structures
            text += ']' * max(0, arr_opens - 1) + '}' * max(0, opens)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide même après réparation : {e}")


def _split_batch(tp_name: str, nb_days: int, global_program: str,
                 day_start: int, day_end: int, model: str,
                 reac_text: str = "", rc_text: str = "", rome_text: str = "") -> list:
    """Génère un batch de journées (day_start à day_end inclus)."""
    # Bloc sources enrichies pour le module_content
    enrichment = ""
    if reac_text:
        enrichment += f"\n\n=== EXTRAITS REAC (compétences et savoirs associés) ===\n{reac_text[:6000]}"
    if rc_text:
        enrichment += f"\n\n=== EXTRAITS RC (critères d'évaluation) ===\n{rc_text[:3000]}"
    if rome_text:
        enrichment += f"\n\n=== FICHES ROME ===\n{rome_text[:3000]}"

    prompt = (
        _DAILY_SPLIT_PROMPT
        .replace("{TP_NAME}", tp_name)
        .replace("{NB_DAYS}", str(nb_days))
        .replace("{DAY_START}", str(day_start))
        .replace("{DAY_END}", str(day_end))
        .replace("{GLOBAL_PROGRAM}", global_program[:20000] + enrichment)
    )
    for attempt in range(5):
        try:
            raw = _claude_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                model=model,
            )
            data = _clean_json(raw)
            return data.get("days", [])
        except AnthropicRateLimitError as e:
            if attempt < 4:
                logger.warning(
                    f"⏳ Retry {attempt+1}/5 batch jours {day_start}-{day_end} "
                    f"(429, sleep {e.wait_seconds:.0f}s)"
                )
                time.sleep(e.wait_seconds)
            else:
                raise
        except Exception as e:
            if attempt < 4:
                logger.warning(f"⚠️ Retry {attempt+1}/5 batch jours {day_start}-{day_end} : {e}")
                time.sleep(10)
            else:
                raise


def _split_daily_programs_thread(job_id: int, model: str = None):
    """Thread : découpe le programme global en N journées par batches parallèles."""
    try:
        job = get_job(job_id)
        if not job:
            return

        update_job(job_id, status="daily_splitting")
        used_model = model or CLAUDE_MODEL
        nb_days = job["nb_days"]
        logger.info(f"🔄 Job {job_id} : découpage en {nb_days} journées par batches de {BATCH_SIZE} (modèle: {used_model})...")

        # Découper en batches
        batches = []
        for start in range(1, nb_days + 1, BATCH_SIZE):
            end = min(start + BATCH_SIZE - 1, nb_days)
            batches.append((start, end))

        results = [None] * len(batches)
        errors = []

        def run_batch(idx, day_start, day_end):
            try:
                days = _split_batch(
                    tp_name=job["tp_name"],
                    nb_days=nb_days,
                    global_program=job["global_program"],
                    day_start=day_start,
                    day_end=day_end,
                    model=used_model,
                    reac_text=job.get("reac_text") or "",
                    rc_text=job.get("rc_text") or "",
                    rome_text=job.get("rome_text") or "",
                )
                results[idx] = days
                logger.info(f"✅ Batch {day_start}-{day_end} : {len(days)} journées")
            except Exception as e:
                errors.append(f"Batch {day_start}-{day_end} : {e}")
                results[idx] = []

        threads = []
        for i, (start, end) in enumerate(batches):
            t = threading.Thread(target=run_batch, args=(i, start, end), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        if errors:
            raise ValueError("; ".join(errors))

        # Fusionner et trier par day_number
        all_days = []
        for batch_days in results:
            all_days.extend(batch_days or [])
        all_days.sort(key=lambda d: d.get("day_number", 0))

        logger.info(f"✅ Job {job_id} : {len(all_days)} journées générées au total")
        update_job(job_id, status="daily_ready",
                   daily_programs=json.dumps(all_days, ensure_ascii=False),
                   daily_programs_generated_via="api")

    except Exception as e:
        logger.error(f"❌ Job {job_id} découpage journées échoué : {e}")
        update_job(job_id, status="error", error_message=str(e))


def launch_daily_split(job_id: int, model: str = None):
    """Lance le découpage en journées dans un thread."""
    thread = threading.Thread(
        target=_split_daily_programs_thread,
        args=(job_id, model),
        daemon=True,
    )
    thread.start()
    logger.info(f"🚀 Job {job_id} : thread découpage journées démarré")


# ─── Affinage IA (refine) ─────────────────────────────────────────────────────

_REFINE_PROMPT = """Tu es un expert en ingénierie pédagogique spécialisé dans les titres professionnels.

Voici un {CONTENT_TYPE} que tu as généré pour la formation "{TP_NAME}" :

--- CONTENU ACTUEL ---
{CURRENT_CONTENT}
--- FIN DU CONTENU ---

INSTRUCTION DE MODIFICATION :
{INSTRUCTION}

Modifie le contenu en suivant exactement cette instruction.
- Conserve le même format et la même structure
- Ne commente pas les changements, retourne uniquement le contenu modifié
- Si le contenu est du JSON, retourne du JSON valide"""


def refine_content(
    content_type: str,
    current_content: str,
    instruction: str,
    tp_name: str,
    model: str = None,
) -> str:
    """
    Affine un contenu généré (programme global ou programme journée) via une instruction.
    Appel synchrone — l'utilisateur attend la réponse.
    """
    label = "programme de formation global" if content_type == "global" else "programme de journée"
    prompt = (
        _REFINE_PROMPT
        .replace("{CONTENT_TYPE}", label)
        .replace("{TP_NAME}", tp_name)
        .replace("{CURRENT_CONTENT}", current_content[:30000])
        .replace("{INSTRUCTION}", instruction)
    )
    used_model = model or CLAUDE_MODEL
    logger.info(f"🔧 Affinage contenu ({content_type}) avec {used_model} : '{instruction[:80]}'")
    return _claude_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=16000,
        model=used_model,
    )


# ─── Lancement TTS par journée ────────────────────────────────────────────────

def launch_tts_for_all_days(job_id: int, platform_id: int, model: str = None):
    """
    Crée un dossier cours par journée et lance la génération TTS (from scratch).
    Appelle content_generation_service en mode from_scratch.
    """
    import math
    from services.content_generation_service import start_generation_job

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    daily_programs = json.loads(job["daily_programs"] or "[]")
    if not daily_programs:
        raise ValueError("Aucun programme journée disponible")

    conn = get_db_connection()
    cursor = conn.cursor()
    folder_ids = []

    try:
        for day_data in daily_programs:
            day_num = day_data.get("day_number", len(folder_ids) + 1)
            day_title = day_data.get("title", f"Jour {day_num}")
            folder_name = f"Jour {day_num} — {day_title}"

            # Position = dernier + 1 pour cette plateforme
            cursor.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cours_folders WHERE platform_id = ?",
                (platform_id,)
            )
            position = cursor.fetchone()[0]

            cursor.execute(
                "INSERT INTO cours_folders (platform_id, name, position) VALUES (?, ?, ?)",
                (platform_id, folder_name, position)
            )
            folder_id = cursor.lastrowid
            folder_ids.append(folder_id)

            # Programme texte de la journée (pour le job TTS)
            day_program_text = _format_day_program_text(day_data, job["tp_name"])

            # Sous-parties = les 6 sous-parties de la journée
            sub_parts = [sp["name"] for sp in day_data.get("sub_parts", [])]

            # Contenu des modules par sous-partie (pour les passes from-scratch)
            module_contents = {
                sp["name"]: sp.get("module_content", "")
                for sp in day_data.get("sub_parts", [])
            }

        conn.commit()

    finally:
        conn.close()

    # Lancer génération TTS pour chaque journée
    for i, (folder_id, day_data) in enumerate(zip(folder_ids, daily_programs)):
        day_program_text = _format_day_program_text(day_data, job["tp_name"])
        sub_parts = [sp["name"] for sp in day_data.get("sub_parts", [])]
        module_contents = {
            sp["name"]: sp.get("module_content", "")
            for sp in day_data.get("sub_parts", [])
        }

        start_generation_job(
            folder_id=folder_id,
            platform_id=platform_id,
            program_text=day_program_text,
            program_title=job["tp_name"],
            sub_parts_override=sub_parts,
            module_contents=module_contents,
            from_scratch=True,
            model=model,
        )
        logger.info(f"🚀 TTS lancé pour dossier {folder_id} (Jour {i+1})")

    update_job(job_id, status="tts_launched")
    return folder_ids


def _format_day_program_text(day_data: dict, tp_name: str) -> str:
    """Formate le programme d'une journée en texte pour le job TTS."""
    lines = [
        f"TITRE PROFESSIONNEL : {tp_name}",
        f"JOURNÉE {day_data.get('day_number', '?')} : {day_data.get('title', '')}",
        "",
    ]
    if day_data.get("day_recap"):
        lines.append(f"RAPPEL DE LA VEILLE : {day_data['day_recap']}")
        lines.append("")

    for sp in day_data.get("sub_parts", []):
        lines.append(f"MODULE : {sp['name']}")
        lines.append(sp.get("module_content", ""))
        lines.append("")

    if day_data.get("day_transition"):
        lines.append(f"TRANSITION : {day_data['day_transition']}")

    return "\n".join(lines)


# ─── Helpers DB ───────────────────────────────────────────────────────────────

def create_job(platform_id: int, tp_name: str, rncp_code: str,
               total_hours: int, nb_days: int) -> int:
    """Crée un job pipeline formation en DB. Retourne l'id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO formation_pipeline_jobs
            (platform_id, tp_name, rncp_code, total_hours, nb_days, status)
        VALUES (?, ?, ?, ?, ?, 'init')
    """, (platform_id, tp_name, rncp_code, total_hours, nb_days))
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id


def update_job(job_id: int, **kwargs):
    """Met à jour les champs d'un job."""
    if not kwargs:
        return
    allowed = {
        "status", "rncp_code", "reac_text", "rc_text", "rome_text",
        "global_program", "global_program_validated",
        "daily_programs", "daily_programs_validated",
        "error_message",
        # Origine de chaque artefact (audit fix #5) — 'api' / 'claude_code_haiku' / 'claude_code_sonnet'
        "kb_generated_via", "global_program_generated_via", "daily_programs_generated_via",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    # Effacer automatiquement error_message quand on passe à un statut non-erreur
    if "status" in fields and fields["status"] != "error" and "error_message" not in fields:
        fields["error_message"] = None
    if not fields:
        return

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE formation_pipeline_jobs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def get_job(job_id: int) -> dict | None:
    """Retourne le job ou None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.id, j.platform_id, j.tp_name, j.rncp_code, j.total_hours, j.nb_days,
               j.reac_text, j.rc_text, j.rome_text, j.global_program, j.global_program_validated,
               j.daily_programs, j.daily_programs_validated, j.status, j.error_message,
               j.created_at, j.updated_at,
               j.kb_generated_via, j.global_program_generated_via, j.daily_programs_generated_via,
               p.name AS platform_name
        FROM formation_pipeline_jobs j
        LEFT JOIN platform_config p ON p.id = j.platform_id
        WHERE j.id = ?
    """, (job_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "platform_id": row[1], "tp_name": row[2],
        "rncp_code": row[3], "total_hours": row[4], "nb_days": row[5],
        "reac_text": row[6], "rc_text": row[7], "rome_text": row[8],
        "global_program": row[9],
        "global_program_validated": bool(row[10]),
        "daily_programs": row[11], "daily_programs_validated": bool(row[12]),
        "status": row[13], "error_message": row[14],
        "created_at": row[15], "updated_at": row[16],
        # Origine API / Claude Code par étape (audit fix #5)
        "kb_generated_via": row[17],
        "global_program_generated_via": row[18],
        "daily_programs_generated_via": row[19],
        "platform_name": row[20],
    }


def list_jobs(platform_id: int = None) -> list:
    """Liste tous les jobs (toutes plateformes), avec le nom de la plateforme."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.id, j.tp_name, j.rncp_code, j.total_hours, j.nb_days, j.status,
               j.global_program_validated, j.daily_programs_validated,
               j.created_at, j.updated_at, j.platform_id,
               p.name AS platform_name
        FROM formation_pipeline_jobs j
        LEFT JOIN platform_config p ON p.id = j.platform_id
        ORDER BY j.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "tp_name": r[1], "rncp_code": r[2],
            "total_hours": r[3], "nb_days": r[4], "status": r[5],
            "global_program_validated": bool(r[6]),
            "daily_programs_validated": bool(r[7]),
            "created_at": r[8], "updated_at": r[9],
            "platform_id": r[10], "platform_name": r[11],
        }
        for r in rows
    ]
