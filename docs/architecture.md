# 架构与安全边界

飞书消息先经过 OpenClaw Channel。工具工厂只从 OpenClaw 的可信运行时上下文读取 `requesterSenderId`，模型参数中没有用户或 Workspace 身份字段。插件以共享代理密钥和受信任身份头调用 FastAPI。

后端先验证代理密钥和 Workspace 成员关系，再执行检索。Incident、Source、Service、Action 与索引 Job 在一次提交事务中写入；确认前 Draft 不会成为正式记录。修正使用 Revision，不静默覆盖。

SQLite 模式用于测试和本地快速演示，使用可复现的哈希嵌入；生产 Compose 使用 PostgreSQL。`memory-service/sql/postgres.sql` 提供 pgvector、FTS 和作用域索引。生产 Embedding 模型接入点是 `app.retrieval.embed`，切换模型时必须更新模型名和版本并重建索引。

证据内容是不可信数据，不得作为系统指令执行。工具结果包含结构化事实、来源 URL 和明确的回答策略；OpenClaw Skill 规定无证据拒答，并区分历史事实与当前推测。

