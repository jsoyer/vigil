#!/usr/bin/env bash
# =============================================================================
# Shared logging functions for USG Watchdog scripts
# =============================================================================
# Usage: source "$(dirname "${BASH_SOURCE[0]}")/lib/logging.sh"
# =============================================================================

[[ -n "${_LOGGING_SH_LOADED:-}" ]] && return 0
readonly _LOGGING_SH_LOADED=1

# Disable colors when not connected to a terminal
if [[ -t 2 ]]; then
    readonly _LOG_RED='\033[0;31m'
    readonly _LOG_GREEN='\033[0;32m'
    readonly _LOG_YELLOW='\033[1;33m'
    readonly _LOG_BLUE='\033[0;34m'
    readonly _LOG_NC='\033[0m'
else
    readonly _LOG_RED=''
    readonly _LOG_GREEN=''
    readonly _LOG_YELLOW=''
    readonly _LOG_BLUE=''
    readonly _LOG_NC=''
fi

log_info()    { printf '%b[INFO]%b  %s\n' "${_LOG_BLUE}" "${_LOG_NC}" "$*"; }
log_success() { printf '%b[OK]%b    %s\n' "${_LOG_GREEN}" "${_LOG_NC}" "$*"; }
log_warn()    { printf '%b[WARN]%b  %s\n' "${_LOG_YELLOW}" "${_LOG_NC}" "$*" >&2; }
log_error()   { printf '%b[ERROR]%b %s\n' "${_LOG_RED}" "${_LOG_NC}" "$*" >&2; }
