#!/usr/bin/env bash
# =============================================================================
# deploy.sh -- Deploy and start the Vigil service
# =============================================================================
# Usage : sudo ./scripts/deploy.sh
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/vigil"
SERVICE_NAME="vigil"
SERVICE_USER="vigil"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

echo ""
echo "---------------------------------------------------"
echo "   Vigil -- Deploiement"
echo "---------------------------------------------------"
echo ""

if [[ $EUID -ne 0 ]]; then
    log_error "Ce script doit etre execute en root : sudo $0"
    exit 1
fi

# --- Migration depuis l'ancien nom (usg-watchdog -> vigil) --------------------
# Si l'ancien repertoire existe et le nouveau n'existe pas encore, on migre
# uniquement .env et .ssh (deplaces, jamais copies silencieusement). Le venv
# n'est PAS repris ici -- il est toujours (re)cree plus bas par
# `python3 -m venv`, jamais copie : un pyvenv.cfg pointant sur l'ancien
# chemin /opt/usg-watchdog casse paramiko/paho-mqtt en silence.
OLD_INSTALL_DIR="/opt/usg-watchdog"
if [[ -d "${OLD_INSTALL_DIR}" && ! -d "${INSTALL_DIR}" ]]; then
    log_info "Migration detectee : ${OLD_INSTALL_DIR} -> ${INSTALL_DIR}"
    install -d -m 750 "${INSTALL_DIR}"

    if [[ -f "${OLD_INSTALL_DIR}/.env" ]]; then
        mv "${OLD_INSTALL_DIR}/.env" "${INSTALL_DIR}/.env"
        log_success ".env migre : ${INSTALL_DIR}/.env"
    fi

    if [[ -d "${OLD_INSTALL_DIR}/.ssh" ]]; then
        mv "${OLD_INSTALL_DIR}/.ssh" "${INSTALL_DIR}/.ssh"
        log_success ".ssh migre : ${INSTALL_DIR}/.ssh (cles USG conservees telles quelles, non renommees)"
    fi

    log_info "Venv non repris -- ${OLD_INSTALL_DIR}/venv laisse en place (rollback), un venv neuf sera cree dans ${INSTALL_DIR}/venv"
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

    read -rp "  URL du serveur Ntfy (ex: http://127.0.0.1:7171, vide = skip) : " INPUT_NTFY_URL || INPUT_NTFY_URL=""
    INPUT_NTFY_TOPIC=""
    INPUT_NTFY_TOKEN=""
    if [[ -n "${INPUT_NTFY_URL}" ]]; then
        read -rp "  Topic Ntfy du site (ex: vigil-dijon) : " INPUT_NTFY_TOPIC || INPUT_NTFY_TOPIC=""
        read -rsp "  Jeton Ntfy (Authorization: Bearer, vide = anonyme) : " INPUT_NTFY_TOKEN || INPUT_NTFY_TOKEN=""
        echo ""
    fi

    GENERATED_API_TOKEN=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")

    cat > "${ENV_FILE}" <<ENVEOF
USG_IP=${INPUT_USG_IP}
USG_USER=${INPUT_USG_USER}
NTFY_URL=${INPUT_NTFY_URL}
NTFY_TOPIC=${INPUT_NTFY_TOPIC}
NTFY_TOKEN=${INPUT_NTFY_TOKEN}
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

# --- Copy files (releases + symlink 'current', meme layout que l'updater) ---
log_info "Copie des fichiers vers ${INSTALL_DIR}..."
install -d -m 750 "${INSTALL_DIR}" "${INSTALL_DIR}/releases"

if [[ -d "${INSTALL_DIR}/.ssh" ]]; then
    log_info "Dossier .ssh existant conserve"
fi

# Migration ponctuelle du layout a plat (${INSTALL_DIR}/src) vers le layout
# releases -- l'ancien layout est deplace, jamais supprime (rollback de
# dernier recours).
if [[ -d "${INSTALL_DIR}/src" && ! -L "${INSTALL_DIR}/src" ]]; then
    if [[ -e "${INSTALL_DIR}/src.flat-backup" ]]; then
        log_info "Ancien layout a plat deja sauvegarde : ${INSTALL_DIR}/src.flat-backup (conserve tel quel)"
    else
        log_info "Ancien layout a plat detecte (${INSTALL_DIR}/src) -- deplacement vers ${INSTALL_DIR}/src.flat-backup"
        mv "${INSTALL_DIR}/src" "${INSTALL_DIR}/src.flat-backup"
        log_success "Layout a plat sauvegarde : ${INSTALL_DIR}/src.flat-backup"
    fi
