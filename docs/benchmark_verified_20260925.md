# RecallOps 可复现工程评测（2026-09-25）

## 测量范围

本报告使用本机 FastAPI TestClient、SQLite 文件库和确定性 hashing embedding。规模实验使用 160 条规则生成种子扩增，在内存中运行 Python 排序，不经过数据库。检索准确率数据集由规则生成，未经独立人工标注，因此准确率只用于比较此数据集内的算法行为。服务 API 当前只返回检索证据，没有 LLM 答案生成；LLM TTFT 与总延迟不适用。本节记录早期 SQLite/TestClient 基线；同日后续完成的 MySQL/RabbitMQ/Redis 本机 Docker Compose 实验见 `docs/backend_experiments_20260925.md`。目前仍没有 PostgreSQL/pgvector 压力数据。

## 功能与正确性

`memory-service/tests` 最新复测 10 项通过。权限隔离、草稿确认入库、重复 `request_id`、修订与再索引、无答案拒答均有测试覆盖。同一 `request_id` 并发提交 2、10、100 次，每档均只生成 1 条正式 incident；成功响应分别为 2/2、10/10、84/100。100 并发下恰好一次写入成立，请求可靠性未达到全成功。

## 检索延迟与消融

既有 200 查询分阶段基线的检索端到端 P50/P95/P99 为 10.218/14.821/16.836 ms。阶段 P95：query parse 0.006 ms，embedding 0.098 ms，FTS 6.041 ms，vector search 0.893 ms，RRF 8.191 ms，reranker 0.020 ms。阶段计时来自当前本地实现，不能直接归因于 PostgreSQL FTS 或 pgvector。

160 条规则生成 incident、1140 条规则生成 query 上，FTS 的 Recall@5 为 0.9396，weighted 为 0.8808，RRF hybrid 为 0.8902。本地 hashing vector 的 Recall@5 为 0.4637。该结果显示此数据集下混合策略没有胜过 FTS，因此简历不宣称“混合检索提升准确率”。完整消融和 K=1/3/5/10 见 `eval/reports/latest.json`。

## N+1 修复与并发复测

搜索路径原先对每条候选 incident 单独查询服务名。已改为一次批量查询；相同脚本、每档 200 请求的结果如下。两个测试轮次受机器负载影响，变化只作本机对照。

| 并发 | 原 QPS | 修复后 QPS | 原 P95 ms | 修复后 P95 ms | 修复后错误率 |
|---:|---:|---:|---:|---:|---:|
| 1 | 7.425 | 15.943 | 171.502 | 73.955 | 0% |
| 10 | 6.969 | 15.712 | 1698.682 | 1205.775 | 0% |
| 50 | 6.863 | 15.379 | 7922.217 | 4560.687 | 0% |
| 100 | 1.985 | 2.092 | 94228.892 | 92204.716 | 56.5% |
| 200 | 1.591 | 1.624 | 124493.941 | 122155.860 | 69.5% |

100/200 并发仍出现严重错误，连接池观测峰值为 15，当前 SQLite/TestClient 条件下没有高并发容量证据。原始结果在 `eval/reports/system_20260924_v2`；修复后的 JSON、CSV、Markdown 在 `eval/reports/system_20260925_batch_services`。

## 规模退化

5 查询/档、内存 Python 排序的修正后结果如下；P95 因样本仅 5 个而不适合推断稳定尾延迟。

| 合成 incident 数 | mean ms | P95 ms | Python 峰值内存 |
|---:|---:|---:|---:|
| 160 | 37.575 | 40.486 | 687518 B |
| 1000 | 239.953 | 256.010 | 1713701 B |
| 10000 | 2484.784 | 2682.820 | 12438830 B |
| 100000 | 29791.135 | 32217.867 | 126874651 B |

这个结果暴露全量 Python 排序的线性瓶颈，不代表 PostgreSQL/pgvector 索引查询时间。原始 JSON、CSV、Markdown 在 `eval/reports/scale_20260925_corrected`。
