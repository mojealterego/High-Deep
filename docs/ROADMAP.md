# Release gates
- G01: provenance for 47 sources, SHA-256 verified against original archive; Gitlinks pin immutable revisions.
- G02: standard-library registry, deterministic capability/token routing, HTTP adapter and CLI; local tests required.
- G03: complete license audit, dependency locks, resolved SBOM, supply-chain vulnerability scan; OPEN.
- G04: native DeepInfer/DeepEP/FlashMLA/DeepGEMM/Ascend integration and real hardware benchmarks; OPEN.
- G05: modality-specific OCR, vision, image generation and 3D adapters with real model weights; OPEN.
- G06: agent DAG, scoped tool gateway, checkpoint and tenant isolation; OPEN.
- G07: 3FS/smallpond data plane, distributed recovery and accelerator stress tests; OPEN.
- G08: baseline/paired quality and performance measurements (TTFT, inter-token latency, throughput, VRAM, task success, p95/p99); OPEN.
- G09: reproducible release, security evidence and deployment verification; OPEN.

No automatic claim of faster inference, better reasoning, or improved model weights. Source references are not equivalent to runtime integration. Use a hardware-specific environment for each native project rather than merging incompatible toolchains. Do not run upstream build scripts before review.

G06 partial: SQLite durable queue, worker, idempotent submission, tenant-key scoping and fenced lease recovery implemented. Authentication, sandbox, DAG, distributed state and end-to-end tool authorization remain OPEN.

G06 update: durable DAG definitions and state, topological validation, bounded
step count and requested generation-token reservation, atomic enqueue/binding,
dependency failure propagation, exact-match gates, fail-closed lease expiry,
and CLI reconciliation/status implemented. Local test evidence covers restart
and concurrent scheduling. Tool authorization, semantic/formal verification,
distributed execution, authenticated tenancy and sandbox remain OPEN.

G02/G08 update: optional adaptive execution with process-local circuit breaker,
exclusive half-open probes, epoch fencing, per-backend concurrency bounds,
EWMA latency and content-free counters; bounded batch CLI integrated with
durable queue. Local HTTP failure/alternate-backend regression and concurrent
circuit tests added. Shared cross-process breaker state, admission queues,
authenticated provider policy and real model performance benchmarks remain OPEN.

## Stages v0.4–v0.6
- v0.4 Memory Fabric: persistent lexical retrieval, episodic records, typed graph
  links, bounded context export and opt-in inference integration implemented.
  Learned embeddings, native Engram and distributed memory remain OPEN.
- v0.5 Symbolic Engine: restricted exact-rational interpreter and workflow
  acceptance gate implemented. General SMT/Lean proof verification remains OPEN.
- v0.6 Evolution Engine: measured replay collection, per-case non-regression,
  paired latency gating, configuration-bound policy promotion with CAS and
  local hash chain, optional batch activation implemented. Signed/anchored
  evidence, external holdout governance, code evolution and weight training
  remain OPEN.

Validation: 69 local tests pass (44 baseline + 25 new). Includes subprocess CLI,
SQLite persistence and real local HTTP protocol fixtures. No real accelerator
or model-quality benchmark was run. Native upstream suites remain separate.
