from __future__ import annotations
import csv
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory-service"))
from app.retrieval import embed, incident_text, rank, trusted_match


def load_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(mode: str, incidents: list[dict], queries: list[dict]) -> dict:
    rows = []
    for item in incidents:
        row = SimpleNamespace(
            **{
                k: item[k]
                for k in (
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
    answer_count = 0
    reciprocals = []
    latencies = []
    no_answer_count = 0
    false_recalls = 0
    recall_values = {k: [] for k in (1, 3, 5, 10)}
    type_stats: dict[str, list[int]] = {}
    for item in queries:
        started = time.perf_counter()
        result = [
            entry
            for entry in rank(rows, item["query"], mode)
            if trusted_match(entry[1], mode)
        ][:10]
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [row.id for row, _ in result]
        label = item.get("query_type", "unspecified")
        stats = type_stats.setdefault(label, [0, 0])  # answered correctly, total
        stats[1] += 1
        if not item["relevant"]:
            no_answer_count += 1
            if ids:
                false_recalls += 1
                stats[0] += 1
            continue
        answer_count += 1
        positions = [
            ids.index(target) + 1 for target in item["relevant"] if target in ids
        ]
        for k in recall_values:
            recall_values[k].append(
                sum(position <= k for position in positions) / len(item["relevant"])
            )
        if positions:
            reciprocals.append(1 / min(positions))
            stats[0] += 1
        else:
            reciprocals.append(0)
    ordered = sorted(latencies)
    percentile = lambda value: round(ordered[max(0, int(len(ordered) * value) - 1)], 3)
    return {
        "queries": len(queries),
        "answer_queries": answer_count,
        "no_answer_queries": no_answer_count,
        **{
            f"recall_at_{k}": round(statistics.mean(values), 4)
            for k, values in recall_values.items()
        },
        "mrr": round(statistics.mean(reciprocals), 4),
        "no_answer_false_recall_rate": round(false_recalls / no_answer_count, 4),
        "p50_latency_ms": percentile(0.50),
        "p95_latency_ms": percentile(0.95),
        "p99_latency_ms": percentile(0.99),
        "by_query_type": {
            kind: round(correct / total, 4)
            for kind, (correct, total) in sorted(type_stats.items())
        },
    }


if __name__ == "__main__":
    data = ROOT / "eval" / "datasets"
    incidents = load_jsonl(data / "incidents.jsonl")
    queries = load_jsonl(data / "queries.jsonl")
    modes = ("fts", "vector", "weighted", "hybrid")
    report = {mode: evaluate(mode, incidents, queries) for mode in modes}
    report["dataset"] = {
        "incidents": len(incidents),
        "queries": len(queries),
        "source": "deterministic synthetic benchmark; 10 seed cases plus generated variations",
    }
    report["methodology"] = (
        "Deterministic local hashing embeddings; results are reproducible synthetic baselines, not production-model or live-incident claims."
    )
    reports = ROOT / "eval" / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fields = [
        "mode",
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "recall_at_10",
        "mrr",
        "no_answer_false_recall_rate",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
    ]
    with (reports / "latest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for mode in modes:
            writer.writerow(
                {"mode": mode, **{key: report[mode][key] for key in fields[1:]}}
            )
    lines = [
        "# RecallOps Retrieval Benchmark",
        "",
        "| mode | R@1 | R@3 | R@5 | R@10 | MRR | no-answer FP | P50 ms | P95 ms | P99 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in modes:
        row = report[mode]
        values = [
            mode,
            row["recall_at_1"],
            row["recall_at_3"],
            row["recall_at_5"],
            row["recall_at_10"],
            row["mrr"],
            row["no_answer_false_recall_rate"],
            row["p50_latency_ms"],
            row["p95_latency_ms"],
            row["p99_latency_ms"],
        ]
        lines.append("| " + " | ".join(map(str, values)) + " |")
    (reports / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
