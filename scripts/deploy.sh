#!/usr/bin/env bash
# =============================================================================
# deploy.sh -- Deploy and start the USG Watchdog service
# =============================================================================
# Usage : sudo ./scripts/deploy.sh
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/usg-watchdog"
SERVICE_NAME="usg-watchdog"
SERVICE_USER="usg-watchdog"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

echo ""
echo "---------------------------------------------------"
echo "   USG Watchdog -- Deploiement"
echo "---------------------------------------------------"
echo ""

if [[ $EUID -ne 0 ]]; then
    log_error "Ce script doit etre execute en root : sudo $0"
    exit 1
fi

# --- Configuration interactive (.env) ----------------------------------------
ENV_FILE="${INSTALL_DIR}/.env"
mkdir -p "${INSTALL_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
    log_info "Premier deploiement -- configuration initiale"
    echo ""

    read -rp "  IP du USG (gateway) [192.168.1.1] : " INPUT_USG_IP || INPUT_USG_IP=""
    INPUT_USG_IP="${INPUT_USG_IP:-192.168.1.1}"

    read -rp "  Utilisateur SSH du USG [maintenance] : " INPUT_USG_USER || INPUT_USG_USER=""
    INPUT_USG_USER="${INPUT_USG_USER:-maintenance}"

    read -rp "  Token bot Telegram (vide = skip) : " INPUT_TG_TOKEN || INPUT_TG_TOKEN=""
    INPUT_TG_CHAT=""
    if [[ -n "${INPUT_TG_TOKEN}" ]]; then
        read -rp "  Chat ID Telegram : " INPUT_TG_CHAT || INPUT_TG_CHAT=""
    fi

    GENERATED_API_TOKEN=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")

    cat > "${ENV_FILE}" <<ENVEOF
USG_IP=${INPUT_USG_IP}
USG_USER=${INPUT_USG_USER}
TELEGRAM_BOT_TOKEN=${INPUT_TG_TOKEN}
TELEGRAM_CHAT_ID=${INPUT_TG_CHAT}
API_TOKEN=${GENERATED_API_TOKEN}
ENVEOF

    chmod 600 "${ENV_FILE}"
    chown root:root "${ENV_FILE}"
    log_success "Fichier .env cree : ${ENV_FILE}"
    log_info "API_TOKEN genere automatiquement"
    echo ""
else
    # Verifier que USG_IP est configure
    if ! grep -q "^USG_IP=" "${ENV_FILE}" 2>/dev/null; then
        echo ""
        read -rp "  IP du USG (gateway) [192.168.1.1] : " INPUT_USG_IP || INPUT_USG_IP=""
        INPUT_USG_IP="${INPUT_USG_IP:-192.168.1.1}"
        echo "USG_IP=${INPUT_USG_IP}" >> "${ENV_FILE}"
        log_success "USG_IP ajoute au .env"
    fi
    log_info "Fichier .env existant conserve : ${ENV_FILE}"
fi

# --- Python ------------------------------------------------------------------
if ! command -v python3 &>/dev/null; then
    log_error "Python3 introuvable -- installer python3"
    exit 1
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log_info "Python detecte : ${PYTHON_VERSION}"

if ! python3 -c "import venv" &>/dev/null; then
    log_info "Installation de python3-venv..."
    if command -v dnf &>/dev/null; then
        dnf install -y python3-venv
    elif command -v apt-get &>/dev/null; then
        apt-get install -y python3-venv
    else
        log_error "Impossible d'installer python3-venv -- gestionnaire de paquets inconnu"
        exit 1
    fi
fi

# --- Dedicated service user --------------------------------------------------
if ! id "${SERVICE_USER}" &>/dev/null; then
    log_info "Creation de l'utilisateur systeme ${SERVICE_USER}..."
    useradd -r -s /usr/sbin/nologin -d "${INSTALL_DIR}" "${SERVICE_USER}"
    log_success "Utilisateur ${SERVICE_USER} cree"
else
    log_info "Utilisateur ${SERVICE_USER} existe deja"
fi

