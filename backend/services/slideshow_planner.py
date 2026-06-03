# slideshow_planner.py - Service de construction du plan de slides
# Decide quels evenements meritent une slide et genere le contenu minimal

import json
import requests
import os
from utils.logger import get_logger

logger = get_logger(__name__)


def get_api_key():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY non definie")
    return api_key


# Mapping type d'evenement -> templates recommandes
# Note: Le premier template est le defaut, les autres sont des alternatives
EVENT_TO_TEMPLATES = {
    # Types pedagogiques de base
    "story": ["story", "reflection", "playful"],
    "definition": ["reflection"],
    "concept": ["reflection", "casestudy"],
    "example": ["casestudy", "playful"],
    "process": ["facilitator"],
    "comparison": ["casestudy", "chart"],
    "data": ["stats", "chart"],
    "recap": ["recap", "casestudy", "facilitator"],

    # Types narratifs/rhetoriques (templates dedies)
    "analogy": ["analogy", "reflection"],      # Metaphore explicative
    "warning": ["warning", "reflection"],      # Piege a eviter
    "tip": ["tip", "reflection"],              # Conseil pratique
    "opinion": ["opinion", "reflection"],      # Point de vue

    # Types structurels
    "transition": ["transition"],
    "filler": ["reflection"]  # Filler utilise reflection par defaut
}

# Prompt pour la construction du plan
# Note: Chaque evenement = 1 slide (pas de filtrage arbitraire)
PROMPT_SLIDESHOW_PLAN = """Tu es un concepteur de presentations pedagogiques experimente.
Tu analyses une timeline d'evenements extraits d'une formation audio.

REGLE FONDAMENTALE: CHAQUE EVENEMENT = 1 SLIDE
Chaque evenement detecte doit generer exactement une slide.
Le type de l'evenement determine le template a utiliser.

MAPPING TYPE -> TEMPLATE:
- story -> story (histoire/anecdote)
- recap -> recap (recapitulatif)
- definition -> reflection (definition/concept)
- concept -> reflection (idee abstraite)
- example -> casestudy (illustration concrete)
- process -> facilitator (methode/etapes)
- comparison -> casestudy (mise en parallele)
- data -> stats (chiffres/statistiques)
- analogy -> analogy (metaphore explicative)
- warning -> warning (piege a eviter)
- tip -> tip (conseil pratique)
- opinion -> opinion (point de vue)
- transition -> transition (passage entre sujets)
- filler -> reflection (pause/respiration)

Pour CHAQUE evenement de la timeline, genere une slide avec:
- event_index: index de l'evenement (0-based)
- trigger_time: timecode de debut de l'evenement
- template: selon le mapping ci-dessus
- title_hint: indication pour le titre (3-5 mots MAX)
- content_hint: indication pour le contenu (1 phrase MAX)

Timeline des evenements:
{timeline}

Duree totale couverte: {total_duration} secondes

IMPORTANT: Tu dois generer exactement {event_count} slides (une par evenement).

Reponds UNIQUEMENT en JSON valide:
{{
  "slides": [
    {{
      "event_index": 0,
      "trigger_time": 45.2,
      "template": "story",
      "title_hint": "Origine du telemarketing",
      "content_hint": "Les scripts de vente naissent dans les annees 1920"
    }}
  ],
  "reasoning": "Explication concise..."
}}"""


