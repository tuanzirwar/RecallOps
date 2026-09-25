"""RecallOps 检索各阶段及端到端延迟 benchmark。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT / "memory-service"))

from app.retrieval import (  # noqa: E402
    embed,
    incident_text,
    rank,
    tokens,
    trusted_match,
)

STAGES = (
    "query_parse",
    "embedding",
    "fts",
    "vector_search",
    "rrf",
    "reranker",
    "end_to_end",
)


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * fraction) - 1)], 3)


def run(output: Path, limit: int = 200) -> list[dict[str, object]]:
    data = ROOT / "eval" / "datasets"
    incidents = _load(data / "incidents.jsonl")
    queries = _load(data / "queries.jsonl")[:limit]
    rows = []
    for item in incidents:
        row = SimpleNamespace(
            **{
                key: item[key]
                for key in (
                    "id",
                    "title",
                    "symptom",
                    "root_cause",
                    "resolution",
                    "error_codes",
                )
            }
        )
        row.embedding = embed(incident_text(row, item["services"]))
        rows.append((row, item["services"]))
    samples = {name: [] for name in STAGES}
    for item in queries:
        total_started = time.perf_counter()
        started = time.perf_counter()
        tokens(item["query"])
        samples["query_parse"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        vector = embed(item["query"])
        samples["embedding"].append((time.perf_counter() - started) * 1000)
        timings: dict[str, float] = {}
        ranked = rank(
            rows, item["query"], "hybrid", query_vector=vector, timings=timings
        )
        for name in ("fts", "vector_search", "rrf"):
            samples[name].append(timings[name])
        started = time.perf_counter()
        [entry for entry in ranked if trusted_match(entry[1], "hybrid")][:10]
        samples["reranker"].append((time.perf_counter() - started) * 1000)
        samples["end_to_end"].append((time.perf_counter() - total_started) * 1000)
    report = [
        {
            "stage": name,
            "samples": len(samples[name]),
            "p50_ms": _percentile(samples[name], 0.50),
            "p95_ms": _percentile(samples[name], 0.95),
            "p99_ms": _percentile(samples[name], 0.99),
            "llm_ttft_ms": None,
            "llm_total_latency_ms": None,
        }
        for name in STAGES
    ]
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output / "result.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report[0]))
        writer.writeheader()
        writer.writerows(report)
    headers = list(report[0])
    lines = ["# Retrieval Stage Latency", "", "| " + " | ".join(headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    lines.extend(
        "| " + " | ".join(str(row[key]) for key in headers) + " |"
        for row in report
    )
    lines.extend(
        [
            "",
            "LLM TTFT 与 total latency 为 null：当前 RecallOps 服务不发起 LLM 请求，"
            "且未配置外部 LLM trace。",
        ]
    )
    (output / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queries", type=int, default=200)
    args = parser.parse_args()
    run(args.output, args.queries)


if __name__ == "__main__":
    main()
