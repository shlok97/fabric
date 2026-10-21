# Contributing to Fabric

Start with the fictional demo and read [AGENTS.md](AGENTS.md). The implemented scope and gaps are in [the architecture](docs/architecture.md) and [validation](docs/validation.md).

Use Python 3.11+ and `uv sync --extra mcp --extra dev`. Run `uv run --no-sync pytest -q`. Optional semantic tests require `--extra semantic` and explicitly downloaded weights; see the README.

Useful contributions add a bounded read-only adapter, improve measured retrieval quality, or close an authorization/lifecycle gap. Include a fictional example, source/version semantics, limits and meaningful tests. Real private source data belongs outside the repo, including screenshots and test receipts.

Keep generic APIs separate from domain readers. Do not introduce unrestricted SQL, implicit memory extraction, ambient model keys, or production source writes. Describe what was actually tested and what still needs qualification.
