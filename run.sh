#!/bin/bash
# 用 skill 專用的 Python 執行主程式。
# 想用別的 Python 環境：設定環境變數 INSTA360_AUTO_PY=/path/to/python
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${INSTA360_AUTO_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "找不到 Python 環境：$PY"
  echo "請先執行：$DIR/setup.sh"
  exit 1
fi
exec "$PY" "$DIR/scripts/insta360_auto.py" "$@"
