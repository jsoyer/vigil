"""Network diagnostics -- traceroute and path analysis on failure."""

import logging
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class TracerouteHop:
    """A single hop in a traceroute."""

    hop_number: int
    host: str
    rtt_ms: float | None  # None if timeout (*)


@dataclass(frozen=True)
class TracerouteResult:
    """Complete traceroute result."""

    target: str
    hops: tuple[TracerouteHop, ...]
    last_responsive_hop: int
    total_hops: int
    reached_target: bool
    break_point: str  # human-readable description of where it breaks

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "hops": [
                {"hop": h.hop_number, "host": h.host, "rtt_ms": h.rtt_ms}
                for h in self.hops
            ],
            "last_responsive_hop": self.last_responsive_hop,
            "total_hops": self.total_hops,
            "reached_target": self.reached_target,
            "break_point": self.break_point,
        }

    def summary(self) -> str:
        """One-line summary for notifications."""
        if self.reached_target:
            return f"Traceroute OK -> {self.target} ({self.total_hops} hops)"
        return (
            f"Coupure au hop {self.last_responsive_hop + 1}/{self.total_hops} "
            f"({self.break_point})"
        )


def run_traceroute(
    target: str = "8.8.8.8",
    max_hops: int = 20,
    timeout: int = 15,
) -> TracerouteResult | None:
    """Run traceroute and parse the output.

    Returns TracerouteResult on success, None on execution failure.
    Never raises.
    """
    try:
        result = subprocess.run(
            ["traceroute", "-n", "-m", str(max_hops), "-w", "2", target],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
    except subprocess.TimeoutExpired:
        logging.warning("Traceroute timeout apres %ds", timeout)
        return None
    except FileNotFoundError:
        logging.warning("Commande 'traceroute' introuvable -- installer traceroute")
        return None
    except Exception as e:
        logging.warning("Erreur traceroute : %s", e)
        return None

    return _parse_traceroute(target, output)


def _parse_traceroute(target: str, output: str) -> TracerouteResult:
    """Parse traceroute -n output into structured result."""
    hops: list[TracerouteHop] = []
    last_responsive = 0

    for line in output.strip().splitlines()[1:]:  # skip header line
        line = line.strip()
        if not line:
            continue

        # Parse hop number
        match = re.match(r"^\s*(\d+)\s+(.+)", line)
        if not match:
            continue

        hop_num = int(match.group(1))
        rest = match.group(2)

        # Check if all attempts timed out (*)
        if re.match(r"^[\s*]+$", rest):
            hops.append(TracerouteHop(hop_number=hop_num, host="*", rtt_ms=None))
            continue

        # Parse IP and RTT
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", rest)
        rtt_match = re.search(r"([\d.]+)\s*ms", rest)

        host = ip_match.group(1) if ip_match else "*"
        rtt = float(rtt_match.group(1)) if rtt_match else None

        hops.append(TracerouteHop(hop_number=hop_num, host=host, rtt_ms=rtt))

        if host != "*":
            last_responsive = hop_num

    reached = any(h.host == target for h in hops)
    total = len(hops)

    # Determine break point
    if reached:
        break_point = "aucune coupure"
    elif last_responsive == 0:
        break_point = "coupure des le premier hop (gateway?)"
    elif last_responsive <= 2:
        break_point = f"coupure apres hop {last_responsive} (reseau local/USG)"
    elif last_responsive <= 5:
        break_point = f"coupure apres hop {last_responsive} (infrastructure FAI/NRO)"
    else:
        break_point = f"coupure apres hop {last_responsive} (backbone internet)"

    return TracerouteResult(
        target=target,
        hops=tuple(hops),
        last_responsive_hop=last_responsive,
        total_hops=total,
        reached_target=reached,
        break_point=break_point,
    )
