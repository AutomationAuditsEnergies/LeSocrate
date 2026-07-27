"""
Couche 1 du pipeline formation — Enrichissement REAC → Knowledge Base.

Objectif : transformer un REAC brut (~15k mots, PDF extrait par PyPDF2) en une
base de connaissances pédagogique dense (~120-150k mots exploitables) avant
la génération du programme de formation.

Flux :
  1. Extraction des compétences structurées depuis le REAC brut (DeepSeek)
  2. Enrichissement de chaque compétence (DeepSeek, 1 appel par compétence) :
     définition pédagogique, études de cas, pièges, vocabulaire métier,
     contexte terrain, liens connexes
  3. Stockage checkpointé en DB (table formation_knowledge_base)
  4. Assemblage d'un contexte dense pour injection dans le prompt du
     programme global

Le checkpointing permet de relancer l'enrichissement après incident sans
refaire les compétences déjà traitées (UNIQUE(job_id, competence_index)).
Le flag `dirty` permet la régénération sélective si l'utilisateur édite.
"""

import os
import re
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from repositories.pipeline_repository import (
    clear_knowledge_base,
    knowledge_base_stats_rows,
    list_knowledge_base_rows,
    mark_knowledge_base_entry_error,
    save_enriched_knowledge_base_entry,
    upsert_pending_knowledge_base_entries,
)
from utils.deepseek_client import (
    DeepSeekAPIError,
    DeepSeekRateLimitError,
    default_model,
    post_message as _post_deepseek_message,
)
from utils.logger import get_logger

logger = get_logger(__name__)

DEEPSEEK_MODEL = default_model()

# Concurrence enrichissement : 1 par défaut pour éviter les 429 en cascade.
# Configurable via env pour les quotas DeepSeek plus élevés.
KB_ENRICH_CONCURRENCY = int(os.environ.get("KB_ENRICH_CONCURRENCY", "1"))

# Lock pour les écritures DB concurrentes (évite "database is locked" SQLite)
_DB_WRITE_LOCK = threading.Lock()


# ─── Règles éditoriales partagées avec la génération TTS ──────────────────────
# La Couche 1 (enrichissement KB) doit respecter exactement les mêmes règles
# éthiques, de contenu, et anti-hallucination que les 3 passes TTS. Ces règles
# sont éditables par l'utilisateur via /schedule-config → POST /api/hr/tts-prompt,
# on les charge donc dynamiquement depuis le fichier source (pas de duplication).
# Le fichier de prompts généraux contient les règles de la pipeline formation active.

_TTS_PROMPT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "prompts-generaux-contenu-formation.md"
)

_EDITORIAL_RULES_CACHE = None
_EDITORIAL_RULES_MTIME = 0.0


