"""Convertit la zone tutoyée (L5-L130 environ) du formation_jour2.txt en vouvoiement.

Stratégie : on travaille uniquement sur les ~130 premières lignes (zone problématique
identifiée par l'audit qualité), et on applique des substitutions ciblées avec word
boundaries pour éviter les collisions avec « Tutoyer », « statut », « Toutefois », etc.
Le reste du fichier est déjà au vouvoiement et n'est pas touché.
"""
from __future__ import annotations
import re
from pathlib import Path

SRC = Path("/Users/amelle/Desktop/SocrateReprise/LeSocrate/courstxt/formation_jour2.txt")
LINE_MAX = 130  # zone tutoyée détectée par l'audit, on stoppe au-delà

# Substitutions ordonnées (les plus longues / spécifiques d'abord pour éviter
# qu'un remplacement plus court n'amorce un mismatch).
SUBS: list[tuple[str, str]] = [
    # Pronoms / déterminants génériques (word boundary stricte)
    (r"\bTu vois\b", "Vous voyez"),
    (r"\btu vois\b", "vous voyez"),
    (r"\bTu peux\b", "Vous pouvez"),
    (r"\btu peux\b", "vous pouvez"),
    (r"\btu dois\b", "vous devez"),
    (r"\bTu dois\b", "Vous devez"),
    (r"\btu vas voir\b", "vous allez voir"),
    (r"\bTu vas voir\b", "Vous allez voir"),
    (r"\btu vends\b", "vous vendez"),
    (r"\btu lui demandes\b", "vous lui demandez"),
    (r"\btu as compris\b", "vous avez compris"),
    (r"\btu réfléchis\b", "vous réfléchissez"),
    (r"\btu élèves\b", "vous élevez"),
    (r"\btu proposes\b", "vous proposez"),
    (r"\btu finis\b", "vous finissez"),
    (r"\btu fais\b", "vous faites"),
    (r"\bTu fais\b", "Vous faites"),
    (r"\btu les aides\b", "vous les aidez"),
    (r"\btu leur simplifies\b", "vous leur simplifiez"),
    (r"\btu défendrais\b", "vous défendriez"),
    (r"\btu adores\b", "vous adorez"),
    (r"\bTu adores\b", "Vous adorez"),
    (r"\btu peux vraiment\b", "vous pouvez vraiment"),
    # Verbes impératifs (début de phrase ou après ponctuation)
    (r"\bPrends le temps\b", "Prenez le temps"),
    (r"\bÉcoute vraiment\b", "Écoutez vraiment"),
    (r"\bÉcoute les mots\b", "Écoutez les mots"),
    (r"\béécoute les pauses\b", "écoutez les pauses"),  # safety, sans accent
    (r"\bécoute les pauses\b", "écoutez les pauses"),
    (r"\bécoute ce qui n'est pas dit\b", "écoutez ce qui n'est pas dit"),
    (r"\bRaconte le produit\b", "Racontez le produit"),
    (r"\bne les sous-estime jamais\b", "ne les sous-estimez jamais"),
    (r"\bne lui vends pas\b", "ne lui vendez pas"),
    (r"\bNe lui propose pas\b", "Ne lui proposez pas"),
    (r"\bPropose-lui\b", "Proposez-lui"),
    (r"\bSimplifie\.", "Simplifiez."),
    (r"\bRésume\.", "Résumez."),
    (r"\bGuide\.", "Guidez."),
    (r"\bne te permets\b", "ne vous permettez"),
    (r"\bsois toujours chaleureux\b", "soyez toujours chaleureux"),
    (r"\bconseille plutôt\b", "conseillez plutôt"),
    # Pronoms / possessifs
    (r"\bton rôle\b", "votre rôle"),
    (r"\btes conseils\b", "vos conseils"),
    (r"\bton pain\b", "votre pain"),
    (r"\bta longue journée\b", "votre longue journée"),
    (r"\bavec toi\b", "avec vous"),
    (r"\bque toi\b", "que vous"),
    (r"\bparleront de toi\b", "parleront de vous"),
    # « te dit » → « vous dit » dans des constructions « un client te dit »
    (r"\bclient te dit\b", "client vous dit"),
    (r"\bil te dit\b", "il vous dit"),
    (r"\bs'il te dit\b", "s'il vous dit"),
    (r"\bS'il te dit\b", "S'il vous dit"),
]


def main() -> int:
    text = SRC.read_text(encoding="utf-8")
    lines = text.split("\n")

    # On découpe sur LINE_MAX (en gardant la marge pour ne pas trop loin)
    head = "\n".join(lines[:LINE_MAX])
    tail = "\n".join(lines[LINE_MAX:])

    fixed = head
    total = 0
    for pattern, repl in SUBS:
        fixed, n = re.subn(pattern, repl, fixed)
        if n:
            total += n
            print(f"  {pattern!r:50} → {repl!r:25} ({n}×)")

    SRC.write_text(fixed + "\n" + tail, encoding="utf-8")
    print(f"\nTotal : {total} substitutions appliquées dans les {LINE_MAX} premières lignes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
