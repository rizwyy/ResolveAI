# Decisions

| Decision | Reason | Consequence |
|---|---|---|
| Modular monolith | A solo founder needs one deployable boundary, not microservice overhead. | API and worker share domain code. |
| Durable turns + outbox | A chat request can exceed an HTTP timeout. | The API returns `202`; a worker processes only persisted work. |
| Local identity adapter only in dev/test | Demo convenience must not become cloud authentication. | Cloud startup rejects `AUTH_PROVIDER=local`. Cognito wiring is deployment work. |
| Mock AI is explicit | Fake replies must not masquerade as Bedrock. | `AI_PROVIDER=mock` is visible in configuration; Bedrock needs a model ID. |
| Sandbox refund adapter | Demo money movement cannot be real. | It changes the demo database transactionally and is labelled sandbox. |
| Nuxt 3 preserved | It was specified by the brief. | Nuxt says v3 reached EOL on 31 July 2026; migrate to Nuxt 4 before a public release. |

## Trust boundary

```text
browser -> authenticated API -> database/outbox -> worker -> model adapter
                  |                    ^              |
                  +-- permission/state checks ---------+
```

The model can request an allowlisted tool. It never provides identity, tenant, permission, confirmation, approval, or refund execution authority.