def _load_editorial_rules() -> str:
    """
    Extrait la section 'CONTENU — RÈGLES ABSOLUES' + 'HALLUCINATION' du
    fichier de prompts généraux de contenu formation (règles #1 à #20).
    Cache invalidé si le fichier est modifié (mtime).
    """
    global _EDITORIAL_RULES_CACHE, _EDITORIAL_RULES_MTIME
    try:
        mtime = os.path.getmtime(_TTS_PROMPT_FILE)
        if _EDITORIAL_RULES_CACHE is not None and mtime == _EDITORIAL_RULES_MTIME:
            return _EDITORIAL_RULES_CACHE
        with open(_TTS_PROMPT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # Extrait de "CONTENU — RÈGLES ABSOLUES" jusqu'à "FORMAT DE SORTIE"
        match = re.search(
            r"(CONTENU\s*[—-]\s*RÈGLES ABSOLUES.*?)═+\s*\n\s*FORMAT DE SORTIE",
            content,
            re.DOTALL,
        )
        if match:
            rules = match.group(1).strip()
        else:
            # Fallback : tout le contenu entre "RÈGLE #1" et la dernière règle
            match = re.search(r"(RÈGLE #1 —.*?NON NÉGOCIABLES\..*?)(?=\n═|$)", content, re.DOTALL)
            rules = match.group(1).strip() if match else ""
        _EDITORIAL_RULES_CACHE = rules
        _EDITORIAL_RULES_MTIME = mtime
        logger.info(f"📖 Règles éditoriales chargées ({len(rules)} chars)")
        return rules
    except Exception as e:
        logger.warning(f"⚠️ Impossible de charger les règles éditoriales : {e}")
        return ""

# ─── Prompts DeepSeek ─────────────────────────────────────────────────────────

_EXTRACT_COMPETENCES_PROMPT = """Tu es un expert en ingénierie pédagogique spécialisé dans l'analyse des référentiels de titres professionnels (REAC, France Compétences).

Voici le texte brut extrait d'un REAC officiel pour le titre professionnel : **{TP_NAME}** (RNCP {RNCP_CODE}).

Ta mission : identifier et extraire **toutes les compétences clés** de ce REAC pour construire une base de connaissances pédagogique.

═══════════════════════════════════════════════════
RÈGLES ÉDITORIALES À RESPECTER (partagées avec génération TTS)
═══════════════════════════════════════════════════
Ces règles s'appliquent à TOUS les champs que tu vas produire (titres de
compétences, raw_source, mots-clés) : aucune mention contraire à ces
règles, même indirecte, même dans un extrait du REAC à reformuler.

{EDITORIAL_RULES}
═══════════════════════════════════════════════════

Pour chaque compétence, identifie :
- `bloc` : le Certificat de Compétences Professionnelles (CCP) ou bloc de compétences auquel elle appartient (ex: "CCP1 — Vendre en magasin")
- `competence_title` : le titre exact de la compétence (ex: "Accueillir le client et identifier ses besoins")
- `competence_key` : un slug court en kebab-case (ex: "accueillir-client-identifier-besoins")
- `raw_source` : l'extrait pertinent du REAC qui définit cette compétence (200-500 mots, incluant savoirs associés, savoir-faire, conditions d'exercice)

Réponds **uniquement avec un JSON valide** au format suivant, sans préambule ni commentaire :

```json
{
  "competences": [
    {
      "bloc": "CCP1 — Vendre en magasin",
      "competence_title": "Accueillir le client et identifier ses besoins",
      "competence_key": "accueillir-client-identifier-besoins",
      "raw_source": "La compétence consiste à... [texte du REAC concernant cette compétence]"
    }
  ]
}
```

Règles strictes :
- Viser 8 à 20 compétences (selon la richesse du REAC)
- Une compétence par entrée, pas de regroupement
- `raw_source` doit être un extrait **fidèle du REAC**, pas une reformulation
- Ne pas inventer de compétences absentes du REAC

=== TEXTE REAC ===
{REAC_TEXT}
"""


_ENRICH_COMPETENCE_PROMPT = """Tu es un formateur expert en ingénierie pédagogique, spécialisé dans la préparation de formations professionnelles certifiantes.

Formation : **{TP_NAME}** (RNCP {RNCP_CODE})
Bloc : **{BLOC}**
Compétence à enrichir : **{COMPETENCE_TITLE}**

Voici l'extrait officiel du REAC concernant cette compétence :

=== EXTRAIT REAC ===
{RAW_SOURCE}
===

Ta mission : produire une base de connaissances pédagogique dense et exploitable pour générer un cours de formation audio sur cette compétence. Pense à un formateur qui doit animer 45 minutes à 2 heures de cours sur ce sujet — donne-lui de quoi ne jamais être en panne de matière.

═══════════════════════════════════════════════════
RÈGLES ÉDITORIALES NON NÉGOCIABLES
═══════════════════════════════════════════════════
Le contenu que tu produis (études de cas, pièges, vocabulaire, contexte
terrain, définition) sera injecté comme source primaire dans la génération
du cours audio final. TOUTES les règles éditoriales qui s'appliquent au
cours audio s'appliquent donc AUSSI à ta sortie JSON, sans exception :

{EDITORIAL_RULES}

Points d'attention spécifiques à l'enrichissement :
- Les **études de cas** sont souvent des cas fictifs — tu dois les annoncer
  comme tels dans la clé `situation` (ex: "Cas fictif pédagogique : une
  entreprise du secteur X...") et JAMAIS inventer un nom d'entreprise ou
  des chiffres précis non vérifiables.
- Le **vocabulaire métier** doit rester factuel et professionnel, sans
  références spirituelles, religieuses, ésotériques, ni promotion
  implicite de secteurs proscrits.
- Les **pièges fréquents** peuvent décrire des comportements problématiques
  (manipulation, vente agressive, etc.) uniquement pour expliquer COMMENT
  LES ÉVITER, jamais comme techniques à maîtriser.
- Le **contexte terrain** reste strictement professionnel : pas de mention
  d'alcool, fêtes (anniversaires, nouvel an…), paris, dénigrement de tiers.
═══════════════════════════════════════════════════

Réponds **uniquement avec un JSON valide** au format suivant, sans préambule :

```json
{
  "definition_pedagogique": "Explication claire et structurée de la compétence en ~250 mots. Va au-delà du REAC : explique POURQUOI cette compétence existe, dans QUELS contextes elle s'applique, ce qu'elle permet d'accomplir concrètement. Un apprenant doit comprendre l'enjeu.",
  "etudes_de_cas": [
    {
      "titre": "Titre court de l'étude de cas",
      "situation": "Décor concret : lieu, acteurs, contexte (80 mots)",
      "enjeu": "Qu'est-ce qui se joue dans cette situation ? (40 mots)",
      "resolution_attendue": "Comment un professionnel compétent s'y prend (120 mots)",
      "variantes": "Variantes courantes du cas (50 mots)"
    }
  ],
  "pieges_frequents": [
    {
      "piege": "Description du piège (30 mots)",
      "pourquoi_frequent": "Pourquoi les débutants y tombent (50 mots)",
      "comment_eviter": "Contre-mesure concrète (50 mots)"
    }
  ],
  "vocabulaire_metier": {
    "terme_1": "Définition pédagogique (30-50 mots, avec synonymes si pertinent)",
    "terme_2": "..."
  },
  "contexte_terrain": "Description immersive du métier sur cette compétence : qui sont les acteurs impliqués, quels outils, quels rythmes, quelles contraintes, quels enjeux économiques/humains. 200 mots, ton journalistique.",
  "liens_connexes": ["autre-competence-key-1", "autre-competence-key-2"]
}
```

Contraintes de densité :
- `etudes_de_cas` : **4 à 6 études** concrètes, ancrées dans la réalité du métier
- `pieges_frequents` : **4 à 6 pièges** réalistes
- `vocabulaire_metier` : **8 à 15 termes** clés
- `contexte_terrain` : 200 mots minimum, immersif
- Total attendu : ~1500-2500 mots de contenu enrichi (hors formatage JSON)

Évite les généralités creuses. Sois concret, spécifique, ancré dans le métier.
"""


# ─── Helper DeepSeek ──────────────────────────────────────────────────────────

def _deepseek_post(messages, max_tokens=8000, model=None):
    """Wrapper local qui injecte le modèle par défaut du service."""
    return _post_deepseek_message(
        messages,
        max_tokens=max_tokens,
        model=model or DEEPSEEK_MODEL,
    )


def _parse_json_response(text: str) -> dict:
    """
    Extrait un JSON depuis une réponse DeepSeek (```json ... ``` ou JSON brut).
    Tolère les réponses tronquées (max_tokens atteint) en réparant le JSON :
    on coupe au dernier champ complet et on ferme les structures ouvertes.
    """
    text = text.strip()
    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        if end == -1:
            # Bloc de code jamais refermé = réponse tronquée dans le markdown
            text = text[start:].strip()
        else:
            text = text[start:end].strip()
    elif text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as first_err:
        logger.warning(f"⚠️ JSON malformé ({first_err}), tentative de réparation (troncature probable)")
        repaired = _repair_truncated_json(text)
        try:
            result = json.loads(repaired)
            logger.info(f"✅ JSON réparé avec succès ({len(text)} → {len(repaired)} chars)")
            return result
        except json.JSONDecodeError as second_err:
            logger.error(f"❌ Réparation JSON échouée : {second_err}")
            raise first_err  # on remonte l'erreur originale


def _repair_truncated_json(text: str) -> str:
    """
    Répare un JSON tronqué en :
    1. Trouvant la dernière position 'sûre' (après une virgule ou un ]/} complet, hors string)
    2. Coupant à cette position
    3. Fermant les structures ({, [) encore ouvertes

    Principe : si DeepSeek a coupé au milieu d'un champ, on garde tous les
    champs précédents complets et on ferme proprement les crochets/accolades.
    """
    stack = []          # pile des caractères fermants attendus (']' ou '}')
    in_string = False
    escape_next = False
    last_safe = 0       # position après le dernier ',', '}', ']' hors string

    for i, c in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if c == '\\':
                escape_next = True
            elif c == '"':
                in_string = False
            continue
        # Hors string
        if c == '"':
            in_string = True
        elif c == '{':
            stack.append('}')
        elif c == '[':
            stack.append(']')
        elif c == '}' or c == ']':
            if stack and stack[-1] == c:
                stack.pop()
                last_safe = i + 1
        elif c == ',':
            last_safe = i + 1

    if last_safe == 0:
        return '{}'

    truncated = text[:last_safe].rstrip()
    if truncated.endswith(','):
        truncated = truncated[:-1].rstrip()

    # Recalcule la pile sur la portion conservée (certaines structures
    # peuvent avoir été fermées proprement avant la troncature)
    stack2 = []
    in_str = False
    esc = False
    for c in truncated:
        if esc:
            esc = False
            continue
        if in_str:
            if c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            stack2.append('}')
        elif c == '[':
            stack2.append(']')
        elif c in ('}', ']') and stack2 and stack2[-1] == c:
            stack2.pop()

    return truncated + ''.join(reversed(stack2))


# ─── DB helpers ───────────────────────────────────────────────────────────────

def clear_kb(job_id: int) -> None:
    """Supprime toutes les entrées KB d'un job (pour relance complète)."""
    clear_knowledge_base(job_id)


def insert_pending_competences(job_id: int, competences: list) -> None:
    """Insère les compétences extraites en status='pending'."""
    upsert_pending_knowledge_base_entries(job_id, competences)


def save_enriched_competence(job_id: int, competence_index: int, enriched: dict, word_count: int) -> None:
    """Enregistre le contenu enrichi d'une compétence. Protégé par lock pour workers parallèles."""
    with _DB_WRITE_LOCK:
        save_enriched_knowledge_base_entry(
            job_id=job_id,
            competence_index=competence_index,
            definition_pedagogique=enriched.get("definition_pedagogique", ""),
            etudes_de_cas_json=json.dumps(enriched.get("etudes_de_cas", []), ensure_ascii=False),
            pieges_frequents_json=json.dumps(enriched.get("pieges_frequents", []), ensure_ascii=False),
            vocabulaire_metier_json=json.dumps(enriched.get("vocabulaire_metier", {}), ensure_ascii=False),
            contexte_terrain=enriched.get("contexte_terrain", ""),
            liens_connexes_json=json.dumps(enriched.get("liens_connexes", []), ensure_ascii=False),
            word_count=word_count,
        )


def mark_competence_error(job_id: int, competence_index: int, error_msg: str) -> None:
    """Marque une compétence en erreur. Protégé par lock pour workers parallèles."""
    with _DB_WRITE_LOCK:
        mark_knowledge_base_entry_error(job_id, competence_index, error_msg)


def list_kb(job_id: int) -> list:
    """Liste toutes les entrées KB d'un job (pour UI + consommation)."""
    rows = list_knowledge_base_rows(job_id)
    return [
        {
            "id": r.get("id"),
            "competence_index": r.get("competence_index"),
            "competence_key": r.get("competence_key"),
            "competence_title": r.get("competence_title"),
            "bloc": r.get("bloc"),
            "definition_pedagogique": r.get("definition_pedagogique"),
            "etudes_de_cas": json.loads(r.get("etudes_de_cas")) if r.get("etudes_de_cas") else [],
            "pieges_frequents": json.loads(r.get("pieges_frequents")) if r.get("pieges_frequents") else [],
            "vocabulaire_metier": json.loads(r.get("vocabulaire_metier")) if r.get("vocabulaire_metier") else {},
            "contexte_terrain": r.get("contexte_terrain"),
            "liens_connexes": json.loads(r.get("liens_connexes")) if r.get("liens_connexes") else [],
            "status": r.get("status"),
            "total_words": r.get("total_words") or 0,
            "error_message": r.get("error_message"),
            "raw_source": r.get("raw_source") or "",
        }
        for r in rows
    ]


def kb_stats(job_id: int) -> dict:
    """Statistiques agrégées : nb total, nb completed, nb error, total mots."""
    rows = knowledge_base_stats_rows(job_id)
    stats = {"total": 0, "pending": 0, "processing": 0, "completed": 0, "error": 0, "total_words": 0}
    for row in rows:
        status = row.get("status")
        count = row.get("count") or 0
        words = row.get("words") or 0
        stats[status] = count
        stats["total"] += count
        stats["total_words"] += words or 0
    return stats


# ─── Extraction compétences ───────────────────────────────────────────────────

def extract_competences(reac_text: str, tp_name: str, rncp_code: str, model: str = None) -> list:
    """Appelle DeepSeek pour extraire les compétences structurées du REAC."""
    prompt = (
        _EXTRACT_COMPETENCES_PROMPT
        .replace("{TP_NAME}", tp_name)
        .replace("{RNCP_CODE}", rncp_code or "")
        .replace("{EDITORIAL_RULES}", _load_editorial_rules())
        .replace("{REAC_TEXT}", reac_text[:80000])
    )
    for attempt in range(5):
        try:
            response = _deepseek_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                model=model,
            )
            data = _parse_json_response(response)
            competences = data.get("competences", [])
            if not competences:
                raise ValueError("Réponse DeepSeek sans compétences")
            logger.info(f"✅ {len(competences)} compétences extraites du REAC")
            return competences
        except DeepSeekRateLimitError as e:
            if attempt < 4:
                logger.warning(f"⏳ Retry {attempt+1}/5 extraction (429, sleep {e.wait_seconds:.0f}s)")
                time.sleep(e.wait_seconds)
            else:
                raise
        except Exception as e:
            if attempt < 4:
                logger.warning(f"⚠️ Retry {attempt+1}/5 extraction compétences : {e}")
                time.sleep(10)
            else:
                raise


