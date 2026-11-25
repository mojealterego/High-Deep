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
