"""
Service de closing contextuel pour fin de bloc cours.

Quand un bloc cours, après cap budget cascade et redistribution backward, finit
toujours avant son créneau audio cible, on ajoute une **transition pédagogique** au
texte du bloc lui-même (PAS dans le fichier de pause). Le bloc se termine ainsi
proprement, sur une vraie clôture, plutôt que sur du silence padding.

Calibration du closing selon la taille du gap résiduel :

| Gap résiduel    | Registre                  | Cible mots | Source       |
|-----------------|---------------------------|------------|--------------|
| < 15 s          | Aucun (silence padding)   | 0          | —            |
| 15–45 s         | Phrase de clôture courte  | 30–100     | Template     |
| 45–120 s        | Transition pédagogique    | 130–360    | LLM          |
| 120–300 s       | Recap + respiration       | 360–900    | LLM          |
| Bloc 7 final    | Conclusion de journée     | selon gap  | LLM          |

La fin du cours tient aussi compte de l'élément suivant dans la playlist :
si une Q&A ou une pause arrive, c'est le cours qui l'annonce sobrement.
"""

import re
from utils.anthropic_client import default_model, post_message as _llm_post, AnthropicAPIError
from utils.logger import get_logger

logger = get_logger(__name__)

# Seuils en secondes
GAP_NEGLIGIBLE_SEC = 15
GAP_SHORT_SEC = 45
GAP_MEDIUM_SEC = 120

# Coefficient de remplissage : le gap est déjà calculé jusqu'à la dernière
# parole visée. On le remplit presque entièrement, en gardant une
# petite marge de sécurité.
GAP_FILL_RATIO = 0.92
# wpm Fish Audio calibré pour la voix/vitesse de production.
WPM_REFERENCE = 165.7
# Cap absolu du closing : ~4 min audio max. Au-delà, le résidu reste silence
# (un gap > 5 min signale un volume_safety insuffisant en amont, pas un closing à
# rallonge pédagogiquement absurde).
MAX_CLOSING_WORDS = 700
_FORBIDDEN_DEICTIC_RE = re.compile(r"\b(hier|demain)\b", re.IGNORECASE)


# Templates pour le cas court (15-45 s) — cycle déterministe par bloc
_SHORT_CLOSINGS = [
    "On va s'arrêter ici pour le moment, prenez le temps d'intégrer ce qu'on vient de voir.",
    "On va s'arrêter ici pour cette partie, avec ces repères bien en tête.",
    "C'est l'essentiel sur ce point. Gardez cette logique, elle servira pour la suite.",
    "On a posé une base importante ici, et elle va éclairer les notions suivantes.",
    "On va fermer cette partie tranquillement, sans perdre le fil de ce qu'on vient de construire.",
]


def _words_target_for_gap(gap_sec):
    """Nombre de mots cible pour combler ~80% du gap audio (cap à MAX_CLOSING_WORDS)."""
    raw = int((gap_sec * GAP_FILL_RATIO / 60) * WPM_REFERENCE)
    return min(raw, MAX_CLOSING_WORDS)


def _short_closing_for_bloc(bloc_num):
    """Phrase courte cyclée par numéro de bloc (déterministe, pas d'appel LLM)."""
    return _SHORT_CLOSINGS[(bloc_num - 1) % len(_SHORT_CLOSINGS)]


def _item_type(item) -> str | None:
    try:
        return item[2]
    except Exception:
        return None


def _item_duration(item) -> int:
    try:
        return int(item[1] or 0)
    except Exception:
        return 0


def _handoff_sentence(next_item) -> str:
    next_type = _item_type(next_item)
    duration_sec = _item_duration(next_item)
    if next_type in {"qa", "pause", "pause_midi"}:
        try:
            from services.content_generation_service import _break_intro_text_for_playlist_item
            planned_intro = _break_intro_text_for_playlist_item(next_item)
        except Exception:
            planned_intro = ""
        if planned_intro:
            return planned_intro
        try:
            from services.break_transition_service import duration_label
            label = duration_label(duration_sec, next_type)
        except Exception:
            label = ""
        if next_type == "qa":
            return (
                "On va maintenant prendre un temps pour vos questions. "
                "Gardez les points importants en tête, et posez ce que vous voulez clarifier."
            )
        if next_type == "pause_midi" or label == "pause déjeuner":
            return (
                "On va maintenant marquer la pause déjeuner. "
                "Prenez le temps de souffler, et on reprendra ensuite calmement."
            )
        if label:
            return f"On va maintenant prendre une pause de {label}. Profitez-en pour souffler un peu."
        return "On va maintenant prendre une courte pause. Profitez-en pour souffler un peu."
    if next_type == "cours":
        return "On enchaînera ensuite avec la suite du parcours, en gardant cette base comme appui."
    return ""


