#!/usr/bin/env bash
# =============================================================================
# setup_ssh.sh -- Generate and deploy SSH key for USG Ubiquiti access
# =============================================================================
# Usage : sudo ./scripts/setup_ssh.sh
#
# COMPATIBILITY: USG runs EdgeOS with OpenSSH 6.6.1 (old firmware).
# We use Ed25519 which is supported since OpenSSH 6.5 and compatible with
# modern OpenSSH clients (which dropped rsa-sha2 for old servers).
# =============================================================================

set -euo pipefail

# --- Config ------------------------------------------------------------------
SSH_DIR="/opt/usg-watchdog/.ssh"
KEY_FILE="${SSH_DIR}/usg_ed25519"
KNOWN_HOSTS="${SSH_DIR}/known_hosts"
KEY_COMMENT="usg-watchdog@$(hostname)"

USG_IP="${USG_IP:-192.168.1.1}"
USG_USER="${USG_USER:-maintenance}"
# -----------------------------------------------------------------------------

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

# Track whether key existed before script ran
_KEY_EXISTED_BEFORE=false
[[ -f "${KEY_FILE}" ]] && _KEY_EXISTED_BEFORE=true

# Cleanup partial files on failure
_cleanup() {
    local code=$?
    if [[ ${code} -ne 0 ]]; then
        # Remove key only if it was created by this run
        if [[ "${_KEY_EXISTED_BEFORE}" == false && -f "${KEY_FILE}" ]]; then
            rm -f "${KEY_FILE}" "${KEY_FILE}.pub"
            log_warn "Cleaned up partial key files after failure"
        fi
        # Always clean up temp known_hosts
        rm -f "${KNOWN_HOSTS}.tmp"
    fi
    exit "${code}"
}
trap _cleanup EXIT

echo ""
echo "---------------------------------------------------"
echo "   USG Watchdog -- Setup SSH Key"
echo "   (Ed25519 -- compatible EdgeOS OpenSSH 6.6.1)"
echo "---------------------------------------------------"
echo ""

if [[ $EUID -ne 0 ]]; then
    log_error "Ce script doit etre execute en root : sudo $0"
    exit 1
fi

if ! command -v ssh-keygen &>/dev/null; then
    log_error "ssh-keygen introuvable -- installer openssh-client"
    exit 1
fi

if ! command -v ssh-copy-id &>/dev/null; then
    log_warn "ssh-copy-id introuvable -- copie manuelle de la cle publique"
    MANUAL_COPY=true
else
    MANUAL_COPY=false
fi

# Create SSH directory with restrictive permissions from the start
log_info "Creation du dossier SSH : ${SSH_DIR}"
install -d -m 700 "${SSH_DIR}"

# Detect existing key and offer migration
if [[ -f "${KEY_FILE}" ]]; then
    KEY_TYPE=$(ssh-keygen -l -f "${KEY_FILE}" 2>/dev/null | awk '{print $4}')
    KEY_TYPE="${KEY_TYPE:-unknown}"
    log_warn "Cle SSH deja existante : ${KEY_FILE} (type: ${KEY_TYPE})"
    if [[ "${KEY_TYPE}" == "(RSA)" ]]; then
        log_warn "Cle RSA detectee -- migration vers Ed25519 recommandee pour compatibilite EdgeOS"
    fi
    read -rp "  Regenerer en Ed25519 ? (o/N) : " REGEN || REGEN=""
    if [[ "${REGEN,,}" == "o" || "${REGEN,,}" == "oui" || "${REGEN,,}" == "y" ]]; then
        rm -f "${KEY_FILE}" "${KEY_FILE}.pub"
        log_info "Ancienne cle supprimee"
    else
        log_info "Conservation de la cle existante"
    fi
fi

if [[ ! -f "${KEY_FILE}" ]]; then
    log_info "Generation de la cle Ed25519..."
    ssh-keygen -t ed25519 \
        -f "${KEY_FILE}" \
        -N "" \
        -C "${KEY_COMMENT}"
    chmod 600 "${KEY_FILE}"
    chmod 644 "${KEY_FILE}.pub"
    log_success "Cle Ed25519 generee : ${KEY_FILE}"
fi

echo ""
log_info "Cle publique a deployer sur le USG :"
echo ""
echo "  $(cat "${KEY_FILE}.pub")"
echo ""

# --- Capture USG host key ----------------------------------------------------
echo "---------------------------------------------------"
log_info "Capture de la cle hote du USG ${USG_IP}..."
echo ""

