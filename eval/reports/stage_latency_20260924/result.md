# Retrieval Stage Latency

| stage | samples | p50_ms | p95_ms | p99_ms | llm_ttft_ms | llm_total_latency_ms |
|---|---|---|---|---|---|---|
| query_parse | 200 | 0.003 | 0.006 | 0.007 | None | None |
| embedding | 200 | 0.057 | 0.098 | 0.129 | None | None |
| fts | 200 | 4.008 | 6.041 | 7.039 | None | None |
| vector_search | 200 | 0.521 | 0.893 | 0.97 | None | None |
| rrf | 200 | 5.454 | 8.191 | 9.921 | None | None |
| reranker | 200 | 0.012 | 0.02 | 0.024 | None | None |
| end_to_end | 200 | 10.218 | 14.821 | 16.836 | None | None |

LLM TTFT 与 total latency 为 null：当前 RecallOps 服务不发起 LLM 请求，且未配置外部 LLM trace。
