# RecallOps

面向研发团队的故障记忆与证据检索服务。当前默认 Compose 使用 MySQL 保存审核记录、RabbitMQ 执行独立抽取任务、Redis 协调多 Worker 的模型调用额度；提交材料、人工审核、正式入库和授权检索均可通过 API 完成。默认演示模式使用固定解析器，真实模型模式需配置兼容 OpenAI Chat Completions 的接口。

> 旧版 PostgreSQL FTS/pgvector 代码仍保留供对照；当前 MySQL 版本的检索排序使用本地确定性 hashing embedding。简历中的 MySQL 查询优化仅指服务关联批量加载，不能表述为 pgvector 或生产语义检索效果。

## 已实现

- FastAPI：健康检查、异步抽取任务、草稿、确认提交、详情、搜索、修订、索引任务 API。
- Human-gated Memory：草稿不进入正式检索，提交要求 `confirm=true` 和 Maintainer 权限。
- 幂等：`content_hash` 防重复任务与草稿，`x-request-id` 绑定身份和请求内容；审核结果与幂等记录同事务提交。
- 数据模型：Tenant、Workspace、成员、Incident、Service、Source、Action、Revision、Job 和检索日志。
- 检索：MySQL 先按 Tenant/Workspace 限定范围，服务名批量关联加载；本地确定性 FTS/向量排序用于可复现演示。旧 PostgreSQL FTS/pgvector 路径仍在仓库中。
- Evidence-first：结果包含来源 URL 和回答策略；无可信结果时返回空结果。
- 可修正：正式字段修改生成 Revision，并创建可重试的重新索引 Job。
- OpenClaw：异步提交、任务查询/重试、审核和证据查询工具，身份只取可信 `requesterSenderId`。
- 评测：160 条故障、1,140 条标注查询（960 条有答案、180 条无答案），比较 FTS、向量和混合方案。

## 快速启动

要求：Docker Desktop，以及用于插件构建的 Node.js 22.22.3+/24.15+/25.9+。

```powershell
Copy-Item .env.example .env
docker compose up --build
```

另开终端运行完整演示：

```powershell
pwsh -File scripts/demo.ps1
```

API 文档位于 `http://localhost:18000/docs`（可用 `RECALLOPS_HTTP_PORT` 修改宿主机端口）。首次演示由 `/dev/bootstrap` 创建演示租户、Workspace 和成员；生产部署应禁用该路由并通过管理流程预置成员。

异步业务流程：`POST /v1/extractions` 返回任务编号；轮询 `GET /v1/extractions/{task_id}`，成功后展示草稿；人工确认后调用 `POST /v1/incidents`。任务失败可调用 `POST /v1/extractions/{task_id}/retry`。API、Publisher、Worker 是独立进程；Outbox 与任务同事务写入，Publisher 确认发布，Worker 提交结果后 ACK。

默认 `RECALLOPS_EXTRACTION_MODE=fixture` 仅用于本地演示。实际调用模型时，改为 `model`，并在本地 `.env` 设置 `RECALLOPS_MODEL_BASE_URL`、`RECALLOPS_MODEL_NAME`、`RECALLOPS_MODEL_API_KEY`。密钥不要提交。

## 本地测试与评测

```powershell
python -m pip install -r memory-service/requirements.txt
Set-Location memory-service
python -m pytest -q
Set-Location ..
python eval/generate_dataset.py
python eval/retrieval_eval.py
Set-Location openclaw-plugin
npm install --legacy-peer-deps
npm run build
npm test
```

最新可复现基线写入 [`eval/reports/latest.json`](eval/reports/latest.json)。这些数字来自仓库内确定性哈希嵌入，不代表生产 Embedding 模型效果；接入模型后必须重新评测。

## 飞书与 OpenClaw

1. 构建 `openclaw-plugin`，将包含 `dist/`、`package.json` 和 `openclaw.plugin.json` 的目录安装到 OpenClaw。
2. 参考 [`openclaw.example.json5`](openclaw.example.json5) 配置插件、群 allowlist、`groupSessionScope: "group_topic"` 和 `replyInThread: "enabled"`。
3. 将 `RECALLOPS_TRUSTED_PROXY_TOKEN` 设置为长随机值，不要把它暴露给模型或写入仓库。
4. 将本仓库 [`SKILL.md`](SKILL.md) 放入 Agent 工作区，保证草稿展示后等待确认、证据不足时拒答。

插件接口按当前 OpenClaw 官方文档实现：[Tool plugins](https://docs.openclaw.ai/plugins/tool-plugins)、[Building plugins](https://docs.openclaw.ai/plugins/building-plugins)、[Feishu Channel](https://docs.openclaw.ai/channels/feishu)。

## 关键安全边界

- 后端不接受请求体中的用户或 Workspace 身份；插件从运行时上下文注入身份并使用代理密钥认证。
- 所有读取都在 Tenant/Workspace 条件下执行，未授权按 ID 读取返回 404。
- Source 内容按不可信证据处理，不能成为 Prompt 指令。
- 正式写入和修正需要角色权限；核心事实、来源、关系、行动项和索引 Job 在事务中提交。
- 生产环境应在反向代理层禁止公网访问 `/dev/bootstrap`，轮换代理密钥，并落实 MySQL 账号权限与备份。

更多信息见 [`docs/architecture.md`](docs/architecture.md)、[`docs/evaluation.md`](docs/evaluation.md) 和 [`docs/demo-script.md`](docs/demo-script.md)。

首次阅读项目建议从 [`docs/项目快速上手.md`](docs/项目快速上手.md) 开始。

项目设计、简历与面试材料：

- [`docs/RecallOps完整流程与分支设计.md`](docs/RecallOps完整流程与分支设计.md)：从 Session 触发到整理、审批、索引、查询和修订的全流程及异常分支。
- [`docs/RecallOps项目设计文档.md`](docs/RecallOps项目设计文档.md)：统一的生命周期、触发、队列、审批、检索和维护设计。
- [`docs/RecallOps简历表述.md`](docs/RecallOps简历表述.md)：当前代码安全口径与自动触发完成后的增强口径。
- [`docs/RecallOps面试完全手册.md`](docs/RecallOps面试完全手册.md)：高频问题、连续追问和指标说明。

## 当前边界

仓库不包含真实飞书企业应用凭据，也不伪造线上效果。真实飞书验收需要在你的 OpenClaw/飞书环境中完成安装、授权和群 allowlist；生产 Embedding/LLM 需要在 `app.retrieval.embed` 的接口处接入并重新生成向量。当前实现可在无模型密钥环境用固定响应桩演示写入、权限、检索、证据、修订与队列恢复；真实模型质量与耗时仍需单独验收。

后端改造实测结果与简历口径见 [`docs/backend_experiments_20260925.md`](docs/backend_experiments_20260925.md)。
