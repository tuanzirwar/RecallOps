# RecallOps

面向研发团队的故障记忆与混合 RAG MVP：从飞书话题生成待确认草稿，确认后以事务写入 PostgreSQL；查询时在授权 Workspace 内并行使用 PostgreSQL FTS 和 pgvector 召回，再用 RRF 融合，返回结构化根因、处理方案和原始证据。

## 已实现

- FastAPI：健康检查、草稿、确认提交、详情、搜索、修订、索引任务 API。
- Human-gated Memory：草稿不进入正式检索，提交要求 `confirm=true` 和 Maintainer 权限。
- 幂等：`content_hash` 防重复草稿，`x-request-id` 防重试重复写入。
- 数据模型：Tenant、Workspace、成员、Incident、Service、Source、Action、Revision、Job 和检索日志。
- 混合检索：PostgreSQL FTS 与 pgvector 在 Tenant/Workspace 条件内召回；RRF 融合。SQLite 测试模式使用同接口的本地确定性基线。
- Evidence-first：结果包含来源 URL 和回答策略；无可信结果时返回空结果。
- 可修正：正式字段修改生成 Revision，并创建可重试的重新索引 Job。
- OpenClaw：五个 TypeScript ESM 工具，身份只取可信 `requesterSenderId`，没有模型可覆盖的用户字段。
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

API 文档位于 `http://localhost:8000/docs`。首次演示由 `/dev/bootstrap` 创建演示租户、Workspace 和成员；生产部署应禁用该路由并通过管理流程预置成员。

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
- 所有读取和两路 PostgreSQL 候选召回都在 Tenant/Workspace 条件下执行，未授权按 ID 读取返回 404。
- Source 内容按不可信证据处理，不能成为 Prompt 指令。
- 正式写入和修正需要角色权限；核心事实、来源、关系、行动项和索引 Job 在事务中提交。
- 生产环境应在反向代理层禁止公网访问 `/dev/bootstrap`，轮换代理密钥，并按组织要求补充 PostgreSQL RLS。

更多信息见 [`docs/architecture.md`](docs/architecture.md)、[`docs/evaluation.md`](docs/evaluation.md) 和 [`docs/demo-script.md`](docs/demo-script.md)。

首次阅读项目建议从 [`docs/项目快速上手.md`](docs/项目快速上手.md) 开始。

项目设计、简历与面试材料：

- [`docs/RecallOps项目设计文档.md`](docs/RecallOps项目设计文档.md)：统一的生命周期、触发、队列、审批、检索和维护设计。
- [`docs/RecallOps简历表述.md`](docs/RecallOps简历表述.md)：当前代码安全口径与自动触发完成后的增强口径。
- [`docs/RecallOps面试完全手册.md`](docs/RecallOps面试完全手册.md)：高频问题、连续追问和指标说明。

## 当前边界

仓库不包含真实飞书企业应用凭据，也不伪造线上效果。真实飞书验收需要在你的 OpenClaw/飞书环境中完成安装、授权和群 allowlist；生产 Embedding/LLM 需要在 `app.retrieval.embed` 的接口处接入并重新生成向量。当前实现可在无模型密钥环境完整演示可信写入、权限、检索、证据、修订和评测闭环。
