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

## Adaptive inference routing

An operator can opt into a bounded batch of queue executions with a shared
process-local circuit breaker:

```sh
python3 -m highdeep work-batch --db jobs.db --tenant local --worker local-1 \
  --config backends.json --max-jobs 100 --failure-threshold 3 --cooldown 30
```

The executor filters by capability, generation-token limit, circuit state and
capacity, then ranks eligible backends by configured priority, in-flight count,
EWMA response latency and name. The circuit states are closed, open and
half-open (one recovery probe at a time). In-flight responses from an older
circuit epoch cannot close a circuit opened by a newer failure. Metrics contain
backend labels, counters and EWMA latency, not request content or credentials.

The batch worker is sequential; applications embedding AdaptiveExecutor can
share it across threads. Circuit state and concurrency bounds are per executor
instance, not per cluster, and reset at process exit. Backends are trusted
operator configuration: do not mix providers with incompatible data-handling
policies. A failed request is not automatically replayed; a later independent
job may be routed elsewhere. If no backend is available the existing worker
marks that job failed. The metrics do not measure actual tokens or GPU usage.

## Memory, symbolic verification and controlled policy evolution

Memory is opt-in, tenant-scoped and persistent in the existing SQLite database.
It supports lexical cosine ranking over normalized word counts, typed graph
edges, bounded breadth-first traversal, chronological episodes and logical
deletion. It does not implement learned embeddings, neural Engram, secure
physical erasure or authenticated tenant identity.

```sh
ID=$(python3 -m highdeep memory-put --db jobs.db --tenant local --key note-1 "Model routing observations")
python3 -m highdeep memory-search --db jobs.db --tenant local routing
python3 -m highdeep memory-neighbors --db jobs.db --tenant local "$ID"
python3 -m highdeep run --config backends.json --memory-db jobs.db --memory-tenant local --memory-query routing "Summarize routing"
python3 -m highdeep symbolic '1/3+1/6'
```

A workflow step may specify `rational_expected` instead of `expected`.
The verifier compares exact rational values using a restricted AST interpreter,
with bounded length, nesting, operations and integer size. Calls, names,
floating-point literals, powers and arbitrary Python execution are rejected.
This proves arithmetic equality only, not general theorems. Retrieved memory
is untrusted context, not a security boundary; only explicitly selected records
are sent to a configured inference backend.

For controlled evolution, initialize a policy, collect paired observations on
trusted evaluation tasks, evaluate a candidate ordering, and explicitly use
the promoted policy at runtime:

```sh
python3 -m highdeep evolve-init --db jobs.db --tenant local --config backends.json
python3 -m highdeep evolve-collect --config backends.json --tasks evaluation.json > replay.json
python3 -m highdeep evolve-status --db jobs.db --tenant local
python3 -m highdeep evolve-promote --db jobs.db --tenant local --config backends.json --evidence replay.json --expected HEAD_SHA BACKEND_B BACKEND_A
python3 -m highdeep evolve-verify --db jobs.db --tenant local
python3 -m highdeep work-batch --db jobs.db --tenant local --worker local-1 --config backends.json --evolved-policy
```

Here HEAD_SHA is the evolution ledger head returned by evolve-status, not a Git
commit. Backend names must be a complete permutation of the configured names.
Evaluation tasks are JSON objects containing id, capability, max_tokens,
prompt and exactly one trusted expected or rational_expected answer.
The collector performs real HTTP inference, alternates backend ordering,
and records measured wall-clock latency and checked correctness. It is bounded
to 2,048 calls; operators should estimate provider costs before running it.
The replay report requires no per-case correctness regression, at least four
paired correct cases, at least 5% mean latency gain on jointly correct cases
and at most 5% p95 latency regression. The policy and evidence fingerprints
are bound to the configuration and a compare-and-swap ledger head.
Repeated identical case sets are rejected, even when timings change.
The local hash chain detects accidental edits but is neither signed nor
externally anchored and cannot prove dataset independence or prevent a
privileged database administrator from rewriting the complete ledger.
The replay gate is a controlled configuration optimization, not autonomous
source mutation, neural training, DGM or general recursive self-improvement.
Production promotion requires representative, independently controlled cases
and real model benchmarks; the integration tests use local HTTP fixtures.
