"""使用规则生成种子扩增到 100K 的内存排序规模基准。"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT / "memory-service"))

from app.retrieval import embed, incident_text, rank  # noqa: E402

SCALES = (160, 1_000, 10_000, 100_000)


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * fraction) - 1)], 3)


def _write(rows: list[dict[str, object]], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "scale.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output / "scale.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    headers = list(rows[0])
    lines = ["# Data Scale Benchmark", "", "| " + " | ".join(headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    lines.extend(
        "| " + " | ".join(str(row[key]) for key in headers) + " |"
        for row in rows
    )
    (output / "scale.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _expand(source: list[dict], count: int):
    templates = []
    for item in source:
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
        templates.append((row, item["services"]))
    rows = []
    for index in range(count):
        template, services = templates[index % len(templates)]
        row = SimpleNamespace(**vars(template))
        row.id = f"{template.id}-scale-{index:06d}"
        rows.append((row, services))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queries", type=int, default=5)
    args = parser.parse_args()
    if args.queries < 1:
        parser.error("--queries 必须为正数")
    data = ROOT / "eval" / "datasets"
    incidents = _load(data / "incidents.jsonl")
    query_rows = [item for item in _load(data / "queries.jsonl") if item["relevant"]]
    selected_queries = [
        query_rows[index % len(query_rows)]["query"] for index in range(args.queries)
    ]
    report: list[dict[str, object]] = []
    tracemalloc.start()
    for count in SCALES:
        tracemalloc.reset_peak()
        build_started = time.perf_counter()
        rows = _expand(incidents, count)
        build_seconds = time.perf_counter() - build_started
        latencies = []
        for query in selected_queries:
            started = time.perf_counter()
            rank(rows, query, "hybrid")[:10]
            latencies.append((time.perf_counter() - started) * 1000)
        _, peak = tracemalloc.get_traced_memory()
        report.append(
            {
                "incidents": count,
                "queries": len(selected_queries),
                "mode": "hybrid_rrf",
                "p50_ms": _percentile(latencies, 0.50),
                "p95_ms": _percentile(latencies, 0.95),
                "p99_ms": _percentile(latencies, 0.99),
                "mean_ms": round(statistics.mean(latencies), 3),
                "qps": round(1000 / statistics.mean(latencies), 4),
                "build_seconds": round(build_seconds, 3),
                "python_peak_memory_bytes": peak,
                "data_source": "seeded-synthetic-160-expanded-synthetic",
            }
        )
        _write(report, args.output)
    tracemalloc.stop()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
