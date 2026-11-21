#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
RTK_BIN="$HOME/.local/bin/rtk"
RTK_VERSION=v1.2.1
INSTALLER_SHA256=85ae798116fa0dda42a627333b36903b71291785c7395ad3634f8419f7adaeb5

for tool in curl sha256sum uv; do
    command -v "$tool" >/dev/null || { printf 'Required tool missing: %s\n' "$tool" >&2; exit 1; }
done
test -x "$ROOT/.venv/bin/python" || { printf '%s\n' 'Activate/setup the repo .venv first.' >&2; exit 1; }

# A matching binary alone does not identify the OSS edition; verify its release digest.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/$RTK_VERSION/install.sh" -o "$work/install.sh"
printf '%s  %s\n' "$INSTALLER_SHA256" "$work/install.sh" | sha256sum --check --status
RTK_VERSION="$RTK_VERSION" RTK_EDITION=oss RTK_INSTALL_DIR="$HOME/.local/bin" sh "$work/install.sh"

uv pip install --python "$ROOT/.venv/bin/python" 'ast-grep-cli==0.51.3'
"$RTK_BIN" --version
"$ROOT/.venv/bin/ast-grep" --version
printf '%s\n' 'Ready: export PATH="$HOME/.local/bin:$PATH"; source .venv/bin/activate'
