#!/usr/bin/env bash
# =============================================================================
# uninstall.sh -- Cleanly remove the USG Watchdog service
# =============================================================================

set -euo pipefail

SERVICE_NAME="usg-watchdog"
SERVICE_USER="usg-watchdog"
INSTALL_DIR="/opt/usg-watchdog"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    log_error "Executer en root : sudo $0"
    exit 1
fi

echo ""
echo "---------------------------------------------------"
echo "   USG Watchdog -- Desinstallation"
echo "---------------------------------------------------"
echo ""

# Stop and disable service
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    log_info "Arret du service..."
    systemctl stop "${SERVICE_NAME}"
    log_success "Service arrete"
fi

if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    systemctl disable "${SERVICE_NAME}"
    log_success "Service desactive"
fi

# Remove systemd unit file
if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    rm "/etc/systemd/system/${SERVICE_NAME}.service"
    log_success "Service systemd supprime"
fi

systemctl daemon-reload

# Remove logrotate config
if [[ -f "/etc/logrotate.d/${SERVICE_NAME}" ]]; then
    rm "/etc/logrotate.d/${SERVICE_NAME}"
    log_success "Logrotate supprime"
fi

# Remove install directory (with SSH keys)
if [[ -d "${INSTALL_DIR}" ]]; then
    read -rp "  Supprimer ${INSTALL_DIR} (cles SSH incluses) ? (o/N) : " CONFIRM || CONFIRM=""
    if [[ "${CONFIRM,,}" == "o" || "${CONFIRM,,}" == "oui" || "${CONFIRM,,}" == "y" ]]; then
        [[ -n "${INSTALL_DIR}" && "${INSTALL_DIR}" != "/" ]] || {
            log_error "INSTALL_DIR invalide"
            exit 1
        }
        rm -rf "${INSTALL_DIR}"
        log_success "Repertoire ${INSTALL_DIR} supprime"
    else
        log_info "Repertoire conserve : ${INSTALL_DIR}"
    fi
fi

# Remove logs
read -rp "  Supprimer les logs /var/log/usg-watchdog.log* ? (o/N) : " CONFIRM_LOGS || CONFIRM_LOGS=""
if [[ "${CONFIRM_LOGS,,}" == "o" || "${CONFIRM_LOGS,,}" == "oui" || "${CONFIRM_LOGS,,}" == "y" ]]; then
    rm -f /var/log/usg-watchdog.log*
    log_success "Logs supprimes"
fi

# Remove service user
if id "${SERVICE_USER}" &>/dev/null; then
    read -rp "  Supprimer l'utilisateur systeme ${SERVICE_USER} ? (o/N) : " CONFIRM_USER || CONFIRM_USER=""
    if [[ "${CONFIRM_USER,,}" == "o" || "${CONFIRM_USER,,}" == "oui" || "${CONFIRM_USER,,}" == "y" ]]; then
        userdel "${SERVICE_USER}" 2>/dev/null || true
        log_success "Utilisateur ${SERVICE_USER} supprime"
    fi
fi

echo ""
log_success "Desinstallation terminee"
echo "---------------------------------------------------"
echo ""
