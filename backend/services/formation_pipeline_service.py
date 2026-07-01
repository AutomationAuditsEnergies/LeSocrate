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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests as _http

from database.db import get_db_connection
from repositories.pipeline_repository import (
    create_pipeline_job,
    get_auto_pilot_pipeline_jobs_to_resume,
    get_pipeline_job,
    list_pipeline_jobs,
    update_pipeline_job,
)
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

COURSE_AUDIO_SLOTS = [
    {"index": 0, "label": "Cours 1", "start": "9h00", "end": "9h45", "duration_min": 45, "filename": "cours_9h00_9h45.mp3"},
    {"index": 1, "label": "Cours 2", "start": "10h05", "end": "10h50", "duration_min": 45, "filename": "cours_10h05_10h50.mp3"},
    {"index": 2, "label": "Cours 3", "start": "11h05", "end": "12h00", "duration_min": 55, "filename": "cours_11h05_12h00.mp3"},
    {"index": 3, "label": "Cours 4", "start": "12h20", "end": "13h05", "duration_min": 45, "filename": "cours_12h20_13h05.mp3"},
    {"index": 4, "label": "Cours 5", "start": "14h45", "end": "15h45", "duration_min": 60, "filename": "cours_14h45_15h45.mp3"},
    {"index": 5, "label": "Cours 6", "start": "16h00", "end": "17h00", "duration_min": 60, "filename": "cours_16h00_17h00.mp3"},
    {"index": 6, "label": "Cours 7", "start": "17h25", "end": "18h15", "duration_min": 50, "filename": "cours_17h25_18h15.mp3"},
]


_INTERNAL_SCHEDULE_TIME_RANGE_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?\s*"
    r"(?:[-–—]|à|a)\s*"
    r"(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?\b",
    re.IGNORECASE,
)
_INTERNAL_SCHEDULE_SINGLE_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])\s*h\s*(?:[0-5]\d)?\b|"
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
    re.IGNORECASE,
)


def _strip_internal_schedule_from_label(value: str | None) -> str:
    original = str(value or "").strip()
    if not original:
        return ""
    text = _INTERNAL_SCHEDULE_TIME_RANGE_RE.sub("", original)
    text = _INTERNAL_SCHEDULE_SINGLE_TIME_RE.sub("", text)
    text = re.sub(r"\b(?:45|50|55|60)\s*minutes\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-–—]\s*[-–—]\s*", " — ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s*[-–—]\s*$", "", text).strip()
    text = re.sub(r"^\s*[-–—]\s*", "", text).strip()
    text = re.sub(r"^cours\s+\d+\s*[-–—:]\s*", "", text, flags=re.IGNORECASE).strip()
    return text or original


def _course_audio_slots_prompt() -> str:
    return "\n".join(
        f"- {slot['label']} · données internes: {slot['start']}-{slot['end']}, "
        f"{slot['duration_min']} min, fichier {slot['filename']}. "
        "Le nom pédagogique ne doit jamais reprendre ces données."
        for slot in COURSE_AUDIO_SLOTS
    )


def _normalize_day_audio_slots(day_data: dict) -> dict:
    """Garantit que daily_programs expose 7 cours audio internes."""
    sub_parts = list(day_data.get("sub_parts") or [])
    normalized = []
    for idx, slot in enumerate(COURSE_AUDIO_SLOTS):
        raw = sub_parts[idx] if idx < len(sub_parts) else {}
        src = raw if isinstance(raw, dict) else {}
        name = (src.get("name") or "").strip()
        if not name and isinstance(raw, str):
            name = raw.strip()
        name = _strip_internal_schedule_from_label(name)
        if not name:
            name = f"{slot['label']} — Sujet à préciser"
        elif not name.lower().startswith("cours"):
            name = f"{slot['label']} — {name}"
        module_content = (src.get("module_content") or "").strip()
        if not module_content:
            module_content = (
                "Développer le contenu prévu pour cette partie de la journée "
                "en respectant le budget interne du cours, sans mentionner le planning."
            )
        normalized.append({
            **src,
            "index": idx,
            "audio_slot": slot["label"],
            "start_time": slot["start"],
            "end_time": slot["end"],
            "duration_min": slot["duration_min"],
            "filename": slot["filename"],
            "name": name,
            "module_content": module_content,
        })
    day_data["sub_parts"] = normalized
    day_data["audio_slots"] = COURSE_AUDIO_SLOTS
    day_data["hours"] = HOURS_PER_DAY
    return day_data


