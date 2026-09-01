#requires -Version 7.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$base = 'http://localhost:8000'
$proxy = if ($env:RECALLOPS_TRUSTED_PROXY_TOKEN) { $env:RECALLOPS_TRUSTED_PROXY_TOKEN } else { 'dev-proxy-token' }
Invoke-RestMethod -Method Post -Uri "$base/dev/bootstrap?x_proxy_token=$proxy" -ContentType 'application/json' -Body '{}'
$headers = @{'x-proxy-token'=$proxy;'x-tenant-id'='tenant-demo';'x-workspace-id'='workspace-demo';'x-user-id'='ou_maintainer'}
$draftBody = @{thread_id='omt_demo';messages=@(@{message_id='om_demo';source_url='https://open.feishu.cn/demo/thread';content="故障现象：付款成功后订单状态长时间未更新`n最终根因：order-service 数据库连接池耗尽`n临时方案：max_pool_size 从 50 调整到 200`n长期行动：改造动态连接池`nPAYMENT_5032 影响 payment-service"})} | ConvertTo-Json -Depth 5
$draft = Invoke-RestMethod -Method Post -Uri "$base/v1/drafts" -Headers $headers -ContentType 'application/json' -Body $draftBody
$headers['x-request-id'] = "demo-commit-$($draft.draft_id)"
$commit = Invoke-RestMethod -Method Post -Uri "$base/v1/incidents" -Headers $headers -ContentType 'application/json' -Body (@{draft_id=$draft.draft_id;confirm=$true} | ConvertTo-Json)
$search = Invoke-RestMethod -Method Post -Uri "$base/v1/incidents/search" -Headers $headers -ContentType 'application/json' -Body (@{query='付款以后订单一直不更新';mode='hybrid'} | ConvertTo-Json)
@{draft=$draft;commit=$commit;search=$search} | ConvertTo-Json -Depth 8
