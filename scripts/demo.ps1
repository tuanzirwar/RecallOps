#requires -Version 7.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$port = if ($env:RECALLOPS_HTTP_PORT) { $env:RECALLOPS_HTTP_PORT } else { '18000' }
$base = "http://localhost:$port"
$proxy = if ($env:RECALLOPS_TRUSTED_PROXY_TOKEN) { $env:RECALLOPS_TRUSTED_PROXY_TOKEN } else { 'dev-proxy-token' }
Invoke-RestMethod -Method Post -Uri "$base/dev/bootstrap?x_proxy_token=$proxy" -ContentType 'application/json' -Body '{}'
$headers = @{'x-proxy-token'=$proxy;'x-tenant-id'='tenant-demo';'x-workspace-id'='workspace-demo';'x-user-id'='ou_maintainer'}
$suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
$body = @{thread_id="omt_demo_$suffix";messages=@(@{message_id="om_demo_$suffix";source_url="https://open.feishu.cn/demo/thread/$suffix";content="故障现象：付款成功后订单状态长时间未更新`n最终根因：order-service 数据库连接池耗尽`n临时方案：max_pool_size 从 50 调整到 200`n长期行动：改造动态连接池`nPAYMENT_5032 影响 payment-service"})} | ConvertTo-Json -Depth 5
$task = Invoke-RestMethod -Method Post -Uri "$base/v1/extractions" -Headers $headers -ContentType 'application/json' -Body $body
$draft = $null
for ($i = 0; $i -lt 100; $i++) {
  $draft = Invoke-RestMethod -Method Get -Uri "$base/v1/extractions/$($task.task_id)" -Headers $headers
  if ($draft.status -eq 'succeeded') { break }
  if ($draft.status -eq 'failed') { throw "抽取失败：$($draft.last_error)" }
  Start-Sleep -Milliseconds 200
}
if ($draft.status -ne 'succeeded') { throw "抽取超时：$($task.task_id)" }
$headers['x-request-id'] = "demo-commit-$suffix"
$commit = Invoke-RestMethod -Method Post -Uri "$base/v1/incidents" -Headers $headers -ContentType 'application/json' -Body (@{draft_id=$draft.draft_id;confirm=$true} | ConvertTo-Json)
$search = Invoke-RestMethod -Method Post -Uri "$base/v1/incidents/search" -Headers $headers -ContentType 'application/json' -Body (@{query='PAYMENT_5032';mode='fts'} | ConvertTo-Json)
@{task=$task;draft=$draft;commit=$commit;search=$search} | ConvertTo-Json -Depth 8
