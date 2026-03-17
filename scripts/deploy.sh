#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Déploie et démarre le service USG Watchdog
# =============================================================================
# Usage : sudo ./scripts/deploy.sh
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/usg-watchdog"
SERVICE_NAME="usg-watchdog"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   USG Watchdog — Déploiement"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ $EUID -ne 0 ]]; then
    log_error "Ce script doit être exécuté en root : sudo $0"
    exit 1
fi

# ─── Python ──────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    log_error "Python3 introuvable — installer python3"
    exit 1
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log_info "Python détecté : ${PYTHON_VERSION}"

if ! python3 -c "import venv" &>/dev/null; then
    log_info "Installation de python3-venv..."
    if command -v dnf &>/dev/null; then
        dnf install -y python3-venv
    elif command -v apt-get &>/dev/null; then
        apt-get install -y python3-venv
    fi
fi

# ─── Copie des fichiers ───────────────────────────────────────────────────────
log_info "Copie des fichiers vers ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"

# Conserver le dossier .ssh existant
if [[ -d "${INSTALL_DIR}/.ssh" ]]; then
    log_info "Dossier .ssh existant conservé"
fi

cp -r "${REPO_DIR}/src/." "${INSTALL_DIR}/src/"
cp "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/"
log_success "Fichiers copiés"

# ─── Virtualenv ──────────────────────────────────────────────────────────────
log_info "Création du virtualenv..."
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip -q
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q
log_success "Dépendances installées"

# ─── Fichier de log ──────────────────────────────────────────────────────────
touch /var/log/usg-watchdog.log
chmod 640 /var/log/usg-watchdog.log
log_success "Fichier de log créé : /var/log/usg-watchdog.log"

# ─── Logrotate ───────────────────────────────────────────────────────────────
cp "${REPO_DIR}/systemd/usg-watchdog.logrotate" /etc/logrotate.d/usg-watchdog
log_success "Logrotate configuré"

# ─── Service systemd ─────────────────────────────────────────────────────────
log_info "Installation du service systemd..."
cp "${REPO_DIR}/systemd/usg-watchdog.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
log_success "Service systemd activé au démarrage"

# ─── Démarrage ───────────────────────────────────────────────────────────────
log_info "Démarrage du service..."
systemctl restart "${SERVICE_NAME}"
sleep 3

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log_success "Service démarré et actif"
else
    log_error "Le service a échoué au démarrage"
    echo ""
    systemctl status "${SERVICE_NAME}" --no-pager -l || true
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_success "Déploiement terminé !"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status ${SERVICE_NAME}"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
echo "    sudo tail -f /var/log/usg-watchdog.log"
echo ""
echo "  Test SSH rapide :"
echo "    sudo ./scripts/test.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
