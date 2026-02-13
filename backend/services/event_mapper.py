# event_mapper.py - Service de cartographie des evenements pedagogiques
# Analyse un chunk de transcription et identifie les evenements avec leurs timecodes

import json
import requests
import os
from utils.logger import get_logger

logger = get_logger(__name__)

# Recuperer la cle API
def get_api_key():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY non definie")
    return api_key

# Types d'evenements possibles
# Note: Cette liste est extensible - chaque type pourra avoir plusieurs templates de rendu
EVENT_TYPES = [
    # === Types pedagogiques de base ===
    "recap",       # Recapitulatif, resume
    "story",       # Histoire, anecdote, narration chronologique
    "definition",  # Definition formelle d'un terme
    "concept",     # Idee abstraite, theorie
    "example",     # Illustration concrete, cas pratique
    "process",     # Methode, etapes, procedure
    "comparison",  # Mise en parallele, contraste
    "data",        # Chiffres, statistiques, donnees

    # === Types narratifs/rhetoriques ===
    "analogy",     # Metaphore, comparaison explicative
    "warning",     # Piege a eviter, erreur frequente
    "tip",         # Conseil pratique, astuce
    "opinion",     # Point de vue du formateur

    # === Types structurels ===
    "transition",  # Passage entre sujets
    "filler"       # Hesitation, digression non pertinente
]

# Prompt pour l'analyse locale d'un chunk
PROMPT_EVENT_MAPPING = """Tu analyses un extrait d'une formation audio.
Ton role: CARTOGRAPHIER les evenements pedagogiques pour l'apprenant.

PRINCIPE FONDAMENTAL:
Un evenement = UNE intention pedagogique identifiable pour l'apprenant.
(Pas le rendu visuel, pas la slide - juste l'intention du formateur)

Pour chaque evenement, identifie:
- type: recap|story|definition|concept|example|process|comparison|data|analogy|warning|tip|opinion|transition|filler
- start_time: timecode debut (secondes depuis le debut du chunk)
- end_time: timecode fin
- summary: 1 phrase decrivant l'intention pedagogique
- keywords: 2-3 mots-cles
- source_text: extrait exact correspondant

=== INDICES LINGUISTIQUES (aide a la detection) ===
- definition: "c'est", "on appelle", "cela signifie", "par definition", "qu'est-ce que"
- example: "par exemple", "prenons le cas", "imaginons", "concretement", "illustrons"
- story: narration chronologique, "il etait une fois", dates, acteurs, "a l'epoque"
- recap: "pour resumer", "on a vu", "rappelez-vous", "la derniere fois", "en resume"
- process: "d'abord", "ensuite", "etape", "methode", "processus", "comment faire"
- comparison: "contrairement a", "alors que", "en comparaison", "vs", "par rapport a"
- data: chiffres explicites, pourcentages, statistiques, "les donnees montrent"
- analogy: "c'est comme", "imagine que", "pense a", metaphores explicatives
- warning: "attention", "erreur frequente", "piege", "ne faites pas", "evitez"
- tip: "astuce", "conseil", "je vous recommande", "mon experience"
- opinion: "je pense que", "a mon avis", "personnellement"

=== GRANULARITE (CRITIQUE) ===
- Duree cible: 30 secondes a 2 minutes par evenement
- >2-3 minutes = PROBABLEMENT plusieurs evenements distincts
- Detecte CHAQUE definition, CHAQUE exemple, CHAQUE changement narratif

REGLE NARRATIVE (pour les longues narrations):
Une narration longue DOIT etre decoupee si:
- Changement d'epoque ou de periode
- Changement de technologie ou d'outil
- Changement d'acteur principal
- Nouveau exemple concret insere dans l'histoire

Exemple: une story de 4 min qui contient 3 exemples = 1 story + 3 example (pas 1 seul bloc)

=== MARQUEURS DE CONTINUITE ===
(UNIQUEMENT pour les frontieres de chunk, PAS pour la continuite thematique)
- continues_next: true SEULEMENT si coupe en plein milieu d'une phrase/histoire
- continues_previous: true SEULEMENT si reprise directe d'un evenement coupe
- La plupart des evenements = continues_next: false, continues_previous: false

IMPORTANT:
- Sois volontairement GRANULAIRE - mieux vaut trop d'evenements que pas assez
- Ne pense PAS au rendu visuel ou aux slides
- Ton role = classifier l'intention pedagogique, rien d'autre

Contexte du chunk:
- Numero du chunk: {chunk_index}
- Est-ce le premier chunk: {is_first}
- Duree totale du chunk: {chunk_duration}s

Transcription avec timecodes:
{transcription}

Reponds UNIQUEMENT en JSON valide:
{{
  "events": [
    {{
      "type": "story",
      "start_time": 45.2,
      "end_time": 120.5,
      "summary": "Histoire de la naissance du telemarketing dans les annees 1920",
      "keywords": ["telemarketing", "annees 1920", "scripts"],
      "source_text": "Le texte exact...",
      "continues_previous": false,
      "continues_next": false
    }}
  ]
}}"""


