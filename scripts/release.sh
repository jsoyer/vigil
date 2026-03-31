#!/usr/bin/env bash
# =============================================================================
# release.sh -- Create a signed semver tag for USG Watchdog
# =============================================================================
# Usage:
#   ./scripts/release.sh patch    # 1.0.0 -> 1.0.1
#   ./scripts/release.sh minor    # 1.0.0 -> 1.1.0
#   ./scripts/release.sh major    # 1.0.0 -> 2.0.0
#   ./scripts/release.sh 1.2.3    # explicit version
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${REPO_DIR}/VERSION"

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

# Update VERSION file
echo "${NEXT}" > "${VERSION_FILE}"
git -C "${REPO_DIR}" add "${VERSION_FILE}"
git -C "${REPO_DIR}" commit -m "chore: bump version to ${NEXT}"

# Create signed tag
log_info "Creation du tag v${NEXT}..."
git -C "${REPO_DIR}" tag -s "v${NEXT}" -m "Release v${NEXT}"

log_success "Tag v${NEXT} cree"
echo ""
echo "  Pour publier :"
echo "    git push origin main"
echo "    git push origin v${NEXT}"
echo ""