# --- Copy files (atomic) -----------------------------------------------------
log_info "Copie des fichiers vers ${INSTALL_DIR}..."
install -d -m 750 "${INSTALL_DIR}" "${INSTALL_DIR}/src"

if [[ -d "${INSTALL_DIR}/.ssh" ]]; then
    log_info "Dossier .ssh existant conserve"
fi

# Atomic copy: stage in temp dir, then swap
STAGE_DIR="${INSTALL_DIR}/src.new.$$"
cp -r "${REPO_DIR}/src/." "${STAGE_DIR}/"
cp "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/"
cp "${REPO_DIR}/VERSION" "${INSTALL_DIR}/" 2>/dev/null || true
if [[ -d "${INSTALL_DIR}/src" ]]; then
    mv "${INSTALL_DIR}/src" "${INSTALL_DIR}/src.old.$$"
fi
mv "${STAGE_DIR}" "${INSTALL_DIR}/src"
rm -rf "${INSTALL_DIR}/src.old.$$" 2>/dev/null || true
log_success "Fichiers copies"

# --- Virtualenv (idempotent) -------------------------------------------------
if [[ ! -d "${INSTALL_DIR}/venv" ]]; then
    log_info "Creation du virtualenv..."
    python3 -m venv "${INSTALL_DIR}/venv"
else
    log_info "Virtualenv existant conserve"
fi
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip -q
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q
log_success "Dependances installees"

# --- Ownership ---------------------------------------------------------------
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
log_success "Permissions ajustees pour ${SERVICE_USER}"

# --- Log file ----------------------------------------------------------------
install -m 640 -o "${SERVICE_USER}" -g adm /dev/null /var/log/usg-watchdog.log 2>/dev/null || {
    touch /var/log/usg-watchdog.log
    chown "${SERVICE_USER}:adm" /var/log/usg-watchdog.log
    chmod 640 /var/log/usg-watchdog.log
}
log_success "Fichier de log cree : /var/log/usg-watchdog.log"

# --- Logrotate ---------------------------------------------------------------
install -m 644 -o root -g root \
    "${REPO_DIR}/systemd/usg-watchdog.logrotate" /etc/logrotate.d/usg-watchdog
log_success "Logrotate configure"

# --- systemd service ---------------------------------------------------------
log_info "Installation du service systemd..."
install -m 644 -o root -g root \
    "${REPO_DIR}/systemd/usg-watchdog.service" "/etc/systemd/system/${SERVICE_NAME}.service"

# --- Auto-updater timer ------------------------------------------------------
if [[ -f "${REPO_DIR}/systemd/usg-watchdog-updater.service" ]]; then
    log_info "Installation de l'auto-updater..."
    install -m 644 -o root -g root \
        "${REPO_DIR}/systemd/usg-watchdog-updater.service" /etc/systemd/system/
    install -m 644 -o root -g root \
        "${REPO_DIR}/systemd/usg-watchdog-updater.timer" /etc/systemd/system/
    # Copier le script updater
    install -d -m 750 "${INSTALL_DIR}/updater"
    cp "${REPO_DIR}/updater/"*.py "${INSTALL_DIR}/updater/"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/updater"
    log_success "Auto-updater installe"
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl enable usg-watchdog-updater.timer 2>/dev/null || true
systemctl start usg-watchdog-updater.timer 2>/dev/null || true
log_success "Service systemd + auto-updater actives au demarrage"

# --- Start -------------------------------------------------------------------
log_info "Demarrage du service..."
systemctl restart "${SERVICE_NAME}"

for (( i = 1; i <= 10; i++ )); do
    sleep 1
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        break
    fi
    if [[ "${i}" -eq 10 ]]; then
        log_error "Le service n'a pas demarre apres 10s"
        systemctl status "${SERVICE_NAME}" --no-pager -l >&2 || true
        exit 1
    fi
done

log_success "Service demarre et actif"

echo ""
echo "---------------------------------------------------"
log_success "Deploiement termine !"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status ${SERVICE_NAME}"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
echo "    sudo tail -f /var/log/usg-watchdog.log"
echo ""
echo "  Test SSH rapide :"
echo "    sudo ./scripts/test.sh"
echo "---------------------------------------------------"
echo ""
