#!/usr/bin/env bash
# =============================================================================
# validate.sh -- Quality gate: run all checks before pushing
# =============================================================================
# Usage: ./scripts/validate.sh
# Exit 0 = all checks pass, non-zero = at least one failed
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_DIR}/src"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

echo ""
echo "---------------------------------------------------"
echo "   USG Watchdog -- Validation pre-push"
echo "---------------------------------------------------"
echo ""

ERRORS=0
# Le venv du projet est cree par deploy.sh sous "venv/" ; ".venv/" est tolere
# pour les postes de dev qui suivent l'autre convention. Fallback : python3
# systeme (qui n'a pas forcement pytest -- la section tests le signalera).
PYTHON=""
for candidate in "${REPO_DIR}/venv/bin/python" "${REPO_DIR}/.venv/bin/python"; do
    if [[ -f "${candidate}" ]]; then
        PYTHON="${candidate}"
        break
    fi
done
if [[ -z "${PYTHON}" ]]; then
    PYTHON="python3"
fi

# --- 1. Syntax check --------------------------------------------------------
log_info "Verification syntaxe Python..."
SYNTAX_OK=true
for pyfile in $(find "${SRC_DIR}" -name "*.py" -type f); do
    if ! "${PYTHON}" -m py_compile "${pyfile}" 2>/dev/null; then
        log_error "Erreur syntaxe : ${pyfile}"
        SYNTAX_OK=false
    fi
done
if [[ "${SYNTAX_OK}" == true ]]; then
    log_success "Syntaxe OK"
else
    ((ERRORS++))
fi

# --- 2. Import check --------------------------------------------------------
log_info "Verification imports..."
if PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "
import watchdog
import config
import connectivity
import usg
import state
import events
import report
import messages
print('OK')
" 2>/dev/null | grep -q "OK"; then
    log_success "Imports OK"
else
    log_error "Echec import -- verifier les dependances"
    ((ERRORS++))
fi

# --- 3. Tests + coverage ----------------------------------------------------
log_info "Execution des tests..."
TEST_OUTPUT=$("${PYTHON}" -m pytest "${REPO_DIR}/tests/" \
    --cov="${SRC_DIR}" \
    --cov-fail-under=80 \
    -q --tb=line 2>&1) || {
    log_error "Tests echoues :"
    echo "${TEST_OUTPUT}" | tail -20
    ((ERRORS++))
}

if [[ ${ERRORS} -eq 0 ]]; then
    PASSED=$(echo "${TEST_OUTPUT}" | grep -oE '[0-9]+ passed' | head -1)
    COVERAGE=$(echo "${TEST_OUTPUT}" | grep -oE 'TOTAL.*[0-9]+%' | grep -oE '[0-9]+%' | tail -1)
    log_success "Tests OK (${PASSED}, coverage ${COVERAGE:-?})"
fi

# --- 4. Secrets scan --------------------------------------------------------
log_info "Scan de secrets dans le diff..."
if git -C "${REPO_DIR}" diff --cached --diff-filter=ACMR -- '*.py' '*.sh' '*.env' 2>/dev/null | \
    grep -iE '(bot_token|webhook_url|ssh_password|api_key)\s*=\s*["\x27][^"\x27]' | \
    grep -v 'os\.getenv\|os\.environ\|getenv(' > /dev/null 2>&1; then
    log_error "Secrets potentiels detectes dans le diff staged"
    ((ERRORS++))
else
    log_success "Pas de secrets detectes"
fi

# --- 5. Conventional commits check -------------------------------------------
log_info "Verification du dernier commit..."
LAST_MSG=$(git -C "${REPO_DIR}" log -1 --pretty=%s 2>/dev/null || echo "")
if [[ -n "${LAST_MSG}" ]] && ! echo "${LAST_MSG}" | grep -qE '^(feat|fix|security|refactor|docs|test|chore|perf):'; then
    log_warn "Le dernier commit ne suit pas la convention : '${LAST_MSG}'"
    # Warning seulement, pas bloquant
fi

# --- Resume ------------------------------------------------------------------
echo ""
echo "---------------------------------------------------"
if [[ ${ERRORS} -eq 0 ]]; then
    log_success "Toutes les validations passent -- pret a push"
else
    log_error "${ERRORS} validation(s) echouee(s) -- corriger avant de push"
fi
echo "---------------------------------------------------"
echo ""

exit "${ERRORS}"
