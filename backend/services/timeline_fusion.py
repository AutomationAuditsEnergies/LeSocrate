# timeline_fusion.py - Service de fusion des evenements aux frontieres de chunks
# Reconstitue la continuite semantique entre les blocs de transcription

from utils.logger import get_logger

logger = get_logger(__name__)


def fuse_events(all_chunks_events: list) -> list:
    """
    Fusionne les evenements aux frontieres de chunks.

    Algorithme:
    1. Parcourir les evenements de chaque chunk sequentiellement
    2. Si evenement N a continues_next=true ET evenement N+1 a continues_previous=true:
       - Fusionner en un seul evenement
       - Garder le type du premier (le debut definit le type)
       - Combiner les timecodes (start du 1er, end du dernier)
       - Concatener les summaries
       - Fusionner les keywords (sans doublons)
       - Concatener les source_text
    3. Les evenements peuvent s'etendre sur plus de 2 chunks

    Args:
        all_chunks_events: Liste de listes d'evenements, une liste par chunk

    Returns:
        Liste fusionnee d'evenements avec timecodes absolus
    """
    if not all_chunks_events:
        return []

    logger.info(f"Fusion de {len(all_chunks_events)} chunks")

    # Compter les evenements avant fusion
    total_before = sum(len(chunk) for chunk in all_chunks_events)
    logger.info(f"Evenements avant fusion: {total_before}")

    merged_timeline = []
    pending_event = None  # Evenement en attente de fusion

    for chunk_idx, chunk_events in enumerate(all_chunks_events):
        logger.debug(f"Traitement chunk #{chunk_idx} ({len(chunk_events)} evenements)")

        for event in chunk_events:
            if pending_event:
                # On a un evenement en attente de fusion
                if event.get("continues_previous", False):
                    # Fusion!
                    merged = merge_two_events(pending_event, event)
                    logger.debug(f"Fusion: {pending_event['type']} + continuation -> {merged['type']}")

                    if event.get("continues_next", False):
                        # L'evenement fusionne continue encore
                        pending_event = merged
                    else:
                        # Fin de la chaine de fusion
                        merged_timeline.append(merged)
                        pending_event = None
                else:
                    # Pas de continuation - l'evenement precedent etait peut-etre mal marque
                    # ou il y a eu une rupture semantique
                    logger.debug(f"Pas de continuation pour {pending_event['type']}, ajout tel quel")
                    merged_timeline.append(pending_event)
                    pending_event = None

                    # Traiter l'evenement courant
                    if event.get("continues_next", False):
                        pending_event = event
                    else:
                        merged_timeline.append(event)
            else:
                # Pas d'evenement en attente
                if event.get("continues_previous", False):
                    # Orphelin - continuation sans debut
                    logger.warning(f"Continuation orpheline ignoree: {event.get('type')}")
                    # On l'ajoute quand meme mais sans fusion
                    event["orphan_continuation"] = True
                    if event.get("continues_next", False):
                        pending_event = event
                    else:
                        merged_timeline.append(event)
                elif event.get("continues_next", False):
                    # Debut d'une chaine
                    pending_event = event
                else:
                    # Evenement complet
                    merged_timeline.append(event)

    # S'il reste un evenement en attente a la fin
    if pending_event:
        logger.debug(f"Evenement final en attente: {pending_event['type']}")
        pending_event["incomplete"] = True
        merged_timeline.append(pending_event)

    logger.info(f"Evenements apres fusion: {len(merged_timeline)}")

    # Stats de fusion
    fused_count = total_before - len(merged_timeline)
    if fused_count > 0:
        logger.info(f"Fusions effectuees: {fused_count} evenements fusionnes")

    return merged_timeline


def merge_two_events(event1: dict, event2: dict) -> dict:
    """
    Fusionne deux evenements en un seul.

    Args:
        event1: Premier evenement (avec continues_next=true)
        event2: Second evenement (avec continues_previous=true)

    Returns:
        Evenement fusionne
    """
    # Keywords uniques
    keywords1 = event1.get("keywords", [])
    keywords2 = event2.get("keywords", [])
    merged_keywords = list(dict.fromkeys(keywords1 + keywords2))  # Preserve order, remove dupes

    # Source text concatene
    source1 = event1.get("source_text", "")
    source2 = event2.get("source_text", "")
    merged_source = f"{source1} {source2}".strip()

    # Summary concatene (avec separation)
    summary1 = event1.get("summary", "")
    summary2 = event2.get("summary", "")

    # Eviter la repetition si les summaries sont similaires
    if summary1.lower() in summary2.lower() or summary2.lower() in summary1.lower():
        merged_summary = summary1 if len(summary1) >= len(summary2) else summary2
    else:
        merged_summary = f"{summary1} {summary2}".strip()

    return {
        "type": event1.get("type"),  # Le type du premier definit le type global
        "start_time": event1.get("start_time"),
        "end_time": event2.get("end_time"),
        "summary": merged_summary,
        "keywords": merged_keywords,
        "source_text": merged_source,
        "continues_previous": event1.get("continues_previous", False),
        "continues_next": event2.get("continues_next", False),
        "chunk_indices": list(set(
            [event1.get("chunk_index", 0)] +
            event1.get("chunk_indices", []) +
            [event2.get("chunk_index", 0)] +
            event2.get("chunk_indices", [])
        )),
        "fused": True  # Marqueur pour debug
    }


def get_timeline_summary(timeline: list) -> str:
    """
    Genere un resume de la timeline pour debug.
    """
    lines = ["Timeline fusionnee:"]

    for i, event in enumerate(timeline):
        start = event.get("start_time", 0)
        end = event.get("end_time", 0)
        etype = event.get("type", "?")
        summary = event.get("summary", "")[:60]
        fused = " [FUSED]" if event.get("fused") else ""
        incomplete = " [INCOMPLETE]" if event.get("incomplete") else ""

        start_str = f"{int(start//60)}:{int(start%60):02d}"
        end_str = f"{int(end//60)}:{int(end%60):02d}"
        duration = end - start

        lines.append(f"  {i+1}. [{start_str}-{end_str}] ({duration:.0f}s) {etype}{fused}{incomplete}")
        lines.append(f"      -> {summary}...")

    return "\n".join(lines)


def validate_timeline(timeline: list) -> dict:
    """
    Valide la coherence de la timeline fusionnee.

    Returns:
        Dict avec les resultats de validation
    """
    issues = []

    # Verifier l'ordre chronologique
    prev_end = 0
    for i, event in enumerate(timeline):
        start = event.get("start_time", 0)
        end = event.get("end_time", 0)

        if start < prev_end - 1:  # Tolerance de 1 seconde
            issues.append(f"Evenement {i+1}: chevauchement detecte (start={start:.1f} < prev_end={prev_end:.1f})")

        if end < start:
            issues.append(f"Evenement {i+1}: fin avant debut (start={start:.1f} > end={end:.1f})")

        prev_end = end

    # Verifier les types
    valid_types = [
        # Types pedagogiques de base
        "recap", "story", "definition", "concept", "example",
        "process", "comparison", "data",
        # Types narratifs/rhetoriques
        "analogy", "warning", "tip", "opinion",
        # Types structurels
        "transition", "filler"
    ]

    for i, event in enumerate(timeline):
        if event.get("type") not in valid_types:
            issues.append(f"Evenement {i+1}: type invalide '{event.get('type')}'")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "event_count": len(timeline)
    }
