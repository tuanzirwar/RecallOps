export type TrustedContext = { tenantId: string; workspaceId: string; requesterSenderId: string };

export class RecallOpsClient {
  constructor(private readonly baseUrl: string, private readonly proxyToken: string, private readonly fetcher: typeof fetch = fetch) {}
  async request(path: string, method: string, body: unknown, context: TrustedContext, requestId = crypto.randomUUID()) {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      method,
      headers: {"content-type":"application/json", "x-proxy-token":this.proxyToken, "x-tenant-id":context.tenantId,
        "x-workspace-id":context.workspaceId, "x-user-id":context.requesterSenderId, "x-request-id":requestId},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(`RecallOps ${response.status}: ${JSON.stringify(data)}`);
    return data;
  }
}

