# Model profiles

One file per model on one address. `python -m graphrag.bench check <profile>` says whether it is usable; `run` measures it; `compare` lines runs up. The fields are explained in the [engine README](../../../graphrag/README.md#trying-a-model-profiles-and-the-bench-d-62-d-68).

| Profile | Model and where it runs | Use |
|---|---|---|
| `qwen3-8b.local` | Qwen3-8B, 4-bit, llama.cpp on a GPU, port 8080 | The baseline model of every recorded result; a rented GPU runs this |
| `qwen3-4b.local` | Qwen3-4B, 4-bit, llama.cpp, port 8082 | The extraction model |
| `qwen3-4b.laptop-cpu` | Qwen3-4B, 4-bit, llama.cpp on a laptop CPU, port 8080 | A slow check with a real model when no GPU is at hand |
| `qwen3-8b.openrouter` | Qwen3-8B served by a third party | The demo and quick checks, public data only. Unverified until `check` has run |

## Adding one

Any server that speaks the OpenAI API works. Copy a profile and change three fields:

| Server | `base_url` | `model` |
|---|---|---|
| llama.cpp (`llama-server`) | `http://127.0.0.1:8080/v1` | The server's `--alias` |
| Ollama | `http://127.0.0.1:11434/v1` | The tag you pulled, for example `qwen3:8b` |
| LM Studio | `http://127.0.0.1:1234/v1` | The name its server page shows |
| vLLM | `http://127.0.0.1:8000/v1` | The `--served-model-name` |
| A rented machine | The same, through `ssh -L 8080:127.0.0.1:8080 <machine>` | As above |

Rules:

- Only open-weight models of about 8B parameters or smaller (specification D-37).
- An address that is not on this machine counts as hosted and takes public data only (D-68). A rented machine reached through an SSH tunnel is on this machine's address.
- Scores are comparable only between runs of the same model copy. Ollama and vLLM ship their own copies and settings, so give such a profile its own `compare_as` and rerun the baseline with it before comparing anything.
- Thinking must be off, and the model must honour a JSON schema. `check` tests both; do not skip it.
