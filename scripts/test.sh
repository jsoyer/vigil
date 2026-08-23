#!/usr/bin/env bash
# =============================================================================
# test.sh -- Test SSH config and internet connectivity
# =============================================================================
# Usage : ./scripts/test.sh [--reboot]
# =============================================================================

set -euo pipefail

readonly INSTALL_DIR="/opt/vigil"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${INSTALL_DIR}/src"
PYTHON="${INSTALL_DIR}/venv/bin/python"

# Fallback if not yet deployed
if [[ ! -f "${PYTHON}" ]]; then
    PYTHON="python3"
    SRC_DIR="${REPO_DIR}/src"
fi

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

# Load .env if it exists (same as systemd EnvironmentFile)
ENV_FILE="${INSTALL_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
fi

# Validate arguments
case "${1:-}" in
    ""|"--reboot") ;;
    *) log_error "Argument inconnu : ${1}"; exit 2 ;;
esac

echo ""
echo "---------------------------------------------------"
echo "   Vigil -- Tests de configuration"
echo "---------------------------------------------------"
echo ""

ERRORS=0

# --- Test 1 : Python and modules --------------------------------------------
log_info "Test des dependances Python..."
if PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "import paramiko; import requests; print('OK')" 2>/dev/null | grep -q "OK"; then
    log_success "paramiko et requests disponibles"
else
    log_error "Modules Python manquants -- executer deploy.sh d'abord"
    ((ERRORS++))
fi

# --- Test 2 : Internet connectivity -----------------------------------------
log_info "Test de la connexion internet..."
if PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "
from connectivity import check_connectivity
result = check_connectivity()
print('UP' if result.gateway_ok and result.internet_ok_count > 0 else 'DOWN')
" 2>/dev/null | grep -q "UP"; then
    log_success "Connexion internet : UP"
else
    log_warn "Connexion internet : DOWN (normal si hors ligne)"
fi

# --- Test 3 : SSH connection to USG ------------------------------------------
log_info "Test de la connexion SSH au USG..."
SSH_RESULT=$(PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "
import logging
logging.basicConfig(level=logging.WARNING)
from usg import test_ssh_connection
result = test_ssh_connection()
print('OK' if result else 'FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "${SSH_RESULT}" == "OK" ]]; then
    log_success "Connexion SSH au USG : OK"
else
    log_error "Connexion SSH au USG : ECHEC"
    echo ""
    echo "  Verifier :"
    echo "  1. USG_IP dans src/config.py"
    echo "  2. Cle SSH : sudo ./scripts/setup_ssh.sh"
    echo "  3. SSH active sur le USG (Controller > Settings > Device Authentication)"
    echo ""
    ((ERRORS++))
fi

# --- Test 4 : Ntfy notification -----------------------------------------
log_info "Test des notifications Ntfy..."
NTFY_RESULT=$(PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "
from config import NTFY_URL, NTFY_TOPIC
if not NTFY_URL or not NTFY_TOPIC:
    print('NOT_CONFIGURED')
else:
    from notifier import notify
    results = notify('Test de notification Vigil')
    print('OK' if results.get('ntfy') else 'FAIL')
" 2>/dev/null || echo "ERROR")

case "${NTFY_RESULT}" in
    "OK")             log_success "Notification Ntfy envoyee" ;;
    "NOT_CONFIGURED") log_warn "Ntfy non configure (optionnel)" ;;
    *)                log_error "Notification Ntfy echouee" ; ((ERRORS++)) ;;
esac

# --- Test 5 : Reboot (if --reboot passed) -----------------------------------
if [[ "${1:-}" == "--reboot" ]]; then
    if [[ $EUID -ne 0 ]]; then
        log_error "Le test de reboot necessite les droits root : sudo $0 --reboot"
        ((ERRORS++))
    else
        echo ""
        log_warn "MODE REBOOT REEL -- Le USG va redemarrer dans 5 secondes !"
        log_warn "Ctrl+C pour annuler..."
        sleep 5
        log_info "Envoi du reboot..."
        REBOOT_RESULT=$(PYTHONPATH="${SRC_DIR}" "${PYTHON}" -c "
import logging
logging.basicConfig(level=logging.INFO)
from usg import reboot_usg
result = reboot_usg()
print('OK' if result else 'FAIL')
" 2>/dev/null || echo "ERROR")
        if [[ "${REBOOT_RESULT}" == "OK" ]]; then
            log_success "Commande reboot envoyee au USG"
        else
            log_error "Reboot echoue"
            ((ERRORS++))
        fi
    fi
fi

# --- Summary -----------------------------------------------------------------
echo ""
echo "---------------------------------------------------"
if [[ ${ERRORS} -eq 0 ]]; then
    log_success "Tous les tests passes -- configuration OK !"
    echo ""
    echo "  -> Deployer : sudo ./scripts/deploy.sh"
else
    log_error "${ERRORS} test(s) echoue(s) -- corriger avant de deployer"
fi
echo "---------------------------------------------------"
echo ""

exit "${ERRORS}"
