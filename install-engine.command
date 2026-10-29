#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")" && pwd)"
TRANSYH_UV="$(command -v uv || true)"
if [[ -z "$TRANSYH_UV" ]]; then
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [[ -x "$candidate" ]]; then TRANSYH_UV="$candidate"; break; fi
  done
fi
if [[ -z "$TRANSYH_UV" ]]; then
  echo "请先从 https://docs.astral.sh/uv/getting-started/installation/ 安装 uv。"
  echo "使用 Homebrew 时可运行：brew install uv。然后重新运行本脚本。"
  exit 1
fi
if [[ "$(uname -s)" == Darwin ]]; then
  TRANSYH_ENGINE="$HOME/Library/Application Support/TransYH/engine"
else
  TRANSYH_ENGINE="$HOME/.local/share/TransYH/engine"
fi
echo "正在安装 TransYH 本地引擎：$TRANSYH_ENGINE"
"$TRANSYH_UV" venv --python 3.12 --allow-existing "$TRANSYH_ENGINE"
if [[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]]; then
  "$TRANSYH_UV" pip sync --python "$TRANSYH_ENGINE/bin/python" "$TASK_ROOT/engine/requirements-macos.lock"
else
  "$TRANSYH_UV" pip install --python "$TRANSYH_ENGINE/bin/python" -r "$TASK_ROOT/engine/requirements.txt"
fi
echo '{"action":"check"}' | "$TRANSYH_ENGINE/bin/python" "$TASK_ROOT/engine/worker.py" --stdio
echo "安装完成。回到 Zotero 设置 → TransYH，点击“检测本地引擎”。"
echo "首次翻译会自动下载开源模型和字体；不需要云平台账号或会员。"
