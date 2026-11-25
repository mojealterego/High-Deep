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