fi

DEPLOY_VERSION="$(cat "${REPO_DIR}/VERSION" 2>/dev/null || echo "0.0.0")"
RELEASE_DIR="${INSTALL_DIR}/releases/v${DEPLOY_VERSION}"

# Stage la release dans un dossier temporaire avant de la publier (au moins
# src/ + VERSION, meme structure minimale que celle extraite par l'updater).
STAGE_DIR="${INSTALL_DIR}/releases/.stage.$$"
install -d -m 750 "${STAGE_DIR}/src"
cp -r "${REPO_DIR}/src/." "${STAGE_DIR}/src/"
cp "${REPO_DIR}/VERSION" "${STAGE_DIR}/VERSION" 2>/dev/null || echo "${DEPLOY_VERSION}" > "${STAGE_DIR}/VERSION"
cp "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"

if [[ -d "${RELEASE_DIR}" ]]; then
    log_info "Release v${DEPLOY_VERSION} deja presente -- remplacement"
    rm -rf "${RELEASE_DIR}"
fi
mv "${STAGE_DIR}" "${RELEASE_DIR}"
log_success "Release v${DEPLOY_VERSION} installee : ${RELEASE_DIR}"

# Bascule atomique du symlink 'current' -- meme mecanisme que
# updater/update.py::apply_update() (nouveau lien temporaire puis rename
# atomique par-dessus l'ancien).
CURRENT_LINK="${INSTALL_DIR}/current"
NEW_LINK="${INSTALL_DIR}/current.new"
rm -f "${NEW_LINK}"
ln -s "${RELEASE_DIR}" "${NEW_LINK}"
mv -T "${NEW_LINK}" "${CURRENT_LINK}"
log_success "Symlink mis a jour : current -> releases/v${DEPLOY_VERSION}"

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
install -m 640 -o "${SERVICE_USER}" -g adm /dev/null /var/log/vigil.log 2>/dev/null || {
    touch /var/log/vigil.log
    chown "${SERVICE_USER}:adm" /var/log/vigil.log
    chmod 640 /var/log/vigil.log
}
# Repertoire d'etat des evenements : cree par systemd (StateDirectory=vigil)
# au demarrage du service ; on le pre-cree ici pour les executions hors
# systemd (mode dev, tests manuels).
install -d -m 750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" /var/lib/vigil 2>/dev/null || true
log_success "Fichier de log cree : /var/log/vigil.log"

# --- Logrotate ---------------------------------------------------------------
install -m 644 -o root -g root \
    "${REPO_DIR}/systemd/vigil.logrotate" /etc/logrotate.d/vigil
log_success "Logrotate configure"

# --- systemd service ---------------------------------------------------------
log_info "Installation du service systemd..."
install -m 644 -o root -g root \
    "${REPO_DIR}/systemd/vigil.service" "/etc/systemd/system/${SERVICE_NAME}.service"

# --- Auto-updater timer ------------------------------------------------------
if [[ -f "${REPO_DIR}/systemd/vigil-updater.service" ]]; then
    log_info "Installation de l'auto-updater..."
    install -m 644 -o root -g root \
        "${REPO_DIR}/systemd/vigil-updater.service" /etc/systemd/system/
    install -m 644 -o root -g root \
        "${REPO_DIR}/systemd/vigil-updater.timer" /etc/systemd/system/
    # Copier le script updater
    install -d -m 750 "${INSTALL_DIR}/updater"
    cp "${REPO_DIR}/updater/"*.py "${INSTALL_DIR}/updater/"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/updater"
    log_success "Auto-updater installe"
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl enable vigil-updater.timer 2>/dev/null || true
systemctl start vigil-updater.timer 2>/dev/null || true
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
echo "    sudo tail -f /var/log/vigil.log"
echo ""
echo "  Test SSH rapide :"
echo "    sudo ./scripts/test.sh"
echo "---------------------------------------------------"
echo ""
