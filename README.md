# ResolveAI

ResolveAI is a local-first, synthetic-data MVP for retail support operations. It demonstrates a safe boundary: a language model may propose one of a few tools, while trusted backend code scopes data and controls every state transition. It is **not production-ready** and it does not move real money.

## What works locally

- Customer order lookup, policy answers, ticket proposal/confirmation, human handoff, refund-review proposal/confirmation, supervisor approval, and one-time sandbox refund execution.
- Two isolated synthetic organizations. Ava at Northstar cannot read Liam's order or Harbor data.
- Durable turns: the API stores a turn and outbox record before returning `202`; a separate worker consumes the queued work.
- Local demo identities only when `APP_ENV=development` and `AUTH_PROVIDER=local`. Cloud mode rejects local auth at startup.

## Start the full local demo

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:3000. Start as **Ava Customer** and ask `Where is order NS-1042?`; create a ticket; request a refund for `NS-1042`; then switch to **Sam Supervisor** to approve it. Switch to Ava to see the persisted conversation. All identities and orders are synthetic `.test` data.

For a direct Python run, install `apps/api/requirements.txt`, copy `apps/api/.env.example` to `apps/api/.env`, run `uvicorn app.main:app --reload` in `apps/api`, and run `python -m app.worker` separately.

## Useful commands

```bash
npm ci --ignore-scripts
npm run web:build
npm run web:typecheck
cd apps/api && python -m pytest
cd apps/api && python -m ruff check .
docker compose down
```

`docker compose down` preserves the named database volume. Removing it is deliberately not part of normal startup.

## Architecture and trust boundary

The browser only calls the API. The API derives the organization and role from a trusted authentication adapter, writes a customer message and outbox event atomically, and returns a turn ID. The worker processes the persisted turn later. Confirmation and approval are backend-owned state transitions; sandbox refund execution is separate from the chat/model path.

See [decisions](docs/decisions.md) and [progress](docs/progress.md). The API includes a Bedrock Converse client-side tool loop, but the local runnable path is explicitly `AI_PROVIDER=mock`; it never silently falls back from Bedrock.

## AWS deployment status

`infra/` contains a starting CDK stack for private RDS, Lambda images, SQS/DLQ, outbox recovery scheduling, S3/CloudFront, Secrets Manager, and a 29-second HTTP API integration. It has **not** been synthesized or deployed. It needs a selected AWS region, Cognito callback/domain configuration, a specific Bedrock model/inference profile, narrowed Bedrock IAM resources, VPC endpoint/NAT cost decision, migration job, budget alarms, and deployment authorization.

Before deployment, inspect `cdk diff`, expected RDS/NAT/CloudFront/Lambda/SQS costs and retention, then establish rollback and teardown procedures. Do not call this architecture free: RDS and NAT have meaningful baseline cost.

## Known limitations

- Nuxt 3 is required by the brief but reached end of life on 31 July 2026. Migrate to Nuxt 4 before public use.
- Cognito token exchange/JWT validation, CloudWatch alarms, migration job, full CDK validation, rate-limit store, production headers/CSP, Playwright, and the 60-case live/deterministic evaluation suite are not complete.
- The Alembic baseline exists, but local demo startup currently uses metadata bootstrap for zero-friction setup; production must be migration-only.
- The external payment adapter is intentionally absent. Sandbox refunds change only synthetic PostgreSQL records.
