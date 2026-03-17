#!/usr/bin/env bash
# =============================================================================
# test.sh — Teste la configuration SSH et la connexion internet
# =============================================================================
# Usage : ./scripts/test.sh [--reboot]
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/usg-watchdog"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${INSTALL_DIR}/src"
PYTHON="${INSTALL_DIR}/venv/bin/python"

# Fallback si pas encore déployé
if [[ ! -f "${PYTHON}" ]]; then
    PYTHON="python3"
    SRC_DIR="${REPO_DIR}/src"
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[TEST]${NC}  $*"; }
log_success() { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[FAIL]${NC}  $*" >&2; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   USG Watchdog — Tests de configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ERRORS=0

# ─── Test 1 : Python et modules ──────────────────────────────────────────────
log_info "Test des dépendances Python..."
if ${PYTHON} -c "import paramiko; import requests; print('OK')" 2>/dev/null | grep -q "OK"; then
    log_success "paramiko et requests disponibles"
else
    log_error "Modules Python manquants — exécuter deploy.sh d'abord"
    ((ERRORS++))
fi

# ─── Test 2 : Connexion internet ─────────────────────────────────────────────
log_info "Test de la connexion internet..."
if ${PYTHON} -c "
import sys
sys.path.insert(0, '${SRC_DIR}')
from connectivity import check_connectivity
result = check_connectivity()
print('UP' if result else 'DOWN')
" 2>/dev/null | grep -q "UP"; then
    log_success "Connexion internet : UP"
else
    log_warn "Connexion internet : DOWN (normal si hors ligne)"
fi

# ─── Test 3 : Connexion SSH au USG ───────────────────────────────────────────
log_info "Test de la connexion SSH au USG..."
SSH_RESULT=$(${PYTHON} -c "
import sys
sys.path.insert(0, '${SRC_DIR}')
import logging
logging.basicConfig(level=logging.WARNING)
from usg import test_ssh_connection
result = test_ssh_connection()
print('OK' if result else 'FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "${SSH_RESULT}" == "OK" ]]; then
    log_success "Connexion SSH au USG : OK"
else
    log_error "Connexion SSH au USG : ÉCHEC"
    echo ""
    echo "  Vérifier :"
    echo "  1. USG_IP dans src/config.py (actuel : $(grep USG_IP ${SRC_DIR}/config.py | head -1))"
    echo "  2. Clé SSH : sudo ./scripts/setup_ssh.sh"
    echo "  3. SSH activé sur le USG (Controller > Settings > Device Authentication)"
    echo ""
    ((ERRORS++))
fi

# ─── Test 4 : Notification Telegram ──────────────────────────────────────────
log_info "Test des notifications Telegram..."
TELEGRAM_RESULT=$(${PYTHON} -c "
import sys
sys.path.insert(0, '${SRC_DIR}')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print('NOT_CONFIGURED')
else:
    from notifier import send_notification
    result = send_notification('🧪 Test de notification USG Watchdog')
    print('OK' if result else 'FAIL')
" 2>/dev/null || echo "ERROR")

case "${TELEGRAM_RESULT}" in
    "OK")           log_success "Notification Telegram envoyée" ;;
    "NOT_CONFIGURED") log_warn "Telegram non configuré (optionnel)" ;;
    *)              log_error "Notification Telegram échouée" ; ((ERRORS++)) ;;
esac

# ─── Test 5 : Reboot (si --reboot passé) ─────────────────────────────────────
if [[ "${1:-}" == "--reboot" ]]; then
    echo ""
    log_warn "⚠️  MODE REBOOT RÉEL — Le USG va redémarrer dans 5 secondes !"
    log_warn "Ctrl+C pour annuler..."
    sleep 5
    log_info "Envoi du reboot..."
    REBOOT_RESULT=$(${PYTHON} -c "
import sys
sys.path.insert(0, '${SRC_DIR}')
import logging
logging.basicConfig(level=logging.INFO)
from usg import reboot_usg
result = reboot_usg()
print('OK' if result else 'FAIL')
" 2>&1)
    if echo "${REBOOT_RESULT}" | grep -q "OK$"; then
        log_success "Commande reboot envoyée au USG"
    else
        log_error "Reboot échoué"
        ((ERRORS++))
    fi
fi

# ─── Résumé ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ ${ERRORS} -eq 0 ]]; then
    log_success "Tous les tests passés — configuration OK !"
    echo ""
    echo "  → Déployer : sudo ./scripts/deploy.sh"
else
    log_error "${ERRORS} test(s) échoué(s) — corriger avant de déployer"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exit ${ERRORS}
