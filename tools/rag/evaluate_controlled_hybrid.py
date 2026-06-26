#!/usr/bin/env python3
"""
Évaluation contrôlée BM25 vs hybrid search directement dans Azure AI Search.

Le script:
1. insère un mini-corpus synthétique dans l'index existant avec un préfixe unique;
2. lance les mêmes questions en recherche textuelle simple et en recherche hybride;
3. calcule Recall@K, Precision@K et MRR sur les chunk_id attendus;
4. supprime les documents de test par défaut.
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


DEFAULT_PREFIX = "ctrl-hybrid-20260617"

DOCS = [
    {
        "suffix": "voice-regulation",
        "title": "Module contrôlé - Régulation vocale",
        "chunk": (
            "Lorsqu'un conseiller parle avec une prosodie stable, un rythme lent et une voix posée, "
            "il favorise la co-régulation émotionnelle. Cette présence vocale aide le client tendu "
            "à retrouver un état plus calme pendant l'appel, même si le texte n'utilise pas les mots "
            "stressé, apaiser ou ton calme."
        ),
    },
    {
        "suffix": "written-tone-distractor",
        "title": "Module contrôlé - Ton écrit",
        "chunk": (
            "Le ton posé dans un courriel marketing améliore la lisibilité d'une newsletter. "
            "Ce passage parle de style rédactionnel, de ponctuation, de paragraphes courts et de "
            "formules commerciales, pas de gestion émotionnelle d'un client au téléphone."
        ),
    },
    {
        "suffix": "traceability",
        "title": "Module contrôlé - Traçabilité CRM",
        "chunk": (
            "Après chaque échange sensible, le conseiller doit documenter l'action dans le CRM. "
            "La note doit préciser la demande, l'engagement pris, le délai annoncé et le service "
            "responsable. Cette trace évite qu'une réclamation soit perdue entre plusieurs équipes."
        ),
    },
    {
        "suffix": "generic-crm-distractor",
        "title": "Module contrôlé - CRM commercial",
        "chunk": (
            "Le CRM peut servir à suivre des campagnes promotionnelles, segmenter des prospects, "
            "mesurer le taux de conversion et organiser des relances commerciales. Ce passage contient "
            "le terme CRM mais ne traite pas de traçabilité d'une réclamation."
        ),
    },
    {
        "suffix": "rare-code",
        "title": "Module contrôlé - Code procédure",
        "chunk": (
            "La procédure QSAT-5 impose de vérifier la satisfaction du client avant la clôture. "
            "Le conseiller reformule la solution, demande une validation explicite, puis note le résultat "
            "dans le dossier."
        ),
    },
    {
        "suffix": "rare-code-rgpd",
        "title": "Module contrôlé - Code RGPD",
        "chunk": (
            "La règle RGPD-MIN-12 impose de ne collecter que les informations strictement nécessaires "
            "au traitement de la demande. Le conseiller ne doit pas demander de justificatif ou de détail "
            "personnel sans lien direct avec le dossier."
        ),
    },
    {
        "suffix": "privacy-distractor",
        "title": "Module contrôlé - Vie privée générale",
        "chunk": (
            "La protection de la vie privée demande une attitude prudente, une information claire du client "
            "et une conservation limitée des données. Ce passage parle de confidentialité en général mais "
            "ne décrit pas la règle RGPD-MIN-12."
        ),
    },
    {
        "suffix": "rare-code-escalation",
        "title": "Module contrôlé - Code escalade",
        "chunk": (
            "Le repère ECH-3X-45 désigne une escalade en trois temps : reconnaître la difficulté, "
            "orienter vers le bon interlocuteur, puis confirmer au client le suivi prévu. Ce code est "
            "utilisé uniquement pour les situations qui dépassent le périmètre du conseiller."
        ),
    },
    {
        "suffix": "escalation-distractor",
        "title": "Module contrôlé - Escalade générique",
        "chunk": (
            "Une escalade peut être nécessaire lorsqu'un conseiller n'a pas la réponse. Il peut transférer "
            "l'appel, solliciter un superviseur ou créer une tâche interne. Ce passage est proche du thème "
            "mais ne contient pas le repère ECH-3X-45."
        ),
    },
    {
        "suffix": "satisfaction-distractor",
        "title": "Module contrôlé - Satisfaction générale",
        "chunk": (
            "La satisfaction client peut être mesurée avec des enquêtes, des étoiles, des verbatims "
            "et des tableaux de bord. Ce passage parle de pilotage qualité global sans décrire la "
            "procédure QSAT-5."
        ),
    },
    {
        "suffix": "vulnerability",
        "title": "Module contrôlé - Client vulnérable",
        "chunk": (
            "Face à une personne en difficulté de compréhension, le conseiller ralentit le rythme, "
            "emploie des phrases courtes, vérifie chaque étape et laisse au client le temps de répondre. "
            "L'objectif est de rendre l'échange accessible sans infantiliser l'interlocuteur."
        ),
    },
    {
        "suffix": "slow-pace-distractor",
        "title": "Module contrôlé - Rythme lent hors sujet",
        "chunk": (
            "Un rythme lent est utile dans une vidéo de méditation, dans un podcast de relaxation "
            "ou dans une ambiance sonore. Ce passage ne concerne ni la relation client ni l'adaptation "
            "à une personne vulnérable."
        ),
    },
]

for code, action in [
    ("ZXQ-914-BETA", "ouvrir un dossier de médiation prioritaire sous vingt-quatre heures"),
    ("ZXQ-914-DELTA", "envoyer une synthèse commerciale au responsable de secteur"),
    ("ZXQ-914-GAMMA", "mettre la demande en attente jusqu'à réception du justificatif"),
    ("ZXQ-914-OMEGA", "clôturer le ticket sans relance si le client ne répond pas"),
    ("ZXQ-914-SIGMA", "transférer le dossier vers le support technique niveau deux"),
    ("ZXQ-914-ALPHA", "déclencher une enquête de satisfaction automatisée"),
    ("ZXQ-914-KAPPA", "planifier un rappel simple dans les quarante-huit heures"),
    ("ZXQ-914-THETA", "classer la demande comme information générale"),
    ("ZXQ-914-LAMBDA", "demander une confirmation écrite avant toute action"),
    ("ZXQ-914-PI", "archiver la conversation dans le dossier administratif"),
    ("MND-772-ROUGE", "appliquer la remise exceptionnelle après validation superviseur"),
    ("MND-772-BLEU", "refuser la remise et proposer une alternative standard"),
    ("MND-772-VERT", "convertir la demande en opportunité commerciale"),
    ("MND-772-NOIR", "envoyer un message de clôture sans enquête complémentaire"),
    ("MND-772-ORANGE", "ouvrir une alerte qualité auprès de l'équipe formation"),
]:
    DOCS.append(
        {
            "suffix": "code-" + code.lower().replace("-", "-"),
            "title": f"Module contrôlé - Procédure {code}",
            "chunk": (
                f"La procédure interne {code} concerne une demande client sensible. "
                f"Lorsque ce repère est mentionné, le conseiller doit {action}. "
                "Le reste du traitement est volontairement formulé comme les autres procédures "
                "afin de tester la capacité du moteur à distinguer des codes exacts dans des "
                "passages presque identiques."
            ),
        }
    )

SEMANTIC_TRAP_QUERIES = []

for idx, item in enumerate(
    [
        {
            "suffix": "semantic-fatigue",
            "title": "Module contrôlé - Fatigue émotionnelle en appel",
            "chunk": (
                "Après plusieurs interactions difficiles, le conseiller peut ressentir une saturation "
                "relationnelle. Les signes sont une baisse d'écoute, une parole plus mécanique, une "
                "irritabilité discrète et une difficulté à rester disponible pour le client suivant."
            ),
            "question": "Quels signes montrent qu'un conseiller commence à être épuisé par les échanges difficiles ?",
            "distractor": (
                "Un échange difficile peut concerner une facture, une livraison ou un remboursement. "
                "Ce passage répète les mots conseiller, échanges difficiles et signes, mais il décrit "
                "seulement des catégories administratives sans parler de fatigue émotionnelle."
            ),
        },
        {
            "suffix": "semantic-trust",
            "title": "Module contrôlé - Confiance client",
            "chunk": (
                "La confiance se construit lorsque le client constate que le conseiller tient ses "
                "engagements, reformule correctement la demande et annonce des délais réalistes. "
                "Cette cohérence rend l'échange crédible."
            ),
            "question": "Comment rassurer quelqu'un qui doute de la promesse faite au téléphone ?",
            "distractor": (
                "Une promesse faite au téléphone peut être une offre commerciale, un rendez-vous ou "
                "une phrase de politesse. Ce passage contient les mots rassurer, promesse et téléphone, "
                "mais ne traite pas de construction de confiance."
            ),
        },
        {
            "suffix": "semantic-active-listening",
            "title": "Module contrôlé - Écoute active",
            "chunk": (
                "L'écoute active consiste à laisser le client terminer son explication, repérer le besoin "
                "principal, reformuler sans déformer et vérifier que la compréhension est partagée avant "
                "de proposer une solution."
            ),
            "question": "Que doit faire un conseiller avant de proposer une solution à un client confus ?",
            "distractor": (
                "Proposer une solution à un client confus peut être rapide si le conseiller dispose d'un "
                "catalogue standard. Ce passage reprend les mots de la question mais parle d'automatisation, "
                "pas d'écoute active."
            ),
        },
        {
            "suffix": "semantic-escalation",
            "title": "Module contrôlé - Orientation hors périmètre",
            "chunk": (
                "Quand une demande dépasse son périmètre, le conseiller ne se défausse pas. Il explique "
                "la limite de son rôle, oriente vers le bon interlocuteur et confirme au client que le "
                "suivi sera transmis."
            ),
            "question": "Comment éviter de donner l'impression d'abandonner le client quand on ne peut pas traiter sa demande ?",
            "distractor": (
                "Abandonner le client peut donner une mauvaise impression dans une demande difficile. "
                "Ce passage répète abandonner, client, traiter et demande, mais il ne donne aucune méthode "
                "d'orientation hors périmètre."
            ),
        },
        {
            "suffix": "semantic-clarity",
            "title": "Module contrôlé - Clarté pédagogique",
            "chunk": (
                "Pour rendre une consigne compréhensible, le formateur découpe l'explication en étapes, "
                "utilise des phrases courtes, donne un exemple concret et vérifie que l'apprenant peut "
                "reformuler l'action attendue."
            ),
            "question": "Comment expliquer simplement une tâche à quelqu'un qui n'a pas compris la première fois ?",
            "distractor": (
                "Expliquer simplement une tâche peut vouloir dire lire plus lentement une notice. "
                "Ce passage contient les mots expliquer, tâche et compris, mais ne parle pas de découpage "
                "pédagogique ni de reformulation."
            ),
        },
        {
            "suffix": "semantic-deescalation",
            "title": "Module contrôlé - Désamorçage émotionnel",
            "chunk": (
                "Désamorcer une tension suppose d'abord de reconnaître l'émotion exprimée, puis de "
                "recadrer calmement le problème et de proposer une prochaine étape claire. Le conseiller "
                "évite de se justifier trop vite."
            ),
            "question": "Que répondre à une personne énervée pour faire redescendre la tension ?",
            "distractor": (
                "Une personne énervée peut faire redescendre la tension après une pause ou un changement "
                "de sujet. Ce passage reprend les mots personne, énervée et tension, mais ne décrit pas "
                "la méthode de désamorçage."
            ),
        },
    ],
    start=1,
):
    DOCS.append(
        {
            "suffix": item["suffix"],
            "title": item["title"],
            "chunk": item["chunk"],
        }
    )
    DOCS.append(
        {
            "suffix": f"{item['suffix']}-bm25-distractor",
            "title": f"Distracteur lexical {idx}",
            "chunk": item["distractor"],
        }
    )
    SEMANTIC_TRAP_QUERIES.append(
        {
            "id": f"q_semantic_bm25_trap_{idx}",
            "question": item["question"],
            "relevant_suffixes": [item["suffix"]],
            "context": (
                "Cas de reformulation: le bon chunk partage le sens de la question, "
                "tandis qu'un distracteur reprend davantage de mots exacts sans répondre réellement."
            ),
        }
    )

for code, action in [
    ("META-AX7-PRIORITE", "ouvrir une médiation prioritaire sous vingt-quatre heures"),
    ("META-BQ9-QUALITE", "transmettre une alerte qualité au responsable de plateau"),
    ("META-CM4-SUIVI", "programmer un rappel de suivi dans les deux jours ouvrés"),
    ("META-DN2-CLOTURE", "clôturer le dossier après validation explicite du client"),
    ("META-EP8-TRANSFERT", "transférer la demande vers le service expert"),
]:
    DOCS.append(
        {
            "suffix": "meta-" + code.lower().replace("-", "-"),
            "title": f"Fiche procédure {code}",
            "chunk": (
                "Cette fiche décrit une procédure interne de relation client. "
                f"Lorsque la fiche est sélectionnée, le conseiller doit {action}. "
                "Le texte de la fiche ne répète pas l'identifiant exact, qui est porté uniquement "
                "par le titre du document. Ce cas teste l'intérêt d'un signal lexical sur les métadonnées "
                "en complément d'une recherche vectorielle sur le contenu."
            ),
        }
    )

QUERIES = [
    {
        "id": "q_sem_1",
        "question": "Comment un ton calme peut-il apaiser un client stressé pendant un appel ?",
        "relevant_suffixes": ["voice-regulation"],
        "context": "Question reformulée: le chunk pertinent parle de prosodie stable et de co-régulation, tandis qu'un distracteur contient les mots exacts ton posé.",
    },
    {
        "id": "q_sem_2",
        "question": "Que faire pour aider une personne qui comprend difficilement les consignes ?",
        "relevant_suffixes": ["vulnerability"],
        "context": "Question reformulée: le chunk pertinent traite du client vulnérable sans reprendre exactement tous les mots de la question.",
    },
    {
        "id": "q_lex_1",
        "question": "Que signifie la procédure QSAT-5 avant la clôture ?",
        "relevant_suffixes": ["rare-code"],
        "context": "Question lexicale: le code rare QSAT-5 doit favoriser la recherche textuelle et l'hybride.",
    },
    {
        "id": "q_lex_2",
        "question": "Que demande exactement la règle RGPD-MIN-12 ?",
        "relevant_suffixes": ["rare-code-rgpd"],
        "context": "Question lexicale avec code rare: la recherche hybride doit bénéficier du signal BM25 sur RGPD-MIN-12.",
    },
    {
        "id": "q_code_only_1",
        "question": "RGPD-MIN-12",
        "relevant_suffixes": ["rare-code-rgpd"],
        "context": "Requête volontairement minimale: seul le code est fourni. Le signal lexical exact devrait avantager l'hybride par rapport au vectoriel seul.",
    },
    {
        "id": "q_lex_3",
        "question": "À quoi correspond le repère ECH-3X-45 dans une situation hors périmètre ?",
        "relevant_suffixes": ["rare-code-escalation"],
        "context": "Question lexicale avec code rare: le code exact ECH-3X-45 doit aider l'hybride lorsque le vectoriel hésite entre passages d'escalade.",
    },
    {
        "id": "q_code_only_2",
        "question": "ECH-3X-45",
        "relevant_suffixes": ["rare-code-escalation"],
        "context": "Requête volontairement minimale: seul le code est fourni. Le signal BM25 exact devrait être utile.",
    },
    {
        "id": "q_mix_1",
        "question": "Pourquoi faut-il garder une trace dans le CRM quand une réclamation passe entre plusieurs équipes ?",
        "relevant_suffixes": ["traceability"],
        "context": "Question mixte: CRM est lexical, mais le sens attendu porte sur la traçabilité d'une réclamation.",
    },
    {
        "id": "q_adversarial_code_1",
        "question": "Que faut-il faire pour la procédure ZXQ-914-BETA ?",
        "relevant_suffixes": ["code-zxq-914-beta"],
        "context": "Cas adversarial: de nombreux chunks sont quasi identiques et ne diffèrent que par le code. Le signal lexical exact devrait avantager l'hybride.",
    },
    {
        "id": "q_adversarial_code_2",
        "question": "Quelle action est associée au repère MND-772-ORANGE ?",
        "relevant_suffixes": ["code-mnd-772-orange"],
        "context": "Cas adversarial: le sens général est commun à tous les chunks, seul le code exact identifie le bon passage.",
    },
    {
        "id": "q_adversarial_code_only",
        "question": "ZXQ-914-BETA",
        "relevant_suffixes": ["code-zxq-914-beta"],
        "context": "Requête composée uniquement d'un identifiant arbitraire: le vectoriel seul peut perdre le signal exact, l'hybride conserve BM25.",
    },
    {
        "id": "q_metadata_code_1",
        "question": "Que prévoit la fiche META-AX7-PRIORITE ?",
        "relevant_suffixes": ["meta-meta-ax7-priorite"],
        "context": "Cas métadonnée: l'identifiant exact est dans le titre searchable, mais pas dans le chunk vectorisé. L'hybride peut exploiter BM25 sur le titre.",
    },
    {
        "id": "q_metadata_code_2",
        "question": "Quelle action correspond à META-BQ9-QUALITE ?",
        "relevant_suffixes": ["meta-meta-bq9-qualite"],
        "context": "Cas métadonnée: le vector-only ne voit pas l'identifiant dans text_vector, l'hybride le retrouve via la recherche textuelle.",
    },
    {
        "id": "q_metadata_code_only",
        "question": "META-EP8-TRANSFERT",
        "relevant_suffixes": ["meta-meta-ep8-transfert"],
        "context": "Requête identifiant seul, présent uniquement dans le titre du document.",
    },
]

QUERIES.extend(SEMANTIC_TRAP_QUERIES)


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


def search_url(cfg: dict[str, str]) -> str:
    endpoint = cfg["AZURE_SEARCH_ENDPOINT"].rstrip("/")
    index = cfg["AZURE_SEARCH_INDEX_NAME"]
    return f"{endpoint}/indexes/{index}/docs/search?api-version=2024-07-01"


def index_url(cfg: dict[str, str]) -> str:
    endpoint = cfg["AZURE_SEARCH_ENDPOINT"].rstrip("/")
    index = cfg["AZURE_SEARCH_INDEX_NAME"]
    return f"{endpoint}/indexes/{index}/docs/index?api-version=2024-07-01"


def upload_docs(cfg: dict[str, str], prefix: str) -> list[dict[str, Any]]:
    docs = []
    for doc in DOCS:
        chunk_id = f"{prefix}-{doc['suffix']}"
        docs.append(
            {
                "@search.action": "mergeOrUpload",
                "chunk_id": chunk_id,
                "parent_id": f"{prefix}-parent",
                "title": doc["title"],
                "chunk": doc["chunk"],
                "text_vector": embedding(cfg, doc["chunk"]),
            }
        )

    r = requests.post(
        index_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json={"value": docs},
        timeout=30,
    )
    r.raise_for_status()
    return docs


def delete_docs(cfg: dict[str, str], prefix: str) -> None:
    docs = [
        {"@search.action": "delete", "chunk_id": f"{prefix}-{doc['suffix']}"}
        for doc in DOCS
    ]
    requests.post(
        index_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json={"value": docs},
        timeout=30,
    ).raise_for_status()


def run_search(cfg: dict[str, str], prefix: str, question: str, mode: str, top_k: int) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "filter": f"parent_id eq '{prefix}-parent'",
        "select": "chunk_id,title,chunk",
        "top": top_k,
    }
    if mode == "simple":
        payload["search"] = question
    elif mode == "vector":
        payload["search"] = "*"
        payload["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": embedding(cfg, question),
                "fields": "text_vector",
                "k": top_k,
            }
        ]
    elif mode == "hybrid":
        payload["search"] = question
        payload["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": embedding(cfg, question),
                "fields": "text_vector",
                "k": top_k,
            }
        ]
    else:
        raise ValueError(f"Mode inconnu: {mode}")

    r = requests.post(
        search_url(cfg),
        headers={"api-key": cfg["AZURE_SEARCH_API_KEY"], "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("value", [])


def metrics(results: list[dict[str, Any]], relevant_ids: set[str], top_k: int) -> dict[str, Any]:
    returned = [r["chunk_id"] for r in results[:top_k]]
    relevant_returned = [chunk_id for chunk_id in returned if chunk_id in relevant_ids]
    first_rank = None
    for idx, chunk_id in enumerate(returned, start=1):
        if chunk_id in relevant_ids:
            first_rank = idx
            break
    return {
        "recall_at_k": len(set(relevant_returned)) / len(relevant_ids),
        "precision_at_k": len(relevant_returned) / top_k,
        "mrr": 1 / first_rank if first_rank else 0,
        "first_relevant_rank": first_rank,
        "returned_ids": returned,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--keep-docs", action="store_true")
    parser.add_argument("--output", default="rag_eval_runs/controlled-hybrid-eval.json")
    args = parser.parse_args()

    cfg = load_env()
    prefix = args.prefix or f"{DEFAULT_PREFIX}-{int(time.time())}-{os.getpid()}"
    print("Indexation du corpus contrôlé...")
    upload_docs(cfg, prefix)
    time.sleep(3)

    rows = []
    try:
        for query in QUERIES:
            relevant_ids = {f"{prefix}-{suffix}" for suffix in query["relevant_suffixes"]}
            for mode in ("simple", "vector", "hybrid"):
                results = run_search(cfg, prefix, query["question"], mode, args.top_k)
                row = {
                    "id": query["id"],
                    "context": query["context"],
                    "question": query["question"],
                    "mode": mode,
                    **metrics(results, relevant_ids, args.top_k),
                    "results": [
                        {
                            "rank": idx,
                            "chunk_id": r.get("chunk_id"),
                            "title": r.get("title"),
                            "score": r.get("@search.score"),
                            "chunk": r.get("chunk"),
                        }
                        for idx, r in enumerate(results, start=1)
                    ],
                }
                rows.append(row)
                print(
                    f"{query['id']} {mode}: "
                    f"R@{args.top_k}={row['recall_at_k']:.2f} "
                    f"P@{args.top_k}={row['precision_at_k']:.2f} "
                    f"MRR={row['mrr']:.2f}"
                )
    finally:
        if not args.keep_docs:
            print("Suppression du corpus contrôlé...")
            delete_docs(cfg, prefix)

    summary = {}
    for mode in ("simple", "vector", "hybrid"):
        subset = [r for r in rows if r["mode"] == mode]
        summary[mode] = {
            f"recall@{args.top_k}": statistics.mean(r["recall_at_k"] for r in subset),
            f"precision@{args.top_k}": statistics.mean(r["precision_at_k"] for r in subset),
            "mrr": statistics.mean(r["mrr"] for r in subset),
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nRésumé:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nRapport: {output}")


if __name__ == "__main__":
    main()
