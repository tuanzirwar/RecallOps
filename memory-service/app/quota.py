from __future__ import annotations

import time

import redis

from .config import get_settings


class QuotaUnavailable(RuntimeError):
    pass


# 时间取自 Redis，所有 Worker 在同一时钟下原子扣减令牌。
TOKEN_BUCKET = """
local current = redis.call('TIME')
local now = tonumber(current[1]) + tonumber(current[2]) / 1000000
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens')) or capacity
local last = tonumber(redis.call('HGET', KEYS[1], 'time')) or now
tokens = math.min(capacity, tokens + math.max(0, now - last) * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'time', now)
redis.call('EXPIRE', KEYS[1], math.max(2, math.ceil(capacity / rate) * 2))
return allowed
"""


def acquire(timeout_seconds: float = 30) -> None:
    settings = get_settings()
    if settings.model_quota_rate <= 0 or settings.model_quota_capacity < 1:
        raise ValueError("model quota must be positive")
    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if client.eval(TOKEN_BUCKET, 1, "recallops:model-quota", settings.model_quota_rate, settings.model_quota_capacity):
                return
            if time.monotonic() >= deadline:
                raise QuotaUnavailable("model quota wait timed out")
            time.sleep(min(0.2, max(0.01, 1 / settings.model_quota_rate)))
    except redis.RedisError as exc:
        raise QuotaUnavailable("shared model quota unavailable") from exc