def _format_slot_generation_source(slot_data: dict) -> str:
    """Texte source injecté dans le prompt TTS pour un cours interne."""
    brief = slot_data.get("generation_brief") or {}
    lines = [
        f"COURS AUDIO INTERNE : {slot_data.get('audio_slot')}.",
        "Les horaires, durées et fichiers associés à ce cours sont internes et ne doivent jamais être verbalisés.",
        f"OBJECTIF DU COURS : {_strip_internal_schedule_from_label(slot_data.get('name') or '')}",
        "",
        "CONTENU PRIORITAIRE :",
        slot_data.get("module_content", "") or "",
    ]
    if isinstance(brief, dict) and brief:
        lines.extend(["", "BRIEF DE GÉNÉRATION DU COURS :"])
        for key, label in (
            ("must_cover", "À couvrir"),
            ("examples", "Exemples à intégrer"),
            ("finish", "Fin attendue"),
            ("avoid", "À éviter / ne pas répéter"),
            ("handoff", "Transition"),
        ):
            value = brief.get(key)
            if isinstance(value, list):
                value = "; ".join(str(item).strip() for item in value if str(item).strip())
            if value:
                lines.append(f"- {label} : {value}")
    return "\n".join(lines).strip()

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
- Chaque journée a EXACTEMENT 7 cours dans "sub_parts", alignés sur la playlist audio interne ci-dessous.
- Les durées pédagogiques du programme global doivent être redistribuées sur ces cours internes.
- Un module peut occuper plusieurs cours, ou plusieurs petits modules peuvent partager un cours si c'est pédagogiquement cohérent.
- Ne coupe jamais une idée au hasard : chaque cours doit avoir une fin propre, avec chute, synthèse ou transition naturelle.
- Jour 1 : pas de rappel. Autres jours : bref rappel de la séance précédente.
- "day_recap" : commence par "Lors de la dernière séance, nous avons vu…" (sauf jour 1)
- "day_transition" : commence par "À la prochaine séance, nous aborderons…" (jamais "demain" ni "la semaine prochaine")
- "module_content" : 5-8 phrases détaillées : compétences visées, notions clés, exemples concrets, points de vigilance, progression interne du cours. Ce contenu sera la base directe de la génération TTS.
- "generation_brief" : objet opérationnel qui servira au prompt TTS du cours. Il doit dire quoi couvrir, quels exemples intégrer, comment finir, quoi éviter pour ne pas répéter les autres cours.
- Les horaires, durées et fichiers sont strictement internes. Ils peuvent rester dans les champs techniques start_time/end_time/duration_min/filename, mais ne doivent jamais apparaître dans "name", "module_content" ou "generation_brief".
- "name" doit contenir seulement "Cours N — thème pédagogique précis", sans heure, sans durée, sans mot "créneau" et sans planning.

COURS AUDIO INTERNES À RESPECTER STRICTEMENT :
{COURSE_AUDIO_SLOTS}

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
          "index": 0,
          "audio_slot": "Cours 1",
          "start_time": "9h00",
          "end_time": "9h45",
          "duration_min": 45,
          "filename": "cours_9h00_9h45.mp3",
          "name": "Cours 1 — Nom précis du thème",
          "module_content": "Contenu condensé et structuré de ce cours, sans mentionner l'horaire ni la durée.",
          "generation_brief": {{
            "must_cover": ["notion prioritaire 1", "notion prioritaire 2"],
            "examples": ["exemple métier à développer"],
            "finish": "Type de chute ou synthèse attendue à la fin du cours",
            "avoid": ["notion réservée à un autre cours", "redite à éviter"],
            "handoff": "Lien naturel avec le Q&A, la pause ou le cours suivant"
          }}
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


def _cooperative_sleep(seconds: float) -> None:
    try:
        import eventlet
        eventlet.sleep(seconds)
    except Exception:
        time.sleep(seconds)


def _reac_retry_delays(attempts: int) -> list[float]:
    raw = (os.getenv("FORMATION_REAC_RETRY_DELAYS_SEC") or "").strip()
    if raw:
        values = []
        for part in raw.split(","):
            try:
                values.append(max(0.0, float(part.strip())))
            except (TypeError, ValueError):
                continue
        if values:
            return values[: max(0, attempts - 1)]
    return [30.0, 90.0][: max(0, attempts - 1)]