# ─── Enrichissement d'une compétence ──────────────────────────────────────────

def enrich_competence(competence: dict, tp_name: str, rncp_code: str, model: str = None) -> dict:
    """Appelle DeepSeek pour enrichir une compétence avec une KB dense."""
    prompt = (
        _ENRICH_COMPETENCE_PROMPT
        .replace("{TP_NAME}", tp_name)
        .replace("{RNCP_CODE}", rncp_code or "")
        .replace("{BLOC}", competence.get("bloc", ""))
        .replace("{COMPETENCE_TITLE}", competence["competence_title"])
        .replace("{EDITORIAL_RULES}", _load_editorial_rules())
        .replace("{RAW_SOURCE}", competence.get("raw_source", ""))
    )
    for attempt in range(5):
        try:
            response = _deepseek_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=12000,  # augmenté de 8000 : JSON enrichi peut dépasser
                model=model,
            )
            return _parse_json_response(response)
        except DeepSeekRateLimitError as e:
            if attempt < 4:
                logger.warning(
                    f"⏳ Retry {attempt+1}/5 enrichissement '{competence['competence_title']}' "
                    f"(429, sleep {e.wait_seconds:.0f}s)"
                )
                time.sleep(e.wait_seconds)
            else:
                raise
        except DeepSeekAPIError as e:
            # Fail-fast sur les erreurs déterministes (400, 401, 403, 404, 422) :
            # retry n'aidera pas (credit balance vide, mauvaise clé, modèle
            # invalide…). Propager le message lisible plutôt que de spammer.
            if e.is_deterministic:
                logger.error(
                    f"⛔ Enrichissement '{competence['competence_title']}' — "
                    f"erreur déterministe {e.status_code} ({e.error_type}), no retry : {e.message}"
                )
                raise
            if attempt < 4:
                logger.warning(f"⚠️ Retry {attempt+1}/5 enrichissement '{competence['competence_title']}' : {e}")
                time.sleep(10)
            else:
                raise
        except Exception as e:
            if attempt < 4:
                logger.warning(f"⚠️ Retry {attempt+1}/5 enrichissement '{competence['competence_title']}' : {e}")
                time.sleep(10)
            else:
                raise