if ssh-keyscan -t ed25519,rsa "${USG_IP}" > "${KNOWN_HOSTS}.tmp" 2>/dev/null && [[ -s "${KNOWN_HOSTS}.tmp" ]]; then
    mv "${KNOWN_HOSTS}.tmp" "${KNOWN_HOSTS}"
    chmod 644 "${KNOWN_HOSTS}"
    log_success "Cle hote capturee dans ${KNOWN_HOSTS}"
    log_info "Empreinte de la cle hote :"
    ssh-keygen -l -f "${KNOWN_HOSTS}" 2>/dev/null || true
    echo ""
    read -rp "  Cette empreinte correspond a votre USG ? (o/N) : " CONFIRM_FP || CONFIRM_FP=""
    if [[ "${CONFIRM_FP,,}" != "o" && "${CONFIRM_FP,,}" != "oui" && "${CONFIRM_FP,,}" != "y" ]]; then
        rm -f "${KNOWN_HOSTS}"
        log_error "Empreinte rejetee -- verifier que ${USG_IP} est bien votre USG"
        exit 1
    fi
else
    rm -f "${KNOWN_HOSTS}.tmp"
    log_warn "Impossible de capturer la cle hote -- ssh-keyscan a echoue"
    log_warn "La verification de cle hote sera desactivee (risque MITM sur LAN)"
fi

# --- Deploy public key -------------------------------------------------------
echo "---------------------------------------------------"
log_info "Deploiement sur le USG ${USG_USER}@${USG_IP}"
echo ""
log_warn "Vous allez devoir entrer le mot de passe SSH du USG UNE DERNIERE FOIS."
echo ""

SSH_OPTS=(-o ConnectTimeout=10)
if [[ -f "${KNOWN_HOSTS}" ]]; then
    SSH_OPTS+=(-o "UserKnownHostsFile=${KNOWN_HOSTS}")
else
    SSH_OPTS+=(-o StrictHostKeyChecking=accept-new)
fi

if [[ "${MANUAL_COPY}" == false ]]; then
    if ssh-copy-id -i "${KEY_FILE}.pub" \
        "${SSH_OPTS[@]}" \
        "${USG_USER}@${USG_IP}" 2>/dev/null; then
        log_success "Cle deployee avec succes sur ${USG_IP}"
    else
        log_warn "ssh-copy-id a echoue -- tentative manuelle..."
        MANUAL_COPY=true
    fi
fi

if [[ "${MANUAL_COPY}" == true ]]; then
    log_info "Copie manuelle de la cle publique..."
    # Pass public key via stdin to avoid shell injection
    ssh "${SSH_OPTS[@]}" "${USG_USER}@${USG_IP}" \
        'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' \
        < "${KEY_FILE}.pub" || {
        log_error "Copie manuelle echouee"
        echo ""
        echo "  Copier manuellement cette cle dans ~/.ssh/authorized_keys du USG :"
        echo "  $(cat "${KEY_FILE}.pub")"
        exit 1
    }
fi

# --- Test connection ----------------------------------------------------------
echo ""
log_info "Test de la connexion SSH sans mot de passe..."

TEST_SSH_OPTS=(-i "${KEY_FILE}" -o BatchMode=yes -o ConnectTimeout=10)
if [[ -f "${KNOWN_HOSTS}" ]]; then
    TEST_SSH_OPTS+=(-o "UserKnownHostsFile=${KNOWN_HOSTS}")
else
    TEST_SSH_OPTS+=(-o StrictHostKeyChecking=accept-new)
fi

if ssh "${TEST_SSH_OPTS[@]}" "${USG_USER}@${USG_IP}" "exit" 2>/dev/null; then
    log_success "Connexion SSH par cle Ed25519 fonctionne !"
else
    # EdgeOS may return non-zero even on success (restricted shell)
    SSH_OUTPUT=$(ssh "${TEST_SSH_OPTS[@]}" -v \
        "${USG_USER}@${USG_IP}" "exit" 2>&1 || true)

    if echo "${SSH_OUTPUT}" | grep -q "Authenticated\|Authentication succeeded"; then
        log_success "Connexion SSH par cle Ed25519 fonctionne ! (EdgeOS shell restreint -- comportement normal)"
    else
        log_error "Test SSH echoue -- verifier les credentials et que SSH est active sur le USG"
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
echo "---------------------------------------------------"
log_success "Setup SSH termine !"
echo ""
echo "  Type de cle : Ed25519 (compatible EdgeOS 6.6.1)"
echo "  Cle privee  : ${KEY_FILE}"
echo "  Known hosts : ${KNOWN_HOSTS}"
echo "  USG IP      : ${USG_IP}"
echo "  USG User    : ${USG_USER}"
echo ""
echo "  -> Lancer maintenant : sudo ./scripts/deploy.sh"
echo "---------------------------------------------------"
echo ""