def _handoff_instruction(next_item) -> str:
    sentence = _handoff_sentence(next_item)
    if not sentence:
        return (
            "Termine sans annoncer de logistique particulière, simplement avec "
            "une fermeture pédagogique naturelle."
        )
    return (
        "Termine avec cette transition de playlist, reformulée naturellement si besoin : "
        f"{sentence} "
        "N'ajoute pas d'horaire absolu. Si c'est une pause, rappelle-toi que le "
        "fichier pause suivant ne refera pas d'intro."
    )


def _append_handoff_if_missing(text: str, next_item) -> str:
    handoff = _handoff_sentence(next_item)
    if not handoff:
        return text
    if handoff.lower() in (text or "").lower():
        return text
    return f"{(text or '').rstrip()} {handoff}".strip()


def _build_medium_prompt(prev_excerpt, next_excerpt, target_words, next_handoff_instruction):
    return f"""Tu es un formateur en classe virtuelle audio. Les apprenants sont
des adultes en formation professionnelle, qui suivent un cours horodaté à
distance. Le bloc actuel se termine. Génère une CLÔTURE PÉDAGOGIQUE douce
de fin de bloc.

CE QUI VIENT D'ÊTRE VU (fin du bloc) :
---
{prev_excerpt}
---

CE QUI ARRIVE ENSUITE (début du bloc suivant) :
---
{next_excerpt or "(pas de bloc suivant — c'est bientôt la fin de journée)"}
---

CONSIGNES :
- Vise environ {target_words} mots (±15%).
- Ton clair, posé, comme un formateur adulte en classe virtuelle audio.
- Applique les règles d'humanisation : respiration, phrases simples,
  micro-interactions sobres, pas d'effet conférence ni accumulation de slogans.
- Fais une mini-synthèse (2-3 idées clés DU BLOC qui vient de se terminer).
- Termine par une petite phrase d'ouverture pédagogique vers la suite.
- TRANSITION PLAYLIST : {next_handoff_instruction}
- Ne présente jamais cette notion suivante comme l'audio immédiatement suivant :
  l'ordre des fichiers peut varier selon le mode été/hiver.
- PAS de "Voilà pour cette partie" générique.
- Termine sans sécheresse, avec la transition playlist demandée si elle existe.
- Pas de tag TTS spécifique, juste du texte oral fluide.
- Ne dis jamais "hier" ni "demain" ; utilise "la dernière fois", "lors du
  dernier cours" ou "au prochain cours" si nécessaire.
- N'invente jamais une échéance d'examen, un passage devant jury ou un contexte
  de certification daté qui n'apparaît pas explicitement dans l'extrait.
- Ne parle de "questions", "questions-réponses", "pause" ou "chat" QUE si la
  TRANSITION PLAYLIST ci-dessus le demande.

Réponds UNIQUEMENT par le texte de la transition, rien d'autre (ni intro, ni explication)."""


