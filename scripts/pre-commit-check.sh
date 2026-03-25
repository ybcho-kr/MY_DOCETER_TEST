#!/usr/bin/env bash
# AI-EMS v5.1 Pre-commit Check Script
# Runs pytest, ops: write protection, and schema validation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0

echo "========================================="
echo " AI-EMS v5.1 Pre-commit Checks"
echo "========================================="

# 1. ops: write protection — ensure no AI code writes to ops: namespace
echo -e "\n${YELLOW}[1/3] ops: namespace write protection check${NC}"
# Search for redis writes to ops: namespace in layer2 (AI agent code)
OPS_VIOLATIONS=$(grep -rn 'ops:' "$PROJECT_ROOT/src/layer2/" --include='*.py' | grep -iE '(set|hset|lpush|rpush|sadd|zadd|xadd|write|put|insert)' || true)
if [ -n "$OPS_VIOLATIONS" ]; then
    echo -e "${RED}FAIL: AI layer (layer2) attempting to write to ops: namespace${NC}"
    echo "$OPS_VIOLATIONS"
    FAILED=1
else
    echo -e "${GREEN}PASS: No ops: write violations found in AI layer${NC}"
fi

# 2. Schema validation — ensure all schema files are importable
echo -e "\n${YELLOW}[2/3] Schema import validation${NC}"
cd "$PROJECT_ROOT"
if python -c "from src.shared.schemas import *" 2>/dev/null; then
    echo -e "${GREEN}PASS: All schemas import successfully${NC}"
else
    echo -e "${RED}FAIL: Schema import error${NC}"
    FAILED=1
fi

# 3. Run pytest
echo -e "\n${YELLOW}[3/3] Running pytest${NC}"
cd "$PROJECT_ROOT"
if python -m pytest tests/ -x -q --tb=short 2>/dev/null; then
    echo -e "${GREEN}PASS: All tests passed${NC}"
else
    echo -e "${RED}FAIL: Tests failed${NC}"
    FAILED=1
fi

echo -e "\n========================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All pre-commit checks passed!${NC}"
    exit 0
else
    echo -e "${RED}Pre-commit checks failed!${NC}"
    exit 1
fi
