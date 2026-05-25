"""
Service des missions Claude Code local — Phase 3.

Spec : memoire/03-decisions/pipeline-dual-api-et-claude-code.md

Le backend écrit des fichiers dans review_queue/<job_id>/<step_key>/, l'utilisateur
lance `claude --model <haiku|sonnet>` dans son terminal, Claude Code exécute la
tâche décrite dans task.md, écrit le résultat dans output.md, puis l'utilisateur
clique "Importer" dans l'UI — le backend parse output.md et met à jour la DB.

Gating : toutes les fonctions retournent une erreur si LOCAL_DEV != 'true' dans
l'env. Le binaire `claude` n'est PAS requis côté serveur (le workflow est
export/import manuel, l'utilisateur peut lancer Claude Code depuis n'importe
quelle machine avec accès aux fichiers exportés).
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta

from database.db import get_db_connection
from utils.logger import get_logger


class _RateLimitError(RuntimeError):
    """Levée quand un subprocess Claude Code a échoué à cause d'un 429
    Anthropic. Permet à _execute_chunked de retry avec backoff dédié."""
    pass

logger = get_logger(__name__)


# ─── Gating LOCAL_DEV ─────────────────────────────────────────────────────────

def local_dev_enabled() -> bool:
    return os.getenv("LOCAL_DEV", "").lower() == "true"


# ─── Chemins et modèles ───────────────────────────────────────────────────────

_REVIEW_QUEUE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "review_queue")
)
_DONE_ROOT = os.path.join(_REVIEW_QUEUE_ROOT, "_done")

ALLOWED_MODELS = {"haiku", "sonnet"}

STEP_LABELS = {
    "kb": "Enrichissement Knowledge Base",
    "global": "Programme global",
    "daily": "Programmes journée",
    "content": "Génération des cours (texte)",
    "humanization_review": "Révision humanisation et rythme",
    "review": "Révision conformité (étape 6bis)",
    "post_review_docs": "Documents post-révision",
}

# Étapes dont l'output total dépasse la limite de 1 appel Claude (64k tokens
# output Sonnet) : on découpe en N missions séquentielles, 1 subprocess `claude`
# par chunk. content = 1 segment calibré sur les cours internes, 21 par journée.
# humanization_review/review = 1 journée × groupe de règles en input, patches
# courts en output.
_CHUNKED_STEPS = {"content", "humanization_review", "review"}

# État partagé des exécutions subprocess en cours / terminées (par process backend).
# Clé : (job_id, step_key) → {status, model, error, result}
# status : 'running' | 'done' | 'error'
_EXECUTION_STATE = {}


def _course_audio_slots_prompt() -> str:
    from services.formation_pipeline_service import COURSE_AUDIO_SLOTS
    return "\n".join(
        f"- {slot['label']} · données internes: {slot['start']}-{slot['end']}, "
        f"{slot['duration_min']} min, fichier {slot['filename']}. "
        "Le nom pédagogique ne doit jamais reprendre ces données."
        for slot in COURSE_AUDIO_SLOTS
    )


def _normalize_day_audio_slots(day_data: dict) -> dict:
    from services.formation_pipeline_service import _normalize_day_audio_slots as _normalize
    return _normalize(day_data)


def mission_dir(job_id: int, step_key: str) -> str:
    return os.path.join(_REVIEW_QUEUE_ROOT, f"job_{job_id}", f"step_{step_key}")


# ─── Helpers DB ───────────────────────────────────────────────────────────────

def _get_job_row(job_id: int) -> dict:
    conn = get_db_connection()
    conn.row_factory = None
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(formation_pipeline_jobs)")
    cols = [c[1] for c in cursor.fetchall()]
    cursor.execute("SELECT * FROM formation_pipeline_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(zip(cols, row))


def _load_kb_entries(job_id: int) -> list:
    """Charge les entrées KB completed pour fournir comme input à l'étape
    programme global / daily."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT competence_title, bloc, definition_pedagogique,
               contexte_terrain, etudes_de_cas, pieges_frequents,
               vocabulaire_metier, liens_connexes
        FROM formation_knowledge_base
        WHERE job_id = ? AND status = 'completed'
        ORDER BY competence_index ASC
        """,
        (job_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "competence_title": r[0],
            "bloc": r[1],
            "definition_pedagogique": r[2] or "",
            "contexte_terrain": r[3] or "",
            "etudes_de_cas": json.loads(r[4] or "[]"),
            "pieges_frequents": json.loads(r[5] or "[]"),
            "vocabulaire_metier": json.loads(r[6] or "{}"),
            "liens_connexes": json.loads(r[7] or "[]"),
        })
    return out


def _load_rules_text() -> str:
    """Règles #1-#28 pour les étapes `content` et `review`."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "prompts-generaux-contenu-formation.md"
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        m = re.search(
            r"CONTENU — RÈGLES ABSOLUES\s*\n═+\n(.*?)décroche, les apprentissages ne passent pas\.",
            content,
            re.DOTALL,
        )
        return m.group(0) if m else content[:20000]
    except Exception:
        return "(règles indisponibles)"


def _load_review_rules_text() -> str:
    """Règles de review alignées sur la pipeline API.

    Contrairement à `_load_rules_text`, ce bloc inclut aussi les règles
    d'humanisation #101-#114 et sert au calcul des signatures API.
    """
    try:
        from services.content_generation_service import _load_review_rules
        return _load_review_rules()
    except Exception as exc:
        logger.warning(f"⚠️ Règles review API indisponibles, fallback prompt local : {exc}")
        return _load_rules_text()


# ─── Export de mission ────────────────────────────────────────────────────────