def _count_words_in_enriched(enriched: dict) -> int:
    """Compte les mots produits par l'enrichissement (pour suivi ratio dilution)."""
    parts = [
        enriched.get("definition_pedagogique", ""),
        enriched.get("contexte_terrain", ""),
    ]
    for c in enriched.get("etudes_de_cas", []):
        parts.extend([c.get("titre", ""), c.get("situation", ""), c.get("enjeu", ""),
                      c.get("resolution_attendue", ""), c.get("variantes", "")])
    for p in enriched.get("pieges_frequents", []):
        parts.extend([p.get("piege", ""), p.get("pourquoi_frequent", ""), p.get("comment_eviter", "")])
    for term, defn in enriched.get("vocabulaire_metier", {}).items():
        parts.append(f"{term} {defn}")
    return sum(len(p.split()) for p in parts if p)


# ─── Orchestration ────────────────────────────────────────────────────────────

def _build_kb_thread(job_id: int, model: str = None):
    """
    Thread : construit la KB pour un job. **Résumable** — si des compétences
    sont déjà en DB (completed), on les garde et on n'enrichit que les
    pending/error. Permet de reprendre après crash / redémarrage backend /
    re-clic sur "Relancer" sans tout perdre.
    """
    # Import local pour éviter un import circulaire
    from services.formation_pipeline_service import get_job, update_job

    try:
        job = get_job(job_id)
        if not job:
            logger.error(f"❌ Job {job_id} introuvable")
            return

        reac_text = job.get("reac_text") or ""
        if not reac_text.strip():
            update_job(job_id, status="error", error_message="REAC vide — télécharger d'abord le REAC")
            return

        update_job(job_id, status="kb_building")
        logger.info(f"🔄 Job {job_id} : construction knowledge base (modèle: {model or DEEPSEEK_MODEL})...")

        # ── Étape 1 : déterminer la liste des compétences à enrichir ──
        # Si des entrées existent déjà en DB (reprise après crash), on les
        # réutilise plutôt que de re-extraire depuis le REAC (ce qui
        # donnerait des competence_key différentes et reset tout le boulot).
        existing = list_kb(job_id)
        completed_count = sum(1 for e in existing if e["status"] == "completed")

        if existing and completed_count > 0:
            logger.info(
                f"🔁 Reprise Job {job_id} : {completed_count}/{len(existing)} compétences déjà enrichies, "
                f"on ne retraite que les pending/error"
            )
            # Reconstruit la liste depuis la DB
            competences = [
                {
                    "competence_index": e["competence_index"],
                    "competence_title": e["competence_title"],
                    "competence_key": e["competence_key"],
                    "bloc": e["bloc"],
                    "raw_source": e["raw_source"],
                    "_status_in_db": e["status"],
                }
                for e in existing
            ]
        else:
            # Première exécution : extraction depuis le REAC
            extracted = extract_competences(
                reac_text=reac_text,
                tp_name=job["tp_name"],
                rncp_code=job.get("rncp_code") or "",
                model=model,
            )
            clear_kb(job_id)
            insert_pending_competences(job_id, extracted)
            competences = [
                {**c, "competence_index": idx, "_status_in_db": "pending"}
                for idx, c in enumerate(extracted)
            ]

        # ── Étape 2 : enrichissement parallèle (pool de workers) ──
        # KB_ENRICH_CONCURRENCY workers simultanés pour accélérer × 3.
        # Chaque worker gère sa propre requête DeepSeek + écriture DB (lock).
        total_words_kb = sum(e["total_words"] for e in existing if e["status"] == "completed")
        to_enrich = [c for c in competences if c["_status_in_db"] != "completed"]
        skipped = len(competences) - len(to_enrich)
        errors = 0

        def _enrich_one(c):
            """Enrichit une compétence unique (exécuté dans un worker)."""
            idx = c["competence_index"]
            title = c["competence_title"]
            try:
                logger.info(f"🔄 Job {job_id} : enrichissement '{title}' (#{idx+1})...")
                enriched = enrich_competence(
                    competence=c,
                    tp_name=job["tp_name"],
                    rncp_code=job.get("rncp_code") or "",
                    model=model,
                )
                word_count = _count_words_in_enriched(enriched)
                save_enriched_competence(job_id, idx, enriched, word_count)
                logger.info(f"✅ '{title}' enrichi ({word_count} mots)")
                return ("ok", word_count)
            except Exception as e:
                logger.error(f"❌ Enrichissement '{title}' : {e}")
                mark_competence_error(job_id, idx, str(e))
                return ("error", 0)

        if to_enrich:
            logger.info(
                f"🚀 Job {job_id} : enrichissement en parallèle "
                f"({len(to_enrich)} à traiter, {KB_ENRICH_CONCURRENCY} workers, "
                f"{skipped} réutilisées)"
            )
            with ThreadPoolExecutor(max_workers=KB_ENRICH_CONCURRENCY) as executor:
                futures = {executor.submit(_enrich_one, c): c for c in to_enrich}
                for fut in as_completed(futures):
                    status, words = fut.result()
                    if status == "ok":
                        total_words_kb += words
                    else:
                        errors += 1

        completed_final = len(competences) - errors
        if completed_final == 0:
            raise Exception(f"Toutes les compétences ({errors}) ont échoué à l'enrichissement")

        update_job(job_id, status="kb_ready", kb_generated_via="api")
        logger.info(
            f"✅ Job {job_id} : KB prête — {completed_final}/{len(competences)} compétences "
            f"(dont {skipped} réutilisées de la précédente exécution), "
            f"{total_words_kb} mots au total, "
            f"ratio x{total_words_kb / max(len(reac_text.split()), 1):.1f} vs REAC"
        )

    except Exception as e:
        logger.error(f"❌ Job {job_id} construction KB échouée : {e}")
        # Import local pour éviter un import circulaire
        from services.formation_pipeline_service import update_job as _uj
        _uj(job_id, status="error", error_message=str(e))


