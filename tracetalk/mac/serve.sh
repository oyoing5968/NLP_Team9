#!/usr/bin/env bash
# The Mac's own Ollama on 127.0.0.1:11435 (this machine only), models and keys inside _mac_runtime. Foreground in its
# own terminal; Ctrl-C stops it. Keep it on only while using TraceTalk.
exec bash "$(dirname "$0")/run.sh" ollama serve
