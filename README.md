# High-Deep
A modular DeepSeek-derived engineering platform, not a merged neural checkpoint.

## Reproducible upstream workspace
47 pinned Git submodules, grouped by responsibility. Each retains its upstream license and origin. Some repositories have no explicit root license; public visibility is not permission to redistribute. They are referenced rather than vendored pending license review. Recursive initialization of nested dependencies is a separate trust decision.

```sh
git clone https://github.com/mojealterego/High-Deep.git
cd High-Deep
git submodule update --init
python3 -m unittest discover -s tests -v
python3 -m highdeep inventory
```

Run text inference with a trusted operator-supplied configuration containing a JSON array of backend objects. Fields: name, hardware (cpu/cuda/ascend/remote), capabilities (chat/code/math/reasoning), endpoint (HTTPS origin or explicit loopback HTTP), model, max_tokens, priority (lower wins), optional token_env. Backend servers and model weights must be installed separately. No automatic execution of upstream scripts.

```sh
python3 -m highdeep run --config backends.json --capability reasoning --max-tokens 256 "Solve 2+2"
```

The control plane uses only Python 3.10+ standard library. The adapter implements non-streaming OpenAI-compatible chat completions. Hardware labels describe configured backends, not verified accelerator support. Configuration is trusted operator input; do not accept it from remote clients. No redirects, dynamic tools or shell execution. Per-socket timeout is not a strict overall request deadline. Do not expose this CLI directly as a multi-tenant service.

See docs/ROADMAP.md and docs/source-bom.cdx.json. The latter inventories pinned source projects, not their resolved transitive dependencies.

## Durable queue

```sh
python3 -m highdeep submit --db jobs.db --tenant local --key example-1 "Solve 2+2"
python3 -m highdeep work --db jobs.db --tenant local --worker local-1 --config backends.json
# Use the job identifier printed by submit:
python3 -m highdeep status --db jobs.db --tenant local JOB_ID
```

The SQLite queue provides atomic claims, tenant-scoped idempotency, bounded attempts after lease expiration, and fenced completion. Worker processes can execute concurrently. Tenant identifiers are operator-supplied, not authenticated identities; do not expose this to untrusted callers. Crash recovery is at-least-once execution, not exactly-once external inference. Store the database on a local filesystem with restrictive permissions; payloads and results are not encrypted by this module. Explicit inference failures are terminal, and expired claims are recovered on subsequent polling.
