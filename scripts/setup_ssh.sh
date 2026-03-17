#!/usr/bin/env bash
# =============================================================================
# setup_ssh.sh — Génère et déploie la clé SSH pour accès au USG Ubiquiti
# =============================================================================
# Usage : ./scripts/setup_ssh.sh
# =============================================================================

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
SSH_DIR="/opt/usg-watchdog/.ssh"
KEY_FILE="${SSH_DIR}/usg_rsa"
KEY_COMMENT="usg-watchdog@$(hostname)"

# Lire les valeurs ou utiliser les défauts
USG_IP="${USG_IP:-192.168.1.1}"
USG_USER="${USG_USER:-admin}"
# ─────────────────────────────────────────────────────────────────────────────

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
echo "   USG Watchdog — Setup SSH Key"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Vérifications préalables
if [[ $EUID -ne 0 ]]; then
    log_error "Ce script doit être exécuté en root : sudo $0"
    exit 1
fi

if ! command -v ssh-keygen &>/dev/null; then
    log_error "ssh-keygen introuvable — installer openssh-client"
    exit 1
fi

if ! command -v ssh-copy-id &>/dev/null; then
    log_warn "ssh-copy-id introuvable — copie manuelle de la clé publique"
    MANUAL_COPY=true
else
    MANUAL_COPY=false
fi

# Créer le dossier SSH
log_info "Création du dossier SSH : ${SSH_DIR}"
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"

# Générer la clé si elle n'existe pas déjà
if [[ -f "${KEY_FILE}" ]]; then
    log_warn "Clé SSH déjà existante : ${KEY_FILE}"
    read -rp "  Regénérer ? (o/N) : " REGEN
    if [[ "${REGEN,,}" == "o" || "${REGEN,,}" == "oui" || "${REGEN,,}" == "y" ]]; then
        rm -f "${KEY_FILE}" "${KEY_FILE}.pub"
    else
        log_info "Conservation de la clé existante"
    fi
fi

if [[ ! -f "${KEY_FILE}" ]]; then
    log_info "Génération de la clé RSA 4096 bits..."
    ssh-keygen -t rsa -b 4096 \
        -f "${KEY_FILE}" \
        -N "" \
        -C "${KEY_COMMENT}"
    chmod 600 "${KEY_FILE}"
    chmod 644 "${KEY_FILE}.pub"
    log_success "Clé générée : ${KEY_FILE}"
fi

echo ""
log_info "Clé publique à déployer sur le USG :"
echo ""
echo "  $(cat "${KEY_FILE}.pub")"
echo ""

# Déploiement de la clé sur le USG
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_info "Déploiement sur le USG ${USG_USER}@${USG_IP}"
echo ""
log_warn "Vous allez devoir entrer le mot de passe SSH du USG UNE DERNIÈRE FOIS."
echo ""

if [[ "${MANUAL_COPY}" == false ]]; then
    if ssh-copy-id -i "${KEY_FILE}.pub" \
        -o StrictHostKeyChecking=no \
        "${USG_USER}@${USG_IP}" 2>/dev/null; then
        log_success "Clé déployée avec succès sur ${USG_IP}"
    else
        log_warn "ssh-copy-id a échoué — tentative manuelle..."
        MANUAL_COPY=true
    fi
fi

if [[ "${MANUAL_COPY}" == true ]]; then
    log_info "Copie manuelle de la clé publique..."
    PUB_KEY=$(cat "${KEY_FILE}.pub")
    # shellcheck disable=SC2029
    ssh -o StrictHostKeyChecking=no "${USG_USER}@${USG_IP}" \
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '${PUB_KEY}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" || {
        log_error "Copie manuelle échouée"
        echo ""
        echo "  Copier manuellement cette clé dans ~/.ssh/authorized_keys du USG :"
        echo "  $(cat "${KEY_FILE}.pub")"
        exit 1
    }
fi

# Test de connexion sans mot de passe
echo ""
log_info "Test de la connexion SSH sans mot de passe..."
if ssh -i "${KEY_FILE}" \
    -o StrictHostKeyChecking=no \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    "${USG_USER}@${USG_IP}" \
    "echo 'SSH_AUTH_OK'" 2>/dev/null | grep -q "SSH_AUTH_OK"; then
    log_success "Connexion SSH par clé fonctionne !"
else
    log_error "Test SSH échoué — vérifier les credentials et que SSH est activé sur le USG"
    echo ""
    echo "  Sur le USG Controller :"
    echo "  Settings > System > Advanced > Device Authentication"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_success "Setup SSH terminé !"
echo ""
echo "  Clé privée : ${KEY_FILE}"
echo "  USG IP     : ${USG_IP}"
echo "  USG User   : ${USG_USER}"
echo ""
echo "  → Lancer maintenant : ./scripts/deploy.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