# Prompts de generation de contenu par template
CONTENT_PROMPTS = {
    "reflection": """Cree le contenu pour une slide de type "reflection" (panneau de reflexion).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: 3-5 mots MAX, le concept/idee principale
- text: 1-2 phrases courtes de synthese reflexive

JSON: {{"title": "...", "text": "..."}}""",

    "casestudy": """Cree le contenu pour une slide de type "casestudy" (etude de cas).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le theme principal (3-5 mots)
- cases: 1 a 3 points cles MAXIMUM, chacun avec un "title" court et une "desc" d'1 phrase

JSON: {{"title": "...", "cases": [{{"title": "...", "desc": "..."}}]}}""",

    "facilitator": """Cree le contenu pour une slide de type "facilitator" (processus/etapes).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: nom du processus/methode (3-5 mots)
- steps: 2 a 4 etapes MAXIMUM, chacune avec un "title" court et un "detail" d'1 phrase

JSON: {{"title": "...", "steps": [{{"title": "...", "detail": "..."}}]}}""",

    "stats": """Cree le contenu pour une slide de type "stats" (statistiques).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le theme (3-5 mots)
- stats: 1 a 3 statistiques avec "value" (le chiffre) et "label" (ce qu'il represente)
- columns: 2 a 3 colonnes de texte explicatif (titre + contenu court)

JSON: {{"title": "...", "stats": [{{"value": "...", "label": "..."}}], "columns": [{{"title": "...", "content": "..."}}]}}""",

    "playful": """Cree le contenu pour une slide de type "playful" (ludique/visuel).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: accrocheur et engageant (3-6 mots)
- cards: 1 a 3 cartes avec "title" court et "desc" d'1 phrase, optionnel "image" (theme d'image)

JSON: {{"title": "...", "cards": [{{"title": "...", "desc": "...", "image": "business"}}]}}""",

    "chart": """Cree le contenu pour une slide de type "chart" (graphique).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le theme (3-5 mots)
- text: 1-2 phrases de contexte
- chart_data: données pour le graphique (optionnel, peut etre vide)

JSON: {{"title": "...", "text": "...", "chart_data": []}}""",

    "transition": """Cree le contenu pour une slide de type "transition" (passage entre sujets).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: phrase de transition courte (3-6 mots)
- from_topic: le sujet qu'on quitte (2-4 mots)
- to_topic: le sujet vers lequel on va (2-4 mots)

JSON: {{"title": "...", "from_topic": "...", "to_topic": "..."}}""",

    "filler": """Cree le contenu pour une slide de type "filler" (pause/respiration).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: message de pause ou reflexion (3-6 mots)
- text: courte phrase d'accompagnement ou question rhetorique

JSON: {{"title": "...", "text": "..."}}""",

    "story": """Cree le contenu pour une slide de type "story" (histoire/anecdote).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le titre de l'histoire (3-6 mots)
- narrative: le recit ou l'anecdote en 2-3 phrases
- moral: la lecon ou conclusion a retenir (1 phrase)

JSON: {{"title": "...", "narrative": "...", "moral": "..."}}""",

    "recap": """Cree le contenu pour une slide de type "recap" (recapitulatif/checklist).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le titre du recap (3-6 mots, ex: "Ce qu'il faut retenir")
- points: liste de 2 a 4 points cles a retenir (phrases courtes)

JSON: {{"title": "...", "points": ["Point 1", "Point 2", "Point 3"]}}""",

    "analogy": """Cree le contenu pour une slide de type "analogy" (metaphore explicative).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: la metaphore ou image mentale en 5-10 mots
- analogy_label: la situation concrete hors metier (2-5 mots)
- concept_label: la notion metier mise en parallele (2-5 mots)
- text: explication de l'analogie en 1 phrase courte
- takeaway: phrase cle finale
- image_prompt: prompt PNG 16:9 sans texte, sans humains, sans visages, sans silhouettes, sans personnages
- image_alt: description accessible de l'image

JSON: {{"title": "...", "analogy_label": "...", "concept_label": "...", "text": "...", "takeaway": "...", "image_prompt": "...", "image_alt": "..."}}""",

    "warning": """Cree le contenu pour une slide de type "warning" (piege a eviter).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le piege en 3-5 mots (ex: "Erreur classique a eviter")
- text: explication du piege et comment l'eviter en 2-3 phrases

JSON: {{"title": "...", "text": "..."}}""",

    "tip": """Cree le contenu pour une slide de type "tip" (conseil pratique).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le conseil en 3-5 mots (ex: "Astuce pour gagner du temps")
- text: le conseil detaille en 2-3 phrases

JSON: {{"title": "...", "text": "..."}}""",

    "opinion": """Cree le contenu pour une slide de type "opinion" (point de vue du formateur).
L'evenement: {event_summary}
Source: {source_text}

Genere:
- title: le point de vue en 3-5 mots
- text: l'opinion argumentee en 2-3 phrases

JSON: {{"title": "...", "text": "..."}}"""
}


def format_timeline_for_prompt(timeline: list) -> str:
    """
    Formate la timeline pour le prompt de planification.
    """
    lines = []
    for i, event in enumerate(timeline):
        start = event.get("start_time", 0)
        end = event.get("end_time", 0)
        etype = event.get("type", "unknown")
        summary = event.get("summary", "")
        duration = end - start

        start_str = f"{int(start//60)}:{int(start%60):02d}"
        end_str = f"{int(end//60)}:{int(end%60):02d}"

        lines.append(f"[{i}] {start_str}-{end_str} ({duration:.0f}s) | {etype} | {summary}")

    return "\n".join(lines)


