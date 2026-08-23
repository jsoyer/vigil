#!/usr/bin/env bash
# =============================================================================
# release.sh -- Create an annotated (or signed) semver tag for USG Watchdog
# =============================================================================
# Usage:
#   ./scripts/release.sh patch    # 1.0.0 -> 1.0.1
#   ./scripts/release.sh minor    # 1.0.0 -> 1.1.0
#   ./scripts/release.sh major    # 1.0.0 -> 2.0.0
#   ./scripts/release.sh 1.2.3    # explicit version
#
# Idempotence :
#   Si VERSION est deja a la version cible (bump + commit fait a la main au
#   prealable), le script ne recommite rien et enchaine directement sur la
#   creation du tag.
#
# Tag :
#   Annote (`git tag -a`) par defaut. Signe (`git tag -s`) uniquement si
#   `git config user.signingkey` est renseignee sur cette machine.
#
# Dry-run :
#   RELEASE_DRY_RUN=1 ./scripts/release.sh patch
#   N'effectue aucune ecriture (pas de commit, pas de tag) -- affiche les
#   actions qui auraient ete executees.
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${REPO_DIR}/VERSION"
DRY_RUN="${RELEASE_DRY_RUN:-0}"

# --- Shared logging ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/logging.sh
source "${SCRIPT_DIR}/lib/logging.sh"
# -----------------------------------------------------------------------------

if [[ ! -f "${VERSION_FILE}" ]]; then
    log_error "VERSION file not found at ${VERSION_FILE}"
    exit 1
fi

CURRENT=$(cat "${VERSION_FILE}" | tr -d '[:space:]')
log_info "Version actuelle : ${CURRENT}"

# Parse current version
IFS='.' read -r MAJOR MINOR PATCH <<< "${CURRENT}"

# Determine next version
case "${1:-}" in
    patch)
        NEXT="${MAJOR}.${MINOR}.$((PATCH + 1))"
        ;;
    minor)
        NEXT="${MAJOR}.$((MINOR + 1)).0"
        ;;
    major)
        NEXT="$((MAJOR + 1)).0.0"
        ;;
    "")
        log_error "Usage: $0 {patch|minor|major|X.Y.Z}"
        exit 1
        ;;
    *)
        # Explicit version
        if [[ ! "${1}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            log_error "Version invalide : ${1} (format attendu: X.Y.Z)"
            exit 1
        fi
        NEXT="${1}"
        ;;
esac

log_info "Nouvelle version : ${NEXT}"

# Check for uncommitted changes
if ! git -C "${REPO_DIR}" diff-index --quiet HEAD -- 2>/dev/null; then
    log_error "Des modifications non committees existent -- committer d'abord"
    exit 1
fi

# Check tag doesn't already exist
if git -C "${REPO_DIR}" rev-parse "v${NEXT}" &>/dev/null; then
    log_error "Le tag v${NEXT} existe deja"
    exit 1
fi

if [[ "${CURRENT}" == "${NEXT}" ]]; then
    # Idempotence : VERSION est deja a la cible (bump manuel prealable et
    # deja committe, sinon le check diff-index ci-dessus aurait echoue).
    log_info "VERSION est deja a ${NEXT} -- pas de nouveau commit, passage direct au tag"
else
    if [[ "${DRY_RUN}" == "1" ]]; then
        log_info "[DRY-RUN] echo ${NEXT} > ${VERSION_FILE}"
        log_info "[DRY-RUN] git commit -m \"chore: bump version to ${NEXT}\""
    else
        echo "${NEXT}" > "${VERSION_FILE}"
        git -C "${REPO_DIR}" add "${VERSION_FILE}"
        git -C "${REPO_DIR}" commit -m "chore: bump version to ${NEXT}"
    fi
fi

# Tag annote par defaut ; signe seulement si une cle de signature existe.
TAG_FLAG="-a"
if [[ -n "$(git -C "${REPO_DIR}" config user.signingkey 2>/dev/null || true)" ]]; then
    TAG_FLAG="-s"
    log_info "Cle de signature detectee -- tag signe (-s)"
else
    log_info "Aucune cle de signature configuree -- tag annote (-a)"
fi

log_info "Creation du tag v${NEXT}..."
if [[ "${DRY_RUN}" == "1" ]]; then
    log_info "[DRY-RUN] git tag ${TAG_FLAG} v${NEXT} -m \"Release v${NEXT}\""
    log_success "[DRY-RUN] Tag v${NEXT} aurait ete cree"
else
    git -C "${REPO_DIR}" tag "${TAG_FLAG}" "v${NEXT}" -m "Release v${NEXT}"
    log_success "Tag v${NEXT} cree"
fi

echo ""
echo "  Pour publier :"
echo "    git push origin main"
echo "    git push origin v${NEXT}"
echo ""
