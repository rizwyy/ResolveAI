# Progress checkpoint

## Implemented locally

- Modular FastAPI/Nuxt repository with PostgreSQL Docker Compose, synthetic two-organization seed data, and environment examples.
- Local-only demo identities, customer/order organization checks, persisted conversations/messages/turns/outbox events.
- Mock support workflow: fresh order lookup, policy lookup, ticket confirmation, human handoff, refund-review confirmation, supervisor decision, and sandbox execution.
- Staff queues for tickets, approvals, metrics, and sanitised audit events.
- Alembic baseline, Dockerfiles, initial CDK stack, and workflow tests.

## Verified / pending

- Local test and build results are recorded in the README after commands run.
- Live Bedrock: pending AWS credentials, chosen supported region/model, and a bounded evaluation run.
- AWS: CDK code only until the owner approves a region, cost plan, and deployment. No deployed URL exists.

## Next safety work before public use

1. Replace local auth with Cognito JWT validation and test callback/logout/expiry.
2. Replace metadata `create_all` local bootstrap with migration-only startup.
3. Complete Cognito, API JWT authorizer, alarms, connection budget/RDS Proxy decision, migrations job, and asset deploy steps.
4. Run the supplied evaluation dataset against a selected Bedrock model with a small explicit budget.