def launch_kb_building(job_id: int, model: str = None):
    """Lance la construction de la KB en thread."""
    thread = threading.Thread(target=_build_kb_thread, args=(job_id, model), daemon=True)
    thread.start()
    logger.info(f"🚀 Job {job_id} : construction KB lancée en background")


# ─── Assemblage pour prompt programme global ──────────────────────────────────

def build_kb_context(job_id: int, max_chars: int = 180000) -> str:
    """
    Assemble un contexte dense depuis la KB pour injection dans le prompt du
    programme global. Remplace le `reac_text` brut (15k) par un contenu
    enrichi (~120-150k) structuré.
    """
    entries = list_kb(job_id)
    completed = [e for e in entries if e["status"] == "completed"]
    if not completed:
        return ""

    # Groupement par bloc pour structure pédagogique claire
    blocs = {}
    for e in completed:
        blocs.setdefault(e.get("bloc") or "Compétences transversales", []).append(e)

    parts = ["=== BASE DE CONNAISSANCES ENRICHIE (extraite et expansée depuis le REAC) ===\n"]
    for bloc_name, bloc_entries in blocs.items():
        parts.append(f"\n## {bloc_name}\n")
        for e in bloc_entries:
            parts.append(f"\n### Compétence : {e['competence_title']}\n")
            if e["definition_pedagogique"]:
                parts.append(f"**Définition pédagogique** : {e['definition_pedagogique']}\n")
            if e["contexte_terrain"]:
                parts.append(f"**Contexte terrain** : {e['contexte_terrain']}\n")
            if e["etudes_de_cas"]:
                parts.append("**Études de cas** :")
                for c in e["etudes_de_cas"]:
                    parts.append(f"- *{c.get('titre', '')}* — {c.get('situation', '')} | Enjeu : {c.get('enjeu', '')} | Résolution : {c.get('resolution_attendue', '')}")
            if e["pieges_frequents"]:
                parts.append("**Pièges fréquents** :")
                for p in e["pieges_frequents"]:
                    parts.append(f"- {p.get('piege', '')} (pourquoi : {p.get('pourquoi_frequent', '')}) → {p.get('comment_eviter', '')}")
            if e["vocabulaire_metier"]:
                parts.append("**Vocabulaire métier** :")
                for term, defn in e["vocabulaire_metier"].items():
                    parts.append(f"- **{term}** : {defn}")

    text = "\n".join(parts)
    if len(text) > max_chars:
        logger.warning(f"⚠️ KB contexte tronqué : {len(text)} → {max_chars} chars")
        text = text[:max_chars] + "\n\n[... KB tronquée pour rester dans la fenêtre de contexte ...]"
    return text
