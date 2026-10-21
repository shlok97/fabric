# Fabric contributor instructions

Read README.md, docs/architecture.md and docs/validation.md first. This independent repository is a local context gateway, not an agent runtime.

- Never commit real customer data, private Altys source inventories, emails, tokens, `.env`, databases, model weights or private evaluation receipts. Use fictional fixtures and `.example` domains.
- HTTP/MCP identity comes from trusted credentials. Never take tenant, principal, source path, SQL or upstream owner authority from model arguments.
- Preserve current authorization on discovery, source reads, vector ranking and citation lookup. Test revocation, same-tenant user restrictions and deletion when modifying retrieval.
- Null is unavailable, never zero. Preserve source units, exact selectors, source clocks and versions. Do not introduce financial formulas in adapters.
- Keep source systems read-only. No sibling Python imports, ambient credentials, production migrations, deployment or automatic model calls.
- Optional integrations need explicit configuration. Do not claim a mocked provider test is a real integration or a local diagnostic is an agent benchmark.
- Run the relevant pytest suite. Use FABRIC_TEST_MODEL_CACHE for offline real-model cases; never make tests download weights implicitly.
- Keep the Loop visual direction: warm paper, indigo, honey, editorial serif; no external fonts/assets or frontend build required.
