"""Peer coordination -- query peer state and decide whether to reboot."""

import json
import logging
import time
import urllib.request
import urllib.error

from config import (
    PEER_IP,
    PEER_PORT,
    PEER_TAKEOVER_DELAY,
    POST_REBOOT_GRACE,
    CHECK_INTERVAL,
    REBOOT_SCORE_THRESHOLD,
)
from state import WatchdogState


def query_peer(
    peer_ip: str = PEER_IP,
    peer_port: int = PEER_PORT,
    retries: int = 3,
    timeout: int = 5,
) -> WatchdogState | None:
    """Query the peer's state via HTTP. Returns None if unreachable.

    Retries multiple times to avoid false negatives from a single dropped packet.
    Never raises.
    """
    url = f"http://{peer_ip}:{peer_port}/api/state"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

            state = WatchdogState.from_dict(data)
            if state is not None:
                # Check freshness: reject stale state (older than 3 cycles)
                if state.timestamp:
                    logging.debug("Peer %s:%d repond -- state OK", peer_ip, peer_port)
                return state

        except urllib.error.URLError:
            logging.debug(
                "Peer %s:%d injoignable (tentative %d/%d)",
                peer_ip, peer_port, attempt + 1, retries,
            )
        except (json.JSONDecodeError, ValueError) as e:
            logging.debug("Peer %s:%d reponse invalide -- %s", peer_ip, peer_port, e)
        except Exception as e:
            logging.debug("Peer %s:%d erreur -- %s", peer_ip, peer_port, e)

        if attempt < retries - 1:
            time.sleep(1)

    logging.info("Peer %s:%d injoignable apres %d tentatives", peer_ip, peer_port, retries)
    return None


def should_reboot(
    my_state: WatchdogState,
    gateway_ok: bool,
) -> tuple[bool, str]:
    """Decide whether this instance should proceed with rebooting the USG.

    Returns (proceed: bool, reason: str).
    Never raises -- defaults to (True, ...) on errors to avoid blocking reboots.
    """
    # Standalone mode: no peer configured
    if not PEER_IP:
        return True, "standalone mode"

    try:
        peer_state = query_peer()
    except Exception as e:
        logging.warning("Peer check echoue -- %s -- reboot autorise par defaut", e)
        return True, f"peer check error: {e}"

    # --- Peer reachable ---
    if peer_state is not None:
        # Peer has higher priority (lower number) and is at/above threshold
        if (
            peer_state.instance_priority < my_state.instance_priority
            and peer_state.failure_score >= REBOOT_SCORE_THRESHOLD
            and not peer_state.surveillance_only
        ):
            return False, (
                f"peer (priority={peer_state.instance_priority}) "
                f"a priorite et gere (score={peer_state.failure_score})"
            )

        # Peer already rebooted recently
        if peer_state.last_reboot_time > 0:
            elapsed = time.time() - peer_state.last_reboot_time
            if elapsed < POST_REBOOT_GRACE:
                return False, (
                    f"peer a reboote il y a {int(elapsed)}s "
                    f"(grace {POST_REBOOT_GRACE}s)"
                )

        # I have higher priority (or equal) -> proceed
        if my_state.instance_priority <= peer_state.instance_priority:
            return True, f"priorite {my_state.instance_priority} (peer={peer_state.instance_priority})"

        # I am secondary, peer is primary but not acting
        # (peer score below threshold or peer in surveillance mode)
        if peer_state.failure_score < REBOOT_SCORE_THRESHOLD:
            return False, (
                f"peer primary (score={peer_state.failure_score}) "
                f"n'a pas atteint le seuil -- attente"
            )

        # Peer is primary, score at threshold, but in surveillance mode
        if peer_state.surveillance_only:
            return True, "peer primary en mode surveillance -- secondary prend le relais"

        return True, "peer actif, conditions remplies"

    # --- Peer unreachable ---

    # Self-check: if gateway is also down, my own network may be broken
    if not gateway_ok:
        return False, "peer ET gateway injoignables -- probable probleme local"

    # Primary: proceed directly
    if my_state.instance_priority == 1:
        return True, "primary -- peer injoignable, gateway OK"

    # Secondary: wait PEER_TAKEOVER_DELAY before taking over
    if my_state.threshold_reached_time <= 0:
        return False, "secondary -- seuil atteint mais timestamp non defini"

    elapsed_since_threshold = time.time() - my_state.threshold_reached_time
    if elapsed_since_threshold < PEER_TAKEOVER_DELAY:
        remaining = int(PEER_TAKEOVER_DELAY - elapsed_since_threshold)
        return False, (
            f"secondary -- takeover dans {remaining}s "
            f"(peer injoignable depuis {int(elapsed_since_threshold)}s)"
        )

    return True, (
        f"secondary takeover -- peer injoignable, "
        f"delai {PEER_TAKEOVER_DELAY}s ecoule"
    )


def get_peer_info() -> dict[str, str | int]:
    """Fetch peer status summary for display. Fast: single attempt, short timeout.

    Returns dict with keys: status, score, gateway, internet.
    Never raises.
    """
    if not PEER_IP:
        return {"status": "standalone", "score": 0, "gateway": "", "internet": ""}

    peer = query_peer(retries=1, timeout=3)
    if peer is None:
        return {"status": "unreachable", "score": 0, "gateway": "", "internet": ""}

    if peer.failure_score >= peer.threshold:
        status = "critical"
    elif peer.failure_score > 0:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "score": peer.failure_score,
        "gateway": "OK" if peer.gateway_ok else "KO",
        "internet": f"{peer.internet_ok_count}/{peer.internet_total}",
    }


# Divergence thresholds
_DIVERGENCE_SCORE_GAP = 6  # min score gap to consider divergence


def check_divergence(
    my_score: int,
    my_gateway_ok: bool,
    my_inet_count: int,
) -> str | None:
    """Check if this instance diverges significantly from peer.

    Returns a description string if divergence detected, None otherwise.
    Uses a single fast query. Never raises.
    """
    if not PEER_IP:
        return None

    peer = query_peer(retries=1, timeout=3)
    if peer is None:
        return None

    score_gap = abs(my_score - peer.failure_score)
    if score_gap < _DIVERGENCE_SCORE_GAP:
        return None

    # I see problems but peer is fine
    if my_score > peer.failure_score:
        return (
            f"Divergence detectee\n"
            f"  local  : score={my_score} gw={'OK' if my_gateway_ok else 'KO'} "
            f"inet={my_inet_count}\n"
            f"  peer   : score={peer.failure_score} "
            f"gw={'OK' if peer.gateway_ok else 'KO'} "
            f"inet={peer.internet_ok_count}/{peer.internet_total}\n"
            f"Probleme probable sur cette machine, pas sur le reseau"
        )

    # Peer sees problems but I'm fine
    return (
        f"Divergence detectee\n"
        f"  local  : score={my_score} gw={'OK' if my_gateway_ok else 'KO'} "
        f"inet={my_inet_count}\n"
        f"  peer   : score={peer.failure_score} "
        f"gw={'OK' if peer.gateway_ok else 'KO'} "
        f"inet={peer.internet_ok_count}/{peer.internet_total}\n"
        f"Probleme probable sur le peer, pas sur le reseau"
    )
