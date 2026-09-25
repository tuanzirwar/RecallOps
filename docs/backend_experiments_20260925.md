# RecallOps 后端化实验记录（2026-09-25）

## 可复现边界

代码基线为 `ccfdae4` 加当前工作区改动。宿主机为 Windows、Intel Core Ultra 9 275HX（24 逻辑处理器）、Python 3.14；Docker Desktop 29.7.2。Compose 使用 MySQL 8.4、RabbitMQ 3.13、Redis 7.4，容器 Python 3.12。测试数据为合成故障材料；模型调用使用固定响应 HTTP 桩或确定性解析器，没有真实模型密钥，也没有企业生产事故数据。

新链路为：`POST /v1/extractions` 将任务与 Outbox 同事务入库 → Publisher 获得 RabbitMQ 发布确认 → 独立 Worker 抽取并提交 Draft → 人工修订和确认 → MySQL 事务写入 Incident、Source、Revision 与审核结果 → 授权检索。Worker 提交结果后才 ACK；重复投递按任务终态去重。模型模式在每次调用前通过 Redis Lua 共享令牌桶申请额度；Redis 不可用时不放行调用，任务保留为可重试状态。

## 功能验证

- 后端 pytest：9 passed。OpenClaw 插件 `npm run build` 成功，`npm test`：1 passed。
- 完整 Compose 的真实 HTTP 闭环成功：任务受理、异步生成草稿、人工审核入库均完成。单次受理耗时 37.4 ms，任务完成耗时 968.2 ms；**单样本不是 P95**。原始记录：`eval/reports/compose_smoke.json`。
- 本机独立 API/Publisher/Worker 进程的真实 HTTP 验收：Outbox 尚未发布时任务保持 queued，恢复 Publisher 后成功；重复投递未增加抽取次数，审核修订和按证据检索成功。记录：`eval/reports/backend_smoke.json`。

## MySQL 事务、一致性与权限

同一请求编号对同一草稿并发审核，真实 HTTP + MySQL 单轮结果：

| 并发请求 | 成功响应 | 5xx/超时 | 最终 Incident | Source | 响应结果一致 |
|---:|---:|---:|---:|---:|---|
| 2 | 2/2 | 0 | 1 | 1 | 是 |
| 10 | 10/10 | 0 | 1 | 1 | 是 |
| 100 | 100/100 | 0 | 1 | 1 | 是 |

同一请求编号携带不同内容返回 409；跨 Workspace 按 ID 读取返回 404；Viewer 审核返回 403。不同请求编号并发审核同一草稿时，10 次请求中 1 次创建、9 次业务冲突，最终仅 1 条 Incident。故障注入在事务内已执行部分 SQL 后抛错，回滚后草稿仍 pending，Incident/Source/Revision 均为 0。原始记录：`eval/reports/mysql_consistency.json`、`eval/reports/mysql_rollback.json`。这些是本机单轮验证，不推断长期服务可靠率。

## MySQL 服务关联查询 N+1 对照

同一 MySQL 实例、同一 10K 条合成 Incident、相同权限与请求；仅切换服务名逐条查询和批量关联加载。单请求 SQL 次数由同进程 TestClient 的 SQLAlchemy 事件计数；响应延迟由真实 HTTP 服务测量，先预热，再每版各测 3 次。

| 实现 | 单请求 SQL | HTTP 耗时 3 次（ms） | 均值（ms） |
|---|---:|---|---:|
| 逐条加载 | 10039 | 7056.79 / 7234.30 / 7205.60 | 7165.56 |
| 批量加载 | 40 | 581.44 / 610.16 / 621.05 | 604.22 |

两版返回的前五个 Incident ID 一致。该实验能支持“N+1 查询次数与本机延迟下降”的描述；3 次样本不足以给出稳定 P95/P99，且 MySQL 版本仍对授权范围内记录做 Python 排序。`EXPLAIN` 在这份单 Workspace 集中的合成数据上选择了状态索引，不能声称复合索引带来收益。原始记录：`eval/reports/mysql_query_benchmark.json`。

## RabbitMQ 与 Outbox 故障注入

| 故障点 | 次数 | 结果 |
|---|---:|---|
| 任务/Outbox 已入库，Publisher 尚未发布 | 20 | 20 条 Outbox 保持 pending，恢复后 20/20 成功 |
| 结果提交后重复投递 | 20 | 20/20 仍成功，额外抽取次数 0 |
| Broker 中断期间受理任务，之后重启 | 20 | 中断时 20/20 queued，恢复后 20/20 成功 |
| Worker 已开始模型 HTTP 调用、尚未提交和 ACK 时强制退出 | 20 | 重启 Worker 后 20/20 成功，重复 Draft 0 |

前三项使用 Compose 固定解析器；最后一项使用独立 Worker 和固定响应 HTTP 模型桩，20 个任务共发生 40 次模型 HTTP 调用。这说明**业务结果去重不等于外部模型调用恰好一次**。记录：`eval/reports/queue_faults.json`、`eval/reports/rabbit_recovery.json`。单机 Docker 故障测试不代表高可用集群。

## Redis 共享额度

使用真实 Redis 7.4 Lua、2/4 个独立 Python 进程、同一总额度 8 次/秒和桶容量 8、4 秒内共 48 个申请。静态方案将同一合法总额度均分到各进程；共享方案使用同一个令牌桶。

| Worker | 负载 | 静态放行 | 共享放行 | 窗口上界 |
|---:|---|---:|---:|---:|
| 2 | 均匀 | 38 | 39 | 39 |
| 2 | 偏斜 | 23 | 38 | 39 |
| 4 | 均匀 | 36 | 39 | 39 |
| 4 | 偏斜 | 13 | 39 | 39 |

四组共享方案均未超过包含初始令牌的窗口上界。4 Worker 偏斜组的额度利用率按本窗口上界计为 13/39 → 39/39。另用不可连接的 Redis 地址验证调用拒绝放行。两份原始记录：`eval/reports/redis_multiworker.json`、`eval/reports/redis_quota_benchmark.json`。这是短窗口固定工作负载验证，尚未测量真实上游模型的限额响应或不同故障恢复时延。

## 简历可用表述

> **RecallOps｜研发故障复盘与异步处理平台**：将故障材料抽取移至独立 Worker，以 MySQL 事务发件箱、RabbitMQ 持久化消息和提交后 ACK 串联草稿生成与人工审核；通过请求指纹、唯一约束和行锁处理重复提交与并发审核。在 MySQL 真实 HTTP 实验中，100 路同键审核全部返回成功且只生成 1 条正式记录；20 次 Worker 调用中断均恢复为可追踪成功任务，重复草稿为 0。针对服务名 N+1 查询，在同一 MySQL 10K 合成记录上将单请求 SQL 从 10039 次降至 40 次，3 次 HTTP 测量均值从 7165.56 ms 降至 604.22 ms。基于 Redis Lua 实现跨 Worker 共享模型额度；4 进程偏斜负载短窗实验中，放行数相较合法静态切分由 13/39 提升至 39/39，未观察到越限。

此表述仅对应本机合成负载、固定响应模型桩与当前实验，不应写成生产事故处理经验、真实模型抽取质量或稳定容量 SLA。获得真实模型配置后，需补测抽取正确率、完整任务时延、失败率与上游限额行为。
