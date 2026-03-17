#!/usr/bin/env bash
# =============================================================================
# uninstall.sh — Supprime proprement le service USG Watchdog
# =============================================================================

set -euo pipefail

SERVICE_NAME="usg-watchdog"
INSTALL_DIR="/opt/usg-watchdog"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR]${NC} Exécuter en root : sudo $0"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   USG Watchdog — Désinstallation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Arrêt et désactivation du service
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    log_info "Arrêt du service..."
    systemctl stop "${SERVICE_NAME}"
    log_success "Service arrêté"
fi

if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    systemctl disable "${SERVICE_NAME}"
    log_success "Service désactivé"
fi

# Suppression des fichiers systemd
[[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]] && \
    rm "/etc/systemd/system/${SERVICE_NAME}.service" && \
    log_success "Service systemd supprimé"

systemctl daemon-reload

# Suppression logrotate
[[ -f "/etc/logrotate.d/${SERVICE_NAME}" ]] && \
    rm "/etc/logrotate.d/${SERVICE_NAME}" && \
    log_success "Logrotate supprimé"

# Suppression des fichiers d'install (conservation des logs et clés SSH)
if [[ -d "${INSTALL_DIR}" ]]; then
    read -rp "  Supprimer ${INSTALL_DIR} (clés SSH incluses) ? (o/N) : " CONFIRM
    if [[ "${CONFIRM,,}" == "o" || "${CONFIRM,,}" == "oui" || "${CONFIRM,,}" == "y" ]]; then
        rm -rf "${INSTALL_DIR}"
        log_success "Répertoire ${INSTALL_DIR} supprimé"
    else
        log_info "Répertoire conservé : ${INSTALL_DIR}"
    fi
fi

# Logs
read -rp "  Supprimer les logs /var/log/usg-watchdog.log* ? (o/N) : " CONFIRM_LOGS
if [[ "${CONFIRM_LOGS,,}" == "o" || "${CONFIRM_LOGS,,}" == "oui" || "${CONFIRM_LOGS,,}" == "y" ]]; then
    rm -f /var/log/usg-watchdog.log*
    log_success "Logs supprimés"
fi

echo ""
log_success "Désinstallation terminée"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
