#!/usr/bin/env bash
# Sets up a rented Linux GPU machine to measure models (docs/tracks/B-graphrag/next-runs.md).
#
#     bash scripts/setup_gpu_box.sh [DATA_DIR] [--with-extract]
#
# UNTESTED: written on a machine without a GPU or Linux. Read it before the first run and fix what breaks.
#
# For Ubuntu 22.04 or 24.04 with the NVIDIA driver and the CUDA toolkit (nvcc) present, as in the "devel" images
# of cloud GPU services; run from the repository's root. It
#   1. installs the build tools, and Python 3.12 with the project's packages in .venv (through uv);
#   2. builds llama.cpp's llama-server with CUDA at the pinned release tag;
#   3. downloads the three model files of CLAUDE.md from Hugging Face;
#   4. starts the answer model on port 8080 and the embedding model on port 8081 with the settings of
#      graphrag/README.md ("Running locally"), and the extraction model on 8082 with --with-extract;
#   5. prints the two commands to run next.
# DATA_DIR (default $KG_DATA, else /workspace/kg) holds the build, the models and the server logs: put it on a disk
# that is kept when the machine is stopped. A second run downloads and builds nothing, and leaves running servers be.
# The servers listen on 127.0.0.1 only: reach them from elsewhere through an SSH tunnel, never an open port.
set -euo pipefail

# ---- every version in one place ---------------------------------------------------------------------------------
LLAMA_CPP_TAG="b12015"            # the release every recorded run used (on Windows); built here from its source
UV_VERSION="0.8.0"                # installs Python 3.12 whatever the image ships
PYTHON_VERSION="3.12"
HF_REVISION="main"                # pin a commit of each model repository here once one has been checked
LLM_REPO="Qwen/Qwen3-8B-GGUF";                    LLM_FILE="Qwen3-8B-Q4_K_M.gguf"
EXTRACT_REPO="unsloth/Qwen3-4B-Instruct-2507-GGUF"; EXTRACT_FILE="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
EMBED_REPO="Qwen/Qwen3-Embedding-0.6B-GGUF";      EMBED_FILE="Qwen3-Embedding-0.6B-Q8_0.gguf"
# -------------------------------------------------------------------------------------------------------------------

DATA="${KG_DATA:-/workspace/kg}"
WITH_EXTRACT=0
for arg in "$@"; do
  case "$arg" in
    --with-extract) WITH_EXTRACT=1 ;;
    -*) echo "unknown option $arg" >&2; exit 2 ;;
    *) DATA="$arg" ;;
  esac
done
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LLAMA_DIR="$DATA/llama.cpp-$LLAMA_CPP_TAG"
SERVER="$LLAMA_DIR/build/bin/llama-server"
MODELS="$DATA/models"
LOGS="$DATA/logs"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
mkdir -p "$DATA" "$MODELS" "$LOGS"
cd "$REPO"

say() { printf '\n== %s\n' "$*"; }

say "1. Tools and Python $PYTHON_VERSION"
command -v nvidia-smi >/dev/null || { echo "nvidia-smi is missing: this machine has no NVIDIA driver." >&2; exit 1; }
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
missing=""
for tool in git cmake make g++ curl; do command -v "$tool" >/dev/null || missing="$missing $tool"; done
if [ -n "$missing" ]; then
  $SUDO apt-get update -q
  $SUDO apt-get install -y -q git cmake build-essential curl ca-certificates
fi
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
fi
export PATH="$HOME/.local/bin:$PATH"
[ -x .venv/bin/python ] || uv venv --python "$PYTHON_VERSION" .venv
uv pip install --python .venv/bin/python -q -r requirements.lock.txt
uv pip install --python .venv/bin/python -q -e .

say "2. llama.cpp $LLAMA_CPP_TAG with CUDA"
if [ -x "$SERVER" ]; then
  echo "built already: $SERVER"
else
  if ! command -v nvcc >/dev/null && [ -x /usr/local/cuda/bin/nvcc ]; then export PATH="/usr/local/cuda/bin:$PATH"; fi
  command -v nvcc >/dev/null || { echo "nvcc is missing: choose a CUDA 'devel' image, or install the CUDA toolkit." >&2; exit 1; }
  [ -d "$LLAMA_DIR/.git" ] || git clone --depth 1 --branch "$LLAMA_CPP_TAG" https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
  cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DGGML_CUDA=ON -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
  cmake --build "$LLAMA_DIR/build" --config Release -j "$(nproc)" --target llama-server
fi
"$SERVER" --version 2>&1 | head -n 2 || true

say "3. Model files into $MODELS"
fetch() {  # repository, file: downloads to a partial file, then renames, so an interrupted download resumes
  local target="$MODELS/$2"
  if [ -s "$target" ]; then echo "present: $2"; return; fi
  curl -fL --retry 5 -C - -o "$target.part" "https://huggingface.co/$1/resolve/$HF_REVISION/$2"
  mv "$target.part" "$target"
}
fetch "$LLM_REPO" "$LLM_FILE"
fetch "$EMBED_REPO" "$EMBED_FILE"
fetch "$EXTRACT_REPO" "$EXTRACT_FILE"
# The checksums go with each run's record (B-F19): the file a profile names is then the file that was measured.
(cd "$MODELS" && sha256sum "$LLM_FILE" "$EMBED_FILE" "$EXTRACT_FILE" | tee "$DATA/models.sha256")

say "4. Servers"
start() {  # port, log name, then llama-server's arguments; a port that already answers is left as it is
  local port="$1" name="$2"; shift 2
  if curl -fs "http://127.0.0.1:$port/health" >/dev/null 2>&1; then echo "running already on port $port"; return; fi
  nohup "$SERVER" --host 127.0.0.1 --port "$port" "$@" >"$LOGS/$name.log" 2>&1 &
  for _ in $(seq 1 180); do
    if curl -fs "http://127.0.0.1:$port/health" >/dev/null 2>&1; then echo "$name ready on port $port"; return; fi
    sleep 2
  done
  echo "$name did not start: read $LOGS/$name.log" >&2; exit 1
}
# The answer model (E17): thinking off, one slot, 32k (graphrag/README.md).
start 8080 qwen3-8b -m "$MODELS/$LLM_FILE" -c 32768 -np 1 -ngl 99 --jinja \
  --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3-8b
start 8081 qwen3-embedding -m "$MODELS/$EMBED_FILE" --embedding --pooling last -c 8192 -b 2048 -ub 2048 -ngl 99 \
  --alias qwen3-embedding-0.6b
if [ "$WITH_EXTRACT" -eq 1 ]; then
  start 8082 qwen3-4b -m "$MODELS/$EXTRACT_FILE" -c 32768 -np 1 -ngl 99 --jinja --alias qwen3-4b
fi
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

say "5. Next"
cat <<EOF
Copy the K1 package (public data) to data/interim/k1/ak3-demo-v1/ first, then:

  .venv/bin/python -m graphrag.bench check qwen3-8b.local
  .venv/bin/python -m graphrag.bench run qwen3-8b.local --suite full --k1 data/interim/k1/ak3-demo-v1

Logs: $LOGS. Model checksums: $DATA/models.sha256.
EOF