def plan_slideshow(merged_timeline: list) -> list:
    """
    Analyse la timeline fusionnee et retourne le plan de slides.

    Args:
        merged_timeline: Liste d'evenements fusionnes

    Returns:
        Liste de slides planifiees avec event_index, trigger_time, template, hints
    """
    if not merged_timeline:
        logger.warning("Timeline vide, pas de slides a planifier")
        return []

    logger.info(f"Planification des slides pour {len(merged_timeline)} evenements")

    # Calculer la duree totale
    total_duration = merged_timeline[-1].get("end_time", 0) - merged_timeline[0].get("start_time", 0)

    # Formater la timeline
    formatted_timeline = format_timeline_for_prompt(merged_timeline)

    # Construire le prompt
    prompt = PROMPT_SLIDESHOW_PLAN.format(
        timeline=formatted_timeline,
        total_duration=int(total_duration),
        event_count=len(merged_timeline)
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
                    {"role": "system", "content": "Tu es un expert en conception de presentations pedagogiques. Tu reponds uniquement en JSON valide."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 1500
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"]["content"].strip()

        # Nettoyer si necessaire
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        data = json.loads(content)
        slides = data.get("slides", [])
        reasoning = data.get("reasoning", "")

        logger.info(f"Plan: {len(slides)} slides decidees")
        logger.info(f"Raisonnement: {reasoning[:200]}...")

        return slides

    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON: {e}")
        return []
    except requests.RequestException as e:
        logger.error(f"Erreur API OpenAI: {e}")
        return []


def generate_slide_content(event: dict, plan_item: dict) -> dict:
    """
    Genere le contenu minimal d'une slide basee sur l'evenement et le plan.

    Args:
        event: L'evenement source
        plan_item: L'item du plan (avec template, title_hint, content_hint)

    Returns:
        Dict avec le contenu de la slide selon le template
    """
    template = plan_item.get("template", "reflection")
    title_hint = plan_item.get("title_hint", "")
    content_hint = plan_item.get("content_hint", "")

    logger.info(f"Generation contenu pour template '{template}'")

    # Recuperer le prompt specifique au template
    prompt_template = CONTENT_PROMPTS.get(template, CONTENT_PROMPTS["reflection"])

    # Construire le prompt avec les informations de l'evenement
    prompt = prompt_template.format(
        event_summary=event.get("summary", ""),
        source_text=event.get("source_text", "")[:500]  # Limiter la taille
    )

    # Ajouter les hints si disponibles
    if title_hint or content_hint:
        prompt += f"\n\nIndications supplementaires:\n- Titre suggere: {title_hint}\n- Contenu suggere: {content_hint}"

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
                    {"role": "system", "content": "Tu generes du contenu minimal pour des slides. Reponds uniquement en JSON valide."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": 500
            },
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"]["content"].strip()

        # Nettoyer
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        slide_data = json.loads(content)
        logger.info(f"Contenu genere: {slide_data.get('title', 'N/A')}")

        return slide_data

    except Exception as e:
        logger.error(f"Erreur generation contenu: {e}")
        # Fallback avec les hints
        return {
            "title": title_hint or event.get("summary", "")[:30],
            "text": content_hint or "Contenu en cours de generation..."
        }


def build_final_slides(merged_timeline: list, slide_plan: list) -> list:
    """
    Construit les slides finales a partir de la timeline et du plan.

    Args:
        merged_timeline: Liste d'evenements fusionnes
        slide_plan: Plan de slides (event_index, template, etc.)

    Returns:
        Liste de slides pretes pour l'affichage
    """
    slides = []

    for plan_item in slide_plan:
        event_index = plan_item.get("event_index", 0)

        if event_index >= len(merged_timeline):
            logger.warning(f"Index evenement invalide: {event_index}")
            continue

        event = merged_timeline[event_index]

        # Generer le contenu
        slide_content = generate_slide_content(event, plan_item)

        # Construire la slide
        slide = {
            "trigger_time": plan_item.get("trigger_time", event.get("start_time", 0)),
            "end_time": event.get("end_time", 0),
            "template_type": plan_item.get("template", "reflection"),
            "data": slide_content,
            "event_type": event.get("type"),
            "event_summary": event.get("summary"),
            "source_text": event.get("source_text", "")
        }

        slides.append(slide)

    # Trier par trigger_time
    slides.sort(key=lambda s: s.get("trigger_time", 0))

    logger.info(f"Slides finales construites: {len(slides)}")

    return slides