def download_reac_text_with_retry(
    rncp_code: str,
    *,
    attempts: int = 3,
    delays_sec: list[float] | None = None,
    on_attempt=None,
) -> str:
    """Télécharge le REAC avec retries bornés et erreur finale explicite."""
    attempts = max(1, int(attempts or 1))
    delays = list(delays_sec) if delays_sec is not None else _reac_retry_delays(attempts)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if on_attempt:
                on_attempt(attempt=attempt, total=attempts, status="running", wait_seconds=0, error=None)
            text = download_reac_text(rncp_code)
            if not (text or "").strip():
                raise RuntimeError("REAC extrait vide")
            if on_attempt:
                on_attempt(attempt=attempt, total=attempts, status="success", wait_seconds=0, error=None)
            return text
        except Exception as e:
            last_error = e
            is_last = attempt >= attempts
            wait = 0.0 if is_last else (delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1] if delays else 0.0)
            status = "failed" if is_last else "retrying"
            logger.warning(
                "REAC_DOWNLOAD_ATTEMPT rncp=%s attempt=%s/%s status=%s wait=%.1fs error=%s",
                rncp_code,
                attempt,
                attempts,
                status,
                wait,
                str(e)[:300],
            )
            if on_attempt:
                on_attempt(
                    attempt=attempt,
                    total=attempts,
                    status=status,
                    wait_seconds=wait,
                    error=str(e),
                )
            if is_last:
                break
            _cooperative_sleep(wait)

    raise RuntimeError(
        f"REAC indisponible après {attempts} tentatives pour RNCP {rncp_code}. "
        f"Dernière erreur : {str(last_error)[:300]}"
    ) from last_error


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

def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


# Le daily split était historiquement batché par 5 jours. C'est rapide, mais une
# seule réponse JSON longue et mal fermée bloque toute la pipeline. Par défaut on
# privilégie donc la robustesse : 1 jour par réponse, avec concurrence bornée.
BATCH_SIZE = _env_int("FORMATION_DAILY_BATCH_SIZE", 1, min_value=1, max_value=5)
DAILY_SPLIT_WORKERS = _env_int("FORMATION_DAILY_SPLIT_WORKERS", 3, min_value=1, max_value=6)
DAILY_SPLIT_ATTEMPTS = _env_int("FORMATION_DAILY_SPLIT_ATTEMPTS", 4, min_value=1, max_value=8)
DAILY_SPLIT_MAX_TOKENS = _env_int("FORMATION_DAILY_SPLIT_MAX_TOKENS", 12000, min_value=4000, max_value=24000)


def _escape_control_chars_in_strings(text: str) -> str:
    result = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch in "\n\r\t":
            result.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
        else:
            result.append(ch)
    return "".join(result)


def _balanced_json_slice(text: str) -> str:
    """Retourne le premier objet/array JSON complet, en ignorant les accolades en string."""
    text = str(text or "").strip()
    starts = [(idx, ch) for idx, ch in ((text.find("{"), "{"), (text.find("["), "[")) if idx >= 0]
    if not starts:
        raise ValueError("Aucun début JSON détectable")
    start, _ = min(starts, key=lambda item: item[0])

    stack = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    return text[start:i + 1]

    # JSON tronqué : on garde la zone JSON la plus probable pour json_repair.
    end = max(text.rfind("}"), text.rfind("]"))
    if end > start:
        return text[start:end + 1]
    return text[start:]


def _json_candidates(raw: str) -> list[str]:
    raw = str(raw or "").strip()
    candidates = []
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        candidates.append(match.group(1).strip())
    candidates.append(raw)

    expanded = []
    for candidate in candidates:
        if not candidate:
            continue
        expanded.append(candidate)
        try:
            expanded.append(_balanced_json_slice(candidate))
        except ValueError:
            pass

    seen = set()
    unique = []
    for candidate in expanded:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _loads_lenient_json(candidate: str):
    errors = []
    for text in (candidate, _escape_control_chars_in_strings(candidate)):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            errors.append(str(e))

    try:
        from json_repair import repair_json
        repaired = repair_json(candidate)
        return json.loads(repaired)
    except Exception as e:
        errors.append(str(e))

    raise ValueError(errors[-1] if errors else "JSON invalide")


