#!/usr/bin/env python3
"""
Audit toutes les pipelines formation en DB et donne un verdict de santé.

Usage :
    python tools/pipeline_audit.py            # tous les jobs, format compact
    python tools/pipeline_audit.py --job 10   # détail d'un job précis
    python tools/pipeline_audit.py --broken   # uniquement les jobs en erreur

Codes couleur (terminal) :
- 🟢 vert  : santé OK, pipeline cohérente
- 🟡 jaune : warnings (incohérences mineures, ex: snapshot pre-review absent)
- 🔴 rouge : blocking (incohérence fatale, ex: cg_jobs idle, segments manquants)

Sortie ligne par ligne, scriptable. Code de sortie :
- 0 si tous les jobs audités sont OK
- 1 si au moins 1 job a des blocking issues
"""

import argparse
import os
import sys
from pathlib import Path

# Setup env (en cas de lancement hors backend/)
os.environ.setdefault("LOCAL_DEV", "true")
backend_root = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv
load_dotenv(backend_root / ".env")

from database.db import get_db_connection
from services.formation_health_service import compute_health


# ─── Helpers d'affichage ────────────────────────────────────────────────────

class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def status_emoji(blocking, warnings):
    if blocking:
        return f"{Color.RED}🔴{Color.RESET}"
    if warnings:
        return f"{Color.YELLOW}🟡{Color.RESET}"
    return f"{Color.GREEN}🟢{Color.RESET}"


def list_all_jobs():
    """Retourne (id, tp_name, status, platform_name) pour chaque job."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pj.id, pj.tp_name, pj.status, pj.nb_days, pj.total_hours,
               COALESCE(p.name, '?') AS platform_name
        FROM formation_pipeline_jobs pj
        LEFT JOIN platform_config p ON p.id = pj.platform_id
        ORDER BY pj.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


# Statuts pipeline qui sont supposés indiquer "tous les artefacts produits".
# Pour les autres statuts (init, kb_ready, daily_validated, error, etc.), un
# health-check négatif n'est PAS un bug — c'est juste que la pipeline n'a pas
# fini. On les marque "EN COURS" plutôt que "CASSÉ".
_FINAL_STATUSES = {"audio_launched", "done"}


def print_compact(jobs, only_broken=False):
    """Une ligne par job. Voit tout d'un coup."""
    print(f"\n{Color.BOLD}=== Audit santé pipelines formation ==={Color.RESET}")
    print(f"{Color.DIM}{'ID':<4} {'Status':<18} {'Days':<6} {'Plateforme':<35} {'Santé':<10} {'Issues':<40}{Color.RESET}")
    print(f"{Color.DIM}{'-'*4} {'-'*18} {'-'*6} {'-'*35} {'-'*10} {'-'*40}{Color.RESET}")

    n_ok = n_warn = n_broken = n_inprog = 0
    has_broken = False

    for jid, tp_name, status, nb_days, total_hours, platform_name in jobs:
        # Pipelines pas censées être finies → pas auditables comme "saines"
        is_final = status in _FINAL_STATUSES
        if not is_final:
            if only_broken:
                continue
            n_inprog += 1
            platform_short = platform_name[:33] + "…" if len(platform_name) > 33 else platform_name
            print(f"{jid:<4} {status:<18} {nb_days or '?':<6} {platform_short:<35} {Color.DIM}⏳ EN COURS{Color.RESET}  {Color.DIM}{status}{Color.RESET}")
            continue

        try:
            health = compute_health(jid)
        except Exception as e:
            print(f"{jid:<4} {status:<18} {nb_days or '?':<6} {platform_name[:33]:<35} {Color.RED}ERR{Color.RESET}        compute_health: {str(e)[:40]}")
            has_broken = True
            n_broken += 1
            continue

        blocking = health.get("blocking", [])
        warnings = health.get("warnings", [])
        emoji = status_emoji(blocking, warnings)

        if blocking:
            issue_str = f"{Color.RED}{', '.join(blocking)}{Color.RESET}"
            n_broken += 1
            has_broken = True
        elif warnings:
            issue_str = f"{Color.YELLOW}{', '.join(warnings)}{Color.RESET}"
            n_warn += 1
        else:
            issue_str = ""
            n_ok += 1

        if only_broken and not blocking:
            continue

        platform_short = platform_name[:33] + "…" if len(platform_name) > 33 else platform_name
        print(f"{jid:<4} {status:<18} {nb_days or '?':<6} {platform_short:<35} {emoji:<10} {issue_str}")

    print(f"\n{Color.BOLD}Total :{Color.RESET} 🟢 {n_ok} OK · 🟡 {n_warn} warning · 🔴 {n_broken} cassé(s) · ⏳ {n_inprog} en cours")
    return has_broken


def print_detail(jid):
    """Détail complet d'un job : tous les checks avec leur status."""
    print(f"\n{Color.BOLD}=== Health-check job {jid} ==={Color.RESET}")
    try:
        health = compute_health(jid)
    except Exception as e:
        print(f"{Color.RED}❌ Erreur compute_health : {e}{Color.RESET}")
        return True

    blocking = health.get("blocking", [])
    warnings = health.get("warnings", [])

    overall = status_emoji(blocking, warnings)
    print(f"\n{overall} Verdict : {'OK' if not blocking and not warnings else ('warnings' if not blocking else 'CASSÉ')}\n")

    for k, v in health.get("checks", {}).items():
        marker = f"{Color.GREEN}✓{Color.RESET}" if v["ok"] else f"{Color.RED}✗{Color.RESET}"
        if k in blocking:
            severity = f"{Color.RED}[BLOCKING]{Color.RESET}"
        elif k in warnings:
            severity = f"{Color.YELLOW}[WARNING]{Color.RESET}"
        else:
            severity = ""
        print(f"  {marker} {Color.BOLD}{k}{Color.RESET} {severity}")
        print(f"      {Color.DIM}{v['detail']}{Color.RESET}")

    if blocking:
        print(f"\n{Color.RED}🔴 {len(blocking)} incohérence(s) bloquante(s) — pipeline cassée{Color.RESET}")
    elif warnings:
        print(f"\n{Color.YELLOW}🟡 {len(warnings)} incohérence(s) mineure(s){Color.RESET}")
    else:
        print(f"\n{Color.GREEN}🟢 Pipeline en bonne santé{Color.RESET}")

    return bool(blocking)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit santé des pipelines formation")
    parser.add_argument("--job", type=int, help="Auditer un seul job (vue détaillée)")
    parser.add_argument("--broken", action="store_true", help="Afficher uniquement les jobs cassés")
    args = parser.parse_args()

    if args.job:
        broken = print_detail(args.job)
        sys.exit(1 if broken else 0)

    jobs = list_all_jobs()
    if not jobs:
        print("Aucun job formation dans la DB.")
        sys.exit(0)

    has_broken = print_compact(jobs, only_broken=args.broken)
    sys.exit(1 if has_broken else 0)


if __name__ == "__main__":
    main()
