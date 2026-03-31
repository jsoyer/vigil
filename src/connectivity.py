"""
Module de verification de la connexion internet et du gateway LAN.
Ping gateway USG + multi-cibles internet avec mesure de latence.
"""

import ipaddress
import re
import subprocess
import logging
from collections import deque
from dataclasses import dataclass, field

import socket

from config import PING_TARGETS, PING_TIMEOUT, USG_IP

# DNS resolution target (well-known domain that should always resolve)
DNS_CHECK_DOMAIN = "google.com"
# TCP connect targets (IP:port pairs for TCP-level check)
TCP_CHECK_TARGETS = [("8.8.8.8", 53), ("1.1.1.1", 443)]


@dataclass(frozen=True)
class PingResult:
    """Result of a single ping."""
    ok: bool
    rtt_ms: float | None = None  # None if ping failed


@dataclass(frozen=True)
class ConnectivityResult:
    """Resultat d'un cycle de verification."""
    gateway_ok: bool
    internet_ok_count: int
    internet_total: int
    gateway_rtt_ms: float | None = None
    internet_avg_rtt_ms: float | None = None
    internet_rtts: tuple[float | None, ...] = ()
    dns_ok: bool = True
    tcp_ok_count: int = 0
    tcp_total: int = 0


class LatencyTracker:
    """Sliding window latency tracker for degradation detection."""

    def __init__(self, window_size: int = 10) -> None:
        self._window: deque[float] = deque(maxlen=window_size)

    def record(self, rtt_ms: float) -> None:
        self._window.append(rtt_ms)

    def average(self) -> float | None:
        if not self._window:
            return None
        return sum(self._window) / len(self._window)

    def max(self) -> float | None:
        if not self._window:
            return None
        return max(self._window)

    def is_degraded(self, threshold_ms: float = 200.0) -> bool:
        avg = self.average()
        return avg is not None and avg > threshold_ms

    def to_dict(self) -> dict:
        return {
            "avg_ms": round(self.average(), 1) if self.average() is not None else None,
            "max_ms": round(self.max(), 1) if self.max() is not None else None,
            "samples": len(self._window),
            "degraded": self.is_degraded(),
        }


# Module-level trackers (persist across cycles)
gateway_latency = LatencyTracker()
internet_latency = LatencyTracker()


def ping_host(host: str, timeout: int = PING_TIMEOUT) -> PingResult:
    """
    Ping un host unique. Retourne PingResult avec ok + RTT.
    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        logging.error("Cible de ping invalide (doit etre une adresse IP) : %s", host)
        return PingResult(ok=False)

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        if result.returncode != 0:
            return PingResult(ok=False)

        # Parse RTT from ping output: "time=1.23 ms"
        rtt = _parse_rtt(result.stdout)
        return PingResult(ok=True, rtt_ms=rtt)

    except subprocess.TimeoutExpired:
        logging.debug("Ping timeout -> %s", host)
        return PingResult(ok=False)
    except FileNotFoundError:
        logging.error("Commande 'ping' introuvable -- verifier l'installation")
        return PingResult(ok=False)
    except Exception as e:
        logging.debug("Erreur ping %s : %s", host, e)
        return PingResult(ok=False)


def _parse_rtt(ping_output: str) -> float | None:
    """Extract RTT from ping output (time=X.XX ms)."""
    match = re.search(r"time[=<]([\d.]+)\s*ms", ping_output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def ping_gateway() -> PingResult:
    """Ping le gateway USG sur le LAN."""
    result = ping_host(USG_IP)
    if result.ok:
        logging.debug("Gateway %s repond (%.1fms)", USG_IP, result.rtt_ms or 0)
        if result.rtt_ms is not None:
            gateway_latency.record(result.rtt_ms)
    else:
        logging.debug("Gateway %s ne repond pas", USG_IP)
    return result


def check_internet() -> tuple[int, tuple[float | None, ...]]:
    """
    Ping les cibles internet. Retourne (count, rtts).
    On ping toutes les cibles pour le scoring (pas de short-circuit).
    """
    if not PING_TARGETS:
        logging.error("PING_TARGETS est vide -- impossible de verifier la connexion")
        return 0, ()

    ok_count = 0
    rtts: list[float | None] = []

    for host in PING_TARGETS:
        result = ping_host(host)
        rtts.append(result.rtt_ms)
        if result.ok:
            ok_count += 1
            if result.rtt_ms is not None:
                internet_latency.record(result.rtt_ms)
            logging.debug("Internet %s repond (%.1fms)", host, result.rtt_ms or 0)
        else:
            logging.debug("Internet %s ne repond pas", host)

    return ok_count, tuple(rtts)


def check_dns(domain: str = DNS_CHECK_DOMAIN, timeout: int = 3) -> bool:
    """Check DNS resolution by resolving a well-known domain.

    Returns True if resolution succeeds, False otherwise. Never raises.
    Uses a per-socket timeout to avoid corrupting the global default.
    """
    try:
        # getaddrinfo doesn't support per-call timeout, so we use a
        # TCP connect to verify resolution + reachability in one step
        with socket.create_connection((domain, 80), timeout=timeout) as s:
            pass
        logging.debug("DNS resolution OK : %s", domain)
        return True
    except (socket.gaierror, socket.timeout, ConnectionRefusedError, OSError):
        logging.debug("DNS resolution echouee : %s", domain)
        return False


def check_tcp(targets: list[tuple[str, int]] | None = None, timeout: int = 3) -> tuple[int, int]:
    """Check TCP connectivity by attempting connections to IP:port pairs.

    Returns (ok_count, total). Never raises.
    """
    if targets is None:
        targets = TCP_CHECK_TARGETS

    ok_count = 0
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                ok_count += 1
                logging.debug("TCP connect OK : %s:%d", host, port)
        except (socket.timeout, ConnectionRefusedError, OSError):
            logging.debug("TCP connect echoue : %s:%d", host, port)

    return ok_count, len(targets)


def check_connectivity() -> ConnectivityResult:
    """
    Effectue un cycle complet de verification :
    1. Ping gateway (LAN)
    2. Ping cibles internet (ICMP)
    3. Resolution DNS
    4. Connexion TCP
    """
    gw_result = ping_gateway()
    inet_count, inet_rtts = check_internet()

    # DNS check
    dns_ok = check_dns()

    # TCP check
    tcp_ok, tcp_total = check_tcp()

    # Calculate average internet RTT (only from successful pings)
    valid_rtts = [r for r in inet_rtts if r is not None]
    avg_rtt = sum(valid_rtts) / len(valid_rtts) if valid_rtts else None

    return ConnectivityResult(
        gateway_ok=gw_result.ok,
        internet_ok_count=inet_count,
        internet_total=len(PING_TARGETS),
        gateway_rtt_ms=gw_result.rtt_ms,
        internet_avg_rtt_ms=avg_rtt,
        internet_rtts=inet_rtts,
        dns_ok=dns_ok,
        tcp_ok_count=tcp_ok,
        tcp_total=tcp_total,
    )
