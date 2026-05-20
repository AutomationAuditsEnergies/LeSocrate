"""Convertit les zones tutoyées résiduelles dans formation_jour1.txt et
formation_jour2.txt en vouvoiement, en PRÉSERVANT les citations entre
guillemets français « ... » (où le tutoiement est légitime : dialogue avec
un enfant, paroles d'un manager à son équipe, monologue interne du client,
métaphore boulanger/pain, etc.).

Stratégie : on extrait toutes les zones « ... » dans des placeholders avant
substitution, puis on remet les zones intactes après. Les substitutions
elles-mêmes sont des regex avec word boundaries strictes.
"""
from __future__ import annotations
import re
import uuid
from pathlib import Path

ROOT = Path("/Users/amelle/Desktop/SocrateReprise/LeSocrate/courstxt")
FILES = ["formation_jour1.txt", "formation_jour2.txt"]

# Aussi les citations entre " ... " (apostrophes droites) — moins fréquent
# mais présent. On capture aussi les « ... » classiques.
QUOTE_RE = re.compile(r"«[^»]*»")

SUBS: list[tuple[str, str]] = [
    # Verbes conjugués spécifiques (longs d'abord)
    (r"\bTu vas voir\b", "Vous allez voir"),
    (r"\btu vas voir\b", "vous allez voir"),
    (r"\btu vas développer\b", "vous allez développer"),
    (r"\btu vas les vivre\b", "vous allez les vivre"),
    (r"\bTu peux\b", "Vous pouvez"),
    (r"\btu peux\b", "vous pouvez"),
    (r"\btu auras\b", "vous aurez"),
    (r"\bTu as\b", "Vous avez"),
    (r"\btu as\b", "vous avez"),
    (r"\bTu prends\b", "Vous prenez"),
    (r"\bTu lui demandes\b", "Vous lui demandez"),
    (r"\bTu lui prépares\b", "Vous lui préparez"),
    (r"\bTu lui souris\b", "Vous lui souriez"),
    (r"\bTu lui parles\b", "Vous lui parlez"),
    (r"\btu lui souris\b", "vous lui souriez"),
    (r"\btu lui parles\b", "vous lui parlez"),
    (r"\btu lui demandes\b", "vous lui demandez"),
    (r"\btu lui prépares\b", "vous lui préparez"),
    (r"\btu lui expliques\b", "vous lui expliquez"),
    (r"\btu la glisses\b", "vous la glissez"),
    (r"\btu vends\b", "vous vendez"),
    (r"\btu crées\b", "vous créez"),
    (r"\bTu crées\b", "Vous créez"),
    (r"\btu apportes\b", "vous apportez"),
    (r"\btu transformes\b", "vous transformez"),
    (r"\bTu t'approches\b", "Vous vous approchez"),
    (r"\btu t'approches\b", "vous vous approchez"),
    (r"\btu demandes\b", "vous demandez"),
    (r"\btu proposes\b", "vous proposez"),
    (r"\btu donnes\b", "vous donnez"),
    (r"\btu nourris\b", "vous nourrissez"),
    (r"\btu rythmes\b", "vous rythmez"),
    (r"\btu enrichis\b", "vous enrichissez"),
    (r"\btu ne sais pas\b", "vous ne savez pas"),
    (r"\bTu l'accueilles\b", "Vous l'accueillez"),
    (r"\btu veux proposer\b", "vous voulez proposer"),
    # Verbes impératifs (début phrase / après ponctuation)
    (r"\bAdapte toujours\b", "Adaptez toujours"),
    (r"\bn'hésite pas\b", "n'hésitez pas"),
    (r"\bN'hésite pas\b", "N'hésitez pas"),
    (r"\bPréviens toujours\b", "Prévenez toujours"),
    (r"\bretiens\b", "retenez"),
    (r"\bRetiens\b", "Retenez"),
    (r"\bprends soin\b", "prenez soin"),
    (r"\bPrends soin\b", "Prenez soin"),
    (r"\bPratique-les\b", "Pratiquez-les"),
    (r"\baffine-les\b", "affinez-les"),
    (r"\bfais-les tiens\b", "faites-les vôtres"),
    (r"\binspire-toi\b", "inspirez-vous"),
    (r"\bChoisis toujours\b", "Choisissez toujours"),
    # Pronoms / possessifs
    (r"\bton conseil\b", "votre conseil"),
    (r"\bton sandwich\b", "votre sandwich"),
    (r"\bton métier\b", "votre métier"),
    (r"\bTon métier\b", "Votre métier"),
    (r"\bton propre style\b", "votre propre style"),
    (r"\bta propre façon\b", "votre propre façon"),
    (r"\bton rôle\b", "votre rôle"),
    (r"\bta carrière\b", "votre carrière"),
    # te / toi
    (r"\bil t'en voudra\b", "il vous en voudra"),
    (r"\bElle te demande\b", "Elle vous demande"),
    (r"\bIl te salue\b", "Il vous salue"),
    (r"\bIl t'explique\b", "Il vous explique"),
    (r"\bqui vont t'aider\b", "qui vont vous aider"),
    (r"\bÀ toi\b", "À vous"),
    # « c'est toi qui »
    (r"\bc'est toi qui\b", "c'est vous qui"),
]


def fix_one(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")

    # 1) On masque les citations « ... »
    placeholders: dict[str, str] = {}
    def mask(m: re.Match) -> str:
        key = f"__QUOTE_{uuid.uuid4().hex}__"
        placeholders[key] = m.group(0)
        return key
    masked = QUOTE_RE.sub(mask, text)

    # 2) On applique les substitutions
    total = 0
    for pattern, repl in SUBS:
        masked, n = re.subn(pattern, repl, masked)
        total += n
        if n:
            print(f"  {pattern!r:45} → {repl!r:30} ({n}×)")

    # 3) On remet les citations
    for key, original in placeholders.items():
        masked = masked.replace(key, original)

    path.write_text(masked, encoding="utf-8")
    return total, len(placeholders)


def main() -> int:
    for fname in FILES:
        print(f"\n=== {fname} ===")
        n_subs, n_quotes = fix_one(ROOT / fname)
        print(f"  → {n_subs} substitutions ; {n_quotes} citations « ... » préservées")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
