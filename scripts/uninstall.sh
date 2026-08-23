#!/usr/bin/env bash
# =============================================================================
# uninstall.sh -- Cleanly remove the Vigil service (and, on request, the
# legacy usg-watchdog install left over from the pre-2.0.0 name)
# =============================================================================

set -euo pipefail

SERVICE_NAME="vigil"
SERVICE_USER="vigil"
INSTALL_DIR="/opt/vigil"

# Ancien nom (pre-migration) -- ce script sait le nettoyer aussi, sur demande,
# ce qui evite de dupliquer le runbook de purge J+7 (cf. PRD grand renommage
# Vigil, sprint 5, § 5.4).
LEGACY_SERVICE_NAME="usg-watchdog"
LEGACY_SERVICE_USER="usg-watchdog"
LEGACY_INSTALL_DIR="/opt/usg-watchdog"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    log_error "Executer en root : sudo $0"
    exit 1
fi

# Supprime un utilisateur systeme uniquement si aucun fichier ne lui appartient
# plus sur le systeme de fichiers local (garde -xdev, ne traverse pas les
# points de montage) -- evite un userdel qui laisserait des fichiers orphelins
# ou qui supprimerait par erreur des donnees encore utiles pendant la fenetre
# de rollback.
_userdel_safe() {
    local user="$1"
    local leftover
    leftover=$(find / -xdev -user "${user}" 2>/dev/null | grep -v '^/proc' || true)
    if [[ -n "${leftover}" ]]; then
        log_warn "Fichiers restants appartenant a ${user} detectes -- suppression de l'utilisateur annulee :"
        echo "${leftover}" | head -20
        log_warn "Nettoyer manuellement les fichiers restants puis relancer, ou 'userdel -f ${user}' en connaissance de cause"
        return 1
    fi
    userdel "${user}" 2>/dev/null || true
    return 0
}

# Desinstalle une instance complete (service + updater + logrotate + install
# dir + logs + user), parametree par nom/service/user/dir/chemin de log --
# reutilisee pour l'instance courante (vigil) et, sur demande, pour l'ancien
# nom (usg-watchdog).
_uninstall_instance() {
    local label="$1" svc="$2" user="$3" dir="$4" logpath="$5"

    if systemctl is-active --quiet "${svc}" 2>/dev/null; then
        log_info "Arret du service ${svc}..."
        systemctl stop "${svc}"
        log_success "Service ${svc} arrete"
    fi

    if systemctl is-enabled --quiet "${svc}" 2>/dev/null; then
        systemctl disable "${svc}"
        log_success "Service ${svc} desactive"
    fi

    if [[ -f "/etc/systemd/system/${svc}.service" ]]; then
        rm "/etc/systemd/system/${svc}.service"
        log_success "Service systemd ${svc} supprime"
    fi

    # Auto-updater (service + timer), nom derive : <svc>-updater
    local unit
    for unit in "${svc}-updater.service" "${svc}-updater.timer"; do
        if systemctl is-enabled --quiet "${unit}" 2>/dev/null; then
            systemctl disable --now "${unit}" 2>/dev/null || true
        fi
        if [[ -f "/etc/systemd/system/${unit}" ]]; then
            rm "/etc/systemd/system/${unit}"
            log_success "Unit ${unit} supprime"
        fi
    done

    systemctl daemon-reload

    if [[ -f "/etc/logrotate.d/${svc}" ]]; then
        rm "/etc/logrotate.d/${svc}"
        log_success "Logrotate ${svc} supprime"
    fi

    if [[ -d "${dir}" ]]; then
        read -rp "  Supprimer ${dir} (${label}, cles SSH incluses) ? (o/N) : " CONFIRM || CONFIRM=""
        if [[ "${CONFIRM,,}" == "o" || "${CONFIRM,,}" == "oui" || "${CONFIRM,,}" == "y" ]]; then
            [[ -n "${dir}" && "${dir}" != "/" ]] || {
                log_error "Repertoire invalide : ${dir}"
                return 1
            }
            rm -rf "${dir}"
            log_success "Repertoire ${dir} supprime"
        else
            log_info "Repertoire conserve : ${dir}"
        fi
    fi

    read -rp "  Supprimer les logs ${logpath}* (${label}) ? (o/N) : " CONFIRM_LOGS || CONFIRM_LOGS=""
    if [[ "${CONFIRM_LOGS,,}" == "o" || "${CONFIRM_LOGS,,}" == "oui" || "${CONFIRM_LOGS,,}" == "y" ]]; then
        rm -f "${logpath}"*
        log_success "Logs ${label} supprimes"
    fi

    if id "${user}" &>/dev/null; then
        read -rp "  Supprimer l'utilisateur systeme ${user} (${label}) ? (o/N) : " CONFIRM_USER || CONFIRM_USER=""
        if [[ "${CONFIRM_USER,,}" == "o" || "${CONFIRM_USER,,}" == "oui" || "${CONFIRM_USER,,}" == "y" ]]; then
            if _userdel_safe "${user}"; then
                log_success "Utilisateur ${user} supprime"
            fi
        fi
    fi
}

echo ""
echo "---------------------------------------------------"
echo "   Vigil -- Desinstallation"
echo "---------------------------------------------------"
echo ""

_uninstall_instance "Vigil" "${SERVICE_NAME}" "${SERVICE_USER}" "${INSTALL_DIR}" "/var/log/vigil.log"

# --- Nettoyage optionnel de l'ancien nom (usg-watchdog) -----------------------
if [[ -d "${LEGACY_INSTALL_DIR}" ]] || id "${LEGACY_SERVICE_USER}" &>/dev/null \
    || systemctl list-unit-files "${LEGACY_SERVICE_NAME}.service" &>/dev/null 2>&1; then
    echo ""
    log_info "Installation heritee usg-watchdog detectee sur cette machine"
    read -rp "  Nettoyer aussi l'ancienne installation usg-watchdog ? (o/N) : " CONFIRM_LEGACY || CONFIRM_LEGACY=""
    if [[ "${CONFIRM_LEGACY,,}" == "o" || "${CONFIRM_LEGACY,,}" == "oui" || "${CONFIRM_LEGACY,,}" == "y" ]]; then
        _uninstall_instance "usg-watchdog (legacy)" "${LEGACY_SERVICE_NAME}" "${LEGACY_SERVICE_USER}" \
            "${LEGACY_INSTALL_DIR}" "/var/log/usg-watchdog.log"
    else
        log_info "Installation heritee usg-watchdog conservee"
    fi
fi

echo ""
log_success "Desinstallation terminee"
echo "---------------------------------------------------"
echo ""
