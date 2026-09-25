import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { RecallOpsClient } from "./client.js";
const Config = Type.Object({ baseUrl: Type.String(), proxyToken: Type.String(), tenantId: Type.String(), workspaceId: Type.String() });
const result = (details) => ({ content: [{ type: "text", text: JSON.stringify(details) }], details });
const trusted = (config, context) => {
    if (!context.requesterSenderId)
        throw new Error("RecallOps requires a trusted inbound requesterSenderId");
    return { tenantId: config.tenantId, workspaceId: config.workspaceId, requesterSenderId: context.requesterSenderId };
};
export default defineToolPlugin({
    id: "recallops", name: "RecallOps", description: "Search and curate confirmed incident memory", configSchema: Config,
    tools: (tool) => [
        tool({ name: "incident_search", label: "Search incidents", description: "Search confirmed historical incidents and evidence.", parameters: Type.Object({ query: Type.String(), service_names: Type.Optional(Type.Array(Type.String())), error_codes: Type.Optional(Type.Array(Type.String())), top_k: Type.Optional(Type.Number()), mode: Type.Optional(Type.Union([Type.Literal("fts"), Type.Literal("vector"), Type.Literal("hybrid")])) }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request("/v1/incidents/search", "POST", params, trusted(config, context))); } }),
        tool({ name: "incident_extract", label: "Extract incident", description: "Submit trusted thread messages for asynchronous backend extraction. Returns a task ID.", parameters: Type.Object({ thread_id: Type.String(), messages: Type.Array(Type.Object({ message_id: Type.String(), content: Type.String(), source_url: Type.String() })) }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request("/v1/extractions", "POST", params, trusted(config, context))); } }),
        tool({ name: "incident_extraction_get", label: "Get extraction", description: "Poll an extraction task until it succeeds or fails; a succeeded task contains an unconfirmed draft.", parameters: Type.Object({ task_id: Type.String() }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request(`/v1/extractions/${encodeURIComponent(params.task_id)}`, "GET", undefined, trusted(config, context))); } }),
        tool({ name: "incident_extraction_retry", label: "Retry extraction", description: "Explicitly retry a failed extraction task.", parameters: Type.Object({ task_id: Type.String() }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request(`/v1/extractions/${encodeURIComponent(params.task_id)}/retry`, "POST", {}, trusted(config, context))); } }),
        tool({ name: "incident_commit", label: "Commit incident", description: "Commit only after the user explicitly confirms the displayed draft.", parameters: Type.Object({ draft_id: Type.String(), corrections: Type.Optional(Type.Record(Type.String(), Type.Unknown())), confirm: Type.Boolean() }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request("/v1/incidents", "POST", params, trusted(config, context))); } }),
        tool({ name: "incident_get", label: "Get incident", description: "Get one authorized incident and its sources.", parameters: Type.Object({ incident_id: Type.String() }),
            async execute(params, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request(`/v1/incidents/${encodeURIComponent(params.incident_id)}`, "GET", undefined, trusted(config, context))); } }),
        tool({ name: "incident_correct", label: "Correct incident", description: "Create an audited revision of a confirmed incident.", parameters: Type.Object({ incident_id: Type.String(), field: Type.String(), new_value: Type.String(), reason: Type.String() }),
            async execute({ incident_id, ...body }, config, context) { const client = new RecallOpsClient(config.baseUrl, config.proxyToken); return result(await client.request(`/v1/incidents/${encodeURIComponent(incident_id)}`, "PATCH", body, trusted(config, context))); } }),
    ]
});