def _build_long_prompt(prev_excerpt, next_excerpt, target_words, gap_sec, next_handoff_instruction):
    return f"""Tu es un formateur en classe virtuelle audio. Les apprenants sont
des adultes en formation professionnelle, qui suivent un cours horodaté à
distance. Le bloc actuel se termine plus tôt que prévu — tu as
~{int(gap_sec)} secondes à combler avec un RECAP PÉDAGOGIQUE substantiel
+ une respiration + une ouverture pédagogique.

CE QUI VIENT D'ÊTRE VU (fin du bloc) :
---
{prev_excerpt}
---

CE QUI ARRIVE ENSUITE (début du bloc suivant) :
---
{next_excerpt or "(pas de bloc suivant — c'est bientôt la fin de journée)"}
---

STRUCTURE ATTENDUE (~{target_words} mots, ±15%) :
1. **Récap explicite** : "Avant qu'on passe à la suite, je vais reprendre les points
   clés de ce qu'on vient de voir." Puis 2-3 points clés du bloc, formulés comme
   un vrai prof (pas une liste à puces, mais des phrases qui s'enchaînent).
2. **Respiration pédagogique** : "C'est beaucoup d'informations d'un coup, prenez
   un instant pour digérer." Ou similaire — invite l'apprenant à intégrer.
3. **Ouverture** : référence pédagogique à ce qui sera utile ensuite, sans
   annoncer de Q&A, de pause ou de chat sauf si la transition playlist le demande.
   Ne présente jamais cette suite comme l'audio immédiatement suivant : l'ordre
   des fichiers peut varier selon le mode été/hiver.
4. **Transition playlist** : {next_handoff_instruction}

TON :
- Clair, posé, formateur adulte en classe virtuelle audio.
- Humanisé : ralentis, rassure, laisse vivre les idées importantes, ajoute des
  respirations naturelles quand c'est utile.
- Pas de "Voilà pour cette partie" générique.
- Pas d'énumération mécanique ("Premier point... Deuxième point...").
- Pas de discours direct entre guillemets (TTS le lirait littéralement).
- Ne dis jamais "hier" ni "demain" ; utilise "la dernière fois", "lors du
  dernier cours" ou "au prochain cours" si nécessaire.
- N'invente jamais une échéance d'examen, un passage devant jury ou un contexte
  de certification daté qui n'apparaît pas explicitement dans l'extrait.
- Ne parle de "questions", "questions-réponses", "pause" ou "chat" QUE si la
  TRANSITION PLAYLIST ci-dessus le demande.

Réponds UNIQUEMENT par le texte du recap, rien d'autre."""


def _build_conclusion_prompt(prev_excerpt, target_words, gap_sec, next_handoff_instruction):
    return f"""Tu es un formateur en classe virtuelle audio. Les apprenants sont
des adultes en formation professionnelle, qui suivent un cours horodaté à
distance. C'est le DERNIER BLOC de la journée et il finit ~{int(gap_sec)}
secondes plus tôt que le créneau audio. Tu vas faire une CONCLUSION DE JOURNÉE.

CE QUI VIENT D'ÊTRE VU (fin de la journée) :
---
{prev_excerpt}
---

STRUCTURE ATTENDUE (~{target_words} mots, ±15%) :
1. **Synthèse globale de la journée** (PAS seulement du dernier bloc — toute la
   journée). 3-4 grandes idées qu'on a couvertes, formulées en phrases liées.
2. **Encouragement** : reconnaître l'effort fourni, valoriser les progrès.
3. **Transition playlist** : {next_handoff_instruction}
4. **Annonce de la suite pédagogique** : si utile, projette vers le prochain cours
   sans dire "demain" ni "hier".

TON :
- Clair, posé, formateur adulte qui clôt une journée de classe virtuelle audio.
- Conclusion progressive : ralentissement, synthèse, valorisation du chemin
  parcouru, projection vers la suite.
- Pas mécanique ni grandiloquent.
- Pas de discours direct entre guillemets.
- Ne dis jamais "hier" ni "demain".
- N'invente jamais une échéance d'examen, un passage devant jury ou un contexte
  de certification daté qui n'apparaît pas explicitement dans l'extrait.
- Ne dis pas "je vous vois", "levez la main", "vous m'entendez", ni aucune
  formule qui suppose une présence physique ou une visio.

Réponds UNIQUEMENT par le texte de la conclusion."""


