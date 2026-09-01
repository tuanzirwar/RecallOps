# RecallOps 演示脚本

1. 运行 `docker compose up --build`，确认 `/health` 返回 `ok`。
2. 执行 `pwsh -File scripts/demo.ps1`（PowerShell 7），演示草稿、明确确认、正式记录和语义查询。
3. 用同一 `x-request-id` 重放提交，展示返回同一 Incident ID。
4. 修改根因，展示 Revision 和 `index_status=pending`，再以管理员运行索引任务。
5. 切换到无权限 Workspace，展示搜索为空且按 ID 获取返回 404。
6. 运行 `python eval/retrieval_eval.py`，展示 FTS、向量、混合三组真实基线指标。

飞书验收需要真实企业应用凭据。在 OpenClaw 中安装构建后的插件，应用 `openclaw.example.json5` 的 Channel 设置，并将群 ID 加入 allowlist。
