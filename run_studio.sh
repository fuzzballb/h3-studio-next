#!/bin/bash
# Start H3 Studio with ComfyUI's own Python (it has aiohttp, numpy, Pillow and usually openai-whisper).
#   ./run_studio.sh [--port 8191] [--host 127.0.0.1]
# COMFYUI_DIR: the ComfyUI folder when this repo is not inside it (or in its custom_nodes/).  PYTHON: another interpreter.
cd "$(dirname "$0")"
if [ -z "$COMFYUI_DIR" ]; then
  for d in .. ../..; do [ -f "$d/main.py" ] && COMFYUI_DIR="$(cd "$d" && pwd)" && break; done
fi
if [ -z "$PYTHON" ]; then
  for p in "$COMFYUI_DIR/venv/bin/python" "$COMFYUI_DIR/.venv/bin/python" "$COMFYUI_DIR/python_embeded/python.exe"; do
    [ -x "$p" ] && PYTHON="$p" && break
  done
fi
PYTHON="${PYTHON:-python3}"
export COMFYUI_DIR
exec "$PYTHON" -m studio "$@"
