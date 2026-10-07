#!/data/data/com.termux/files/usr/bin/bash
# termux_setup.sh -- native packages only, no pip, no compiling.
set -e
pkg update -y
pkg install -y poppler tesseract python
echo "--- versions ---"
pdftoppm -v 2>&1 | head -1
tesseract --version 2>&1 | head -1
python3 --version
echo "SETUP-OK"
