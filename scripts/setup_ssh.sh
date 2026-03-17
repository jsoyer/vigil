#!/usr/bin/env bash
# =============================================================================
# setup_ssh.sh — Génère et déploie la clé SSH pour accès au USG Ubiquiti
# =============================================================================
# Usage : sudo ./scripts/setup_ssh.sh
#
# COMPATIBILITÉ : Le USG tourne sur EdgeOS avec OpenSSH 6.6.1 (vieux firmware).
# On utilise Ed25519 qui est supporté depuis OpenSSH 6.5 et compatible avec
# le client OpenSSH moderne (qui a retiré rsa-sha2 pour les vieux serveurs).
# =============================================================================

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
SSH_DIR="/opt/usg-watchdog/.ssh"
KEY_FILE="${SSH_DIR}/usg_rsa"          # On garde le nom usg_rsa pour cohérence
KEY_COMMENT="usg-watchdog@$(hostname)"

# Lire les valeurs ou utiliser les défauts
USG_IP="${USG_IP:-192.168.1.1}"
USG_USER="${USG_USER:-maintenance}"
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
echo "   (Ed25519 — compatible EdgeOS OpenSSH 6.6.1)"
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

# Détecter si une clé RSA existe (ancienne version) → proposer de migrer
if [[ -f "${KEY_FILE}" ]]; then
    KEY_TYPE=$(ssh-keygen -l -f "${KEY_FILE}" 2>/dev/null | awk '{print $4}' || echo "unknown")
    log_warn "Clé SSH déjà existante : ${KEY_FILE} (type: ${KEY_TYPE})"
    if [[ "${KEY_TYPE}" == "(RSA)" ]]; then
        log_warn "Clé RSA détectée — migration vers Ed25519 recommandée pour compatibilité EdgeOS"
    fi
    read -rp "  Regénérer en Ed25519 ? (o/N) : " REGEN
    if [[ "${REGEN,,}" == "o" || "${REGEN,,}" == "oui" || "${REGEN,,}" == "y" ]]; then
        rm -f "${KEY_FILE}" "${KEY_FILE}.pub"
        log_info "Ancienne clé supprimée"
    else
        log_info "Conservation de la clé existante"
    fi
fi

if [[ ! -f "${KEY_FILE}" ]]; then
    log_info "Génération de la clé Ed25519..."
    ssh-keygen -t ed25519 \
        -f "${KEY_FILE}" \
        -N "" \
        -C "${KEY_COMMENT}"
    chmod 600 "${KEY_FILE}"
    chmod 644 "${KEY_FILE}.pub"
    log_success "Clé Ed25519 générée : ${KEY_FILE}"
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
# Note : on test juste le handshake sans exec_command (EdgeOS shell restreint)
echo ""
log_info "Test de la connexion SSH sans mot de passe..."
if ssh -i "${KEY_FILE}" \
    -o StrictHostKeyChecking=no \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    "${USG_USER}@${USG_IP}" \
    "exit" 2>/dev/null; then
    log_success "Connexion SSH par clé Ed25519 fonctionne !"
else
    # EdgeOS peut retourner un code non-nul même en cas de succès (shell restreint)
    # On vérifie manuellement avec -v
    SSH_OUTPUT=$(ssh -i "${KEY_FILE}" \
        -o StrictHostKeyChecking=no \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -v \
        "${USG_USER}@${USG_IP}" \
        "exit" 2>&1 || true)

    if echo "${SSH_OUTPUT}" | grep -q "Authenticated\|Authentication succeeded"; then
        log_success "Connexion SSH par clé Ed25519 fonctionne ! (EdgeOS shell restreint — comportement normal)"
    else
        log_error "Test SSH échoué — vérifier les credentials et que SSH est activé sur le USG"
        echo ""
        echo "  Sur le USG Controller :"
        echo "  Settings > System > Advanced > Device Authentication"
        echo ""
        echo "  Debug SSH :"
        echo "${SSH_OUTPUT}" | grep -E "debug1:|error:" | tail -20
        exit 1
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_success "Setup SSH terminé !"
echo ""
echo "  Type de clé : Ed25519 (compatible EdgeOS 6.6.1)"
echo "  Clé privée  : ${KEY_FILE}"
echo "  USG IP      : ${USG_IP}"
echo "  USG User    : ${USG_USER}"
echo ""
echo "  → Lancer maintenant : sudo ./scripts/deploy.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
