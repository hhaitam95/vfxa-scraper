#!/bin/bash

set -euo pipefail

REPO="$HOME/Desktop/vfxa-scraper"
PROJECT_DIR="$REPO/VFXA HTML Project"

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

echo "Branch:"
git branch --show-current

echo
echo "Remote:"
git remote -v | head -2

echo
echo "Creating project directory..."
mkdir -p "$PROJECT_DIR"

echo
echo "------------------------------------------------------------"
echo "Moving project files"
echo "------------------------------------------------------------"

# Root-level archive/project file types to move.
FILE_PATTERNS=(
    "*.html"
    "*.py"
    "*.sh"
    "*.json"
    "*.csv"
    "*.ipynb"
)

for pattern in "${FILE_PATTERNS[@]}"; do
    find "$REPO" \
        -maxdepth 1 \
        -type f \
        -name "$pattern" \
        -print0 |
    while IFS= read -r -d '' file; do
        echo "  $(basename "$file")"
        mv "$file" "$PROJECT_DIR/"
    done
done

echo
echo "------------------------------------------------------------"
echo "Moving transcription TXT files"
echo "------------------------------------------------------------"

# TXT files belong in the transcription folder INSIDE the project.
TRANSCRIPTION_DIR="$PROJECT_DIR/VFXA Transcription"
mkdir -p "$TRANSCRIPTION_DIR"

find "$REPO" \
    -maxdepth 1 \
    -type f \
    -name "*.txt" \
    -print0 |
while IFS= read -r -d '' file; do
    echo "  $(basename "$file")"
    mv "$file" "$TRANSCRIPTION_DIR/"
done

echo
echo "============================================================"
echo "FINAL PROJECT STRUCTURE"
echo "============================================================"
echo

echo "Root:"
find "$REPO" \
    -maxdepth 1 \
    -mindepth 1 \
    ! -name ".git" \
    -print \
    | sort

echo
echo "Project files:"
find "$PROJECT_DIR" \
    -maxdepth 1 \
    -type f \
    -print \
    | sed "s#^$PROJECT_DIR/##" \
    | sort

echo
echo "Transcriptions:"
find "$TRANSCRIPTION_DIR" \
    -maxdepth 1 \
    -type f \
    -print \
    | sed "s#^$TRANSCRIPTION_DIR/##" \
    | sort

echo
echo "============================================================"
echo "GIT STATUS"
echo "============================================================"
echo

git status --short

echo
echo "============================================================"
echo "STAGING"
echo "============================================================"
echo

git add -A

git status --short

echo
echo "============================================================"
echo "COMMIT"
echo "============================================================"
echo

git commit -m "Organize VFXA HTML project files"

echo
echo "============================================================"
echo "PUSH"
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
echo "Final status:"
git status