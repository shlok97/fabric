# Local validation — 21 October 2026

Status: working local evidence POC. This is not an evaluation of end-to-end answer quality or production tenant security.

## Tests

73 tests passed on Python 3.12.13 / macOS arm64 with MCP 1.30.0 and FastEmbed 0.9.0. The six real-model cases ran with already downloaded BGE-small weights. The suite includes:

- Shared entitlements, two private tenants, two same-tenant users and a workspace outsider.
- Unknown/missing credentials, forged identity/owner/SQL/path fields, guessed and known forbidden references.
- Current grants, disabled identities/connections, connection-level principal changes before reindexing.
- Authorized ranking before top-k; principal restrictions on both passage text and catalog visibility.
- Real offline vector inference, semantic paraphrase retrieval, hybrid/semantic isolation, incremental vectors and delete/revoke behavior.
- Read-only live source reads, PIT-like synthetic vintage cutoffs, exact basis, units, nulls, missing sources, stale numeric citations and descriptor revisions.
- Unchanged/update/delete sync, failed-scan rollback, symlink exclusions and bounded chunks.
- Actual local HTTP authentication/Host/Origin checks and a real MCP client/server stdio session with identity revocation between calls.

No model API key was used. SDK transport tests do not establish that a Claude agent chooses the correct tool or answers correctly.

## Reproducible diagnostic

```sh
uv sync --extra mcp --extra dev --extra semantic
uv run --no-sync python -m fabric demo
uv run --no-sync python -m fabric embed --download-model
FABRIC_TEST_MODEL_CACHE="$PWD/data/models/bge-small" uv run --no-sync pytest -q
uv run --no-sync python scripts/evaluate.py --model-cache data/models/bge-small
```

This creates a temporary synthetic workspace, runs 31 deterministic checks, adds 100,000 source rows, measures 100 repetitions and deletes its temporary source/state. The original demo is not changed. It leaves a local receipt at `reports/local/semantic-evaluation.json` only when that output path is explicitly supplied; the default is `reports/local/evaluation.json`.

One observed warm in-process run:

| Operation | p50 | p95 |
|---|---:|---:|
| Keyword search | 0.939 ms | 1.235 ms |
| One numeric source read | 1.072 ms | 1.543 ms |
| Hybrid search with local embedding | 3.686 ms | 4.167 ms |

Source database size was 16,306,176 bytes. Eight passages were embedded, with zero numeric-row embeddings. Model identity was `BAAI/bge-small-en-v1.5:65fa9b555f6efb7f272e48d38fca7e1805a62077b4d87d6fb87616e07ae50449`. External inference calls and model API cost were zero. Hardware, cache state, filesystem and workload affect timings; they exclude HTTP/MCP transport, cold loading, network, upstream production work and the answering agent.

The paraphrase fixture uses `manufacturing facilities increased turnover`, while the filing mentions `capacity expansion` and `revenue`. Keyword retrieval has no hit; local semantic search includes the relevant filing in the top three. This is one hand-authored relevance check, not a representative recall benchmark. Semantic modes can include irrelevant passages; no judge certifies their support.

The small corpus also illustrates a limit: all authorized raw passage text was 1,370 bytes, while one retrieved evidence bundle including provenance was 1,516 bytes. It does not establish token savings. A strong direct-tools agent could retrieve compact data itself. The diagnostic's full-context byte count is not a competitive baseline.

## Separate internal Altys smoke

An operator used a read-only, three-second-bounded query to capture three current-view observations and one canonical metric definition. A separate ignored local snapshot was read through Fabric: numbers, null, unit, provenance, revalidated references and denied access for a no-entitlement synthetic tenant passed. Historical cutoff use was deliberately refused because the export did not include full vintage history.

The private snapshot and detailed receipts are outside this repository. There were no production writes, no real customer-source reads, no email/Vault access and no live Altys serving integration. The local research/document services were unavailable. This does not certify financial correctness, backtest safety or client-owner mapping.

## Product hypothesis still open

The planned 60-case pilot compares the same authenticated agent using direct tools, direct tools plus Mem0, Fabric without memory, and Fabric plus Mem0. Freeze facts/source versions and independent expected claims; randomize repeated cold/warm runs; measure supported accuracy, unsupported claims, actual tokens/cost, evidence recall and end-to-end latency. Jev is an optional later ablation.

That experiment has not run. Claude Code was installed but signed out in this environment. Mem0, Jev, Gmail/GitHub connectors, production RLS, private-client integration and multi-workspace hosting are not qualified by these results.