def _clean_json(raw: str):
    """Extrait et répare une réponse LLM JSON avec plusieurs stratégies."""
    errors = []
    for candidate in _json_candidates(raw):
        try:
            return _loads_lenient_json(candidate)
        except Exception as e:
            errors.append(str(e))
    raise ValueError(
        "JSON invalide même après réparation : "
        + (errors[-1] if errors else "aucun JSON détectable")
    )


def _coerce_day_number(value) -> int | None:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _normalize_daily_payload(data, day_start: int, day_end: int, tp_name: str) -> list[dict]:
    expected = list(range(day_start, day_end + 1))
    if isinstance(data, dict):
        raw_days = data.get("days")
        if raw_days is None and "day_number" in data:
            raw_days = [data]
    elif isinstance(data, list):
        raw_days = data
    else:
        raise ValueError("Le JSON daily doit être un objet {days:[...]} ou une liste")

    days = [dict(day) for day in _ensure_list(raw_days) if isinstance(day, dict)]
    if len(days) == len(expected):
        for idx, day in enumerate(days):
            if _coerce_day_number(day.get("day_number")) is None:
                day["day_number"] = expected[idx]

    by_number = {}
    for day in days:
        number = _coerce_day_number(day.get("day_number"))
        if number is not None:
            day["day_number"] = number
            by_number[number] = day

    selected = []
    missing = []
    for number in expected:
        day = by_number.get(number)
        if not day:
            missing.append(number)
            continue
        selected.append(_complete_day_program_shape(day, number, tp_name))

    if missing:
        raise ValueError(f"Journée(s) manquante(s) dans le JSON : {missing}")
    return selected


def _complete_day_program_shape(day: dict, day_number: int, tp_name: str) -> dict:
    day = dict(day or {})
    day["day_number"] = day_number
    day["hours"] = HOURS_PER_DAY
    title = _strip_internal_schedule_from_label(day.get("title") or "")
    day["title"] = title or f"Journée {day_number} — Progression {tp_name}"
    modules = day.get("modules_covered")
    if not isinstance(modules, list):
        day["modules_covered"] = [str(modules).strip()] if modules else []
    if day_number == 1 and not str(day.get("day_recap") or "").strip():
        day["day_recap"] = ""
    elif not str(day.get("day_recap") or "").strip():
        day["day_recap"] = "Lors de la dernière séance, nous avons vu les bases nécessaires pour aborder cette nouvelle étape."
    if not str(day.get("day_transition") or "").strip():
        day["day_transition"] = "À la prochaine séance, nous aborderons la suite logique de cette progression."
    return _normalize_day_audio_slots(day)


