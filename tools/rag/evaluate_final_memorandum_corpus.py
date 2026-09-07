#!/usr/bin/env python3
"""
Corpus final d'évaluation RAG pour le mémoire.

Compare trois modes Azure AI Search:
- bm25   : recherche textuelle simple
- vector : recherche vectorielle seule sur text_vector
- hybrid : BM25 + vectoriel, fusion RRF

Le corpus est injecté temporairement dans l'index puis supprimé.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


LEXICAL_CASES = [
    ("META-BQ9-QUALITE", "transmettre une alerte qualité au responsable de plateau"),
    ("META-AX7-PRIORITE", "ouvrir une médiation prioritaire sous vingt-quatre heures"),
    ("META-CM4-SUIVI", "programmer un rappel de suivi dans les deux jours ouvrés"),
    ("META-DN2-CLOTURE", "clôturer le dossier après validation explicite du client"),
    ("META-EP8-TRANSFERT", "transférer la demande vers le service expert"),
    ("META-FR6-RGPD", "limiter la collecte aux seules informations nécessaires"),
    ("META-GH3-CRM", "mettre à jour le dossier client avant la fin de l'appel"),
    ("META-JK8-RECLAM", "ouvrir une fiche de réclamation prioritaire"),
    ("META-LM2-SUPERV", "solliciter une validation superviseur"),
    ("META-NP5-RAPPEL", "planifier un rappel client le lendemain matin"),
]

SEMANTIC_CASES = [
    {
        "suffix": "sem-client-vulnerable",
        "title": "Client vulnérable et compréhension",
        "chunk": "Face à une personne en difficulté de compréhension, le conseiller ralentit le rythme, utilise des phrases courtes, vérifie chaque étape et laisse au client le temps de répondre.",
        "question": "Comment aider une personne qui comprend difficilement les consignes ?",
        "distractor": "Comprendre difficilement les consignes peut arriver dans un manuel technique ou une notice. Ce passage répète les mots de la question mais ne parle pas d'accompagnement client.",
    },
    {
        "suffix": "sem-fatigue-emotionnelle",
        "title": "Fatigue émotionnelle du conseiller",
        "chunk": "Après plusieurs interactions difficiles, le conseiller peut ressentir une saturation relationnelle : baisse d'écoute, parole mécanique, irritabilité discrète et difficulté à rester disponible.",
        "question": "Quels signes montrent qu'un conseiller commence à être épuisé par les échanges difficiles ?",
        "distractor": "Un échange difficile peut concerner une facture, une livraison ou un remboursement. Ce passage mentionne des signes administratifs mais pas l'épuisement émotionnel.",
    },
    {
        "suffix": "sem-confiance-client",
        "title": "Construction de la confiance",
        "chunk": "La confiance se construit lorsque le client constate que le conseiller tient ses engagements, reformule correctement la demande et annonce des délais réalistes.",
        "question": "Comment rassurer quelqu'un qui doute de la promesse faite au téléphone ?",
        "distractor": "Une promesse faite au téléphone peut être une offre commerciale ou un rendez-vous. Ce passage reprend les mots promesse et téléphone sans expliquer la confiance.",
    },
    {
        "suffix": "sem-ecoute-active",
        "title": "Écoute active avant solution",
        "chunk": "L'écoute active consiste à laisser le client terminer son explication, repérer le besoin principal, reformuler sans déformer et vérifier la compréhension avant de proposer une solution.",
        "question": "Que doit faire un conseiller avant de proposer une solution à un client confus ?",
        "distractor": "Proposer une solution à un client confus peut être rapide si un catalogue standard existe. Ce passage reprend les mots mais ne décrit pas l'écoute active.",
    },
    {
        "suffix": "sem-hors-perimetre",
        "title": "Orientation hors périmètre",
        "chunk": "Quand une demande dépasse son périmètre, le conseiller explique la limite de son rôle, oriente vers le bon interlocuteur et confirme au client que le suivi sera transmis.",
        "question": "Comment éviter de donner l'impression d'abandonner le client quand on ne peut pas traiter sa demande ?",
        "distractor": "Abandonner le client peut donner une mauvaise impression dans une demande difficile. Ce texte répète les mots sans donner de méthode d'orientation.",
    },
    {
        "suffix": "sem-clarte-pedagogique",
        "title": "Clarté pédagogique",
        "chunk": "Pour rendre une consigne compréhensible, le formateur découpe l'explication en étapes, utilise des phrases courtes, donne un exemple concret et vérifie la reformulation.",
        "question": "Comment expliquer simplement une tâche à quelqu'un qui n'a pas compris la première fois ?",
        "distractor": "Expliquer simplement une tâche peut vouloir dire lire plus lentement une notice. Ce passage ne parle pas de découpage pédagogique.",
    },
    {
        "suffix": "sem-desamorcage",
        "title": "Désamorçage émotionnel",
        "chunk": "Désamorcer une tension suppose de reconnaître l'émotion exprimée, recadrer calmement le problème et proposer une prochaine étape claire sans se justifier trop vite.",
        "question": "Que répondre à une personne énervée pour faire redescendre la tension ?",
        "distractor": "Une personne énervée peut faire redescendre la tension après une pause. Ce passage reprend les mots mais ne décrit pas de méthode de désamorçage.",
    },
    {
        "suffix": "sem-tracabilite",
        "title": "Trace après échange sensible",
        "chunk": "Après un échange sensible, la note de suivi doit préciser la demande, l'engagement pris, le délai annoncé et le service responsable pour éviter une perte d'information.",
        "question": "Pourquoi écrire ce qui a été promis après un appel compliqué ?",
        "distractor": "Un appel compliqué peut nécessiter d'écrire un message de politesse. Ce passage reprend appel et écrire sans traiter la traçabilité.",
    },
    {
        "suffix": "sem-voix-calme",
        "title": "Voix calme et régulation",
        "chunk": "Une voix posée, stable et lente peut aider à réguler l'interaction avec un client agité en créant un repère émotionnel plus sécurisant.",
        "question": "Comment un ton posé peut-il apaiser une personne stressée au téléphone ?",
        "distractor": "Un ton posé au téléphone peut améliorer la lecture d'un script commercial. Ce passage contient ton posé et téléphone mais pas la régulation émotionnelle.",
    },
    {
        "suffix": "sem-reformulation",
        "title": "Reformulation fiable",
        "chunk": "Reformuler consiste à redire avec ses propres mots le besoin du client afin de vérifier que la demande a été comprise avant de poursuivre le traitement.",
        "question": "Pourquoi répéter autrement ce que le client vient d'expliquer ?",
        "distractor": "Répéter autrement une phrase peut être un exercice de style ou de diction. Ce passage ne parle pas de validation du besoin client.",
    },
]

MIXED_CASES = [
    ("CRM", "trace-crm", "Après une réclamation transmise entre équipes, le CRM doit contenir la demande, le service responsable et l'engagement annoncé afin de conserver une trace exploitable.", "Pourquoi garder une trace dans le CRM lorsqu'une réclamation passe entre plusieurs équipes ?"),
    ("RGPD", "rgpd-minimisation", "Lorsqu'il applique le RGPD, le conseiller limite les données demandées à ce qui est nécessaire pour traiter le dossier et évite les détails personnels inutiles.", "Pourquoi le RGPD oblige-t-il à ne demander que les informations nécessaires au client ?"),
    ("QSAT-5", "qsat-cloture", "La procédure QSAT-5 impose de vérifier la satisfaction du client avant la clôture : reformuler la solution, demander validation et noter le résultat.", "Comment utiliser QSAT-5 pour vérifier qu'un client accepte la solution avant de fermer le dossier ?"),
    ("ROE", "roe-hors-perimetre", "La méthode ROE aide à traiter une demande hors périmètre : refuser avec raison, orienter vers le bon interlocuteur et expliquer pourquoi ce transfert aide le client.", "Comment la méthode ROE évite-t-elle de laisser un client sans réponse quand la demande sort du périmètre ?"),
    ("VTRC", "vtrc-cloture", "La méthode VTRC structure la fin d'un appel difficile : vérifier, tracer, rassurer puis congédier avec une formule claire et professionnelle.", "Pourquoi VTRC aide-t-il à terminer correctement un appel difficile ?"),
    ("SNA", "sna-voix", "La régulation du SNA influence la voix du conseiller : un état plus stable favorise un débit plus posé, un timbre plus calme et une meilleure écoute.", "Quel lien existe entre le SNA et la voix calme du conseiller ?"),
    ("CRM-TRACE", "crm-trace-code", "Le repère CRM-TRACE indique qu'un échange sensible doit être documenté immédiatement pour éviter une perte d'information entre deux services.", "Que signifie CRM-TRACE quand une demande sensible doit être transmise ?"),
    ("ECALM-4", "ecalm-desamorcage", "Le repère ECALM-4 désigne quatre gestes de désamorçage : écouter, calmer, analyser la demande et lancer la prochaine étape.", "Comment ECALM-4 aide-t-il à faire redescendre une tension client ?"),
    ("RGPD-MIN", "rgpd-min-code", "Le repère RGPD-MIN rappelle que la collecte minimale protège le client et réduit les risques liés aux données personnelles.", "Pourquoi RGPD-MIN est-il utile quand on demande des informations personnelles ?"),
    ("ECH-3X", "ech3x-escalade", "Le repère ECH-3X structure l'escalade en trois temps : reconnaître la difficulté, transférer au bon niveau et confirmer le suivi au client.", "Comment ECH-3X organise-t-il le transfert d'une demande complexe ?"),
]


def build_corpus() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    docs: list[dict[str, str]] = []
    questions: list[dict[str, Any]] = []

    for i, (code, action) in enumerate(LEXICAL_CASES, start=1):
        suffix = f"lex-{i:02d}"
        docs.append(
            {
                "suffix": suffix,
                "title": f"Fiche procédure {code}",
                "chunk": (
                    "Cette fiche décrit une procédure interne de relation client. "
                    f"Lorsque cette fiche est sélectionnée, le conseiller doit {action}. "
                    "L'identifiant exact est volontairement porté par le titre, pas par le texte vectorisé."
                ),
            }
        )
        docs.append(
            {
                "suffix": f"{suffix}-distractor",
                "title": f"Fiche procédure voisine {code.replace('META', 'NOTE')}",
                "chunk": (
                    "Cette fiche voisine décrit aussi une procédure interne de relation client, "
                    "avec un vocabulaire très proche, mais elle ne correspond pas au bon identifiant."
                ),
            }
        )
        questions.append(
            {
                "id": f"lex_{i:02d}",
                "family": "lexical_metadata",
                "question": f"Quelle action correspond à {code} ?",
                "relevant_suffixes": [suffix],
                "justification": "Le code exact est dans le titre searchable mais pas dans le texte vectorisé; cela teste la précision lexicale.",
            }
        )

    for i, item in enumerate(SEMANTIC_CASES, start=1):
        docs.append({"suffix": item["suffix"], "title": item["title"], "chunk": item["chunk"]})
        docs.append(
            {
                "suffix": f"{item['suffix']}-distractor",
                "title": f"Distracteur sémantique {i}",
                "chunk": item["distractor"],
            }
        )
        questions.append(
            {
                "id": f"sem_{i:02d}",
                "family": "semantic_reformulation",
                "question": item["question"],
                "relevant_suffixes": [item["suffix"]],
                "justification": "La question reformule le bon passage; un distracteur reprend des mots exacts sans répondre réellement.",
            }
        )

    for i, (term, suffix, chunk, question) in enumerate(MIXED_CASES, start=1):
        docs.append({"suffix": suffix, "title": f"Cas mixte {term}", "chunk": chunk})
        docs.append(
            {
                "suffix": f"{suffix}-distractor",
                "title": f"Distracteur mixte {term}",
                "chunk": f"Ce passage contient le terme {term}, mais il l'emploie dans un contexte général sans répondre à l'intention précise de la question.",
            }
        )
        questions.append(
            {
                "id": f"mix_{i:02d}",
                "family": "mixed",
                "question": question,
                "relevant_suffixes": [suffix],
                "justification": "La question contient un terme exact et une intention sémantique; l'hybride doit combiner les deux signaux.",
            }
        )

    return docs, questions


DOCS, QUESTIONS = build_corpus()


def load_env() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / "backend" / ".env")
    required = [
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_API_KEY",
        "AZURE_SEARCH_INDEX_NAME",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit("Variables manquantes: " + ", ".join(missing))
    return {k: os.environ[k] for k in required}


def embedding(cfg: dict[str, str], text: str) -> list[float]:
    endpoint = cfg["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/"
    deployment = cfg["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
    url = f"{endpoint}openai/deployments/{deployment}/embeddings?api-version=2024-02-01"
    r = requests.post(
        url,
        headers={"api-key": cfg["AZURE_OPENAI_API_KEY"], "Content-Type": "application/json"},
        json={"input": text},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def index_url(cfg: dict[str, str]) -> str:
    endpoint = cfg["AZURE_SEARCH_ENDPOINT"].rstrip("/")
    index = cfg["AZURE_SEARCH_INDEX_NAME"]
    return f"{endpoint}/indexes/{index}/docs/index?api-version=2024-07-01"


def search_url(cfg: dict[str, str]) -> str:
    endpoint = cfg["AZURE_SEARCH_ENDPOINT"].rstrip("/")
    index = cfg["AZURE_SEARCH_INDEX_NAME"]
    return f"{endpoint}/indexes/{index}/docs/search?api-version=2024-07-01"


def upload_docs(cfg: dict[str, str], prefix: str) -> None:
    docs = []
    for doc in DOCS:
        docs.append(
            {
                "@search.action": "mergeOrUpload",
                "chunk_id": f"{prefix}-{doc['suffix']}",
                "parent_id": f"{prefix}-parent",
                "title": doc["title"],
                "chunk": doc["chunk"],
                "text_vector": embedding(cfg, doc["chunk"]),
            }
        )
    requests.post(
        index_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json={"value": docs},
        timeout=60,
    ).raise_for_status()


def delete_docs(cfg: dict[str, str], prefix: str) -> None:
    docs = [{"@search.action": "delete", "chunk_id": f"{prefix}-{doc['suffix']}"} for doc in DOCS]
    requests.post(
        index_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json={"value": docs},
        timeout=60,
    ).raise_for_status()


def run_search(
    cfg: dict[str, str],
    prefix: str,
    question: str,
    mode: str,
    top_k: int,
    hybrid_vector_weight: float,
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "filter": f"parent_id eq '{prefix}-parent'",
        "select": "chunk_id,title,chunk",
        "top": top_k,
    }
    if mode == "bm25":
        payload["search"] = question
    elif mode == "vector":
        payload["search"] = "*"
        payload["vectorQueries"] = [
            {"kind": "vector", "vector": embedding(cfg, question), "fields": "text_vector", "k": top_k}
        ]
    elif mode == "hybrid":
        payload["search"] = question
        payload["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": embedding(cfg, question),
                "fields": "text_vector",
                "k": top_k,
                "weight": hybrid_vector_weight,
            }
        ]
    else:
        raise ValueError(mode)
    r = requests.post(
        search_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("value", [])


def score(results: list[dict[str, Any]], relevant_ids: set[str], top_k: int) -> dict[str, Any]:
    returned = [r["chunk_id"] for r in results[:top_k]]
    hits = [x for x in returned if x in relevant_ids]
    first_rank = next((i for i, x in enumerate(returned, start=1) if x in relevant_ids), None)
    return {
        "recall": len(set(hits)) / len(relevant_ids),
        "precision": len(hits) / top_k,
        "mrr": 1 / first_rank if first_rank else 0,
        "first_rank": first_rank,
        "returned": returned,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"global": {}, "by_family": {}}
    for mode in ["bm25", "vector", "hybrid"]:
        subset = [r for r in rows if r["mode"] == mode]
        out["global"][mode] = {
            "recall": statistics.mean(r["recall"] for r in subset),
            "precision": statistics.mean(r["precision"] for r in subset),
            "mrr": statistics.mean(r["mrr"] for r in subset),
        }
    for family in sorted(set(r["family"] for r in rows)):
        out["by_family"][family] = {}
        for mode in ["bm25", "vector", "hybrid"]:
            subset = [r for r in rows if r["mode"] == mode and r["family"] == family]
            out["by_family"][family][mode] = {
                "recall": statistics.mean(r["recall"] for r in subset),
                "precision": statistics.mean(r["precision"] for r in subset),
                "mrr": statistics.mean(r["mrr"] for r in subset),
            }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--hybrid-vector-weight", type=float, default=1.0)
    parser.add_argument("--keep-docs", action="store_true")
    args = parser.parse_args()

    cfg = load_env()
    prefix = f"memoire-final-{int(time.time())}-{os.getpid()}-k{args.top_k}"
    rows = []
    upload_docs(cfg, prefix)
    time.sleep(3)
    try:
        for q in QUESTIONS:
            relevant = {f"{prefix}-{suffix}" for suffix in q["relevant_suffixes"]}
            for mode in ["bm25", "vector", "hybrid"]:
                results = run_search(
                    cfg,
                    prefix,
                    q["question"],
                    mode,
                    args.top_k,
                    args.hybrid_vector_weight,
                )
                rows.append(
                    {
                        **q,
                        "mode": mode,
                        "top_k": args.top_k,
                        **score(results, relevant, args.top_k),
                        "results": [
                            {
                                "rank": i,
                                "chunk_id": r.get("chunk_id"),
                                "title": r.get("title"),
                                "score": r.get("@search.score"),
                            }
                            for i, r in enumerate(results, start=1)
                        ],
                    }
                )
    finally:
        if not args.keep_docs:
            delete_docs(cfg, prefix)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"summary": summarize(rows), "documents": DOCS, "questions": QUESTIONS, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    print(output)


if __name__ == "__main__":
    main()
