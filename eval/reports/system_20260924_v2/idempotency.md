# idempotency

| concurrency | submissions | success_responses | unique_incident_ids | official_incidents | exactly_once | elapsed_ms |
|---|---|---|---|---|---|---|
| 2 | 2 | 2 | 1 | 1 | True | 83.84 |
| 10 | 10 | 10 | 1 | 1 | True | 185.377 |
| 100 | 100 | 75 | 1 | 1 | True | 30517.391 |