def _global_program_slice(global_program: str, day_number: int, nb_days: int, max_chars: int = 1800) -> str:
    text = re.sub(r"\s+", " ", str(global_program or "")).strip()
    if len(text) <= max_chars:
        return text
    nb_days = max(1, int(nb_days or 1))
    chunk = max(max_chars, len(text) // nb_days)
    start = min(max(0, (day_number - 1) * chunk), max(0, len(text) - max_chars))
    return text[start:start + max_chars].strip()


def _fallback_day_program(tp_name: str, nb_days: int, global_program: str, day_number: int, reason: str) -> dict:
    focus = _global_program_slice(global_program, day_number, nb_days)
    focus_short = focus[:900] if focus else (
        "reprendre les compétences du référentiel et les transformer en progression pédagogique opérationnelle"
    )
    themes = [
        ("Cadre et objectifs du thème", "poser le contexte, les objectifs et les notions clés"),
        ("Notions fondamentales", "expliquer les bases indispensables avec des exemples simples"),
        ("Méthode professionnelle", "montrer une méthode d'action applicable en situation métier"),
        ("Cas pratique guidé", "développer un cas concret et faire verbaliser le raisonnement attendu"),
        ("Points de vigilance", "identifier les erreurs fréquentes, limites et bonnes pratiques"),
        ("Mise en situation", "faire le lien avec une situation réaliste de terrain"),
        ("Synthèse et transition", "résumer les acquis et préparer la suite de la progression"),
    ]
    sub_parts = []
    for idx, (title, role) in enumerate(themes):
        slot = COURSE_AUDIO_SLOTS[idx]
        sub_parts.append({
            "index": idx,
            "audio_slot": slot["label"],
            "start_time": slot["start"],
            "end_time": slot["end"],
            "duration_min": slot["duration_min"],
            "filename": slot["filename"],
            "name": f"{slot['label']} — {title}",
            "module_content": (
                f"Cette partie doit {role}. Elle s'appuie sur le programme global de "
                f"la formation : {focus_short}. Le formateur doit rester concret, "
                "progressif et naturel, sans mentionner les horaires ni la mécanique interne."
            ),
            "generation_brief": {
                "must_cover": [title, "application métier", "lien avec le référentiel"],
                "examples": ["exemple professionnel fictif et réaliste"],
                "finish": "Synthèse courte qui ferme le point avant la suite.",
                "avoid": ["horaires", "durée", "nom de template", "répétition de l'introduction générale"],
                "handoff": "Transition naturelle vers le point suivant ou la pause.",
            },
        })
    return _normalize_day_audio_slots({
        "day_number": day_number,
        "title": f"Journée {day_number} — Progression {tp_name}",
        "hours": HOURS_PER_DAY,
        "modules_covered": [],
        "sub_parts": sub_parts,
        "day_recap": "" if day_number == 1 else "Lors de la dernière séance, nous avons vu les bases nécessaires pour aborder cette nouvelle étape.",
        "day_transition": "À la prochaine séance, nous aborderons la suite logique de cette progression.",
        "generation_warning": f"Fallback déterministe utilisé après échec JSON du batch daily : {reason[:300]}",
    })


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
        .replace("{COURSE_AUDIO_SLOTS}", _course_audio_slots_prompt())
        .replace("{GLOBAL_PROGRAM}", global_program[:20000] + enrichment)
    )
    last_error = None
    for attempt in range(DAILY_SPLIT_ATTEMPTS):
        try:
            raw = _claude_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=DAILY_SPLIT_MAX_TOKENS,
                model=model,
            )
            data = _clean_json(raw)
            return _normalize_daily_payload(data, day_start, day_end, tp_name)
        except AnthropicRateLimitError as e:
            if attempt < DAILY_SPLIT_ATTEMPTS - 1:
                logger.warning(
                    f"⏳ Retry {attempt+1}/{DAILY_SPLIT_ATTEMPTS} batch jours {day_start}-{day_end} "
                    f"(429, sleep {e.wait_seconds:.0f}s)"
                )
                time.sleep(e.wait_seconds)
            else:
                raise
        except Exception as e:
            last_error = e
            if attempt < DAILY_SPLIT_ATTEMPTS - 1:
                logger.warning(
                    f"⚠️ Retry {attempt+1}/{DAILY_SPLIT_ATTEMPTS} "
                    f"batch jours {day_start}-{day_end} : {e}"
                )
                time.sleep(10)
    if day_start < day_end:
        logger.warning(
            "⚠️ Batch jours %s-%s invalide après retries, découpage en journées unitaires",
            day_start,
            day_end,
        )
        days = []
        for day_number in range(day_start, day_end + 1):
            days.extend(
                _split_batch(
                    tp_name=tp_name,
                    nb_days=nb_days,
                    global_program=global_program,
                    day_start=day_number,
                    day_end=day_number,
                    model=model,
                    reac_text=reac_text,
                    rc_text=rc_text,
                    rome_text=rome_text,
                )
            )
        return days

    logger.error(
        "❌ Batch journée %s JSON impossible à réparer, fallback déterministe : %s",
        day_start,
        last_error,
    )
    return [_fallback_day_program(tp_name, nb_days, global_program, day_start, str(last_error or ""))]


