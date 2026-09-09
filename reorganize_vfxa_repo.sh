#!/bin/bash

set -euo pipefail

REPO="$HOME/Desktop/vfxa-scraper"

HTML_DIR="$REPO/VFXA HTML Archive"
TXT_DIR="$REPO/VFXA Transcription"

echo "============================================================"
echo "VFXA REPOSITORY REORGANIZATION"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO"
echo

if [ ! -d "$REPO/.git" ]; then
    echo "ERROR: $REPO is not a Git repository."
    exit 1
fi

cd "$REPO"

echo "Current branch:"
git branch --show-current

echo
echo "Remote:"
git remote -v | head -2

echo
echo "Creating directories..."
mkdir -p "$HTML_DIR"
mkdir -p "$TXT_DIR"

echo
echo "------------------------------------------------------------"
echo "Moving HTML files"
echo "------------------------------------------------------------"

find "$REPO" \
    -maxdepth 1 \
    -type f \
    -name "*.html" \
    -print0 |
while IFS= read -r -d '' file; do
    echo "  $(basename "$file")"
    mv "$file" "$HTML_DIR/"
done

echo
echo "------------------------------------------------------------"
echo "Moving Python files"
echo "------------------------------------------------------------"

find "$REPO" \
    -maxdepth 1 \
    -type f \
    -name "*.py" \
    -print0 |
while IFS= read -r -d '' file; do
    echo "  $(basename "$file")"
    mv "$file" "$HTML_DIR/"
done

echo
echo "------------------------------------------------------------"
echo "Moving VFXA notebook"
echo "------------------------------------------------------------"

if [ -f "$REPO/VFXA_All_Access_Web_Scraper.ipynb" ]; then
    echo "  VFXA_All_Access_Web_Scraper.ipynb"
    mv \
        "$REPO/VFXA_All_Access_Web_Scraper.ipynb" \
        "$HTML_DIR/"
fi

echo
echo "------------------------------------------------------------"
echo "Moving transcription TXT files"
echo "------------------------------------------------------------"

find "$REPO" \
    -maxdepth 1 \
    -type f \
    -name "*.txt" \
    -print0 |
while IFS= read -r -d '' file; do
    echo "  $(basename "$file")"
    mv "$file" "$TXT_DIR/"
done

echo
echo "============================================================"
echo "RESULTING STRUCTURE"
echo "============================================================"
echo

echo "VFXA HTML Archive:"
find "$HTML_DIR" \
    -maxdepth 1 \
    -type f \
    | sed "s#^$HTML_DIR/##" \
    | sort

echo
echo "VFXA Transcription:"
find "$TXT_DIR" \
    -maxdepth 1 \
    -type f \
    | sed "s#^$TXT_DIR/##" \
    | sort

echo
echo "============================================================"
echo "GIT STATUS"
echo "============================================================"
echo

git status --short

echo
echo "============================================================"
echo "STAGING CHANGES"
echo "============================================================"
echo

git add -A

git status --short

echo
echo "============================================================"
echo "COMMIT"
echo "============================================================"
echo

git commit -m "Organize VFXA archive and transcription files"

echo
echo "============================================================"
echo "PUSHING TO ORIGIN/MAIN"
echo "============================================================"
echo

git push origin main

echo
echo "============================================================"
echo "DONE"
echo "============================================================"
echo

echo "Latest commit:"
git log -1 --oneline

echo
echo "Remote status:"
git status
