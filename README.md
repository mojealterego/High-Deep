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

## Durable workflow orchestration

Run a bounded dependency graph using the same queue and worker:

```sh
FLOW=$(python3 -m highdeep flow-submit --db jobs.db --tenant local --key math-1 --budget 144 --plan examples/workflow.json)
python3 -m highdeep flow-tick --db jobs.db --tenant local "$FLOW"
python3 -m highdeep work --db jobs.db --tenant local --worker local-1 --config backends.json
python3 -m highdeep flow-tick --db jobs.db --tenant local "$FLOW"
python3 -m highdeep flow-status --db jobs.db --tenant local "$FLOW"
```

Repeat tick and worker polling until the workflow reaches succeeded or failed.
Workflow graphs contain at most 32 steps. Each node is scheduled atomically with
its queue record, after all dependencies succeed. Failed dependencies block
descendants; independent branches can finish. Exact-match output gates are
deterministic acceptance checks, not mathematical proofs or guarantees of
semantic correctness. Dependency text is serialized as untrusted data, but
this does not eliminate prompt injection. No tool execution is enabled.
The budget bounds requested generation tokens across workflow nodes, not input
tokens, actual backend usage or billing. Workflow jobs have one lease attempt;
an expired running job fails closed. This deliberately avoids automatic repeated
external inference. SQLite transactions provide local persistence, not
distributed consensus. Tenant labels still require an external authentication
boundary. The operator runs reconciliation and workers; no daemon is installed.