def run_daily_split(job_id: int, model: str = None) -> dict:
    """Découpe le programme global en N journées et persiste un résultat exploitable."""
    try:
        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} introuvable")

        update_job(job_id, status="daily_splitting", error_message=None)
        used_model = model or CLAUDE_MODEL
        nb_days = job["nb_days"]
        logger.info(
            "🔄 Job %s : découpage en %s journée(s), batch=%s, workers=%s (modèle: %s)...",
            job_id,
            nb_days,
            BATCH_SIZE,
            DAILY_SPLIT_WORKERS,
            used_model,
        )

        # Découper en batches
        batches = []
        for start in range(1, nb_days + 1, BATCH_SIZE):
            end = min(start + BATCH_SIZE - 1, nb_days)
            batches.append((start, end))

        results = [None] * len(batches)
        errors = []

        def run_batch(day_start, day_end):
            return _split_batch(
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

        workers = min(max(1, DAILY_SPLIT_WORKERS), max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(run_batch, start, end): (idx, start, end)
                for idx, (start, end) in enumerate(batches)
            }
            for future in as_completed(future_map):
                idx, start, end = future_map[future]
                try:
                    days = future.result()
                    results[idx] = days
                    logger.info(f"✅ Batch {start}-{end} : {len(days)} journée(s)")
                except Exception as e:
                    errors.append(f"Batch {start}-{end} : {e}")
                    results[idx] = []

        if errors:
            raise ValueError("; ".join(errors))

        # Fusionner et trier par day_number
        all_days = []
        for batch_days in results:
            all_days.extend(batch_days or [])
        all_days.sort(key=lambda d: d.get("day_number", 0))
        all_days = [_complete_day_program_shape(day, i + 1, job["tp_name"]) for i, day in enumerate(all_days)]

        expected_numbers = list(range(1, nb_days + 1))
        actual_numbers = [_coerce_day_number(day.get("day_number")) for day in all_days]
        if actual_numbers != expected_numbers:
            raise ValueError(
                f"Daily split incohérent : attendu jours {expected_numbers}, reçu {actual_numbers}"
            )

        logger.info(f"✅ Job {job_id} : {len(all_days)} journées générées au total")
        generated_via = (
            "api_fallback"
            if any(day.get("generation_warning") for day in all_days)
            else "api"
        )
        update_job(
            job_id,
            status="daily_ready",
            daily_programs=json.dumps(all_days, ensure_ascii=False),
            daily_programs_generated_via=generated_via,
            error_message=None,
        )
        return {"ok": True, "days": len(all_days), "generated_via": generated_via}

    except Exception as e:
        logger.error(f"❌ Job {job_id} découpage journées échoué : {e}")
        update_job(job_id, status="error", error_message=str(e))
        raise


def _split_daily_programs_thread(job_id: int, model: str = None):
    """Thread manuel : découpe le programme global sans propager l'exception au serveur."""
    try:
        run_daily_split(job_id, model=model)
    except Exception:
        pass


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

def expected_course_folder_name(day_data: dict, fallback_day_number: int) -> str:
    """Nom stable du dossier cours attendu pour une journée validée."""
    day_data = day_data or {}
    day_num = day_data.get("day_number") or fallback_day_number
    day_title = day_data.get("title") or f"Jour {day_num}"
    return f"Jour {day_num} — {day_title}"


def _folder_row_to_dict(row, day_data: dict, day_index: int, duplicate_of: int = None) -> dict:
    return {
        "folder_id": row[0],
        "name": row[1],
        "position": row[2],
        "platform_id": row[3],
        "formation_job_id": row[4],
        "content_job_id": row[5],
        "content_status": row[6],
        "total_words": row[7] or 0,
        "segments_completed": row[8] or 0,
        "day_number": (day_data or {}).get("day_number") or day_index + 1,
        "day_title": (day_data or {}).get("title") or row[1],
        "expected_name": expected_course_folder_name(day_data, day_index + 1),
        "duplicate_of": duplicate_of,
    }


def get_expected_course_folders(
    job_id: int,
    *,
    create_missing: bool = False,
    platform_id: int = None,
) -> dict:
    """Résout les folders canoniques d'un job, un seul par journée attendue.

    Si des doublons existent pour un même nom de journée, on garde le folder le
    plus avancé, puis le plus ancien. Les doublons restent en base mais les
    étapes aval peuvent les ignorer proprement.
    """
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    daily_programs = json.loads(job.get("daily_programs") or "[]")
    resolved_platform_id = platform_id or job.get("platform_id")
    folders = []
    duplicates = []
    missing = []
    created = []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for idx, day_data in enumerate(daily_programs):
            folder_name = expected_course_folder_name(day_data, idx + 1)
            cursor.execute(
                """
                SELECT
                    cf.id,
                    cf.name,
                    cf.position,
                    cf.platform_id,
                    cf.formation_job_id,
                    cgj.id,
                    cgj.status,
                    COALESCE(cgj.total_words, 0),
                    COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0)
                FROM cours_folders cf
                LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
                LEFT JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
                WHERE cf.formation_job_id = ? AND cf.name = ?
                GROUP BY cf.id, cf.name, cf.position, cf.platform_id, cf.formation_job_id,
                         cgj.id, cgj.status, cgj.total_words
                ORDER BY
                    CASE
                        WHEN cgj.status = 'completed' THEN 0
                        WHEN COALESCE(cgj.total_words, 0) > 0 THEN 1
                        WHEN cgj.status = 'running' THEN 2
                        WHEN cgj.status = 'idle' THEN 3
                        WHEN cgj.id IS NULL THEN 5
                        ELSE 4
                    END,
                    COALESCE(cgj.total_words, 0) DESC,
                    COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) DESC,
                    cf.position ASC,
                    cf.id ASC
                """,
                (job_id, folder_name),
            )
            matches = cursor.fetchall()

            if not matches and create_missing:
                cursor.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM cours_folders WHERE platform_id = ?",
                    (resolved_platform_id,),
                )
                position = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO cours_folders (platform_id, name, position, formation_job_id) VALUES (?, ?, ?, ?)",
                    (resolved_platform_id, folder_name, position, job_id),
                )
                folder_id = cursor.lastrowid
                created.append({"folder_id": folder_id, "name": folder_name})
                matches = [(
                    folder_id,
                    folder_name,
                    position,
                    resolved_platform_id,
                    job_id,
                    None,
                    None,
                    0,
                    0,
                )]

            if not matches:
                missing.append({
                    "day_number": (day_data or {}).get("day_number") or idx + 1,
                    "name": folder_name,
                })
                continue

            canonical = _folder_row_to_dict(matches[0], day_data, idx)
            folders.append(canonical)
            for duplicate in matches[1:]:
                duplicates.append(
                    _folder_row_to_dict(
                        duplicate,
                        day_data,
                        idx,
                        duplicate_of=canonical["folder_id"],
                    )
                )

        if created:
            conn.commit()
    finally:
        conn.close()

    return {
        "expected_count": len(daily_programs),
        "folders": folders,
        "folder_ids": [f["folder_id"] for f in folders],
        "duplicates": duplicates,
        "missing": missing,
        "created": created,
    }


