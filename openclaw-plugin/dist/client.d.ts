export type TrustedContext = {
    tenantId: string;
    workspaceId: string;
    requesterSenderId: string;
};
export declare class RecallOpsClient {
    private readonly baseUrl;
    private readonly proxyToken;
    private readonly fetcher;
    constructor(baseUrl: string, proxyToken: string, fetcher?: typeof fetch);
    request(path: string, method: string, body: unknown, context: TrustedContext, requestId?: `${string}-${string}-${string}-${string}-${string}`): Promise<any>;
}