def export_mission(job_id: int, step_key: str, model: str) -> dict:
    """
    Écrit les fichiers task.md, input.md (+ rules.md pour content/review) dans
    review_queue/job_<id>/step_<key>/. Retourne les infos à afficher côté UI
    (chemin, commande à lancer, etc.).
    """
    if not local_dev_enabled():
        raise PermissionError("LOCAL_DEV non activé côté backend")
    if step_key not in STEP_LABELS:
        raise ValueError(f"step_key invalide : {step_key}")
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model invalide : {model} (attendus : {ALLOWED_MODELS})")
    job = _get_job_row(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    target = mission_dir(job_id, step_key)
    os.makedirs(target, exist_ok=True)

    # Génération du task.md et input.md selon l'étape
    builders = {
        "kb": _build_kb_mission,
        "global": _build_global_mission,
        "daily": _build_daily_mission,
        "content": _build_content_mission,
        "humanization_review": _build_humanization_review_mission,
        "review": _build_review_mission,
    }
    builders[step_key](target, job, model)

    # meta.json pour traçabilité
    meta = {
        "job_id": job_id,
        "step_key": step_key,
        "step_label": STEP_LABELS[step_key],
        "model": model,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "tp_name": job.get("tp_name"),
        "rncp_code": job.get("rncp_code"),
    }
    with open(os.path.join(target, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"📤 Mission exportée : job={job_id} step={step_key} model={model} → {target}")

    return {
        "path": os.path.relpath(target, os.path.dirname(_REVIEW_QUEUE_ROOT)),
        "step_label": STEP_LABELS[step_key],
        "model": model,
        "command": f"claude --model {model}",
        "exported_at": meta["exported_at"],
    }


def _write(target: str, filename: str, content: str) -> None:
    with open(os.path.join(target, filename), "w", encoding="utf-8") as f:
        f.write(content)


# ─── Builders par étape ──────────────────────────────────────────────────────

def _build_kb_mission(target, job, model):
    """Mission KB : extraction + enrichissement de toutes les compétences en
    1 seul JSON. Volume cible borné pour rester sous la limite Sonnet 64K
    output et garantir un JSON parseable (pas de troncature).

    Cible : 1500-2500 mots par compétence × ~10 compétences ≈ 25K mots ≈ 38K
    tokens output. Largement sous la limite, et bien plus stable que les
    "120-150k mots" historiques qui faisaient tronquer le JSON.
    """
    _write(
        target,
        "task.md",
        f"""# Mission : Enrichir la Knowledge Base

**TP** : {job['tp_name']} · **RNCP** : {job.get('rncp_code', '?')} · **Modèle demandé** : {model}

Tu lis `input.md` qui contient le REAC brut (Référentiel Emploi Activités Compétences).
Extrait toutes les compétences (une par section, ~10 attendues), puis pour chaque
compétence produit un enrichissement structuré en JSON avec les clés :

- `competence_title` (string)
- `bloc` (string) — ex: "CCP1 — ...", "CCP2 — ...", "Compétences transversales"
- `definition_pedagogique` (string, **150-250 mots**)
- `contexte_terrain` (string, **150-250 mots**, situations réelles du métier)
- `etudes_de_cas` (list) : **3 cas** fictifs avec `{{titre, situation, enjeu, resolution_attendue, variantes}}` — chaque champ ~30-80 mots
- `pieges_frequents` (list) : **3 pièges** avec `{{piege, pourquoi_frequent, comment_eviter}}` — chaque champ ~20-50 mots
- `vocabulaire_metier` (dict) : **8-12 termes** métier → définition courte (~15 mots)
- `liens_connexes` (list) : 2-3 titres d'autres compétences liées

═══════════════════════════════════════════════════════════════════
🎯 VOLUME PAR COMPÉTENCE : **1500-2500 mots** (non négociable)
═══════════════════════════════════════════════════════════════════

Volume total attendu : ~25 000 mots de contenu enrichi (hors balises JSON).
**NE PAS DÉPASSER 2500 mots par compétence** — sinon le JSON sera tronqué et
inutilisable. Sois dense et précis, pas verbeux.

═══ FORMAT DE SORTIE ═══
Écris dans `output.md` UNIQUEMENT un **JSON array valide**, sans aucune autre
sortie. Pas d'enrobage ` ```json ... ``` `, pas de commentaires markdown, pas
d'introduction. Juste `[{{...}}, {{...}}, ...]`.

**Contraintes éthiques** : aucune invention factuelle (pas de citations, pas de
chiffres fabriqués, pas d'études inventées). Contenu 100% professionnel. Pas de
contenu lié à l'alcool, la musique, les jeux de hasard, les crédits à intérêts.
""",
    )
    _write(target, "input.md", job.get("reac_text") or "(REAC non disponible)")


def _build_global_mission(target, job, model):
    kb_entries = _load_kb_entries(job["id"])
    kb_summary = "\n\n".join(
        f"## {e['competence_title']} ({e['bloc']})\n\n"
        f"**Définition** : {e['definition_pedagogique'][:500]}\n\n"
        f"**Contexte** : {e['contexte_terrain'][:300]}"
        for e in kb_entries
    )
    _write(
        target,
        "task.md",
        f"""# Mission : Générer le programme global de formation

**TP** : {job['tp_name']} · **Modèle demandé** : {model} · **Durée totale** : {job['total_hours']}h sur {job['nb_days']} journée(s).

Tu lis `input.md` qui contient la Knowledge Base enrichie (toutes les compétences
avec définition, contexte, etc.).

Produis un **programme global structuré en Markdown** couvrant toute la formation :
- Hiérarchie : Blocs → Modules → Sections → Sous-parties.
- Respecter la répartition pédagogique d'une journée de 7h sans faire apparaître
  les horaires internes dans les titres ou le texte apprenant.
- Chaque sous-partie doit avoir un titre clair et une brève description (2-3 lignes).
- Équilibrer le volume entre compétences selon leur importance dans le REAC.

Écris le résultat dans `output.md` en **Markdown brut** (pas de JSON, pas d'enrobage).
Objectif : ~16 000 tokens de markdown structuré.
""",
    )
    _write(target, "input.md", kb_summary or "(KB non disponible — génère d'abord l'étape 3)")


def _build_daily_mission(target, job, model):
    slots = _course_audio_slots_prompt()
    _write(
        target,
        "task.md",
        f"""# Mission : Découper le programme global en {job['nb_days']} journée(s)

**TP** : {job['tp_name']} · **Modèle demandé** : {model}

Tu lis `input.md` qui contient le programme global (Markdown).

Découpe en **{job['nb_days']} journées** de 7h chacune. Chaque journée a exactement
7 cours alignés sur la playlist audio interne.

Cours audio internes à respecter strictement pour chaque journée :
{slots}

Les modules du programme global doivent être redistribués sur ces cours :
un module peut occuper plusieurs cours, et plusieurs petits modules peuvent
partager un cours si c'est cohérent. Chaque cours doit avoir une fin propre
avec chute, synthèse ou transition naturelle.

Les horaires, durées et fichiers sont strictement internes. Ils peuvent rester
dans start_time/end_time/duration_min/filename, mais ne doivent jamais apparaître
dans "name", "module_content" ou "generation_brief". Le champ "name" doit être
"Cours N — thème pédagogique précis", sans heure, sans durée, sans mot
"créneau" et sans planning.

Produis un **JSON array** avec une entrée par journée :

```json
[
  {{
    "day_number": 1,
    "title": "Journée 1 — titre synthétique",
    "sub_parts": [
      {{
        "index": 0,
        "audio_slot": "Cours 1",
        "start_time": "9h00",
        "end_time": "9h45",
        "duration_min": 45,
        "filename": "cours_9h00_9h45.mp3",
        "name": "Cours 1 — titre pédagogique précis",
        "module_content": "~contenu condensé tiré du programme global, sans mentionner l'horaire ni la durée",
        "generation_brief": {{
          "must_cover": ["notion prioritaire"],
          "examples": ["exemple métier à développer"],
          "finish": "chute, synthèse ou transition attendue",
          "avoid": ["redite ou sujet réservé à un autre cours"],
          "handoff": "lien naturel avec le Q&A, la pause ou le cours suivant"
        }}
      }},
      ... 7 cours au total
    ]
  }},
  ...
]
```

Écris le JSON brut (sans enrobage markdown) dans `output.md`.
""",
    )
    _write(target, "input.md", job.get("global_program") or "(programme global absent)")


def _build_content_mission(target, job, model):
    budget = _content_segment_word_budget()
    target_words = budget["target_words"]
    _write(
        target,
        "task.md",
        f"""# Mission : Générer le texte des cours (toutes les journées)

**TP** : {job['tp_name']} · **Modèle demandé** : {model}

Tu lis `input.md` qui contient les {job['nb_days']} programmes journée (JSON).

Pour chaque journée × chaque sous-partie × chaque passe (3 passes par sous-partie :
Fondation / Pratique / Maîtrise), génère environ {target_words} mots de texte oral TTS-ready.
Les sous-parties sont les 7 cours internes de la journée ; utilise leurs
métadonnées techniques pour calibrer le volume, sans les verbaliser côté apprenant.

**Applique strictement les règles #1 à #28** contenues dans `rules.md` (saturation
sandwich, pas de mensonge, pas d'énumérations mécaniques, registre oral, etc.).

Sortie attendue dans `output.md` : un **JSON** de la forme :

```json
{{
  "days": [
    {{
      "day_number": 1,
      "segments": [
        {{ "sub_part_index": 0, "passe": 1, "text": "... ~{target_words} mots ..." }},
        {{ "sub_part_index": 0, "passe": 2, "text": "... ~{target_words} mots ..." }},
        {{ "sub_part_index": 0, "passe": 3, "text": "... ~{target_words} mots ..." }},
        ... 21 segments par journée
      ]
    }},
    ...
  ]
}}
```

Volume total calibré sur les cours internes uniquement. Les Q&A et pauses ne
comptent pas dans ce texte. Reste dense, mais ne gonfle pas artificiellement.
""",
    )
    _write(target, "input.md", job.get("daily_programs") or "(daily_programs absents)")
    _write(target, "rules.md", _load_rules_text())


def _build_review_mission(target, job, model):
    """Dump les segments completed non-reviewed du job pipeline."""
    from services.content_generation_service import (
        _current_compliance_review_signature,
        _ensure_review_state_columns,
    )
    _ensure_review_state_columns()
    review_signature = _current_compliance_review_signature()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.sub_part_index, s.passe, s.text_content, cf.name, cf.position
        FROM content_generation_segments s
        JOIN content_generation_jobs cj ON cj.id = s.job_id
        JOIN cours_folders cf ON cf.id = cj.folder_id
        WHERE cf.formation_job_id = ?
        AND s.status = 'completed'
        AND (
            COALESCE(s.reviewed, 0) = 0
            OR s.review_signature IS NULL
            OR s.review_signature != ?
        )
        ORDER BY cf.position ASC, s.sub_part_index ASC, s.passe ASC
        """,
        (job["id"], review_signature),
    )
    rows = cursor.fetchall()
    conn.close()
    segs = [
        {
            "segment_id": r[0],
            "sub_idx": r[1],
            "passe": r[2],
            "folder_name": r[4],
            "folder_position": r[5],
            "text": r[3],
        }
        for r in rows
    ]

    _write(
        target,
        "task.md",
        f"""# Mission : Réviser la conformité des segments cours

**TP** : {job['tp_name']} · **Modèle demandé** : {model}

Tu lis `input.md` qui contient les segments à auditer (JSON array). Pour chacun,
vérifie la conformité aux règles #1-#27 de `rules.md`.

Tu **ne réécris pas** les textes. Tu proposes des **patches minimaux** au format :

```json
{{
  "reviews": [
    {{
      "segment_id": 42,
      "patches": [
        {{
          "original": "phrase EXACTE à remplacer (copie verbatim, 3-40 mots)",
          "replacement": "phrase corrigée",
          "rule_violated": "#27",
          "reason": "registre trop écrit"
        }}
      ]
    }}
  ]
}}
```

- Max 10 patches par segment (éthiques #1-#17 prioritaires, puis stylistiques #21-#27).
- `original` doit être trouvable verbatim dans le texte du segment.
- Si un segment est conforme, renvoie `"patches": []` pour ce segment.

Écris dans `output.md` le JSON brut (sans enrobage).
""",
    )
    _write(target, "input.md", json.dumps(segs, ensure_ascii=False, indent=2))
    _write(target, "rules.md", _load_review_rules_text())


def _build_humanization_review_mission(target, job, model):
    """Dump les segments completed à humaniser pour export/import manuel."""
    from services.content_generation_service import (
        _current_humanization_review_signature,
        _ensure_review_state_columns,
    )
    _ensure_review_state_columns()
    review_signature = _current_humanization_review_signature()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.sub_part_index, s.passe, s.text_content, cf.name, cf.position
        FROM content_generation_segments s
        JOIN content_generation_jobs cj ON cj.id = s.job_id
        JOIN cours_folders cf ON cf.id = cj.folder_id
        WHERE cf.formation_job_id = ?
        AND s.status = 'completed'
        AND (
            COALESCE(s.humanized, 0) = 0
            OR s.humanization_signature IS NULL
            OR s.humanization_signature != ?
        )
        ORDER BY cf.position ASC, s.sub_part_index ASC, s.passe ASC
        """,
        (job["id"], review_signature),
    )
    rows = cursor.fetchall()
    conn.close()
    segs = [
        {
            "segment_id": r[0],
            "sub_idx": r[1],
            "passe": r[2],
            "folder_name": r[4],
            "folder_position": r[5],
            "text": r[3],
        }
        for r in rows
    ]

    _write(
        target,
        "task.md",
        f"""# Mission : Révision humanisation et rythme pédagogique

**TP** : {job['tp_name']} · **Modèle demandé** : {model}

Tu lis `input.md` qui contient les segments à améliorer (JSON array). Pour chacun,
vérifie uniquement les règles #101 à #119 dans `rules.md`.

Une intro trop brusque, une ouverture annuelle absente, un début de journée
mécanique, un bloc trop dense, une transition mécanique, une fin sèche,
l'absence de respiration pédagogique, une référence datée entre cours
("hier", "demain"), une confusion entre cours précédent/Q&R/pause/nouveau
cours, ou une double introduction comptent comme des non-conformités.
Tu proposes des corrections concrètes, mais **pas de réécriture complète**.

Contexte positionnel :
- `folder_position = 0`, `sub_idx = 0`, `passe = 1` = ouverture absolue de la formation : règle #112.
- `sub_idx = 0`, `passe = 1` = début de journée : règle #113 (et #114 : pas de "hier" dans l'intro de reprise).
- Interdire les démarrages du type "Bon, on va aborder une nouvelle partie".
- Pour #112, une simple salutation générique ne suffit pas : il faut présenter
  l'utilité concrète de la formation, le parcours, les compétences abordées,
  la manière de progresser et encourager les apprenants avant le premier sujet.

Format attendu :

```json
{{
  "reviews": [
    {{
      "segment_id": 42,
      "patches": [
        {{
          "original": "phrase EXACTE à remplacer (copie verbatim, 3-40 mots)",
          "replacement": "phrase corrigée, même fond pédagogique, plus orale",
          "rule_violated": "#101",
          "reason": "explication brève"
        }}
      ]
    }}
  ]
}}
```

- Max 10 patches par segment.
- `replacement` peut ajouter une courte phrase orale, une micro-interaction ou
  un tag `[pause]` / `[calm]` si cela corrige vraiment le rythme.
- Si un segment est conforme, renvoie `"patches": []` pour ce segment.

Écris dans `output.md` le JSON brut (sans enrobage).
""",
    )
    _write(target, "input.md", json.dumps(segs, ensure_ascii=False, indent=2))
    _write(target, "rules.md", _load_review_rules_text())


# ─── Import du résultat de mission ───────────────────────────────────────────

def import_mission_result(job_id: int, step_key: str) -> dict:
    """Lit output.md écrit par Claude Code, parse selon l'étape, met à jour la
    DB et archive la mission dans review_queue/_done/."""
    if not local_dev_enabled():
        raise PermissionError("LOCAL_DEV non activé côté backend")
    if step_key not in STEP_LABELS:
        raise ValueError(f"step_key invalide : {step_key}")

    target = mission_dir(job_id, step_key)
    output_path = os.path.join(target, "output.md")
    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"{output_path} introuvable — Claude Code doit avoir écrit output.md avant import"
        )
    with open(output_path, "r", encoding="utf-8") as f:
        output = f.read()

    # Lecture du modèle utilisé (depuis meta.json) pour renseigner generated_via
    meta_path = os.path.join(target, "meta.json")
    model = "haiku"
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        model = meta.get("model", "haiku")
    generated_via = f"claude_code_{model}"

    importers = {
        "global": _import_global,
        "daily": _import_daily,
        "humanization_review": _import_humanization_review,
        "review": _import_review,
        "kb": _import_kb,
        "content": _import_content,
    }
    result = importers[step_key](job_id, output, generated_via)

    # Archivage uniquement si import réellement réussi (pas d'exception levée).
    _archive_mission(job_id, step_key)
    logger.info(f"📥 Mission importée : job={job_id} step={step_key} → {result}")
    return result


# ─── Exécution automatique via subprocess `claude` (dev local only) ──────────

def execute_mission_locally(job_id: int, step_key: str, model: str) -> dict:
    """Dispatcher : étapes simples (global/daily/kb) → 1 subprocess, étapes
    chunked (content/review) → boucle de N subprocess séquentiels.

    Dev local only (gating LOCAL_DEV=true + `claude` dans le PATH du backend).
    """
    if not local_dev_enabled():
        raise PermissionError("LOCAL_DEV non activé côté backend")
    if not shutil.which("claude"):
        raise RuntimeError(
            "Binaire `claude` introuvable dans le PATH du backend. "
            "Installe Claude Code CLI (`npm install -g @anthropic-ai/claude-code` "
            "ou équivalent) puis redémarre le backend."
        )
    if step_key not in STEP_LABELS:
        raise ValueError(f"step_key invalide : {step_key}")
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model invalide : {model} (attendus : {ALLOWED_MODELS})")

    if step_key in _CHUNKED_STEPS:
        return _execute_chunked(job_id, step_key, model)
    return _execute_single(job_id, step_key, model)


def _execute_single(job_id: int, step_key: str, model: str) -> dict:
    """Comportement legacy pour global/daily/kb : 1 mission unique, 1 subprocess."""
    target = mission_dir(job_id, step_key)
    if not os.path.isdir(target) or not os.path.exists(os.path.join(target, "task.md")):
        export_mission(job_id, step_key, model)
    else:
        logger.info(f"ℹ️ Mission {step_key} déjà exportée pour job {job_id}, réutilisation")

    log_path = os.path.join(target, "execution.log")
    returncode = _run_subprocess(target, model, log_path=log_path, log_mode="w")
    import_result = import_mission_result(job_id, step_key)
    return {
        "ok": True,
        "returncode": returncode,
        "import_result": import_result,
    }


def _archive_mission(job_id: int, step_key: str) -> None:
    src = mission_dir(job_id, step_key)
    if not os.path.isdir(src):
        return
    os.makedirs(_DONE_ROOT, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(_DONE_ROOT, f"{ts}-job{job_id}-{step_key}")
    shutil.move(src, dest)


def _import_global(job_id, output, generated_via):
    """Remplace le programme global et INVALIDE les étapes aval.

    Audit fix #6 : réimporter un programme global implique que les
    programmes journée précédents ne correspondent plus au programme
    source. On les remet à zéro + on efface leur flag de validation
    pour forcer l'utilisateur à refaire l'étape 5.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    # Détection : des programmes journée existent déjà ?
    cursor.execute(
        "SELECT daily_programs, daily_programs_validated FROM formation_pipeline_jobs WHERE id = ?",
        (job_id,),
    )
    prev = cursor.fetchone()
    had_daily = bool(prev and prev[0] and prev[0] != "[]")
    had_daily_validated = bool(prev and prev[1])

    # Réimport du global = les étapes aval sont invalidées (audit #6)
    cursor.execute(
        "UPDATE formation_pipeline_jobs SET "
        "  global_program = ?, "
        "  global_program_generated_via = ?, "
        "  global_program_validated = 0, "  # non validé, l'utilisateur doit relire
        "  daily_programs = '[]', "          # les journées sont obsolètes
        "  daily_programs_validated = 0, "
        "  daily_programs_generated_via = NULL, "
        "  status = 'global_ready', "
        "  updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (output.strip(), generated_via, job_id),
    )
    conn.commit()
    conn.close()

    invalidated = []
    if had_daily:
        invalidated.append("daily_programs (écrasés)")
    if had_daily_validated:
        invalidated.append("daily_programs_validated (remis à 0)")

    return {
        "ok": True,
        "bytes": len(output),
        "generated_via": generated_via,
        "cascade_invalidated": invalidated,
    }


def _import_daily(job_id, output, generated_via):
    """Remplace les programmes journée. N'invalide PAS automatiquement les
    content_generation_segments (audit fix #6 partiel) — dans cette V1 les
    segments restent tels quels, l'utilisateur doit cliquer "Reprendre" ou
    régénérer explicitement s'il veut refaire l'étape 6. Raison : un
    réimport daily peut ne concerner que quelques journées ajoutées, pas un
    remplacement total ; invalider automatiquement tous les segments serait
    trop agressif."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tp_name, nb_days FROM formation_pipeline_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Job pipeline {job_id} introuvable")
    tp_name, nb_days = row[0], int(row[1] or 0)
    try:
        from services.formation_pipeline_service import _clean_json, _normalize_daily_payload
        parsed_data = _clean_json(output)
        parsed = _normalize_daily_payload(parsed_data, 1, nb_days, tp_name or "formation")
    except Exception as e:
        conn.close()
        raise ValueError(f"JSON invalide dans output.md : {e}")
    cursor.execute(
        "UPDATE formation_pipeline_jobs SET daily_programs = ?, "
        "daily_programs_generated_via = ?, "
        "daily_programs_validated = 0, "    # non validé, relire avant étape 6
        "status = 'daily_ready', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(parsed, ensure_ascii=False), generated_via, job_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "days": len(parsed), "generated_via": generated_via}


def _import_review(job_id, output, generated_via):
    # output = { "reviews": [ { segment_id, patches: [...] } ] }
    try:
        parsed = json.loads(_extract_json(output))
        reviews = parsed.get("reviews", [])
    except Exception as e:
        raise ValueError(f"JSON invalide dans output.md : {e}")

    applied_total = 0
    rejected_total = 0
    failed_total = 0
    from services.content_generation_service import _current_compliance_review_signature
    review_signature = _current_compliance_review_signature()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Restreindre strictement aux segments des dossiers cours de ce job
    # pipeline. Empêche qu'un segment_id d'une autre génération sur la même
    # plateforme soit modifié par erreur via un output.md mal scopé.
    cursor.execute("SELECT id FROM formation_pipeline_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Job pipeline {job_id} introuvable")

    for rev in reviews:
        seg_id = rev.get("segment_id")
        patches = rev.get("patches", []) or []
        if seg_id is None:
            continue
        # Vérif de scope : le segment doit appartenir à un content_generation_job
        # dont le folder_id est rattaché à ce job formation.
        cursor.execute(
            """
            SELECT s.text_content
            FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            JOIN cours_folders cf ON cf.id = cj.folder_id
            WHERE s.id = ? AND cf.formation_job_id = ?
            """,
            (seg_id, job_id),
        )
        row = cursor.fetchone()
        if not row:
            # Segment inexistant OU hors scope plateforme : on log mais on
            # ne touche à rien d'autre.
            logger.warning(
                f"⚠️ Review import : segment_id={seg_id} ignoré (inexistant ou hors job {job_id})"
            )
            failed_total += 1
            continue
        text = row[0]
        seg_applied = 0
        seg_rejected = 0
        for p in patches[:10]:  # hard cap 10 patches / segment (éthiques + stylistiques)
            original = p.get("original")
            replacement = p.get("replacement")
            if not original or replacement is None:
                continue
            count = text.count(original)
            if count == 1:
                text = text.replace(original, replacement, 1)
                seg_applied += 1
            else:
                seg_rejected += 1
        applied_total += seg_applied
        rejected_total += seg_rejected

        # Fix #3 audit : dirty=1 SEULEMENT si au moins un patch a été appliqué
        # (sinon le TTS régénérerait des audios identiques pour rien).
        # reviewed=1 est toujours mis — l'audit a bien été tenté avec succès.
        if seg_applied > 0:
            cursor.execute(
                "UPDATE content_generation_segments "
                "SET text_content = ?, word_count = ?, dirty = 1, "
                "    reviewed = 1, review_error = NULL, review_signature = ? "
                "WHERE id = ?",
                (text, len(text.split()), review_signature, seg_id),
            )
        else:
            cursor.execute(
                "UPDATE content_generation_segments "
                "SET reviewed = 1, review_error = NULL, review_signature = ? WHERE id = ?",
                (review_signature, seg_id),
            )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "segments_reviewed": len(reviews),
        "patches_applied": applied_total,
        "patches_rejected": rejected_total,
        "segments_failed": failed_total,
        "generated_via": generated_via,
    }


def _import_humanization_review(job_id, output, generated_via):
    """Import manuel de la passe humanisation (#101-#114).

    Même format que `_import_review`, mais les patches appliqués invalident la
    conformité stricte pour forcer la passe #1-#27 ensuite.
    """
    try:
        parsed = json.loads(_extract_json(output))
        reviews = parsed.get("reviews", [])
    except Exception as e:
        raise ValueError(f"JSON invalide dans output.md : {e}")

    applied_total = 0
    rejected_total = 0
    failed_total = 0
    from services.content_generation_service import (
        _current_humanization_review_signature,
        _ensure_review_state_columns,
    )
    _ensure_review_state_columns()
    review_signature = _current_humanization_review_signature()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM formation_pipeline_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Job pipeline {job_id} introuvable")

    for rev in reviews:
        seg_id = rev.get("segment_id")
        patches = rev.get("patches", []) or []
        if seg_id is None:
            continue
        cursor.execute(
            """
            SELECT s.text_content
            FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            JOIN cours_folders cf ON cf.id = cj.folder_id
            WHERE s.id = ? AND cf.formation_job_id = ?
            """,
            (seg_id, job_id),
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(
                f"⚠️ Humanization import : segment_id={seg_id} ignoré "
                f"(inexistant ou hors job {job_id})"
            )
            failed_total += 1
            continue
        text = row[0]
        seg_applied = 0
        seg_rejected = 0
        for p in patches[:10]:
            original = p.get("original")
            replacement = p.get("replacement")
            if not original or replacement is None:
                continue
            count = text.count(original)
            if count == 1:
                text = text.replace(original, replacement, 1)
                seg_applied += 1
            else:
                seg_rejected += 1
        applied_total += seg_applied
        rejected_total += seg_rejected

        if seg_applied > 0:
            cursor.execute(
                """
                UPDATE content_generation_segments
                SET text_content = ?, word_count = ?, dirty = 1,
                    humanized = 1, humanization_error = NULL, humanization_signature = ?,
                    reviewed = 0, review_error = NULL, review_signature = NULL
                WHERE id = ?
                """,
                (text, len(text.split()), review_signature, seg_id),
            )
        else:
            cursor.execute(
                """
                UPDATE content_generation_segments
                SET humanized = 1, humanization_error = NULL, humanization_signature = ?
                WHERE id = ?
                """,
                (review_signature, seg_id),
            )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "segments_reviewed": len(reviews),
        "patches_applied": applied_total,
        "patches_rejected": rejected_total,
        "segments_failed": failed_total,
        "generated_via": generated_via,
        "review_kind": "humanization",
        "review_label": "Humanisation",
        "review_signature": review_signature,
    }


def _import_kb(job_id, output, generated_via):
    """Parse output.md (JSON array de compétences enrichies) et remplace
    la KB du job. Schéma attendu par compétence :
      {competence_title, bloc, definition_pedagogique, contexte_terrain,
       etudes_de_cas (list), pieges_frequents (list), vocabulaire_metier (dict),
       liens_connexes (list)}

    Tolérant à la troncature : si le JSON Claude est coupé en plein milieu (ex.
    output dépasse max_tokens), on passe par `_repair_truncated_json` qui
    referme proprement les structures et garde toutes les compétences complètes.
    """
    raw_json = _extract_json(output)
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as first_err:
        # Tentative de réparation (Claude a tronqué au milieu d'une compétence)
        try:
            from services.knowledge_base_service import _repair_truncated_json
            repaired = _repair_truncated_json(raw_json)
            parsed = json.loads(repaired)
            logger.warning(
                f"⚠️ KB output.md tronqué ({len(raw_json)} chars) — réparé "
                f"({len(repaired)} chars), {len(parsed) if isinstance(parsed, list) else '?'} entrées récupérées"
            )
        except Exception as second_err:
            raise ValueError(
                f"JSON invalide dans output.md : {first_err} "
                f"(réparation échouée : {second_err})"
            )
    if not isinstance(parsed, list):
        raise ValueError("output.md doit être un JSON array de compétences")

    conn = get_db_connection()
    cursor = conn.cursor()
    # Remplacement total : on DELETE l'ancienne KB + INSERT la nouvelle
    cursor.execute("DELETE FROM formation_knowledge_base WHERE job_id = ?", (job_id,))
    inserted = 0
    for idx, comp in enumerate(parsed):
        if not isinstance(comp, dict):
            continue
        title = (comp.get("competence_title") or "").strip()
        if not title:
            continue
        key = title[:200].lower().replace(" ", "_")
        definition = comp.get("definition_pedagogique") or ""
        contexte = comp.get("contexte_terrain") or ""
        etudes = comp.get("etudes_de_cas") or []
        pieges = comp.get("pieges_frequents") or []
        vocab = comp.get("vocabulaire_metier") or {}
        liens = comp.get("liens_connexes") or []

        total_words = sum(
            len(str(x).split())
            for x in (definition, contexte, json.dumps(etudes), json.dumps(pieges), json.dumps(vocab))
        )
        cursor.execute(
            """
            INSERT INTO formation_knowledge_base
            (job_id, competence_index, competence_key, competence_title, bloc,
             status, definition_pedagogique, contexte_terrain,
             etudes_de_cas, pieges_frequents, vocabulaire_metier, liens_connexes,
             total_words)
            VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, idx, key, title, comp.get("bloc", ""),
                definition, contexte,
                json.dumps(etudes, ensure_ascii=False),
                json.dumps(pieges, ensure_ascii=False),
                json.dumps(vocab, ensure_ascii=False),
                json.dumps(liens, ensure_ascii=False),
                total_words,
            ),
        )
        inserted += 1

    cursor.execute(
        "UPDATE formation_pipeline_jobs SET status = 'kb_ready', "
        "kb_generated_via = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (generated_via, job_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "competences_imported": inserted, "generated_via": generated_via}


def _import_content(job_id, output, generated_via):
    """Parse output.md (JSON) et upsert les segments via _save_segment_db.
    Format attendu : {days: [{day_number, segments: [{sub_part_index, passe, text}]}]}
    """
    try:
        parsed = json.loads(_extract_json(output))
    except Exception as e:
        raise ValueError(f"JSON invalide dans output.md : {e}")
    days = parsed.get("days") if isinstance(parsed, dict) else None
    if not isinstance(days, list):
        raise ValueError("output.md doit contenir {days: [...]}")

    conn = get_db_connection()
    cursor = conn.cursor()
    # Récupérer les cours_folders du job pipeline + leurs
    # content_generation_jobs associés, dans l'ordre (day_number).
    job = _get_job_row(job_id)
    if not job:
        conn.close()
        raise ValueError(f"Job pipeline {job_id} introuvable")
    cursor.execute(
        """SELECT f.id, cj.id FROM cours_folders f
           LEFT JOIN content_generation_jobs cj ON cj.folder_id = f.id
           WHERE f.formation_job_id = ? ORDER BY f.position ASC""",
        (job_id,),
    )
    folders = cursor.fetchall()  # [(folder_id, cg_job_id), ...]
    conn.close()

    imported = 0
    from services.content_generation_service import _save_segment_db
    for day in days:
        day_num = day.get("day_number", 0)
        idx = day_num - 1 if day_num > 0 else 0
        if idx < 0 or idx >= len(folders):
            continue
        folder_id, cg_job_id = folders[idx]
        if not cg_job_id:
            # Pas de content_generation_job pour ce folder — skip
            continue
        for seg in day.get("segments", []):
            sub_idx = seg.get("sub_part_index")
            passe = seg.get("passe")
            text = seg.get("text", "")
            if sub_idx is None or passe is None or not text:
                continue
            sub_part_name = seg.get("sub_part_name", f"sous-partie {sub_idx + 1}")
            _save_segment_db(cg_job_id, sub_idx, sub_part_name, passe, text)
            imported += 1

    return {"ok": True, "segments_imported": imported, "generated_via": generated_via}


def _extract_json(text: str) -> str:
    """Extrait le premier objet/array JSON du texte (tolère markdown wrap)."""
    text = text.strip()
    # Essai brut
    if text.startswith("[") or text.startswith("{"):
        return text
    # Essai dans un bloc ```json ... ```
    import re
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Dernier recours : chercher { ... } ou [ ... ]
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i >= 0),
        default=-1,
    )
    end = max(text.rfind("}"), text.rfind("]"))
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("Aucun JSON détectable dans output.md")


# ─── Liste des missions en attente d'import ───────────────────────────────────

def list_pending_missions(job_id: int) -> dict:
    """Retourne les missions Claude Code en attente d'import pour ce job.

    Filtres :
    - Une mission chunked dont `progress.json` dit `status: done` (ou
      `done_with_errors`) n'est PAS listée comme en attente — elle a déjà été
      traitée par le subprocess auto (pas de bandeau orange à afficher).
    - Une mission chunked encore en cours (`status: running` / `throttling` /
      `rate_limited`) est listée pour que l'UI puisse afficher la progression.
    - Une mission single-step (mode export/import manuel legacy) avec un
      `output.md` mais sans `progress.json` est listée comme avant.
    """
    if not local_dev_enabled():
        return {}
    out = {}
    root = os.path.join(_REVIEW_QUEUE_ROOT, f"job_{job_id}")
    if os.path.isdir(root):
        for name in os.listdir(root):
            if not name.startswith("step_"):
                continue
            step_key = name[len("step_"):]
            meta_path = os.path.join(root, name, "meta.json")
            if not os.path.exists(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            # Si mission chunked (= progress.json existe) ET status terminal
            # sans erreurs, on ne l'affiche PAS comme "en attente d'import" :
            # le subprocess auto l'a déjà importée.
            progress_path = os.path.join(root, name, "progress.json")
            chunked_done = False
            if os.path.exists(progress_path):
                try:
                    with open(progress_path, "r", encoding="utf-8") as f:
                        prg = json.load(f)
                    chunked_done = (
                        prg.get("status") in ("done", "done_with_errors")
                        and not prg.get("errors")
                    )
                except Exception:
                    pass
            if chunked_done:
                continue  # déjà finalisée, pas de bandeau

            out[step_key] = {
                "path": os.path.relpath(os.path.join(root, name), os.path.dirname(_REVIEW_QUEUE_ROOT)),
                "step_label": meta.get("step_label", step_key),
                "model": meta.get("model"),
                "exported_at": meta.get("exported_at"),
                "command": f"claude --model {meta.get('model', 'haiku')}",
                "has_output": os.path.exists(os.path.join(root, name, "output.md")),
                "execution_status": "idle",
            }
    # Overlay : exécutions en cours / fraîchement terminées (subprocess auto)
    for (jid, step_key), state in _EXECUTION_STATE.items():
        if jid != job_id:
            continue
        entry = out.setdefault(step_key, {
            "step_label": STEP_LABELS.get(step_key, step_key),
            "model": state.get("model"),
            "has_output": False,
            "path": f"review_queue/job_{jid}/step_{step_key}",
            "command": f"claude --model {state.get('model', 'haiku')}",
        })
        entry["execution_status"] = state.get("status", "idle")
        entry["execution_error"] = state.get("error")
        # Progress chunked : si progress.json existe, l'inclure pour l'UI
        progress = _read_progress(jid, step_key)
        if progress:
            entry["progress"] = progress
    return out


# ─── Mode chunked (content + humanization_review + review) ───────────────────
#
# `content` et les deux reviews ne tiennent pas en 1 seul appel CLI : une
# journée complète calibrée audio dépasse largement le contexte utile.
# mots de sortie pour content, jusqu'à 117k tokens d'input par review × N journées.
# Stratégie = boucle de N subprocess `claude` séquentiels, 1 par chunk.
# Chaque chunk a son propre dossier review_queue/job_X/step_Y/<chunk_id>/
# avec task.md + input.md (+ rules.md). Le dossier parent contient meta.json,
# execution.log (concaténé) et progress.json (état temps réel pour l'UI).

def _run_subprocess(mission_dir: str, model: str, log_path: str, log_mode: str = "w") -> int:
    """Lance `claude -p` sur task.md du dossier `mission_dir`. Vérifie qu'output.md
    est créé. Lève RuntimeError si returncode != 0 ou output.md absent.
    Retourne le returncode.

    Streaming stdout vers log_path (append si log_mode='a' pour les chunks).
    """
    output_path = os.path.join(mission_dir, "output.md")
    if os.path.exists(output_path):
        os.remove(output_path)

    task_rel = os.path.relpath(
        os.path.join(mission_dir, "task.md"), os.path.dirname(_REVIEW_QUEUE_ROOT)
    )
    output_rel = os.path.relpath(output_path, os.path.dirname(_REVIEW_QUEUE_ROOT))
    prompt = (
        f"Exécute la mission décrite dans {task_rel}. "
        f"Respecte scrupuleusement le format de sortie demandé dans task.md. "
        f"Écris le résultat dans {output_rel}."
    )
    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--verbose",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]
    cwd = os.path.dirname(_REVIEW_QUEUE_ROOT)
    chunk_label = os.path.basename(mission_dir)

    # IMPORTANT — env propre sans ANTHROPIC_API_KEY pour utiliser le FORFAIT
    # Claude Code (login OAuth local), pas l'API à la carte. Sans ce strip,
    # la CLI hérite de la clé API du shell et tape sur le compte API à la
    # carte — qui peut être à zéro alors que le forfait est dispo.
    # Cas réel observé : "Credit balance is too low" en billing_error alors
    # que le forfait Pro/Max marche normalement en CLI manuel.
    child_env = os.environ.copy()
    stripped_keys = []
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if k in child_env:
            del child_env[k]
            stripped_keys.append(k)
    if stripped_keys:
        logger.info(
            f"🚀 Subprocess claude --model {model} ({chunk_label}, cwd={cwd}) "
            f"— forfait local (env strip: {', '.join(stripped_keys)})"
        )
    else:
        logger.info(f"🚀 Subprocess claude --model {model} ({chunk_label}, cwd={cwd})")

    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=child_env,
        )
    except FileNotFoundError:
        raise RuntimeError("Binaire `claude` introuvable au moment du Popen")

    start = time.time()
    with open(log_path, log_mode, encoding="utf-8") as log_f:
        if log_mode == "w":
            log_f.write(f"$ {' '.join(cmd[:4])} ... ({chunk_label})\n(cwd={cwd})\n---\n")
        else:
            log_f.write(f"\n$ chunk {chunk_label} — claude --model {model}\n---\n")
        log_f.flush()
        for line in proc.stdout:
            log_f.write(line)
            log_f.flush()
            if time.time() - start > 3600:
                proc.kill()
                raise RuntimeError("Claude Code a dépassé le timeout de 1h (tué)")
        proc.wait(timeout=60)
        log_f.write(f"\n---\nreturncode={proc.returncode}\n")

    logger.info(f"📤 Subprocess terminé : code={proc.returncode}, log={log_path}")

    # Soft-success : si output.md existe et n'est pas vide, considérer la
    # mission comme réussie même si returncode != 0. Cas réel observé : Claude
    # Code écrit output.md via un sub-agent, puis un dernier appel ping
    # Anthropic et tape un 429. Le main agent propage le 429 → returncode=1,
    # mais le travail est fait. Sans ce soft-success, on rejouerait pour rien
    # (avec en plus le rate limit qui s'aggrave).
    output_exists = os.path.exists(output_path)
    output_size = os.path.getsize(output_path) if output_exists else 0
    soft_success = output_exists and output_size >= 50  # ~50 bytes mini pour un JSON significatif

    if proc.returncode != 0:
        tail = ""
        is_rate_limit = False
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # On regarde large (200 dernières lignes) parce que les events
            # stream-json sont sur 1 ligne chacun mais peuvent être lourds.
            tail_text = "".join(lines[-200:])
            tail = "".join(lines[-20:])
            if (
                '"api_error_status":429' in tail_text
                or '"error":"rate_limit"' in tail_text
                or "rate limit of " in tail_text.lower()
            ):
                is_rate_limit = True
        except Exception:
            pass

        if soft_success:
            logger.warning(
                f"⚠️ Subprocess {chunk_label} returncode={proc.returncode} "
                f"(rate_limit={is_rate_limit}) MAIS output.md existe "
                f"({output_size} bytes). Soft-success — on importe quand même."
            )
            return proc.returncode

        if is_rate_limit:
            raise _RateLimitError(
                f"Rate limit Anthropic 429 sur {chunk_label} "
                f"(attente automatique avant retry)"
            )
        raise RuntimeError(
            f"Claude Code returncode={proc.returncode}. "
            f"Fin du log : {tail[-500:]}"
        )
    if not output_exists:
        raise RuntimeError(
            f"output.md non créé par Claude Code dans {chunk_label}. "
            f"Voir log : {os.path.relpath(log_path, os.path.dirname(_REVIEW_QUEUE_ROOT))}"
        )
    return proc.returncode


def _write_progress(progress_path: str, progress: dict) -> None:
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _read_progress(job_id: int, step_key: str) -> dict:
    path = os.path.join(mission_dir(job_id, step_key), "progress.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─── Préparation pipeline (avant chunking content) ───────────────────────────

def _format_day_program_text_minimal(day_data: dict, tp_name: str) -> str:
    """Format minimal du programme texte d'1 journée (stocké dans cg_jobs.program_text).
    Pas le format LaTeX complet — juste de quoi alimenter le contexte des passes."""
    day_data = _normalize_day_audio_slots(day_data)
    from services.formation_pipeline_service import _format_slot_generation_source
    title = day_data.get("title", "Journée")
    parts = [f"# {tp_name} — {title}\n"]
    for sp in day_data.get("sub_parts", []):
        parts.append(f"\n## {sp.get('name', '?')}\n")
        parts.append(_format_slot_generation_source(sp) + "\n")
    return "\n".join(parts)


def _ensure_content_pipeline_structure(job: dict) -> list:
    """S'assure que cours_folders + content_generation_jobs existent pour chaque
    journée du daily_programs. Crée les manquants en 'idle' SANS lancer la
    génération. Retourne la liste des cg_job_ids dans l'ordre des journées
    (1 par journée du daily_programs).

    Idempotent : si folders/jobs existent déjà, ne crée pas de doublon.
    """
    daily_programs = json.loads(job["daily_programs"] or "[]")
    if not daily_programs:
        raise ValueError("Aucun programme journée — lance d'abord l'étape 5")

    platform_id = job["platform_id"]
    tp_name = job["tp_name"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cg_job_ids = []

    try:
        normalized_daily_programs = [_normalize_day_audio_slots(day) for day in daily_programs]
        from services.formation_pipeline_service import _format_slot_generation_source
        for i, day_data in enumerate(normalized_daily_programs):
            day_num = day_data.get("day_number", i + 1)
            day_title = day_data.get("title", f"Jour {day_num}")
            folder_name = f"Jour {day_num} — {day_title}"
            sub_parts = [sp["name"] for sp in day_data.get("sub_parts", [])]
            module_contents = {}
            for sp in day_data.get("sub_parts", []):
                module_contents[sp["name"]] = _format_slot_generation_source(sp)

            cursor.execute(
                "SELECT id FROM cours_folders WHERE formation_job_id = ? AND name = ?",
                (job["id"], folder_name),
            )
            row = cursor.fetchone()
            if row:
                folder_id = row[0]
            else:
                cursor.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM cours_folders WHERE platform_id = ?",
                    (platform_id,),
                )
                position = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO cours_folders (platform_id, name, position, formation_job_id) VALUES (?, ?, ?, ?)",
                    (platform_id, folder_name, position, job["id"]),
                )
                folder_id = cursor.lastrowid
                logger.info(f"📁 Folder créé : '{folder_name}' (id={folder_id})")

            cursor.execute(
                "SELECT id FROM content_generation_jobs WHERE folder_id = ?",
                (folder_id,),
            )
            row = cursor.fetchone()
            if row:
                cg_job_id = row[0]
            else:
                day_program_text = _format_day_program_text_minimal(day_data, tp_name)
                cursor.execute(
                    """
                    INSERT INTO content_generation_jobs
                        (folder_id, platform_id, program_text, program_title,
                         sub_parts, from_scratch, module_contents,
                         status, current_sub_part, current_passe, total_words,
                         error_message)
                    VALUES (?, ?, ?, ?, ?, 1, ?, 'idle', 0, 1, 0, NULL)
                    """,
                    (
                        folder_id, platform_id, day_program_text, tp_name,
                        json.dumps(sub_parts, ensure_ascii=False),
                        json.dumps(module_contents, ensure_ascii=False),
                    ),
                )
                cg_job_id = cursor.lastrowid
                logger.info(f"📋 cg_job créé : id={cg_job_id} pour folder {folder_id}")

            cg_job_ids.append(cg_job_id)
        conn.commit()
    finally:
        conn.close()

    return cg_job_ids


# ─── Listers de chunks ────────────────────────────────────────────────────────

def _list_content_chunks(job: dict) -> list:
    """Pour content : 1 chunk par (day, sub_idx, passe). Skippe les segments
    déjà completed en DB (idempotent — le bouton "Exécuter" reprend là où ça
    s'était arrêté en cas de crash backend ou d'erreur sur quelques chunks)."""
    daily_programs = json.loads(job["daily_programs"] or "[]")
    if not daily_programs:
        return []

    cg_job_ids = _ensure_content_pipeline_structure(job)
    from services.formation_pipeline_service import _format_slot_generation_source

    conn = get_db_connection()
    cursor = conn.cursor()
    chunks = []
    try:
        for i, day_data in enumerate(_normalize_day_audio_slots(day) for day in daily_programs):
            day_num = day_data.get("day_number", i + 1)
            cg_job_id = cg_job_ids[i]
            cursor.execute(
                """SELECT sub_part_index, passe FROM content_generation_segments
                   WHERE job_id = ? AND status = 'completed'""",
                (cg_job_id,),
            )
            done = set((r[0], r[1]) for r in cursor.fetchall())

            for sub_idx, sp in enumerate(day_data.get("sub_parts", [])):
                sub_part_name = sp.get("name", f"Sous-partie {sub_idx + 1}")
                module_content = _format_slot_generation_source(sp)
                for passe in (1, 2, 3):
                    if (sub_idx, passe) in done:
                        continue
                    chunks.append({
                        "id": f"day_{day_num}_sub_{sub_idx}_passe_{passe}",
                        "day_num": day_num,
                        "day_idx": i,
                        "folder_name": day_data.get("title") or day_data.get("name") or f"Jour {day_num}",
                        "cg_job_id": cg_job_id,
                        "sub_idx": sub_idx,
                        "sub_part_name": sub_part_name,
                        "module_content": module_content,
                        "passe": passe,
                    })
    finally:
        conn.close()
    return chunks


def _review_step_config(step_key: str) -> dict:
    """Configuration des deux passes locales alignées sur la pipeline API."""
    if step_key == "humanization_review":
        from services.content_generation_service import (
            _HUMANIZATION_REVIEW_RULE_GROUPS,
            _current_humanization_review_signature,
            _ensure_review_state_columns,
        )
        _ensure_review_state_columns()
        return {
            "step_key": "humanization_review",
            "review_kind": "humanization",
            "review_label": "Humanisation",
            "reviewed_column": "humanized",
            "error_column": "humanization_error",
            "signature_column": "humanization_signature",
            "signature": _current_humanization_review_signature(),
            "groups": _HUMANIZATION_REVIEW_RULE_GROUPS,
            "invalidate_compliance_on_change": True,
            "report_source": "humanization_claude_code_aggregate",
        }

    if step_key == "review":
        from services.content_generation_service import (
            _current_compliance_review_signature,
            _ensure_review_state_columns,
        )
        _ensure_review_state_columns()
        return {
            "step_key": "review",
            "review_kind": "compliance",
            "review_label": "Conformité",
            "reviewed_column": "reviewed",
            "error_column": "review_error",
            "signature_column": "review_signature",
            "signature": _current_compliance_review_signature(),
            "groups": _REVIEW_RULE_GROUPS,
            "invalidate_compliance_on_change": False,
            "report_source": "claude_code_aggregate",
        }

    raise ValueError(f"step review inconnu : {step_key}")


def _list_review_like_chunks(job: dict, step_key: str) -> list:
    """Liste les chunks pour une passe de review locale.

    La sélection est pilotée par les mêmes colonnes/signatures que l'API :
    `humanized + humanization_signature` pour la passe humanisation, puis
    `reviewed + review_signature` pour la conformité stricte.
    """
    cfg = _review_step_config(step_key)
    reviewed_col = cfg["reviewed_column"]
    signature_col = cfg["signature_column"]
    if reviewed_col not in {"humanized", "reviewed"}:
        raise ValueError(f"Colonne reviewed non autorisée : {reviewed_col}")
    if signature_col not in {"humanization_signature", "review_signature"}:
        raise ValueError(f"Colonne signature non autorisée : {signature_col}")

    conn = get_db_connection()
    cursor = conn.cursor()
    chunks = []
    try:
        cursor.execute(
            "SELECT id, name, position FROM cours_folders "
            "WHERE formation_job_id = ? ORDER BY position ASC",
            (job["id"],),
        )
        folders = cursor.fetchall()
        for fid, fname, position in folders:
            cursor.execute(
                f"""
                SELECT s.id, s.sub_part_index, s.passe, s.text_content
                FROM content_generation_segments s
                JOIN content_generation_jobs cj ON cj.id = s.job_id
                WHERE cj.folder_id = ? AND s.status = 'completed'
                AND (
                    COALESCE(s.{reviewed_col}, 0) = 0
                    OR s.{signature_col} IS NULL
                    OR s.{signature_col} != ?
                )
                ORDER BY s.sub_part_index ASC, s.passe ASC
                """,
                (fid, cfg["signature"]),
            )
            segs = [
                {"segment_id": r[0], "sub_idx": r[1], "passe": r[2], "text": r[3]}
                for r in cursor.fetchall()
            ]
            if not segs:
                continue
            # Génère 1 chunk par groupe de règles. La réutilisation auto
            # d'output.md (cf. _execute_chunked) skippera les chunks déjà OK.
            for group in cfg["groups"]:
                chunks.append({
                    "id": f"day_{position + 1}_review_{group['id']}",
                    "day_idx": position,
                    "folder_id": fid,
                    "folder_name": fname,
                    "segments": segs,
                    "rule_group": group,
                    "review_step_key": step_key,
                    "review_kind": cfg["review_kind"],
                    "review_label": cfg["review_label"],
                    "review_signature": cfg["signature"],
                    "invalidate_compliance_on_change": cfg["invalidate_compliance_on_change"],
                })
    finally:
        conn.close()
    return chunks


def _list_humanization_chunks(job: dict) -> list:
    return _list_review_like_chunks(job, "humanization_review")


def _list_review_chunks(job: dict) -> list:
    """Multi-agents review : pour chaque journée non encore complètement
    reviewed, on retourne **N chunks** (1 par groupe de règles dans
    `_REVIEW_RULE_GROUPS`). Chaque chunk fait sa propre passe Claude Code
    sur l'intégralité du texte de la journée mais cible UNIQUEMENT son
    sous-ensemble de règles.

    Avantage vs single-agent : pas de favoritisme. Un agent unique tend à
    saturer son budget de patches sur les règles qu'il voit le plus
    (#22 guillemets, #26 énumérations) et oublie #1-#17. Avec N agents
    spécialisés, chaque sous-ensemble de règles a son propre budget complet.

    Idempotence : skippe les journées dont tous les segments sont reviewed=1
    avec la signature de règles actuelle.
    """
    return _list_review_like_chunks(job, "review")


# ─── Builders chunk ───────────────────────────────────────────────────────────

_PASSE_DESCRIPTIONS = {
    1: ("Fondation", "pose les bases. Définitions, principes, contexte. "
                     "C'est la première fois que l'apprenant entend parler de ce module."),
    2: ("Pratique", "concrétise. Exemples détaillés, mises en situation, cas concrets variés. "
                    "Comment ça se passe sur le terrain au quotidien."),
    3: ("Maîtrise", "approfondit. Pièges, nuances, cas limites, contre-exemples, conseils experts."),
}


# Multi-agents review : on découpe la révision en N agents Claude Code
# spécialisés. Chacun reçoit le même texte mais doit chercher UNIQUEMENT ses
# règles attribuées. Ça force une couverture exhaustive sur toutes les règles
# au lieu d'un agent unique qui se concentre sur ce qu'il voit le plus.
_REVIEW_RULE_GROUPS = [
    {
        "id": "ethique_culturelle",
        "label": "Éthique culturelle",
        "rules": [1, 2, 3, 9, 14],
        "description": "Spirituel/religieux, alcool/musique/banques, fêtes émotionnelles, "
                       "humour, respect des tiers",
    },
    {
        "id": "ethique_commerciale",
        "label": "Éthique commerciale",
        "rules": [4, 5, 6, 7, 8],
        "description": "Manipulation/tromperie en vente, persuasion agressive/closing manipulatoire, "
                       "flirt/séduction, chance/destin, célébrités/divertissement",
    },
    {
        "id": "legal_integrite",
        "label": "Légal et intégrité",
        "rules": [10, 11, 12, 13, 15, 16],
        "description": "Cohérence interne, discrimination, RGPD/données personnelles, "
                       "promesses irréalistes, personnes en détresse, "
                       "conseils médicaux/juridiques précis",
    },
    {
        "id": "anti_hallucination",
        "label": "Anti-hallucination",
        "rules": [17, 18, 19, 20],
        "description": "Annonce explicite des exemples fictifs, chiffres/études non sourcés, "
                       "expressions de prudence, posture pédagogique",
    },
    {
        "id": "style_oral_tts",
        "label": "Style oral TTS",
        "rules": [21, 22, 23, 24, 25, 26, 27],
        "description": "Fusion syntaxique hypothétiques, guillemets de discours direct, "
                       "posture dialogale, punchlines isolées, contraintes cours à distance, "
                       "énumérations mécaniques, registre oral",
    },
]

# Seuils continuation loop content (alignés sur _generate_segment_text mode API)
_CONTENT_FALLBACK_MIN_WORDS = 3200
_CONTENT_FALLBACK_TARGET_WORDS = 3600
_CONTENT_FALLBACK_MAX_WORDS = 4100
_CONTENT_MAX_CONTINUATIONS = 2


def _content_segment_word_budget() -> dict:
    """Budget segment Claude Code, dérivé du même calibrage que le mode API."""
    try:
        from services.content_generation_service import get_course_segment_generation_budget
        budget = get_course_segment_generation_budget()
        return {
            "min_words": int(budget["min_words"]),
            "target_words": int(budget["target_words"]),
            "max_words": int(budget["max_words"]),
            "day_budget": budget.get("day_budget") or {},
        }
    except Exception:
        logger.warning("Fallback budget segment content Claude Code", exc_info=True)
        return {
            "min_words": _CONTENT_FALLBACK_MIN_WORDS,
            "target_words": _CONTENT_FALLBACK_TARGET_WORDS,
            "max_words": _CONTENT_FALLBACK_MAX_WORDS,
            "day_budget": {},
        }


def _continue_content_until_volume(
    chunk_dir: str, job: dict, chunk: dict, model: str,
    log_path: str, current_text: str,
) -> str:
    """Si le segment est sous budget, lance 1-2 continuations CLI.

    Aligné sur la continuation loop du mode API
    (`_generate_segment_text`, content_generation_service.py).

    Sur 429 ou erreur de continuation : on garde le texte en l'état
    (pas de fail-fast, le mode API a la même politique)."""
    budget = _content_segment_word_budget()
    min_words = int(budget["min_words"])
    target_words = int(budget["target_words"])
    max_words = int(budget["max_words"])
    word_count = len(current_text.split())
    if word_count >= min_words:
        return current_text

    logger.info(
        f"📏 Chunk {chunk['id']} : {word_count} mots (<{min_words}) — "
        f"continuation(s) requise(s) pour viser {target_words}"
    )
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n📏 Volume insuffisant : {word_count} mots — lancement "
            f"continuation(s) (cible {target_words}, max prudent {max_words})\n"
        )

    text = current_text
    passe_name = _PASSE_DESCRIPTIONS[chunk["passe"]][0]

    for n in range(1, _CONTENT_MAX_CONTINUATIONS + 1):
        words = len(text.split())
        if words >= min_words:
            break

        cont_dir = os.path.join(chunk_dir, f"_cont_{n}")
        os.makedirs(cont_dir, exist_ok=True)

        task = f"""# Mission : CONTINUATION du segment de cours

Tu as écrit **{words} mots** sur une cible de **{target_words} mots** (minimum {min_words}, maximum prudent {max_words}). Tu dois continuer le cours là où tu t'es arrêté, avec :
- Le même ton oral et la même voix narrative
- Les mêmes règles TTS (cf. `rules.md` — règles #1 à #28)
- **Sans RÉPÉTER ce qui a déjà été dit**

**Volume cible pour cette continuation : environ {max(350, target_words - words)} mots supplémentaires, sans dépasser {max_words} mots au total si possible.**

CONSIGNE DE DÉVELOPPEMENT :
- 2 à 4 exemples fictifs supplémentaires dans des contextes variés
- 1 cas contraste explicite : ce qu'il NE FAUT PAS faire + pourquoi
- Nuances selon profil client (novice vs expert, pressé vs exploratoire)
- Mini-récap oral à la fin de chaque nouvelle section

Tu lis `input.md` qui contient les **6000 derniers caractères du texte déjà écrit**. NE RÉPÈTE PAS — enchaîne avec une transition naturelle ("Allons plus loin maintenant…", "On va creuser un autre angle…").

Contexte : Passe {chunk['passe']}/3 ({passe_name}) sur la sous-partie "{chunk['sub_part_name']}" du TP "{job['tp_name']}".

═══ CONSIGNE TECHNIQUE ═══
Écris dans `output.md` UNIQUEMENT le texte de continuation (pas de JSON, pas d'enrobage, pas de répétition de ce qui est dans input.md).
"""
        _write(cont_dir, "task.md", task)
        _write(cont_dir, "input.md", text[-6000:])
        _write(cont_dir, "rules.md", _load_rules_text())

        try:
            _run_subprocess(cont_dir, model, log_path=log_path, log_mode="a")
            with open(os.path.join(cont_dir, "output.md"), "r", encoding="utf-8") as f:
                additional = f.read().strip()
            # Tolérance fenced code
            if additional.startswith("```"):
                lines = additional.split("\n")
                if len(lines) > 2 and lines[-1].strip().startswith("```"):
                    additional = "\n".join(lines[1:-1]).strip()
            if not additional:
                logger.warning(f"⚠️ Continuation {n} : output vide — on garde {words} mots")
                break
            text = text.strip() + "\n\n" + additional
            new_words = len(text.split())
            logger.info(f"➕ Continuation {n} : +{new_words - words} mots → {new_words} total")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"➕ Continuation {n} : +{new_words - words} mots → {new_words} total\n")
        except _RateLimitError:
            logger.warning(
                f"⏳ Continuation {n} bloquée par rate limit — on garde "
                f"{len(text.split())} mots"
            )
            break
        except Exception as e:
            logger.warning(
                f"⚠️ Continuation {n} échouée : {str(e)[:200]} — on garde "
                f"{len(text.split())} mots"
            )
            break

    return text


def _build_content_chunk(chunk_dir: str, job: dict, chunk: dict, model: str) -> None:
    """Construit task.md + input.md + rules.md pour 1 segment.

    Réutilise le **vrai template du mode API** (`prompts-generaux-contenu-formation.md`,
    extrait via `_get_passe_prompts(from_scratch=True)`). Sans ça, Claude Code
    rendait systématiquement des segments trop courts — le prompt minimaliste
    précédent ne contenait pas le bloc de volume audio calibré.

    Pour passe 2/3, injecte les passes précédentes en DB pour la continuité
    narrative (mêmes consignes que le mode API)."""
    from services.content_generation_service import (
        _build_audio_day_plan_context,
        _build_course_position_context,
        _build_course_slot_generation_context,
        _build_generation_volume_context,
        _get_passe_prompts,
    )
    budget = _content_segment_word_budget()

    prev_text = ""
    if chunk["passe"] >= 2:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """SELECT passe, text_content FROM content_generation_segments
                   WHERE job_id = ? AND sub_part_index = ? AND status = 'completed'
                   AND passe < ? ORDER BY passe ASC""",
                (chunk["cg_job_id"], chunk["sub_idx"], chunk["passe"]),
            )
            prev_passes = cursor.fetchall()
        finally:
            conn.close()
        if prev_passes:
            prev_text = "\n\n".join(
                f"### Passe {p}\n\n{t}" for p, t in prev_passes
            )

    # Charge le vrai template par passe (mode from_scratch, identique à
    # _generate_segment_text dans content_generation_service.py).
    try:
        templates = _get_passe_prompts(from_scratch=True)
        template = templates[chunk["passe"] - 1]
    except Exception as e:
        logger.error(f"Impossible de charger les prompts par passe : {e} — fallback minimal")
        template = (
            "Génère un cours oral TTS-ready d'environ **{TARGET_WORDS} mots utiles** "
            "sur la sous-partie {NOM_DE_LA_SOUS_PARTIE} du TP "
            "{NOM_DU_TITRE_PROFESSIONNEL}. Module à couvrir :\n\n"
            "{CONTENU_DU_MODULE}"
        )

    # Remplacements identiques au mode API
    prompt = template
    prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", job["tp_name"])
    prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", chunk["sub_part_name"])
    prompt = prompt.replace("{TARGET_WORDS}", str(budget["target_words"]))
    prompt = prompt.replace(
        "{CONTENU_DU_MODULE}",
        (chunk["module_content"] or "")[:15000],
    )
    generation_context = {
        "folder_position": chunk.get("day_idx"),
        "nb_days": job.get("nb_days"),
        "total_hours": job.get("total_hours"),
        "folder_name": chunk.get("folder_name") or "",
        "sub_part_index": chunk.get("sub_idx"),
        "passe": chunk.get("passe"),
    }
    prompt += "\n\n" + _build_course_position_context(
        **generation_context,
    )
    prompt += "\n\n" + _build_course_slot_generation_context(
        generation_context,
        sub_part_name=chunk["sub_part_name"],
        module_content=chunk["module_content"],
        program_text=job.get("daily_programs") or "",
    )
    prompt += "\n\n" + _build_generation_volume_context(generation_context)
    prompt += "\n\n" + _build_audio_day_plan_context(generation_context)

    # Pour passe 2/3, ajouter le contexte des passes précédentes en fin de prompt
    if prev_text:
        passe_names = "/".join(
            _PASSE_DESCRIPTIONS[p][0] for p in range(1, chunk["passe"])
        )
        passe_courante = _PASSE_DESCRIPTIONS[chunk["passe"]][0]
        prompt += f"""

═══════════════════════════════════════════════════════════════════
PASSES PRÉCÉDENTES — DÉJÀ ÉCRITES, NE PAS RÉPÉTER
═══════════════════════════════════════════════════════════════════

{prev_text}

═══════════════════════════════════════════════════════════════════
CONSIGNE DE CONTINUITÉ
═══════════════════════════════════════════════════════════════════

Les passes ci-dessus ont déjà couvert ce module sous l'angle {passe_names}.
Maintenant écris la Passe {chunk['passe']} ({passe_courante}) en t'appuyant
sur ce qui a été dit, mais SANS RÉPÉTER. Enchaîne avec une transition
naturelle ("Allons plus loin maintenant…", "On va creuser un autre
angle…"). Ne répète pas les exemples ou définitions déjà donnés.
"""

    # Adaptation pour le subprocess CLI : Claude Code lit task.md puis écrit
    # output.md. On ajoute une consigne explicite à la fin pour éviter qu'il
    # ne réponde dans la conversation au lieu d'écrire le fichier.
    prompt += (
        "\n\n═══ CONSIGNE TECHNIQUE FINALE ═══\n"
        f"Écris ta réponse complète (texte oral TTS-ready, environ {budget['target_words']} mots utiles, "
        f"maximum prudent {budget['max_words']} mots) "
        "dans `output.md`. **Aucun autre fichier**, aucun autre format, "
        "aucune réponse dans le chat — uniquement le texte du cours dans "
        "`output.md`."
    )

    _write(chunk_dir, "task.md", prompt)
    # input.md gardé pour traçabilité même si redondant (le module_content
    # est déjà inclus dans task.md via le placeholder remplacé)
    _write(chunk_dir, "input.md", chunk.get("module_content", "") or "(vide)")
    _write(chunk_dir, "rules.md", _load_rules_text())


def _build_review_chunk(chunk_dir: str, job: dict, chunk: dict, model: str) -> None:
    """Construit task.md + input.md + rules.md pour 1 chunk de review.

    Multi-agents : si le chunk a un `rule_group`, le prompt focalise Claude
    sur ce sous-ensemble de règles uniquement. Le contenu détaillé des règles
    reste dans `rules.md` qui est lu par Claude — on ne paraphrase pas les
    règles dans task.md (Claude lit lui-même).
    """
    n_segs = len(chunk["segments"])
    rule_group = chunk.get("rule_group")
    review_kind = chunk.get("review_kind") or "compliance"
    review_label = chunk.get("review_label") or "Conformité"
    is_humanization = review_kind == "humanization"

    if rule_group:
        rules_list_str = ", ".join(f"#{r}" for r in rule_group["rules"])
        if is_humanization:
            scope_intro = (
                "Tu vérifies UNIQUEMENT les règles d'humanisation et de rythme. "
                "Une intro trop brusque, une ouverture annuelle absente, un "
                "début de journée mécanique, un bloc trop dense, une transition "
                "mécanique, une fin sèche ou l'absence de respiration "
                "pédagogique comptent comme des non-conformités."
            )
            out_of_scope = (
                "Ignore les règles de conformité stricte #1-#27 : elles seront "
                "traitées par la passe suivante."
            )
        else:
            scope_intro = (
                f"Tu vérifies UNIQUEMENT les **règles {rules_list_str}** "
                f"({rule_group['description']})."
            )
            out_of_scope = (
                "Si tu vois une violation hors de ton scope, ignore-la — un "
                "autre agent s'en occupe."
            )
        scope_block = f"""
═══════════════════════════════════════════════════════════════════
🎯 TON SCOPE EXCLUSIF : {rule_group['label']}
═══════════════════════════════════════════════════════════════════

{scope_intro}

**Important** : NE PROPOSE AUCUN PATCH sur les autres règles. Elles sont
vérifiées par d'autres agents ou par une passe suivante. {out_of_scope}

Lis le détail complet de chacune de tes règles dans `rules.md` (cherche
"RÈGLE #{rule_group['rules'][0]}" et les suivantes dans le fichier).
"""
        cap_per_segment = 10
    else:
        scope_block = (
            "\nTu vérifies la conformité aux **règles #1 à #28** "
            "détaillées dans `rules.md` (lis le fichier intégralement).\n"
        )
        cap_per_segment = 10
    replacement_constraint = (
        "- `replacement` peut ajouter une phrase orale, une micro-interaction "
        "ou un tag comme `[pause]` / `[calm]` si cela corrige vraiment le rythme, "
        "sans changer le fond pédagogique. Pour une violation #112, `replacement` "
        "doit remplacer l'ouverture trop pauvre par une vraie introduction de "
        "formation développée : utilité concrète, contexte métier, grandes "
        "compétences abordées, progression du parcours, encouragement et "
        "transition vers le premier sujet."
        if is_humanization
        else "- `replacement` corrige la violation sans changer le sens, sans ajouter/retirer de contenu."
    )
    patch_policy = (
        "Tu ne réécris pas les textes — tu proposes des patches ciblés qui "
        "rendent l'introduction, les respirations, les transitions et les fins "
        "plus naturelles quand les règles #101-#114 sont violées."
        if is_humanization
        else "Tu **ne réécris pas** les textes — tu proposes des **patches minimaux**"
    )

    task = f"""# Mission : Révision {review_label.lower()} — Journée {chunk['day_idx'] + 1}

**TP** : {job['tp_name']} · **Folder** : {chunk['folder_name']} · **Modèle** : {model}

Tu lis `input.md` qui contient les **{n_segs} segments** completed de cette journée (JSON array : segment_id, sub_idx, passe, text).
{scope_block}

Contexte positionnel :
- Journée {chunk['day_idx'] + 1}/{job.get('nb_days') or '?'} du parcours.
- Le segment avec `sub_idx = 0` et `passe = 1` est le début de cette journée.
- Si cette journée est la première du parcours, ce même segment est l'ouverture
  absolue de la formation : applique strictement la règle #112.
- Pour tous les débuts de journée, applique strictement la règle #113 : pas de
  démarrage mécanique du type "Bon, on va aborder une nouvelle partie".

{patch_policy} au format :

```json
{{
  "reviews": [
    {{
      "segment_id": 42,
      "patches": [
        {{
          "original": "phrase EXACTE à remplacer (copie verbatim, 3-40 mots)",
          "replacement": "phrase corrigée",
          "rule_violated": "#X",
          "reason": "explication brève (1 phrase)"
        }}
      ]
    }}
  ]
}}
```

Contraintes :
- **Max {cap_per_segment} patches par segment** (les pires violations dans ton scope).
- `original` doit être trouvable verbatim dans `text` du segment, et **non ambigu** (ne pas viser une phrase qui apparaît plusieurs fois dans le segment).
{replacement_constraint}
- Si un segment est conforme **dans ton scope**, renvoie `"patches": []` pour ce segment.
- **Tous les {n_segs} segments doivent figurer** dans le tableau `reviews` (même avec patches vides).

Écris dans `output.md` le **JSON brut** (pas d'enrobage markdown ```).
"""
    _write(chunk_dir, "task.md", task)
    _write(chunk_dir, "input.md", json.dumps(chunk["segments"], ensure_ascii=False, indent=2))
    _write(chunk_dir, "rules.md", _load_review_rules_text())


# ─── Importers chunk ──────────────────────────────────────────────────────────

def _import_content_chunk(job_id: int, chunk: dict, output: str, generated_via: str) -> dict:
    """output.md = texte oral brut d'1 segment. Save direct via _save_segment_db
    (qui écrit avec dirty=1, reviewed=0 — le segment sera audité ensuite et
    régénérera l'audio TTS)."""
    text = output.strip()
    # Tolérance : si Claude a quand même fenced le texte avec ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
    if not text:
        raise ValueError("output.md vide pour ce chunk content")

    word_count = len(text.split())
    budget = _content_segment_word_budget()
    if word_count < 1000:
        logger.warning(
            f"⚠️ Chunk content {chunk['id']} : seulement {word_count} mots "
            f"(cible ~{budget['target_words']}). Enregistré quand même mais qualité douteuse."
        )

    from services.content_generation_service import _save_segment_db
    _save_segment_db(
        chunk["cg_job_id"],
        chunk["sub_idx"],
        chunk["sub_part_name"],
        chunk["passe"],
        text,
    )
    return {
        "ok": True,
        "segment_words": word_count,
        "cg_job_id": chunk["cg_job_id"],
        "sub_idx": chunk["sub_idx"],
        "passe": chunk["passe"],
    }


def _import_review_chunk(job_id: int, chunk: dict, output: str, generated_via: str) -> dict:
    """Import des patches de review pour 1 journée — robuste aux changements
    d'ids segment.

    Le `_import_review` legacy matche par `segment_id` brut. Problème : à
    chaque `_save_segment_db` (mode API ou chunked), `INSERT OR REPLACE`
    DELETE+INSERT le segment, donc il prend un nouvel id auto-incrémenté.
    Si l'utilisateur a relancé `content` entre la production de la review et
    son import (cas observé en prod), les segment_ids du output.md
    correspondent à des segments qui n'existent plus en DB → tous les patches
    sont ignorés silencieusement.

    Stratégie robuste :
    1. Construire un mapping `chunk_segment_id → index dans chunk['segments']`
       depuis le chunk d'origine (qui a aussi sub_idx + passe pour chaque seg).
    2. Pour chaque review, retrouver `(sub_idx, passe)` via le mapping.
    3. Fallback positionnel si aucun chunk_segment_id ne matche (cas obsolescence
       totale) : la i-ème review = le i-ème segment du chunk, dans l'ordre
       (sub_idx ASC, passe ASC) qu'on a passé à Claude.
    4. Résoudre `(folder_id, sub_idx, passe)` → segment ACTUEL en DB
       en prenant le cg_job le plus récent si plusieurs existent pour ce folder.
    5. Appliquer les patches avec `count == 1` strict (idem legacy).
    """
    try:
        parsed = json.loads(_extract_json(output))
        reviews = parsed.get("reviews", [])
    except Exception as e:
        raise ValueError(f"JSON invalide dans output.md : {e}")

    chunk_segments = chunk.get("segments", []) or []
    folder_id = chunk["folder_id"]
    step_key = chunk.get("review_step_key") or "review"
    review_kind = chunk.get("review_kind") or (
        "humanization" if step_key == "humanization_review" else "compliance"
    )
    review_label = chunk.get("review_label") or (
        "Humanisation" if review_kind == "humanization" else "Conformité"
    )
    cfg = _review_step_config("humanization_review" if review_kind == "humanization" else "review")
    review_signature = cfg["signature"]
    from services.content_generation_service import _apply_review_budget_guard

    # Mapping {segment_id_dans_chunk → index dans chunk_segments}
    by_chunk_id = {
        s["segment_id"]: i for i, s in enumerate(chunk_segments)
    }

    # Détecter le besoin de fallback positionnel : si aucun segment_id du output
    # n'apparaît dans by_chunk_id, c'est que les ids sont obsolètes.
    output_ids = [r.get("segment_id") for r in reviews if r.get("segment_id") is not None]
    use_positional = bool(output_ids) and not any(sid in by_chunk_id for sid in output_ids)
    if use_positional:
        logger.warning(
            f"🔀 Review chunk {chunk['id']} : tous les segment_ids du output.md "
            f"sont absents du chunk actuel — content a probablement été relancé "
            f"entre la génération de la review et son import. Fallback : match "
            f"positionnel (i-ème review = i-ème segment du chunk dans l'ordre "
            f"sub_idx ASC, passe ASC)."
        )

    # Sécurité : valider que folder_id appartient bien à la plateforme du job
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"folder_id {folder_id} introuvable")
    folder_platform_id = row[0]

    cursor.execute("SELECT platform_id FROM formation_pipeline_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Job pipeline {job_id} introuvable")
    job_platform_id = row[0]

    if folder_platform_id != job_platform_id:
        conn.close()
        raise ValueError(
            f"folder {folder_id} (platform {folder_platform_id}) hors scope du "
            f"job pipeline (platform {job_platform_id})"
        )

    applied_total = 0
    rejected_total = 0
    failed_total = 0
    by_rule = {}  # règle → {proposed, applied, rejected}
    by_segment = []  # détail par segment audité, pour le rapport modal frontend

    for i, rev in enumerate(reviews):
        patches = rev.get("patches", []) or []

        # Résolution chunk_segment_id → index dans chunk_segments
        if use_positional:
            chunk_idx = i
        else:
            chunk_seg_id = rev.get("segment_id")
            chunk_idx = by_chunk_id.get(chunk_seg_id)
            if chunk_idx is None:
                logger.warning(
                    f"⚠️ Review chunk {chunk['id']} : segment_id={chunk_seg_id} "
                    f"absent du mapping — patch ignoré"
                )
                failed_total += 1
                continue

        if chunk_idx >= len(chunk_segments):
            failed_total += 1
            continue

        seg_info = chunk_segments[chunk_idx]
        sub_idx = seg_info["sub_idx"]
        passe = seg_info["passe"]

        # Résolution (folder_id, sub_idx, passe) → segment ACTUEL en DB.
        # Si plusieurs cg_jobs existent pour le folder (situation anormale mais
        # observée), prendre le cg_job le plus récent (max id) → segment le
        # plus à jour. Filtre status='completed' pour ignorer les segments
        # incomplets/erronés d'un run précédent.
        cursor.execute(
            """
            SELECT s.id, s.text_content
            FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            WHERE cj.folder_id = ? AND s.sub_part_index = ? AND s.passe = ?
            AND s.status = 'completed'
            ORDER BY cj.id DESC, s.id DESC
            LIMIT 1
            """,
            (folder_id, sub_idx, passe),
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(
                f"⚠️ Aucun segment completed en DB pour folder={folder_id} "
                f"sub_idx={sub_idx} passe={passe} — patch ignoré"
            )
            failed_total += 1
            continue
        actual_segment_id, text = row
        original_text = text or ""

        # Application des patches (logique inchangée du legacy) +
        # collecte du détail pour le rapport modal frontend
        seg_applied = 0
        seg_rejected = 0
        seg_applied_patches = []
        seg_patches_detail = []
        for p in patches[:10]:  # hard cap 10 patches / segment (éthiques + stylistiques)
            original = p.get("original")
            replacement = p.get("replacement")
            rule = str(p.get("rule_violated", "?"))[:10]
            reason = str(p.get("reason", ""))[:200]
            if not original or replacement is None:
                continue
            count = text.count(original)
            rule_stat = by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0})
            rule_stat["proposed"] += 1
            if count == 1:
                text = text.replace(original, replacement, 1)
                seg_applied += 1
                rule_stat["applied"] += 1
                seg_applied_patches.append({
                    "original": original,
                    "replacement": replacement,
                    "rule_violated": rule,
                    "reason": reason,
                })
                seg_patches_detail.append({
                    "rule": rule, "reason": reason,
                    "original": original[:200],
                    "replacement": replacement[:200],
                    "status": "applied",
                })
            else:
                seg_rejected += 1
                rule_stat["rejected"] += 1
                seg_patches_detail.append({
                    "rule": rule, "reason": reason,
                    "original": original[:200],
                    "replacement": replacement[:200],
                    "status": "rejected",
                    "reject_reason": (
                        "introuvable verbatim" if count == 0
                        else f"ambiguë ({count} occurrences)"
                    ),
                })
        if seg_applied > 0:
            guarded_text, guarded_applied, budget_rejected = _apply_review_budget_guard(
                original_text,
                text,
                seg_applied_patches,
                review_kind,
            )
            if budget_rejected:
                text = guarded_text
                words_before = budget_rejected[0].get("words_before")
                words_after = budget_rejected[0].get("words_after")
                max_words = budget_rejected[0].get("max_words")
                for p in budget_rejected:
                    rule = str(p.get("rule_violated") or "?")[:10]
                    rule_stat = by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0})
                    rule_stat["applied"] = max(0, int(rule_stat.get("applied") or 0) - 1)
                    rule_stat["rejected"] = int(rule_stat.get("rejected") or 0) + 1
                for detail in seg_patches_detail:
                    if detail.get("status") == "applied":
                        detail["status"] = "rejected"
                        detail["reject_reason"] = "budget_guard"
                        detail["words_before"] = words_before
                        detail["words_after"] = words_after
                        detail["max_words"] = max_words
                seg_rejected += len(budget_rejected)
                seg_applied = len(guarded_applied)
                logger.warning(
                    "CLAUDE_CODE_REVIEW_BUDGET_GUARD job_id=%s folder_id=%s segment_id=%s "
                    "review_kind=%s words_before=%s words_after=%s max_words=%s rejected=%s",
                    job_id,
                    folder_id,
                    actual_segment_id,
                    review_kind,
                    words_before,
                    words_after,
                    max_words,
                    len(budget_rejected),
                )
        applied_total += seg_applied
        rejected_total += seg_rejected

        by_segment.append({
            "sub_idx": sub_idx,
            "passe": passe,
            "segment_id_actual": actual_segment_id,
            "patches_applied": seg_applied,
            "patches_rejected": seg_rejected,
            "patches_detail": seg_patches_detail,
        })

        # Compliance multi-agents : ne PAS marquer reviewed=1 ici. Si on le
        # faisait, `_list_review_chunks` ferait skipper les chunks suivants
        # (autres groupes de règles). Le marquage final est fait par
        # `_finalize_review_step`. Pour l'humanisation, il n'y a qu'une salve :
        # on peut marquer le segment humanized tout de suite, comme l'API.
        if seg_applied > 0:
            if review_kind == "humanization":
                cursor.execute(
                    """
                    UPDATE content_generation_segments
                    SET text_content = ?, word_count = ?, dirty = 1,
                        humanized = 1, humanization_error = NULL, humanization_signature = ?,
                        reviewed = 0, review_error = NULL, review_signature = NULL
                    WHERE id = ?
                    """,
                    (text, len(text.split()), review_signature, actual_segment_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE content_generation_segments
                    SET text_content = ?, word_count = ?, dirty = 1,
                        review_error = NULL
                    WHERE id = ?
                    """,
                    (text, len(text.split()), actual_segment_id),
                )
        else:
            if review_kind == "humanization":
                cursor.execute(
                    """
                    UPDATE content_generation_segments
                    SET humanized = 1, humanization_error = NULL, humanization_signature = ?
                    WHERE id = ?
                    """,
                    (review_signature, actual_segment_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE content_generation_segments
                    SET review_error = NULL
                    WHERE id = ?
                    """,
                    (actual_segment_id,),
                )

    conn.commit()
    conn.close()

    # Écrit un rapport détaillé dans le chunk_dir, lu par le frontend via
    # GET /api/formation/<job>/folders/<folder>/review-report (route ajoutée
    # dans formation_routes.py). Survit dans review_queue/_done/ après
    # archivage de la mission.
    chunk_dir_for_report = os.path.join(mission_dir(job_id, step_key), chunk["id"])
    if os.path.isdir(chunk_dir_for_report):
        report = {
            "folder_id": folder_id,
            "folder_name": chunk.get("folder_name"),
            "imported_at": datetime.utcnow().isoformat() + "Z",
            "generated_via": generated_via,
            "review_kind": review_kind,
            "review_label": review_label,
            "review_signature": review_signature,
            "via_positional_fallback": use_positional,
            "summary": {
                "segments_reviewed": len(reviews),
                "patches_proposed": sum(len(r.get("patches", [])) for r in reviews),
                "patches_applied": applied_total,
                "patches_rejected": rejected_total,
                "segments_failed": failed_total,
            },
            "by_rule": by_rule,
            "by_segment": by_segment,
        }
        try:
            with open(os.path.join(chunk_dir_for_report, "review_report.json"),
                      "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"📋 Rapport {review_label} écrit : {chunk_dir_for_report}/review_report.json")
        except Exception as e:
            logger.warning(f"⚠️ Échec écriture review_report.json : {e}")

    logger.info(
        f"✅ {review_label} chunk {chunk['id']} importé : {applied_total} appliqués, "
        f"{rejected_total} rejetés, {failed_total} échoués sur {len(reviews)} reviews "
        f"(positional={use_positional})"
    )

    return {
        "ok": True,
        "segments_reviewed": len(reviews),
        "patches_applied": applied_total,
        "patches_rejected": rejected_total,
        "segments_failed": failed_total,
        "generated_via": generated_via,
        "review_kind": review_kind,
        "review_label": review_label,
        "review_signature": review_signature,
        "via_positional_fallback": use_positional,
    }


def _persist_review_reports_from_active_files(
    job_id: int,
    generated_via: str,
    step_key: str = "review",
) -> int:
    """Aggregate Claude Code chunk reports into durable DB reports.

    The chunk JSON files are useful for local debugging, but the UI must not
    depend on them after a deploy/restart. This persists one full report per
    folder before the local review step is archived.
    """
    base_dir = mission_dir(job_id, step_key)
    if not os.path.isdir(base_dir):
        return 0

    reports_by_folder = {}
    for entry in sorted(os.listdir(base_dir)):
        report_path = os.path.join(base_dir, entry, "review_report.json")
        if not os.path.exists(report_path):
            continue
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception as exc:
            logger.warning(f"⚠️ Rapport review illisible {report_path}: {exc}")
            continue
        folder_id = report.get("folder_id")
        if folder_id is None:
            continue
        reports_by_folder.setdefault(int(folder_id), []).append((entry, report))

    if not reports_by_folder:
        return 0

    from services.formation_observability_service import persist_review_report

    persisted = 0
    for folder_id, sub_reports in reports_by_folder.items():
        agg_summary = {
            "segments_reviewed": 0,
            "patches_proposed": 0,
            "patches_applied": 0,
            "patches_rejected": 0,
            "segments_failed": 0,
        }
        agg_by_rule = {}
        agg_by_segment = {}
        latest_imported = None
        any_positional = False
        agents_used = []
        folder_name = None
        review_kind = None
        review_label = None
        review_signature = None

        for chunk_id, report in sub_reports:
            review_kind = review_kind or report.get("review_kind")
            review_label = review_label or report.get("review_label")
            review_signature = review_signature or report.get("review_signature")
            summary = report.get("summary") or {}
            agg_summary["segments_reviewed"] = max(
                agg_summary["segments_reviewed"],
                int(summary.get("segments_reviewed") or 0),
            )
            for key in ("patches_proposed", "patches_applied", "patches_rejected", "segments_failed"):
                agg_summary[key] += int(summary.get(key) or 0)

            for rule, stats in (report.get("by_rule") or {}).items():
                agg = agg_by_rule.setdefault(
                    rule,
                    {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0},
                )
                for stat_key, value in (stats or {}).items():
                    agg[stat_key] = agg.get(stat_key, 0) + int(value or 0)

            for segment in (report.get("by_segment") or []):
                key = (segment.get("sub_idx"), segment.get("passe"))
                if key not in agg_by_segment:
                    agg_by_segment[key] = {
                        "sub_idx": segment.get("sub_idx"),
                        "passe": segment.get("passe"),
                        "segment_id_actual": segment.get("segment_id_actual"),
                        "patches_applied": 0,
                        "patches_rejected": 0,
                        "patches_detail": [],
                    }
                agg_by_segment[key]["patches_applied"] += int(segment.get("patches_applied") or 0)
                agg_by_segment[key]["patches_rejected"] += int(segment.get("patches_rejected") or 0)
                for detail in segment.get("patches_detail") or []:
                    detail_copy = dict(detail)
                    detail_copy["agent_group"] = chunk_id
                    agg_by_segment[key]["patches_detail"].append(detail_copy)

            imported_at = report.get("imported_at")
            if imported_at and (latest_imported is None or imported_at > latest_imported):
                latest_imported = imported_at
            if report.get("via_positional_fallback"):
                any_positional = True
            if report.get("folder_name") and not folder_name:
                folder_name = report.get("folder_name")
            agents_used.append(chunk_id)

        review_kind = review_kind or (
            "humanization" if step_key == "humanization_review" else "compliance"
        )
        review_label = review_label or (
            "Humanisation" if review_kind == "humanization" else "Conformité"
        )
        aggregate = {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "imported_at": latest_imported,
            "generated_via": generated_via,
            "review_kind": review_kind,
            "review_label": review_label,
            "review_signature": review_signature,
            "via_positional_fallback": any_positional,
            "n_agents": len(sub_reports),
            "agents_used": agents_used,
            "summary": agg_summary,
            "by_rule": agg_by_rule,
            "by_segment": sorted(
                agg_by_segment.values(),
                key=lambda x: (x.get("sub_idx") or 0, x.get("passe") or 0),
            ),
        }
        persist_review_report(
            job_id,
            folder_id,
            aggregate,
            source=(
                "claude_code_aggregate"
                if review_kind == "compliance"
                else f"{review_kind}_claude_code_aggregate"
            ),
            generated_via=generated_via,
        )
        persisted += 1

    logger.info(
        "PIPELINE_REVIEW_REPORTS_AGGREGATED job_id=%s step=%s persisted=%s folders=%s",
        job_id,
        step_key,
        persisted,
        sorted(reports_by_folder),
    )
    return persisted


# ─── Orchestrateur chunked ────────────────────────────────────────────────────

def _execute_chunked(job_id: int, step_key: str, model: str) -> dict:
    """Boucle séquentielle de N subprocess `claude`, 1 par chunk. Continue sur
    erreur d'un chunk (log dans progress.errors). Statut DB mis à jour à la fin."""
    job = _get_job_row(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    target = mission_dir(job_id, step_key)
    os.makedirs(target, exist_ok=True)

    meta = {
        "job_id": job_id,
        "step_key": step_key,
        "step_label": STEP_LABELS[step_key],
        "model": model,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "tp_name": job.get("tp_name"),
        "rncp_code": job.get("rncp_code"),
        "chunked": True,
    }
    with open(os.path.join(target, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    listers = {
        "content": _list_content_chunks,
        "humanization_review": _list_humanization_chunks,
        "review": _list_review_chunks,
    }
    builders = {
        "content": _build_content_chunk,
        "humanization_review": _build_review_chunk,
        "review": _build_review_chunk,
    }
    importers = {
        "content": _import_content_chunk,
        "humanization_review": _import_review_chunk,
        "review": _import_review_chunk,
    }

    # Snapshot pre-review au plus tôt : si la review patche les segments avant
    # que _finalize_content_step ait pu snapshotter (ex: content terminé avec
    # erreurs résiduelles → finalize partiel → puis review), on perd la version
    # originale. On le fait ici en idempotent (n'écrase jamais un snapshot
    # existant) pour garantir l'invariant "Word original" toujours dispo.
    # Best-effort : un échec snapshot ne doit pas bloquer la review elle-même.
    if step_key in ("humanization_review", "review"):
        try:
            conn_pre = get_db_connection()
            cur_pre = conn_pre.cursor()
            cur_pre.execute(
                "SELECT id FROM cours_folders WHERE formation_job_id = ?",
                (job_id,),
            )
            folder_ids_pre = [r[0] for r in cur_pre.fetchall()]
            conn_pre.close()
            if folder_ids_pre:
                _snapshot_pre_review(folder_ids_pre)
        except Exception as e:
            logger.warning(f"⚠️ Snapshot pre-review job {job_id} échoué : {e} — on continue la review")

    chunks = listers[step_key](job)
    total = len(chunks)
    log_path = os.path.join(target, "execution.log")
    progress_path = os.path.join(target, "progress.json")

    if total == 0:
        _write_progress(progress_path, {
            "current": 0, "total": 0, "status": "done",
            "errors": [], "message": "Aucun chunk à traiter — déjà tout fait",
        })
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Mission {step_key} chunked\n# Aucun chunk à traiter (tout déjà completed)\n")
        # Pour content : si tout est completed ET aucune erreur ouverte, marquer le pipeline
        if step_key == "content":
            _finalize_content_step(job_id, model)
        return {"ok": True, "chunks_total": 0, "chunks_done": 0, "chunks_failed": 0, "errors": []}

    logger.info(f"🚀 Mode chunked {step_key} : {total} chunks à traiter (model={model})")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Mission {step_key} chunked — {total} chunks — {meta['exported_at']}\n")

    # Configuration anti-rate-limit Anthropic (429). Le bootstrap Claude Code
    # à lui seul consomme ~47k tokens d'input par invocation, donc 2 chunks
    # consécutifs dépassent toujours le quota Haiku 50k/min. Le sleep entre
    # chunks aère ce quota ; le retry exponentiel rattrape les 429 résiduels.
    inter_chunk_sleep = int(os.getenv("CC_CHUNK_DELAY_SEC", "75"))
    max_retries_429 = int(os.getenv("CC_MAX_429_RETRIES", "2"))

    progress = {
        "current": 0, "total": total, "status": "running",
        "errors": [], "current_chunk": None,
    }
    _write_progress(progress_path, progress)

    chunks_done = 0
    for i, chunk in enumerate(chunks):
        progress["current"] = i + 1
        progress["current_chunk"] = chunk["id"]
        progress["status"] = "running"
        _write_progress(progress_path, progress)

        chunk_dir = os.path.join(target, chunk["id"])
        os.makedirs(chunk_dir, exist_ok=True)

        # ── Réutilisation gratuite : si output.md existe déjà valide d'une
        # exécution précédente (cas typique : la run précédente a fait son
        # boulot mais a été tuée par watchmedo / coupée par 429 sur l'import,
        # etc.), on l'importe direct sans re-payer Claude Code. Idempotent.
        out_existing = os.path.join(chunk_dir, "output.md")
        ran_subprocess = False  # pour skipper le sleep si on n'a pas vraiment relancé
        if os.path.exists(out_existing) and os.path.getsize(out_existing) >= 50:
            try:
                with open(out_existing, "r", encoding="utf-8") as f:
                    cached_output = f.read()
                importers[step_key](job_id, chunk, cached_output, f"claude_code_{model}")
                chunks_done += 1
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(
                        f"\n♻️ Chunk {i+1}/{total} OK (réutilise output.md existant, "
                        f"{os.path.getsize(out_existing)} bytes) : {chunk['id']}\n"
                    )
                logger.info(
                    f"♻️ Réutilisation output.md existant pour {chunk['id']} — "
                    f"import direct sans re-payer Claude Code"
                )
                # Skip subprocess + sleep : on passe au chunk suivant
                continue
            except Exception as e:
                logger.warning(
                    f"⚠️ Réutilisation output.md échouée pour {chunk['id']} : "
                    f"{str(e)[:150]} — relance subprocess normalement"
                )
                # On laisse tomber dans la boucle normale ci-dessous

        # Boucle de retry sur 429. Tentatives = 1 initiale + max_retries_429.
        # Backoff : 90s, 180s. Toute autre exception sort de la boucle direct.
        success = False
        last_error = None
        for attempt in range(max_retries_429 + 1):
            try:
                builders[step_key](chunk_dir, job, chunk, model)
                _run_subprocess(chunk_dir, model, log_path=log_path, log_mode="a")
                with open(os.path.join(chunk_dir, "output.md"), "r", encoding="utf-8") as f:
                    output = f.read()
                # Continuation loop pour content : si le segment est sous
                # budget, lance 1-2 appels CLI supplémentaires.
                # (aligné sur _generate_segment_text mode API).
                if step_key == "content":
                    output = _continue_content_until_volume(
                        chunk_dir, job, chunk, model, log_path, output
                    )
                    # Réécrit output.md consolidé (pour debug + traçabilité)
                    with open(os.path.join(chunk_dir, "output.md"), "w", encoding="utf-8") as f:
                        f.write(output)
                importers[step_key](job_id, chunk, output, f"claude_code_{model}")
                success = True
                break
            except _RateLimitError as e:
                last_error = str(e)[:300]
                if attempt >= max_retries_429:
                    break  # plus de retry, on log l'échec
                wait = 90 * (attempt + 1)  # 90s, 180s
                logger.warning(
                    f"⏳ Rate limit 429 sur {chunk['id']} (tentative {attempt+1}/"
                    f"{max_retries_429+1}). Attente {wait}s avant retry."
                )
                progress["status"] = "rate_limited"
                progress["sleep_until"] = (
                    datetime.utcnow() + timedelta(seconds=wait)
                ).isoformat() + "Z"
                _write_progress(progress_path, progress)
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"\n⏳ Rate limit 429 — attente {wait}s avant retry {attempt+1}/{max_retries_429}\n")
                time.sleep(wait)
                progress["status"] = "running"
                progress["sleep_until"] = None
                _write_progress(progress_path, progress)
            except Exception as e:
                last_error = str(e)[:300]
                break  # erreur autre que 429 → pas de retry, on passe au suivant

        if success:
            chunks_done += 1
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n✅ Chunk {i+1}/{total} OK : {chunk['id']}\n")
        else:
            logger.error(f"❌ Chunk {chunk['id']} échoué définitivement : {last_error}")
            progress["errors"].append({"chunk": chunk["id"], "error": last_error})
            _write_progress(progress_path, progress)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n❌ Chunk {i+1}/{total} ÉCHEC : {chunk['id']} — {last_error}\n")

        # Sleep anti-rate-limit entre chunks (sauf après le dernier).
        # Sous eventlet+monkey_patch, time.sleep yield aux autres greenlets.
        if i < len(chunks) - 1 and inter_chunk_sleep > 0:
            logger.info(f"⏸ Sleep {inter_chunk_sleep}s avant chunk suivant (anti-rate-limit)")
            progress["status"] = "throttling"
            progress["sleep_until"] = (
                datetime.utcnow() + timedelta(seconds=inter_chunk_sleep)
            ).isoformat() + "Z"
            _write_progress(progress_path, progress)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n⏸ Pause {inter_chunk_sleep}s entre chunks (CC_CHUNK_DELAY_SEC)\n")
            time.sleep(inter_chunk_sleep)
            progress["status"] = "running"
            progress["sleep_until"] = None
            _write_progress(progress_path, progress)

    progress["status"] = "done" if not progress["errors"] else "done_with_errors"
    progress["current_chunk"] = None
    _write_progress(progress_path, progress)

    if step_key == "content":
        # Finalize TOUJOURS, même avec erreurs résiduelles : assemble + upload
        # les journées dont tous les segments sont OK, snapshot pre-review pour
        # celles-là. Le finalize est idempotent (skip cg_jobs déjà completed) et
        # n'archive le step_content que si 100% des assemble_and_upload réussissent
        # (donc en cas d'erreur résiduelle, le dossier reste pour debug). Sans ce
        # finalize, les DOCX ne sont jamais produits et l'UI affiche "0/N journées
        # terminées" même quand 95% du contenu est OK.
        _finalize_content_step(job_id, model)

    if step_key == "humanization_review":
        try:
            persisted_reports = _persist_review_reports_from_active_files(
                job_id,
                f"claude_code_{model}",
                step_key="humanization_review",
            )
            if chunks_done > 0 and persisted_reports == 0:
                logger.warning(
                    "⚠️ Aucun rapport humanisation agrégé persisté en DB "
                    "job=%s chunks_done=%s",
                    job_id,
                    chunks_done,
                )
        except Exception as exc:
            logger.warning(
                "⚠️ Agrégation durable des rapports humanisation échouée job=%s : %s",
                job_id,
                exc,
            )
        if progress["errors"]:
            logger.warning(
                "⚠️ Humanisation non finalisée job=%s : %s chunk(s) en erreur",
                job_id,
                len(progress["errors"]),
            )
        else:
            _finalize_humanization_review_step(job_id)

    if step_key == "review":
        try:
            persisted_reports = _persist_review_reports_from_active_files(
                job_id,
                f"claude_code_{model}",
                step_key="review",
            )
            if chunks_done > 0 and persisted_reports == 0:
                logger.warning(
                    "⚠️ Aucun rapport review agrégé persisté en DB "
                    "job=%s chunks_done=%s",
                    job_id,
                    chunks_done,
                )
        except Exception as exc:
            logger.warning(
                "⚠️ Agrégation durable des rapports review échouée job=%s : %s",
                job_id,
                exc,
            )
        # Marquer reviewed=1 seulement quand tous les chunks ont terminé.
        # Sinon la prochaine exécution reprend les chunks manquants et évite
        # de produire un Word 2 présenté comme conforme alors qu'une salve a
        # échoué.
        if progress["errors"]:
            logger.warning(
                "⚠️ Review conformité non finalisée job=%s : %s chunk(s) en erreur",
                job_id,
                len(progress["errors"]),
            )
        else:
            _finalize_review_step(job_id)

    return {
        "ok": True,
        "chunks_total": total,
        "chunks_done": chunks_done,
        "chunks_failed": len(progress["errors"]),
        "errors": progress["errors"][:10],
    }


def _finalize_humanization_review_step(job_id: int) -> None:
    """Marque la passe humanisation comme à jour sur les segments restants.

    Les segments patchés sont déjà marqués dans `_import_review_chunk`.
    Cette finalisation couvre les segments conformes sans patch, avec la même
    signature que `run_humanization_review` côté API.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    from services.content_generation_service import (
        _current_humanization_review_signature,
        _ensure_review_state_columns,
    )
    _ensure_review_state_columns()
    review_signature = _current_humanization_review_signature()
    cursor.execute(
        """
        UPDATE content_generation_segments
        SET humanized = 1, humanization_error = NULL, humanization_signature = ?
        WHERE id IN (
            SELECT s.id FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            JOIN cours_folders f ON f.id = cj.folder_id
            WHERE f.formation_job_id = ? AND s.status = 'completed'
            AND (
                COALESCE(s.humanized, 0) = 0
                OR s.humanization_signature IS NULL
                OR s.humanization_signature != ?
            )
        )
        """,
        (review_signature, job_id, review_signature),
    )
    n = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(
        f"📋 Finalize humanisation : {n} segments marqués humanized=1 (job {job_id})"
    )

    _archive_mission(job_id, "humanization_review")
    logger.info(f"📦 step_humanization_review archivé vers _done/ (job {job_id})")


def _finalize_review_step(job_id: int) -> None:
    """Multi-agents review : marque reviewed=1 sur tous les segments
    completed du job pipeline (peu importe l'agent qui les a touchés).
    Appelé une fois après la boucle de chunks (4 agents × N journées).

    Archive ensuite le dossier `step_review/` vers `_done/` pour que le
    bandeau "mission en attente d'import" disparaisse de l'UI.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    from services.content_generation_service import _current_compliance_review_signature
    review_signature = _current_compliance_review_signature()
    cursor.execute(
        """
        UPDATE content_generation_segments
        SET reviewed = 1, review_error = NULL, review_signature = ?
        WHERE id IN (
            SELECT s.id FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            JOIN cours_folders f ON f.id = cj.folder_id
            WHERE f.formation_job_id = ? AND s.status = 'completed'
            AND (
                COALESCE(s.reviewed, 0) = 0
                OR s.review_signature IS NULL
                OR s.review_signature != ?
            )
        )
        """,
        (review_signature, job_id, review_signature),
    )
    n = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"📋 Finalize review : {n} segments marqués reviewed=1 (job {job_id})")

    # Archive le dossier step_review/ vers _done/ : libère le bandeau d'alerte
    # côté UI. Les review_report.json restent accessibles via la route
    # /review-report (qui regarde dans _done/ en fallback).
    _archive_mission(job_id, "review")
    logger.info(f"📦 step_review archivé vers _done/ (job {job_id})")


def _ensure_pre_review_column() -> None:
    """Migration idempotente : ajoute la colonne `text_content_pre_review`
    à `content_generation_segments` si elle n'existe pas. Sert à conserver
    un snapshot du texte AVANT la révision (pour le bouton 'Word original')."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE content_generation_segments "
            "ADD COLUMN text_content_pre_review TEXT"
        )
        conn.commit()
        logger.info("📋 Migration : colonne text_content_pre_review ajoutée")
    except Exception:
        # Déjà existe — silent ignore
        pass
    finally:
        conn.close()


def _snapshot_pre_review(folder_ids: list) -> int:
    """Pour les segments completed des cg_jobs des folders donnés, copie
    `text_content` dans `text_content_pre_review` SI cette colonne est NULL
    (idempotent — on n'écrase pas un snapshot existant).

    Retourne le nombre de segments snapshotés."""
    if not folder_ids:
        return 0
    _ensure_pre_review_column()
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(folder_ids))
    cursor.execute(
        f"""
        UPDATE content_generation_segments
        SET text_content_pre_review = text_content
        WHERE id IN (
            SELECT s.id FROM content_generation_segments s
            JOIN content_generation_jobs cj ON cj.id = s.job_id
            WHERE cj.folder_id IN ({placeholders}) AND s.status = 'completed'
            AND s.text_content_pre_review IS NULL
        )
        """,
        tuple(folder_ids),
    )
    n = cursor.rowcount
    conn.commit()
    conn.close()
    if n > 0:
        logger.info(f"📸 Snapshot pre-review : {n} segments copiés en text_content_pre_review")
    return n


def _finalize_content_step(job_id: int, model: str) -> None:
    """Finalize équivalent à ce que fait `run_content_generation` à la fin
    en mode API :
      1. Pour chaque journée, assemble les segments + upload Azure (= DOCX
         téléchargeable via le bouton Word de l'UI).
      2. Marque chaque content_generation_job en status='completed'.
      3. Snapshot pre-review : copie text_content → text_content_pre_review
         (sera utilisé par le bouton 'Word original' avant la révision).
      4. Passe le formation_pipeline_jobs en status='tts_launched'.
      5. Archive le dossier review_queue/job_X/step_content/ vers _done/
         (libère le bandeau "mission en attente d'import").

    Idempotent : skippe les cg_jobs déjà completed. N'archive que si TOUS
    les assemble_and_upload ont réussi.
    """
    from services.content_generation_service import _assemble_and_upload, _update_job_db

    job = _get_job_row(job_id)
    if not job:
        logger.warning(f"⚠️ _finalize_content_step : job {job_id} introuvable")
        return

    platform_id = job["platform_id"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.id, cj.id, cj.status FROM cours_folders f
           JOIN content_generation_jobs cj ON cj.folder_id = f.id
           WHERE f.formation_job_id = ? ORDER BY f.position ASC""",
        (job_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    # Snapshot pre-review immédiat — avant que la révision (qui peut suivre)
    # ne touche au text_content. Idempotent.
    _snapshot_pre_review([fid for fid, _, _ in rows])

    all_finalize_ok = True
    for folder_id, cg_job_id, cg_status in rows:
        if cg_status == "completed":
            logger.info(f"ℹ️ cg_job {cg_job_id} déjà completed — skip finalize")
            continue
        try:
            final_words, filename = _assemble_and_upload(folder_id, platform_id, cg_job_id)
            _update_job_db(cg_job_id, status="completed", total_words=final_words)
            logger.info(
                f"✅ Finalize cg_job {cg_job_id} : {final_words} mots assemblés, "
                f"document {filename} uploadé sur Azure"
            )
        except Exception as e:
            logger.error(f"❌ Finalize cg_job {cg_job_id} échoué : {e}")
            all_finalize_ok = False

    # Passe le pipeline en tts_launched (texte prêt → bouton TTS débloqué)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE formation_pipeline_jobs SET status = 'tts_launched', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    conn.close()
    logger.info(f"📋 Job pipeline {job_id} → status='tts_launched' (content chunked finalize)")

    # Archive le dossier mission UNIQUEMENT si tout a finalisé sans erreur,
    # sinon on garde les fichiers pour debug et on laisse le bandeau alerter.
    if all_finalize_ok:
        _archive_mission(job_id, "content")
        logger.info(f"📦 step_content archivé vers _done/ (job {job_id})")
    else:
        logger.warning(
            f"⚠️ step_content non archivé : au moins 1 assemble_and_upload a échoué "
            f"(job {job_id}). Le dossier reste dans review_queue/ pour debug."
        )


# ─── Étape 6.5 — Sécurité volume ──────────────────────────────────────────────
#
# Audit par-journée du total_words parlé puis enrichissement à la demande des
# segments les plus courts. Sécurité supplémentaire au floor par-segment de
# `_continue_content_until_volume` :
#   - L'étape 6 garantit qu'aucun segment n'est sous-développé.
#   - L'étape 6.5 garantit qu'aucune journée n'est sous le budget calculé
#     depuis les cours internes, hors Q&A/pauses.
#
# Pattern : append-only. Le texte original n'est jamais réécrit, on concatène
# simplement le nouveau contenu. Le snapshot text_content_pre_review (pris au
# finalize content) reste valide : il représente toujours la version brute
# pré-révision, et le bouton "Word" continue de l'utiliser.

_LEGACY_TARGET_WORDS_PER_DAY = 90000
_VOLUME_SAFETY_TOP_N = 5
_VOLUME_SAFETY_MIN_ADDITION = 1500


def _volume_safety_addition_words(segment_data: dict) -> int:
    """Addition visée sans dépasser brutalement le budget journalier."""
    try:
        deficit = int(segment_data.get("deficit_remaining") or 0)
    except Exception:
        deficit = 0
    try:
        candidates = max(1, int(segment_data.get("candidates_count") or 1))
    except Exception:
        candidates = 1
    if deficit > 0:
        return max(250, min(_VOLUME_SAFETY_MIN_ADDITION, int(deficit / candidates) + 150))
    return _VOLUME_SAFETY_MIN_ADDITION


def _course_day_budget_for_volume() -> dict:
    try:
        from services.content_generation_service import get_course_day_word_budget
        budget = get_course_day_word_budget()
        return {
            "target_words": int(budget["target_words"]),
            "min_words": int(budget["min_words"]),
            "max_words": int(budget["max_words"]),
            "words_per_minute": budget.get("words_per_minute"),
            "course_seconds": budget.get("course_seconds"),
            "speakable_seconds": budget.get("speakable_seconds"),
            "final_silence_sec": budget.get("final_silence_sec"),
        }
    except Exception:
        logger.warning("Fallback budget journée volume safety", exc_info=True)
        return {
            "target_words": _LEGACY_TARGET_WORDS_PER_DAY,
            "min_words": int(_LEGACY_TARGET_WORDS_PER_DAY * 0.94),
            "max_words": int(_LEGACY_TARGET_WORDS_PER_DAY * 1.02),
            "words_per_minute": None,
            "course_seconds": None,
            "speakable_seconds": None,
            "final_silence_sec": None,
        }


def compute_volume_audit(job_id: int) -> dict:
    """Calcule total_words par folder + déficit + N segments les plus courts.

    Retourne un dict avec target dynamique et folders=[{folder_id,
    folder_name, day_number, total_words, deficit, overflow,
    segments_count, shortest_segments[]}].
    """
    budget = _course_day_budget_for_volume()
    job = _get_job_row(job_id)
    if not job:
        return {
            "target": budget["target_words"],
            "min_target": budget["min_words"],
            "max_target": budget["max_words"],
            "budget": budget,
            "folders": [],
        }

    try:
        from services.formation_pipeline_service import get_expected_course_folders
        folder_state = get_expected_course_folders(job_id)
        canonical_ids = folder_state.get("folder_ids") or []
    except Exception:
        logger.warning("Volume audit canonical folders failed for job %s", job_id, exc_info=True)
        canonical_ids = []

    conn = get_db_connection()
    cursor = conn.cursor()
    if canonical_ids:
        placeholders = ",".join("?" * len(canonical_ids))
        cursor.execute(
            f"""SELECT id, name, position FROM cours_folders
               WHERE id IN ({placeholders}) ORDER BY position ASC""",
            tuple(canonical_ids),
        )
        folders = cursor.fetchall()
    else:
        folders = []

    out = []
    for fid, fname, pos in folders:
        cursor.execute(
            """SELECT s.id, s.sub_part_index, s.sub_part_name, s.passe,
                      COALESCE(s.text_content, '') AS text_content,
                      COALESCE(s.word_count, 0) AS wc
               FROM content_generation_segments s
               JOIN content_generation_jobs cj ON cj.id = s.job_id
               WHERE cj.folder_id = ? AND s.status = 'completed'
               ORDER BY s.sub_part_index ASC, s.passe ASC""",
            (fid,),
        )
        segs = cursor.fetchall()
        if not segs:
            continue
        try:
            from services.content_generation_service import count_tts_spoken_words
        except Exception:
            count_tts_spoken_words = lambda text: len((text or "").split())

        normalized_segments = []
        total = 0
        raw_total = 0
        for s in segs:
            spoken_wc = count_tts_spoken_words(s[4] or "")
            raw_wc = int(s[5] or len((s[4] or "").split()))
            total += spoken_wc
            raw_total += raw_wc
            normalized_segments.append({
                "segment_id": s[0],
                "sub_idx": s[1],
                "sub_part_name": s[2],
                "passe": s[3],
                "word_count": int(spoken_wc),
                "raw_word_count": int(raw_wc),
            })
        normalized_segments.sort(key=lambda s: s["word_count"])
        deficit = max(0, int(budget["min_words"]) - total)
        overflow = max(0, total - int(budget["max_words"]))
        out.append({
            "folder_id": fid,
            "folder_name": fname,
            "day_number": (pos or 0) + 1,
            "total_words": total,
            "raw_words": raw_total,
            "deficit": deficit,
            "overflow": overflow,
            "target_words": budget["target_words"],
            "min_words": budget["min_words"],
            "max_words": budget["max_words"],
            "segments_count": len(segs),
            "shortest_segments": normalized_segments[:_VOLUME_SAFETY_TOP_N],
        })
    conn.close()
    return {
        "target": budget["target_words"],
        "min_target": budget["min_words"],
        "max_target": budget["max_words"],
        "budget": budget,
        "folders": out,
    }


def _build_volume_safety_chunk(chunk_dir: str, job: dict, segment_data: dict, model: str) -> None:
    """Construit task.md + input.md + rules.md pour 1 enrichissement de segment."""
    sub_part_name = segment_data["sub_part_name"]
    passe = segment_data["passe"]
    word_count_now = segment_data["word_count"]
    passe_name = _PASSE_DESCRIPTIONS.get(passe, (f"Passe {passe}", ""))[0]
    budget = _course_day_budget_for_volume()
    addition_words = _volume_safety_addition_words(segment_data)

    task = f"""# Mission : ENRICHISSEMENT segment de cours (sécurité volume)

**TP** : {job['tp_name']}
**Sous-partie** : {sub_part_name}
**Passe** : {passe} ({passe_name})
**Volume actuel** : {word_count_now} mots

## Contexte

Cette journée est sous le budget audio minimal de **{budget['min_words']} mots parlés**
pour une cible de **{budget['target_words']} mots**.
Tu participes à une opération de sécurité volume : enrichir les segments les plus
courts avec **du contenu nouveau**, sans réécrire l'existant.

## Ce que tu dois faire

Tu lis `input.md` qui contient le **texte actuel complet** de ce segment (texte
oral TTS-ready, déjà validé en passe précédente).

Tu écris dans `output.md` UNIQUEMENT du **contenu additionnel** à concaténer en
fin du texte existant. Volume cible : environ **{addition_words} mots
supplémentaires**.

Le contenu additionnel DOIT :
- Reprendre le ton oral et la voix narrative du texte existant
- Respecter scrupuleusement les règles **#1 à #28** décrites dans `rules.md`
  (lis le fichier intégralement avant d'écrire)
- Enchaîner avec une transition naturelle ("Allons plus loin maintenant…",
  "Je voudrais te donner d'autres exemples…", "On va creuser un autre angle…")
- Rester dans le scope thématique de la sous-partie "{sub_part_name}" et de la
  passe {passe} ({passe_name})

Ce que ton contenu doit contenir (au choix selon ce qui manque dans input.md) :
- 2 à 4 exemples fictifs supplémentaires dans des contextes variés (PME / particulier /
  B2B / situation sensible / situation urgente / dossier complexe…)
- 1 à 2 mises en situation détaillées : dialogue client / conseiller, étape par étape
- 1 cas contraste explicite : ce qu'il NE FAUT PAS faire + pourquoi
- Nuances selon profil client (novice vs expert, pressé vs exploratoire,
  en colère vs résigné)
- Mini-récap oral à la fin de chaque nouvelle section

## Ce que tu NE DOIS PAS faire

- NE PAS répéter ce qui est déjà dans `input.md` (lis-le attentivement avant)
- NE PAS reformuler ou réécrire des passages existants
- NE PAS inclure le texte de `input.md` dans `output.md` — uniquement ton ajout
- NE PAS écrire de balises markdown (titres, listes), de JSON, de fenced code —
  uniquement du texte oral brut destiné au TTS
- NE PAS commencer par "Maintenant je vais te parler de…" si ça ne s'enchaîne
  pas naturellement avec la dernière phrase de `input.md`

## Format de sortie

Écris dans `output.md` le texte oral additionnel **brut** (pas de fenced code
block ```, pas de JSON, pas d'enrobage). Environ {addition_words} mots,
maximum 2500 mots.
"""
    _write(chunk_dir, "task.md", task)
    _write(chunk_dir, "input.md", segment_data.get("text_content", "") or "")
    _write(chunk_dir, "rules.md", _load_rules_text())


_VOLUME_SAFETY_MAX_PASSES = 5  # Boucle anti-déficit bornée sur la cible audio dynamique.


def _build_volume_safety_prompt_api(job: dict, segment: dict) -> str:
    """Construit le prompt complet (task + input + rules) pour l'enrichissement
    en mode API direct. Pas de fichiers, tout dans un seul message Claude."""
    sub_part_name = segment["sub_part_name"]
    passe = segment["passe"]
    word_count_now = segment["word_count"]
    passe_name = _PASSE_DESCRIPTIONS.get(passe, (f"Passe {passe}", ""))[0]
    text_content = segment.get("text_content", "") or ""
    rules = _load_rules_text()
    budget = _course_day_budget_for_volume()
    addition_words = _volume_safety_addition_words(segment)

    return f"""# Mission : ENRICHISSEMENT segment de cours (sécurité volume)

**TP** : {job['tp_name']}
**Sous-partie** : {sub_part_name}
**Passe** : {passe} ({passe_name})
**Volume actuel** : {word_count_now} mots

## Contexte

Cette journée est sous le budget audio minimal de **{budget['min_words']} mots parlés**
pour une cible de **{budget['target_words']} mots**.
Tu participes à une opération de sécurité volume : enrichir les segments les plus
courts avec **du contenu nouveau**, sans réécrire l'existant.

## Ce que tu dois faire

Le **TEXTE ACTUEL** du segment (texte oral TTS-ready, déjà validé en passe précédente)
est fourni plus bas. Tu dois retourner UNIQUEMENT du **contenu additionnel** à
concaténer en fin du texte existant. Volume cible : environ **{addition_words} mots
supplémentaires**.

Le contenu additionnel DOIT :
- Reprendre le ton oral et la voix narrative du texte existant
- Respecter scrupuleusement les règles **#1 à #28** décrites plus bas
- Enchaîner avec une transition naturelle ("Allons plus loin maintenant…",
  "Je voudrais te donner d'autres exemples…", "On va creuser un autre angle…")
- Rester dans le scope thématique de la sous-partie "{sub_part_name}" et de la
  passe {passe} ({passe_name})

Ce que ton contenu doit contenir (au choix selon ce qui manque) :
- 2 à 4 exemples fictifs supplémentaires dans des contextes variés (PME / particulier /
  B2B / situation sensible / situation urgente / dossier complexe…)
- 1 à 2 mises en situation détaillées : dialogue client / conseiller, étape par étape
- 1 cas contraste explicite : ce qu'il NE FAUT PAS faire + pourquoi
- Nuances selon profil client (novice vs expert, pressé vs exploratoire,
  en colère vs résigné)
- Mini-récap oral à la fin de chaque nouvelle section

## Ce que tu NE DOIS PAS faire

- NE PAS répéter ce qui est déjà dans le TEXTE ACTUEL (lis-le attentivement)
- NE PAS reformuler ou réécrire des passages existants
- NE PAS inclure le TEXTE ACTUEL dans ta réponse — uniquement ton ajout
- NE PAS écrire de balises markdown (titres, listes), de JSON, de fenced code —
  uniquement du texte oral brut destiné au TTS

## Format de sortie

Réponds avec le texte oral additionnel **brut** (pas de fenced code block ```,
pas de JSON, pas d'enrobage, pas d'introduction du type "Voici le contenu
additionnel :"). Environ {addition_words} mots, maximum 2500 mots.

═══ TEXTE ACTUEL DU SEGMENT (à enrichir, NE PAS répéter) ═══

{text_content}

═══ RÈGLES À RESPECTER ═══

{rules}
"""


def run_volume_safety_api(job_id: int, folder_id: int, model: str = None) -> dict:
    """Version API de `run_volume_safety` : même invariant de budget audio dynamique,
    même algorithme multi-passes, mais via `_anthropic_post` au lieu de
    subprocess `claude`. Consomme du crédit Anthropic — choisi par le mode
    auto-pilot quand `use_claude_code=False`.

    Append-only : le texte original reste intact. Le snapshot
    text_content_pre_review reste valide.
    """
    from utils.anthropic_client import (
        AnthropicRateLimitError, default_model, post_message as _anthropic_post
    )

    if model is None:
        model = default_model()
    started_at = time.time()
    logger.info(
        "PIPELINE_VOLUME_API_START job=%s folder=%s model=%s max_passes=%s",
        job_id,
        folder_id,
        model,
        _VOLUME_SAFETY_MAX_PASSES,
    )

    job = _get_job_row(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    initial_audit = compute_volume_audit(job_id)
    initial_folder_audit = next(
        (f for f in initial_audit["folders"] if f["folder_id"] == folder_id), None
    )
    if not initial_folder_audit:
        raise ValueError(f"Folder {folder_id} introuvable pour job {job_id}")

    if initial_folder_audit["deficit"] == 0:
        logger.info(
            "PIPELINE_VOLUME_API_SKIP job=%s folder=%s total_words=%s target=%s duration_ms=%s reason=no_deficit",
            job_id,
            folder_id,
            initial_folder_audit["total_words"],
            initial_audit.get("target"),
            int((time.time() - started_at) * 1000),
        )
        return {"ok": True, "skipped": True, "reason": "no_deficit",
                "audit": initial_folder_audit}

    all_enriched = []
    all_failed = []
    passes_run = 0
    aborted_rate_limit = False

    for pass_idx in range(_VOLUME_SAFETY_MAX_PASSES):
        audit = compute_volume_audit(job_id)
        folder_audit = next(
            (f for f in audit["folders"] if f["folder_id"] == folder_id), None
        )
        if not folder_audit or folder_audit["deficit"] == 0:
            logger.info(
                "PIPELINE_VOLUME_API_TARGET_REACHED job=%s folder=%s pass=%s total_words=%s duration_ms=%s",
                job_id,
                folder_id,
                pass_idx,
                folder_audit["total_words"] if folder_audit else "?",
                int((time.time() - started_at) * 1000),
            )
            break

        short_ids = [s["segment_id"] for s in folder_audit["shortest_segments"]]
        if not short_ids:
            logger.warning(
                f"📏 [API] Pass {pass_idx + 1} folder {folder_id} : aucun segment éligible"
            )
            break

        passes_run += 1
        logger.info(
            "PIPELINE_VOLUME_API_PASS_START job=%s folder=%s pass=%s/%s total_words=%s deficit=%s candidates=%s",
            job_id,
            folder_id,
            pass_idx + 1,
            _VOLUME_SAFETY_MAX_PASSES,
            folder_audit.get("total_words"),
            folder_audit.get("deficit"),
            len(short_ids),
        )

        placeholders = ",".join("?" * len(short_ids))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT id, sub_part_index, sub_part_name, passe, text_content,
                       COALESCE(word_count, 0)
                FROM content_generation_segments
                WHERE id IN ({placeholders}) AND status = 'completed'""",
            tuple(short_ids),
        )
        segments = [
            {
                "segment_id": r[0],
                "sub_idx": r[1],
                "sub_part_name": r[2],
                "passe": r[3],
                "text_content": r[4] or "",
                "word_count": int(r[5] or 0),
                "deficit_remaining": int(folder_audit.get("deficit") or 0),
                "candidates_count": len(short_ids),
            }
            for r in cursor.fetchall()
        ]
        conn.close()

        for seg in segments:
            segment_started_at = time.time()
            try:
                logger.info(
                    "PIPELINE_VOLUME_API_SEGMENT_START job=%s folder=%s segment_id=%s pass=%s words_before=%s",
                    job_id,
                    folder_id,
                    seg["segment_id"],
                    pass_idx + 1,
                    seg["word_count"],
                )
                prompt = _build_volume_safety_prompt_api(job, seg)
                addition = _anthropic_post(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=8000,
                    model=model,
                ).strip()

                # Strip fence markdown si Claude a quand même fencé
                if addition.startswith("```"):
                    lines = addition.split("\n")
                    if len(lines) > 2 and lines[-1].strip().startswith("```"):
                        addition = "\n".join(lines[1:-1]).strip()

                added_words = len(addition.split())
                if not addition or added_words < 200:
                    logger.warning(
                        f"⚠️ [API] Volume safety segment {seg['segment_id']} (pass {pass_idx + 1}) : "
                        f"output trop court ({added_words} mots) — skip append"
                    )
                    all_failed.append({
                        "segment_id": seg["segment_id"],
                        "pass": pass_idx + 1,
                        "reason": "output_too_short",
                    })
                    continue

                new_text = (seg["text_content"].rstrip() + "\n\n" + addition).strip()
                new_words = len(new_text.split())

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """UPDATE content_generation_segments
                       SET text_content = ?, word_count = ?, dirty = 1,
                           humanized = 0, humanization_error = NULL, humanization_signature = NULL,
                           reviewed = 0, review_error = NULL, review_signature = NULL
                       WHERE id = ?""",
                    (new_text, new_words, seg["segment_id"]),
                )
                conn.commit()
                conn.close()
                all_enriched.append({
                    "segment_id": seg["segment_id"],
                    "sub_part_name": seg["sub_part_name"],
                    "passe": seg["passe"],
                    "pass_idx": pass_idx + 1,
                    "words_before": seg["word_count"],
                    "words_added": new_words - seg["word_count"],
                    "words_after": new_words,
                })
                logger.info(
                    "PIPELINE_VOLUME_API_SEGMENT_DONE job=%s folder=%s segment_id=%s pass=%s words_before=%s "
                    "words_added=%s words_after=%s duration_ms=%s",
                    job_id,
                    folder_id,
                    seg["segment_id"],
                    pass_idx + 1,
                    seg["word_count"],
                    new_words - seg["word_count"],
                    new_words,
                    int((time.time() - segment_started_at) * 1000),
                )
            except AnthropicRateLimitError as e:
                logger.warning(
                    "PIPELINE_VOLUME_API_SEGMENT_RATE_LIMIT job=%s folder=%s segment_id=%s pass=%s wait_seconds=%s duration_ms=%s",
                    job_id,
                    folder_id,
                    seg["segment_id"],
                    pass_idx + 1,
                    getattr(e, "wait_seconds", "N/A"),
                    int((time.time() - segment_started_at) * 1000),
                )
                all_failed.append({
                    "segment_id": seg["segment_id"],
                    "pass": pass_idx + 1,
                    "reason": "rate_limit",
                })
                aborted_rate_limit = True
                break
            except Exception as e:
                logger.exception(
                    "PIPELINE_VOLUME_API_SEGMENT_ERROR job=%s folder=%s segment_id=%s pass=%s duration_ms=%s error=%s",
                    job_id,
                    folder_id,
                    seg["segment_id"],
                    pass_idx + 1,
                    int((time.time() - segment_started_at) * 1000),
                    e,
                )
                all_failed.append({
                    "segment_id": seg["segment_id"],
                    "pass": pass_idx + 1,
                    "reason": str(e)[:200],
                })

        if aborted_rate_limit:
            break

    # Re-assemble + upload une seule fois à la fin
    if all_enriched:
        try:
            from services.content_generation_service import _assemble_and_upload, _update_job_db
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM content_generation_jobs WHERE folder_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (folder_id,),
            )
            cg = cursor.fetchone()
            conn.close()
            if cg:
                cg_job_id = cg[0]
                final_words, filename = _assemble_and_upload(
                    folder_id, job["platform_id"], cg_job_id
                )
                _update_job_db(cg_job_id, total_words=final_words)
                logger.info(
                    "PIPELINE_VOLUME_API_REASSEMBLE_DONE job=%s folder=%s content_job=%s final_words=%s filename=%s",
                    job_id,
                    folder_id,
                    cg_job_id,
                    final_words,
                    filename,
                )
        except Exception as e:
            logger.warning(
                "PIPELINE_VOLUME_API_REASSEMBLE_ERROR job=%s folder=%s error=%s",
                job_id,
                folder_id,
                e,
            )

    final_audit = compute_volume_audit(job_id)
    final_folder_audit = next(
        (f for f in final_audit["folders"] if f["folder_id"] == folder_id),
        initial_folder_audit,
    )
    logger.info(
        "PIPELINE_VOLUME_API_DONE job=%s folder=%s passes=%s enriched=%s failed=%s "
        "total_before=%s total_after=%s deficit_before=%s deficit_after=%s target_reached=%s duration_ms=%s",
        job_id,
        folder_id,
        passes_run,
        len(all_enriched),
        len(all_failed),
        initial_folder_audit.get("total_words"),
        final_folder_audit.get("total_words"),
        initial_folder_audit.get("deficit"),
        final_folder_audit.get("deficit"),
        final_folder_audit["deficit"] == 0,
        int((time.time() - started_at) * 1000),
    )

    return {
        "ok": True,
        "skipped": False,
        "passes_run": passes_run,
        "audit_before": initial_folder_audit,
        "audit_after": final_folder_audit,
        "enriched": all_enriched,
        "failed": all_failed,
        "model": model,
        "target_reached": final_folder_audit["deficit"] == 0,
    }


def run_volume_safety(job_id: int, folder_id: int, model: str = "sonnet") -> dict:
    """Étape 6.5 — sécurité volume pour un folder donné.

    Pour chaque folder dont total_words parlé < budget minimal :
      1. Identifier les N segments les plus courts (par word_count ASC).
      2. Pour chaque segment : lancer 1 subprocess `claude` qui produit un
         texte additionnel (≥1500 mots) respectant les règles #1-#27.
      3. Append au text_content existant (pas de réécriture). Marque
         dirty=1 et reviewed=0 pour que le segment repasse en révision et
         re-génère son audio TTS.
      4. Re-assemble + re-upload Azure pour que le Word téléchargeable soit
         à jour.

    **Multi-passes (jusqu'à `_VOLUME_SAFETY_MAX_PASSES`)** : un seul passage
    enrichit ~5 segments × ~3000 mots = ~15k mots max. Si le déficit initial
    dépasse cette capacité (cas réel : déficit -30k au job 13 du mode test),
    on relance jusqu'à atteindre la cible OU épuiser les passes. Re-audit
    à chaque itération pour identifier les nouveaux "plus courts".

    Append-only : le texte original reste intact. Le snapshot
    text_content_pre_review reste valide (= état au finalize de l'étape 6).
    """
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model must be in {ALLOWED_MODELS}")

    job = _get_job_row(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    initial_audit = compute_volume_audit(job_id)
    initial_folder_audit = next(
        (f for f in initial_audit["folders"] if f["folder_id"] == folder_id), None
    )
    if not initial_folder_audit:
        raise ValueError(f"Folder {folder_id} introuvable pour job {job_id}")

    if initial_folder_audit["deficit"] == 0:
        logger.info(
            f"📏 Volume safety job {job_id}/folder {folder_id} : déjà au seuil "
            f"({initial_folder_audit['total_words']} mots) — skip"
        )
        return {"ok": True, "skipped": True, "reason": "no_deficit",
                "audit": initial_folder_audit}

    mission_root = os.path.join(
        _REVIEW_QUEUE_ROOT, f"job_{job_id}", "step_volume_safety", f"folder_{folder_id}"
    )
    os.makedirs(mission_root, exist_ok=True)
    log_path = os.path.join(mission_root, "execution.log")

    all_enriched = []
    all_failed = []
    passes_run = 0
    aborted_rate_limit = False

    for pass_idx in range(_VOLUME_SAFETY_MAX_PASSES):
        # Re-audit à chaque passe : le déficit (et donc les "plus courts")
        # ont évolué après les enrichissements précédents.
        audit = compute_volume_audit(job_id)
        folder_audit = next(
            (f for f in audit["folders"] if f["folder_id"] == folder_id), None
        )
        if not folder_audit or folder_audit["deficit"] == 0:
            logger.info(
                f"📏 Volume cible atteinte (folder {folder_id}, "
                f"{folder_audit['total_words'] if folder_audit else '?'} mots) "
                f"après {pass_idx} passe(s)"
            )
            break

        short_ids = [s["segment_id"] for s in folder_audit["shortest_segments"]]
        if not short_ids:
            logger.warning(
                f"📏 Pass {pass_idx + 1} folder {folder_id} : aucun segment "
                f"éligible — abort"
            )
            break

        passes_run += 1
        logger.info(
            f"📏 Volume safety folder {folder_id} — passe {pass_idx + 1}/"
            f"{_VOLUME_SAFETY_MAX_PASSES} (déficit {folder_audit['deficit']} mots, "
            f"top {len(short_ids)} segments à enrichir)"
        )

        placeholders = ",".join("?" * len(short_ids))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT id, sub_part_index, sub_part_name, passe, text_content,
                       COALESCE(word_count, 0)
                FROM content_generation_segments
                WHERE id IN ({placeholders}) AND status = 'completed'""",
            tuple(short_ids),
        )
        segments = [
            {
                "segment_id": r[0],
                "sub_idx": r[1],
                "sub_part_name": r[2],
                "passe": r[3],
                "text_content": r[4] or "",
                "word_count": int(r[5] or 0),
                "deficit_remaining": int(folder_audit.get("deficit") or 0),
                "candidates_count": len(short_ids),
            }
            for r in cursor.fetchall()
        ]
        conn.close()

        for seg in segments:
            # Dossier par-passe pour ne pas écraser les outputs précédents.
            chunk_dir = os.path.join(
                mission_root, f"pass_{pass_idx + 1}_segment_{seg['segment_id']}"
            )
            os.makedirs(chunk_dir, exist_ok=True)
            _build_volume_safety_chunk(chunk_dir, job, seg, model)
            try:
                _run_subprocess(chunk_dir, model, log_path=log_path, log_mode="a")
                with open(os.path.join(chunk_dir, "output.md"), "r", encoding="utf-8") as f:
                    addition = f.read().strip()
                if addition.startswith("```"):
                    lines = addition.split("\n")
                    if len(lines) > 2 and lines[-1].strip().startswith("```"):
                        addition = "\n".join(lines[1:-1]).strip()
                added_words = len(addition.split())
                if not addition or added_words < 200:
                    logger.warning(
                        f"⚠️ Volume safety segment {seg['segment_id']} (pass {pass_idx + 1}) : "
                        f"output trop court ({added_words} mots) — skip append"
                    )
                    all_failed.append({
                        "segment_id": seg["segment_id"],
                        "pass": pass_idx + 1,
                        "reason": "output_too_short",
                    })
                    continue
                new_text = (seg["text_content"].rstrip() + "\n\n" + addition).strip()
                new_words = len(new_text.split())

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """UPDATE content_generation_segments
                       SET text_content = ?, word_count = ?, dirty = 1,
                           humanized = 0, humanization_error = NULL, humanization_signature = NULL,
                           reviewed = 0, review_error = NULL, review_signature = NULL
                       WHERE id = ?""",
                    (new_text, new_words, seg["segment_id"]),
                )
                conn.commit()
                conn.close()
                all_enriched.append({
                    "segment_id": seg["segment_id"],
                    "sub_part_name": seg["sub_part_name"],
                    "passe": seg["passe"],
                    "pass_idx": pass_idx + 1,
                    "words_before": seg["word_count"],
                    "words_added": new_words - seg["word_count"],
                    "words_after": new_words,
                })
                logger.info(
                    f"📏 [Pass {pass_idx + 1}] Segment {seg['segment_id']} enrichi : "
                    f"+{new_words - seg['word_count']} mots ({seg['word_count']} → {new_words})"
                )
            except _RateLimitError:
                logger.warning(
                    f"⏳ Volume safety segment {seg['segment_id']} : rate limit — abort"
                )
                all_failed.append({
                    "segment_id": seg["segment_id"],
                    "pass": pass_idx + 1,
                    "reason": "rate_limit",
                })
                aborted_rate_limit = True
                break  # break inner loop
            except Exception as e:
                logger.error(
                    f"❌ Volume safety segment {seg['segment_id']} (pass {pass_idx + 1}) : {e}"
                )
                all_failed.append({
                    "segment_id": seg["segment_id"],
                    "pass": pass_idx + 1,
                    "reason": str(e)[:200],
                })

        if aborted_rate_limit:
            break  # break outer loop si rate limit hit

    # Re-assemble + upload une seule fois à la fin (pas à chaque passe — économise
    # appels Azure). On re-récupère le cg_job_id pour le folder.
    if all_enriched:
        try:
            from services.content_generation_service import _assemble_and_upload, _update_job_db
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM content_generation_jobs WHERE folder_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (folder_id,),
            )
            cg = cursor.fetchone()
            conn.close()
            if cg:
                cg_job_id = cg[0]
                final_words, filename = _assemble_and_upload(
                    folder_id, job["platform_id"], cg_job_id
                )
                _update_job_db(cg_job_id, total_words=final_words)
                logger.info(
                    f"✅ Re-assemble post volume safety folder {folder_id} : "
                    f"{final_words} mots assemblés, {filename}"
                )
        except Exception as e:
            logger.warning(f"⚠️ Re-assemble post volume safety échoué : {e}")

    final_audit = compute_volume_audit(job_id)
    final_folder_audit = next(
        (f for f in final_audit["folders"] if f["folder_id"] == folder_id),
        initial_folder_audit,
    )

    return {
        "ok": True,
        "skipped": False,
        "passes_run": passes_run,
        "audit_before": initial_folder_audit,
        "audit_after": final_folder_audit,
        "enriched": all_enriched,
        "failed": all_failed,
        "model": model,
        "target_reached": final_folder_audit["deficit"] == 0,
    }