def is_expected_course_folder(job_id: int, folder_id: int) -> bool:
    """True si le folder est le folder canonique d'une journée attendue."""
    try:
        state = get_expected_course_folders(job_id)
    except Exception:
        logger.warning(
            "PIPELINE_FOLDER_CANONICAL_CHECK_FAILED job=%s folder=%s",
            job_id,
            folder_id,
            exc_info=True,
        )
        return True
    expected_ids = set(state.get("folder_ids") or [])
    return not expected_ids or folder_id in expected_ids


def launch_tts_for_all_days(job_id: int, platform_id: int, model: str = None):
    """
    Crée un dossier cours par journée et lance la génération TTS (from scratch).
    Appelle content_generation_service en mode from_scratch.
    """
    from services.content_generation_service import (
        get_job_from_db,
        run_content_generation,
        start_generation_job,
    )

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    daily_programs = json.loads(job["daily_programs"] or "[]")
    if not daily_programs:
        raise ValueError("Aucun programme journée disponible")

    folder_state = get_expected_course_folders(
        job_id,
        create_missing=True,
        platform_id=platform_id,
    )
    folder_ids = folder_state["folder_ids"]
    folders_by_name = {
        f["expected_name"]: f
        for f in folder_state["folders"]
    }

    # Lancer génération TTS pour chaque journée
    for i, day_data in enumerate(daily_programs):
        day_data = _normalize_day_audio_slots(day_data)
        folder_name = expected_course_folder_name(day_data, i + 1)
        folder_info = folders_by_name.get(folder_name)
        if not folder_info:
            raise RuntimeError(f"Folder attendu introuvable : {folder_name}")
        folder_id = folder_info["folder_id"]
        day_program_text = _format_day_program_text(day_data, job["tp_name"])
        sub_parts = [sp["name"] for sp in day_data.get("sub_parts", [])]
        module_contents = {}
        for sp in day_data.get("sub_parts", []):
            module_contents[sp["name"]] = _format_slot_generation_source(sp)

        existing_job = get_job_from_db(folder_id)
        if existing_job:
            status = existing_job.get("status")
            if status == "completed":
                logger.info(f"⏭ Texte déjà complet pour dossier {folder_id} (Jour {i+1})")
                continue
            if status == "running":
                logger.info(f"⏭ Texte déjà en cours pour dossier {folder_id} (Jour {i+1})")
                continue

            def _resume_existing(fid=folder_id):
                try:
                    run_content_generation(fid, mode="normal", model=model)
                except Exception as e:
                    logger.error(f"❌ Reprise génération dossier {fid} : {e}")

            threading.Thread(target=_resume_existing, daemon=True).start()
            logger.info(f"♻️ Reprise génération pour dossier {folder_id} (Jour {i+1})")
        else:
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


