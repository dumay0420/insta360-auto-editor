#!/bin/bash
# 建立 skill 專用的 Python 環境（.venv）並安裝套件。只需要跑一次。
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10 以上"'
"$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python -c "import cv2, Quartz, Vision; print('安裝完成，OpenCV', cv2.__version__)"