def format_transcription_for_prompt(transcription: dict) -> str:
    """
    Formate la transcription avec timecodes pour le prompt.
    Format: [MM:SS] texte
    """
    formatted = []
    for segment in transcription.get("segments", []):
        start = segment["start"]
        minutes = int(start // 60)
        seconds = int(start % 60)
        text = segment["text"].strip()
        formatted.append(f"[{minutes:02d}:{seconds:02d}] {text}")

    return "\n".join(formatted)


def map_events(transcription: dict, chunk_index: int, chunk_offset: int = 0) -> list:
    """
    Analyse un chunk de transcription et retourne la liste des evenements detectes.

    Args:
        transcription: dict avec "segments" (liste de {start, end, text})
        chunk_index: index du chunk (0-based)
        chunk_offset: offset temporel en secondes (pour ajuster les timecodes)

    Returns:
        Liste d'evenements avec timecodes absolus
    """
    logger.info(f"Event mapping pour chunk #{chunk_index} (offset: {chunk_offset}s)")

    if not transcription.get("segments"):
        logger.warning("Pas de segments dans la transcription")
        return []

    # Calculer la duree du chunk
    segments = transcription["segments"]
    chunk_duration = segments[-1]["end"] - segments[0]["start"] if segments else 0

    # Formater la transcription
    formatted_transcript = format_transcription_for_prompt(transcription)

    # Construire le prompt
    prompt = PROMPT_EVENT_MAPPING.format(
        chunk_index=chunk_index,
        is_first="oui" if chunk_index == 0 else "non",
        chunk_duration=int(chunk_duration),
        transcription=formatted_transcript
    )

    # Appel GPT-4
    api_key = get_api_key()

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "system", "content": "Tu es un expert en analyse de discours pedagogique. Tu reponds uniquement en JSON valide."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,  # Basse temperature pour plus de coherence
                "max_tokens": 2000
            },
            timeout=90
        )

        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"]["content"].strip()

        # Nettoyer si necessaire (enlever les backticks markdown)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        # Parser le JSON
        data = json.loads(content)
        events = data.get("events", [])

        # Ajuster les timecodes avec l'offset du chunk
        for event in events:
            event["start_time"] += chunk_offset
            event["end_time"] += chunk_offset
            event["chunk_index"] = chunk_index

        logger.info(f"Chunk #{chunk_index}: {len(events)} evenements detectes")

        # Log des types d'evenements
        types_count = {}
        for e in events:
            t = e.get("type", "unknown")
            types_count[t] = types_count.get(t, 0) + 1
        logger.info(f"Types: {types_count}")

        return events

    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON: {e}")
        logger.error(f"Contenu recu: {content[:500]}")
        return []
    except requests.RequestException as e:
        logger.error(f"Erreur API OpenAI: {e}")
        return []


def get_events_summary(events: list) -> str:
    """
    Genere un resume des evenements pour debug.
    """
    lines = []
    for i, e in enumerate(events):
        start = e.get("start_time", 0)
        end = e.get("end_time", 0)
        etype = e.get("type", "?")
        summary = e.get("summary", "")[:50]

        start_str = f"{int(start//60)}:{int(start%60):02d}"
        end_str = f"{int(end//60)}:{int(end%60):02d}"

        lines.append(f"  {i+1}. [{start_str}-{end_str}] {etype}: {summary}...")

    return "\n".join(lines)
