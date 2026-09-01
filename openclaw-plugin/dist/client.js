export class RecallOpsClient {
    baseUrl;
    proxyToken;
    fetcher;
    constructor(baseUrl, proxyToken, fetcher = fetch) {
        this.baseUrl = baseUrl;
        this.proxyToken = proxyToken;
        this.fetcher = fetcher;
    }
    async request(path, method, body, context, requestId = crypto.randomUUID()) {
        const response = await this.fetcher(`${this.baseUrl}${path}`, {
            method,
            headers: { "content-type": "application/json", "x-proxy-token": this.proxyToken, "x-tenant-id": context.tenantId,
                "x-workspace-id": context.workspaceId, "x-user-id": context.requesterSenderId, "x-request-id": requestId },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        const data = await response.json();
        if (!response.ok)
            throw new Error(`RecallOps ${response.status}: ${JSON.stringify(data)}`);
        return data;
    }
}
