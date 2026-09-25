# RecallOps Benchmark Runbook

所有结果均通过实际运行生成 JSON、CSV 和 Markdown。准确率继续使用
`eval/datasets` 中 160 条 incident、1,140 条人工规则标注 query；1K/10K/100K
只用于性能规模扩增，报告中标记为 `real-labeled-160-expanded-synthetic`。

## 命令

```powershell
# FTS / Vector / Weighted / RRF 准确率与 TopK
python eval/retrieval_eval.py

# query parse / embedding / FTS / vector / RRF / reranker 分阶段延迟
python eval/stage_latency_benchmark.py `
  --output eval/reports/stage_latency --queries 200

# 160 / 1K / 10K / 100K
python eval/scale_benchmark.py --output eval/reports/scale --queries 5

# concurrency 1/10/50/100/200 与 request_id 2/10/100
python eval/system_benchmark.py --output eval/reports/system `
  --requests-per-level 200
```

## 口径

- 分阶段延迟报告 P50/P95/P99。
- 并发报告 QPS、P50/P95/P99、error rate、归一化 CPU、Python 峰值内存和
  SQLAlchemy 连接池峰值。
- request_id 压力测试以正式 incident 数为准；重复响应失败也会保留在报告中。
- 当前 memory-service 不发起 LLM 请求，且没有外部 LLM trace，因此 LLM TTFT
  与 LLM total latency 输出为 null，不使用模拟值填充。
- SQLite 适合本地可复现基线。高并发报告暴露的连接池饱和和写锁问题应作为
  PostgreSQL/pgvector 生产部署对照，而非从报告中删除。