def repair_orphan_content_folders(job_id: int) -> dict:
    """Rattache les dossiers cours créés par l'ancien launch-tts sans job_id.

    Bug historique : la route manuelle de génération texte créait les
    `cours_folders` avec `platform_id` uniquement. Le texte existait, mais le
    dashboard filtrait par `formation_job_id` et voyait donc 0 journée.
    """
    job = get_job(job_id)
    if not job:
        return {"repaired": 0, "missing": 0, "folders": []}

    daily_programs = json.loads(job.get("daily_programs") or "[]")
    if not daily_programs:
        return {"repaired": 0, "missing": 0, "folders": []}

    conn = get_db_connection()
    cursor = conn.cursor()
    repaired = []
    missing = 0
    try:
        for day_data in daily_programs:
            day_num = day_data.get("day_number", len(repaired) + missing + 1)
            day_title = day_data.get("title", f"Jour {day_num}")
            folder_name = f"Jour {day_num} — {day_title}"

            cursor.execute(
                """
                SELECT id FROM cours_folders
                WHERE formation_job_id = ? AND name = ?
                LIMIT 1
                """,
                (job_id, folder_name),
            )
            if cursor.fetchone():
                continue

            cursor.execute(
                """
                SELECT cf.id
                FROM cours_folders cf
                LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
                WHERE cf.platform_id = ?
                  AND cf.name = ?
                  AND cf.formation_job_id IS NULL
                ORDER BY CASE WHEN cgj.id IS NULL THEN 1 ELSE 0 END,
                         cf.created_at DESC,
                         cf.id DESC
                LIMIT 1
                """,
                (job["platform_id"], folder_name),
            )
            row = cursor.fetchone()
            if not row:
                missing += 1
                continue

            folder_id = row[0]
            cursor.execute(
                """
                UPDATE cours_folders
                SET formation_job_id = ?
                WHERE id = ? AND formation_job_id IS NULL
                """,
                (job_id, folder_id),
            )
            if cursor.rowcount:
                repaired.append({"folder_id": folder_id, "name": folder_name})

        conn.commit()
    finally:
        conn.close()

    if repaired:
        logger.warning(
            "PIPELINE_FOLDER_REPAIR job=%s repaired=%s missing=%s folders=%s",
            job_id,
            len(repaired),
            missing,
            repaired,
        )
    return {"repaired": len(repaired), "missing": missing, "folders": repaired}


def _format_day_program_text(day_data: dict, tp_name: str) -> str:
    """Formate le programme d'une journée en texte pour le job TTS."""
    day_data = _normalize_day_audio_slots(day_data)
    lines = [
        f"TITRE PROFESSIONNEL : {tp_name}",
        f"JOURNÉE {day_data.get('day_number', '?')} : {day_data.get('title', '')}",
        "",
    ]
    if day_data.get("day_recap"):
        lines.append(f"RAPPEL DE LA VEILLE : {day_data['day_recap']}")
        lines.append("")

    for sp in day_data.get("sub_parts", []):
        lines.append(_format_slot_generation_source(sp))
        lines.append("")

    if day_data.get("day_transition"):
        lines.append(f"TRANSITION : {day_data['day_transition']}")

    return "\n".join(lines)


# ─── Helpers DB ───────────────────────────────────────────────────────────────

def create_job(platform_id: int, tp_name: str, rncp_code: str,
               total_hours: int, nb_days: int) -> int:
    """Crée un job pipeline formation en DB. Retourne l'id."""
    return create_pipeline_job(
        platform_id=platform_id,
        tp_name=tp_name,
        rncp_code=rncp_code,
        total_hours=total_hours,
        nb_days=nb_days,
    )


def update_job(job_id: int, **kwargs):
    """Met à jour les champs d'un job."""
    update_pipeline_job(job_id, **kwargs)


def get_job(job_id: int) -> dict | None:
    """Retourne le job ou None."""
    return get_pipeline_job(job_id)


def get_auto_pilot_jobs_to_resume() -> list:
    """Retourne les job_ids auto-pilot interrompus : activés, pas terminés, lock absent ou périmé."""
    return get_auto_pilot_pipeline_jobs_to_resume()


def list_jobs(platform_id: int = None) -> list:
    """Liste tous les jobs (toutes plateformes), avec le nom de la plateforme."""
    return list_pipeline_jobs(platform_id)
