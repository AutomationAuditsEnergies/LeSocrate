#!/usr/bin/env python3
"""
Compare plusieurs modes Azure OpenAI On Your Data pour le RAG.

Exemple:
  python3 tools/rag/evaluate_rag.py \
    --dataset tools/rag/eval_questions.example.jsonl \
    --query-types simple,vector_simple_hybrid \
    --output-dir rag_eval_runs

Le script charge backend/.env si disponible. Il n'affiche jamais les clés.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


SYSTEM_PROMPT = """Tu es un assistant pédagogique intégré à une formation en direct.
Réponds en 2 à 4 phrases maximum.
Base-toi sur le contenu du cours fourni.
Si l'information n'est pas dans le cours, dis-le clairement et ne l'invente pas.
"""

OUT_OF_SCOPE_MARKERS = (
    "pas dans le cours",
    "n'est pas dans le cours",
    "ne mentionne pas",
    "ne traite pas",
    "documents fournis ne contiennent pas",
    "documents fournis ne mentionne",
    "documents fournis ne traite",
    "document fourni ne contient pas",
    "document fourni ne mentionne",
    "n'est pas disponible dans les documents",
    "n'est pas disponible dans le document",
    "informations disponibles",
    "not found in the retrieved data",
    "please try another query",
    "provide a document",
    "fournir un document",
    "je n'ai pas cette information",
    "je ne dispose pas",
    "hors du cours",
    "pas couvert",
    "pas abordé",
)


@dataclass
class Config:
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_search_endpoint: str
    azure_search_api_key: str
    azure_search_index_name: str
    embedding_deployment: str | None
    api_version: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config() -> Config:
    root = _repo_root()
    load_dotenv(root / "backend" / ".env")
    load_dotenv(root / ".env")

    required = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_API_KEY",
        "AZURE_SEARCH_INDEX_NAME",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(
            "Variables d'environnement manquantes: "
            + ", ".join(missing)
            + ". Lance ce script dans l'environnement Azure/backend qui contient ces valeurs."
        )

    return Config(
        azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/",
        azure_openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        azure_search_endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        azure_search_api_key=os.environ["AZURE_SEARCH_API_KEY"],
        azure_search_index_name=os.environ["AZURE_SEARCH_INDEX_NAME"],
        embedding_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )


def load_dataset(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("id") or not row.get("question"):
                raise ValueError(f"Ligne {line_no}: champs requis manquants: id, question")
            row.setdefault("expected_terms", [])
            row.setdefault("out_of_scope", False)
            rows.append(row)
    if not rows:
        raise ValueError(f"Dataset vide: {path}")
    return rows


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def term_recall(answer: str, expected_terms: list[str]) -> float | None:
    if not expected_terms:
        return None
    haystack = normalize(answer)
    hits = sum(1 for term in expected_terms if normalize(term) in haystack)
    return hits / len(expected_terms)


def out_of_scope_detected(answer: str) -> bool:
    clean = normalize(answer)
    return any(marker in clean for marker in OUT_OF_SCOPE_MARKERS)


def build_payload(
    cfg: Config,
    question: str,
    query_type: str,
    strictness: int | None,
    top_n_documents: int | None,
    in_scope: bool | None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "endpoint": cfg.azure_search_endpoint,
        "index_name": cfg.azure_search_index_name,
        "authentication": {
            "type": "api_key",
            "key": cfg.azure_search_api_key,
        },
        "query_type": query_type,
    }

    if query_type.startswith("vector") and cfg.embedding_deployment:
        parameters["embedding_dependency"] = {
            "type": "deployment_name",
            "deployment_name": cfg.embedding_deployment,
        }
    if strictness is not None:
        parameters["strictness"] = strictness
    if top_n_documents is not None:
        parameters["top_n_documents"] = top_n_documents
    if in_scope is not None:
        parameters["in_scope"] = in_scope

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "max_tokens": 300,
        "temperature": 0,
        "data_sources": [
            {
                "type": "azure_search",
                "parameters": parameters,
            }
        ],
    }


def call_rag(
    cfg: Config,
    question: str,
    query_type: str,
    strictness: int | None,
    top_n_documents: int | None,
    in_scope: bool | None,
    timeout: int,
) -> tuple[dict[str, Any], float]:
    url = (
        f"{cfg.azure_openai_endpoint}openai/deployments/{cfg.azure_openai_deployment}"
        f"/chat/completions?api-version={cfg.api_version}"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": cfg.azure_openai_api_key,
    }
    payload = build_payload(cfg, question, query_type, strictness, top_n_documents, in_scope)

    started = time.perf_counter()
    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    return response.json(), latency_ms


def extract_answer_and_context(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    message = result["choices"][0]["message"]
    answer = re.sub(r"\[doc\d+\]", "", message.get("content", "")).strip()
    context = message.get("context") or {}
    return answer, context


def count_citations(context: dict[str, Any]) -> int:
    citations = context.get("citations") or []
    return len(citations) if isinstance(citations, list) else 0


def citation_texts(context: dict[str, Any]) -> list[str]:
    citations = context.get("citations") or []
    if not isinstance(citations, list):
        return []

    texts: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        parts = [
            citation.get("content"),
            citation.get("title"),
            citation.get("filepath"),
            citation.get("url"),
        ]
        texts.append("\n".join(str(part) for part in parts if part))
    return texts


def first_relevant_citation_rank(citations: list[str], expected_terms: list[str]) -> int | None:
    if not expected_terms:
        return None
    normalized_terms = [normalize(term) for term in expected_terms]
    for idx, citation in enumerate(citations, start=1):
        clean = normalize(citation)
        if any(term in clean for term in normalized_terms):
            return idx
    return None


def run_eval(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = load_config()
    dataset = load_dataset(Path(args.dataset))
    query_types = [item.strip() for item in args.query_types.split(",") if item.strip()]
    rows: list[dict[str, Any]] = []

    for item in dataset:
        for query_type in query_types:
            record: dict[str, Any] = {
                "id": item["id"],
                "question": item["question"],
                "query_type": query_type,
                "out_of_scope_expected": bool(item.get("out_of_scope")),
            }
            try:
                result, latency_ms = call_rag(
                    cfg,
                    item["question"],
                    query_type,
                    args.strictness,
                    args.top_n_documents,
                    args.in_scope,
                    args.timeout,
                )
                answer, context = extract_answer_and_context(result)
                citations = citation_texts(context)
                recall = term_recall(answer, item.get("expected_terms") or [])
                citation_recall = term_recall(
                    "\n".join(citations),
                    item.get("expected_terms") or [],
                )
                first_rank = first_relevant_citation_rank(
                    citations,
                    item.get("expected_terms") or [],
                )
                refused = out_of_scope_detected(answer)

                record.update(
                    {
                        "ok": True,
                        "latency_ms": round(latency_ms, 1),
                        "answer": answer,
                        "citation_count": len(citations),
                        "citation_snippets": citations,
                        "expected_term_recall": recall,
                        "citation_expected_term_recall": citation_recall,
                        "first_relevant_citation_rank": first_rank,
                        "reciprocal_rank": round(1 / first_rank, 3) if first_rank else 0,
                        "out_of_scope_detected": refused,
                    }
                )
            except Exception as exc:
                record.update(
                    {
                        "ok": False,
                        "error": str(exc)[:500],
                        "latency_ms": None,
                        "answer": "",
                        "citation_count": 0,
                        "citation_snippets": [],
                        "expected_term_recall": None,
                        "citation_expected_term_recall": None,
                        "first_relevant_citation_rank": None,
                        "reciprocal_rank": 0,
                        "out_of_scope_detected": False,
                    }
                )
            rows.append(record)
            print(
                f"{record['id']} {query_type}: "
                f"{'OK' if record['ok'] else 'ERROR'} "
                f"{record.get('latency_ms') or '-'}ms"
            )

    summary = summarize(rows)
    return rows, summary


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row["query_type"], []).append(row)

    summary: dict[str, Any] = {}
    for query_type, items in by_type.items():
        ok_items = [row for row in items if row["ok"]]
        recalls = [
            row["expected_term_recall"]
            for row in ok_items
            if row["expected_term_recall"] is not None
        ]
        citation_recalls = [
            row["citation_expected_term_recall"]
            for row in ok_items
            if row["citation_expected_term_recall"] is not None
        ]
        reciprocal_ranks = [
            row["reciprocal_rank"]
            for row in ok_items
            if row["citation_expected_term_recall"] is not None
        ]
        out_scope_items = [row for row in ok_items if row["out_of_scope_expected"]]
        latencies = [row["latency_ms"] for row in ok_items if row["latency_ms"] is not None]

        summary[query_type] = {
            "total": len(items),
            "ok": len(ok_items),
            "error": len(items) - len(ok_items),
            "avg_expected_term_recall": round(statistics.mean(recalls), 3) if recalls else None,
            "avg_citation_expected_term_recall": (
                round(statistics.mean(citation_recalls), 3) if citation_recalls else None
            ),
            "mrr_proxy": round(statistics.mean(reciprocal_ranks), 3) if reciprocal_ranks else None,
            "out_of_scope_refusal_rate": (
                round(
                    sum(1 for row in out_scope_items if row["out_of_scope_detected"])
                    / len(out_scope_items),
                    3,
                )
                if out_scope_items
                else None
            ),
            "avg_citation_count": (
                round(statistics.mean(row["citation_count"] for row in ok_items), 3)
                if ok_items
                else None
            ),
            "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        }
    return summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"rag-eval-{stamp}.json"
    csv_path = output_dir / f"rag-eval-{stamp}.csv"

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, ensure_ascii=False, indent=2)

    fields = [
        "id",
        "query_type",
        "ok",
        "latency_ms",
        "citation_count",
        "expected_term_recall",
        "citation_expected_term_recall",
        "first_relevant_citation_rank",
        "reciprocal_rank",
        "out_of_scope_expected",
        "out_of_scope_detected",
        "question",
        "answer",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})

    print(f"\nRapports écrits:\n- {json_path}\n- {csv_path}")
    print("\nRésumé:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Évalue le RAG Azure avec plusieurs query_type.")
    parser.add_argument("--dataset", required=True, help="Fichier JSONL de questions d'évaluation.")
    parser.add_argument(
        "--query-types",
        default="simple,vector_simple_hybrid",
        help="Liste séparée par virgules. Exemple: simple,vector_simple_hybrid",
    )
    parser.add_argument("--output-dir", default="rag_eval_runs")
    parser.add_argument("--strictness", type=int, default=None)
    parser.add_argument("--top-n-documents", type=int, default=None)
    parser.add_argument(
        "--in-scope",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Passe in_scope à Azure OpenAI On Your Data.",
    )
    parser.add_argument("--timeout", type=int, default=45)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, summary = run_eval(args)
    write_outputs(rows, summary, Path(args.output_dir))


if __name__ == "__main__":
    main()
