#!/usr/bin/env bash
# AI-EMS v5.1 File Change Tracker
# Tracks file changes and generates summary for devlog

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================="
echo " AI-EMS v5.1 Change Tracker"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

# Show git status summary
echo -e "\n## Git Status"
git status --short

# Show file counts by directory
echo -e "\n## Changed Files by Directory"
git status --short | awk '{print $2}' | xargs -I {} dirname {} | sort | uniq -c | sort -rn

# Show recent commits (last 10)
echo -e "\n## Recent Commits"
git log --oneline -10 2>/dev/null || echo "No commits yet"

# Show lines added/removed
echo -e "\n## Lines Changed (staged + unstaged)"
git diff --stat HEAD 2>/dev/null || git diff --stat 2>/dev/null || echo "No changes"

echo -e "\n========================================="
echo "Done."