def _clean_closing_text(text):
    """Retire les artefacts éventuels (markdown, préambule LLM)."""
    text = text.strip()
    # Retirer un éventuel préambule du genre "Voici la transition :" ou "```"
    text = re.sub(r"^(voici|here is|here's)[^.\n]*[:.]\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "").strip()
    return text


def _has_forbidden_deictic_marker(text):
    """Empêche les closings qui inventent un "demain" ou un "hier" daté."""
    return bool(_FORBIDDEN_DEICTIC_RE.search(text or ""))


def _fallback_for_gap(gap_sec, is_last_bloc, bloc_num):
    """Fallback statique si le LLM échoue. Choisi selon la taille du gap."""
    if gap_sec < GAP_SHORT_SEC:
        return _short_closing_for_bloc(bloc_num)
    if is_last_bloc:
        return (
            "Et voilà pour cette journée. On a couvert beaucoup de notions, "
            "prenez le temps de les laisser décanter d'ici le prochain cours. "
            "Bonne fin de journée à tous."
        )
    return (
        "On a vu pas mal de choses dans ce bloc. Prenez un instant pour intégrer, "
        "et on garde ces repères pour la suite du parcours."
    )


def generate_closing(
    bloc_num,
    prev_excerpt,
    next_excerpt,
    gap_sec,
    is_last_bloc=False,
    model=None,
    max_words=None,
    next_item=None,
):
    """
    Génère le texte de closing à concaténer au bloc cours.

    Args:
        bloc_num: numéro du bloc (1-7).
        prev_excerpt: ~150-200 derniers mots du bloc (synthèse implicite du contenu).
        next_excerpt: ~150-200 premiers mots du bloc suivant (None si dernier bloc).
        gap_sec: secondes à combler dans le créneau audio.
        is_last_bloc: True pour le bloc 7 → conclusion de journée.
        model: identifiant du modèle LLM (None = défaut).
        max_words: cap optionnel pour rester sous le budget TTS prudent du bloc.
        next_item: élément suivant de la playlist effective (filename, duration,
            type, bloc_number), pour annoncer Q&A/pause au bon endroit.

    Returns:
        str — texte du closing (vide si gap < seuil négligeable).
    """
    if gap_sec < GAP_NEGLIGIBLE_SEC:
        return ""

    target_words = max(20, _words_target_for_gap(gap_sec))
    if max_words is not None:
        target_words = min(target_words, max(0, int(max_words)))

    if target_words < 20:
        return ""

    # Cas court : pas de LLM, template déterministe
    if gap_sec < GAP_SHORT_SEC and not is_last_bloc:
        closing = _append_handoff_if_missing(_short_closing_for_bloc(bloc_num), next_item)
        if max_words is not None and len(closing.split()) > max_words:
            return ""
        logger.info(f"   📝 Closing bloc {bloc_num} (gap {gap_sec:.0f}s, court) : template")
        return closing

    # Cas moyen / long / conclusion : LLM
    handoff_instruction = _handoff_instruction(next_item)
    if is_last_bloc:
        prompt = _build_conclusion_prompt(prev_excerpt, target_words, gap_sec, handoff_instruction)
        registre = "conclusion"
    elif gap_sec < GAP_MEDIUM_SEC:
        prompt = _build_medium_prompt(prev_excerpt, next_excerpt, target_words, handoff_instruction)
        registre = "moyen"
    else:
        prompt = _build_long_prompt(prev_excerpt, next_excerpt, target_words, gap_sec, handoff_instruction)
        registre = "long"

    try:
        text = _llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(target_words * 2.5) + 200,
            model=model or default_model(),
        )
        text = _clean_closing_text(text or "")
        if not text:
            raise ValueError("LLM closing empty")
        if _has_forbidden_deictic_marker(text):
            raise ValueError("LLM closing contains forbidden temporal marker")
        text = _append_handoff_if_missing(text, next_item)
        if max_words is not None and len(text.split()) > max_words:
            text = " ".join(text.split()[:max_words])
        logger.info(
            f"   📝 Closing bloc {bloc_num} (gap {gap_sec:.0f}s, {registre}) : "
            f"{len(text.split())} mots générés"
        )
        return text
    except (AnthropicAPIError, Exception) as e:
        logger.warning(
            f"   ⚠️ Closing bloc {bloc_num} (gap {gap_sec:.0f}s, {registre}) "
            f"échec LLM ({type(e).__name__}: {str(e)[:120]}), fallback"
        )
        text = _append_handoff_if_missing(
            _fallback_for_gap(gap_sec, is_last_bloc, bloc_num),
            next_item,
        )
        if max_words is not None and len(text.split()) > max_words:
            text = " ".join(text.split()[:max_words])
        return text
