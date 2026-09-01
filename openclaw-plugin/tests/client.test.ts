import {describe,expect,it,vi} from "vitest";
import {RecallOpsClient} from "../src/client.js";
describe("trusted context",()=>{it("injects identity headers instead of accepting model identity",async()=>{
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({ok:true}),{status:200,headers:{"content-type":"application/json"}}));
  const client=new RecallOpsClient("http://api","secret",fetcher as typeof fetch);
  await client.request("/v1/incidents/search","POST",{query:"x",user_id:"forged"},{tenantId:"t",workspaceId:"w",requesterSenderId:"trusted"},"req");
  const init=fetcher.mock.calls[0][1] as RequestInit; expect((init.headers as Record<string,string>)["x-user-id"]).toBe("trusted");
});});
