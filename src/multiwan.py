"""Multi-WAN detection -- check which WAN interface is active on the USG.

Optional: only useful if USG has dual-WAN with failover configured.
Uses SSH to query the USG routing table.
"""

import logging
from dataclasses import dataclass

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore

from config import USG_IP, USG_USER, USG_SSH_KEY, USG_KNOWN_HOSTS, SSH_TIMEOUT


@dataclass(frozen=True)
class WanStatus:
    """WAN interface status."""

    primary_up: bool = True
    failover_active: bool = False
    active_interface: str = "unknown"
    reachable: bool = False

    def to_dict(self) -> dict:
        return {
            "primary_up": self.primary_up,
            "failover_active": self.failover_active,
            "active_interface": self.active_interface,
            "reachable": self.reachable,
        }

    def summary(self) -> str:
        if not self.reachable:
            return "USG injoignable via SSH"
        if self.failover_active:
            return f"WAN failover actif ({self.active_interface})"
        return f"WAN principal actif ({self.active_interface})"


def check_wan_status() -> WanStatus:
    """Check WAN status via SSH. Never raises.

    Runs 'show interfaces' on EdgeOS to detect active WAN.
    """
    if paramiko is None:
        return WanStatus(reachable=False)

    try:
        client = paramiko.SSHClient()
        try:
            client.load_host_keys(USG_KNOWN_HOSTS)
        except FileNotFoundError:
            return WanStatus(reachable=False)

        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        client.connect(
            hostname=USG_IP,
            username=USG_USER,
            key_filename=USG_SSH_KEY if USG_SSH_KEY else None,
            timeout=SSH_TIMEOUT,
            banner_timeout=SSH_TIMEOUT,
            allow_agent=False,
            look_for_keys=False,
            disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
        )

        # Query default route to see which interface is active
        _, stdout, _ = client.exec_command("ip route show default", timeout=10)
        output = stdout.read().decode("utf-8", errors="replace").strip()
        client.close()

        if not output:
            return WanStatus(reachable=True, active_interface="unknown")

        # Parse: "default via X.X.X.X dev ethX"
        interface = "unknown"
        for part in output.split():
            if part.startswith("eth") or part.startswith("ppp"):
                interface = part
                break

        # eth0 is typically WAN primary, eth2 is WAN2/failover on USG
        failover = interface in ("eth2", "ppp1")

        return WanStatus(
            primary_up=not failover,
            failover_active=failover,
            active_interface=interface,
            reachable=True,
        )

    except Exception as e:
        logging.debug("Multi-WAN check failed: %s", e)
        return WanStatus(reachable=False)
