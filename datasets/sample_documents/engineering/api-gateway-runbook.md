# API Gateway Runbook

This runbook covers day-to-day operation of the Halvorsen public API gateway.

## Rate limiting

Every API key is limited to 600 requests per minute, with a burst allowance of 100 requests.
When a client exceeds the limit the gateway answers with HTTP 429 and the error code ERR-4021.
Limits can be raised per customer by the platform team after a capacity review.

## Error codes

| Code | Meaning | First action |
|------|---------|--------------|
| ERR-4021 | Rate limit exceeded | Check the client's request pattern |
| ERR-4030 | API key revoked | Ask the customer to rotate the key |
| ERR-5003 | Upstream timeout after 30 seconds | Inspect the upstream service dashboard |

## Rollback procedure

To revert a faulty gateway release, run `gwctl rollback --to previous` from the deploy host.
After the rollback, watch the health checks for five minutes. If the 5xx error rate stays above
2 percent, page the platform on-call engineer through PagerDuty and open a SEV2 incident.

## Certificates

Gateway TLS certificates are renewed automatically 30 days before expiry. A failed renewal raises
the alert `gateway-cert-renewal-failed`, which must be handled the same working day.
