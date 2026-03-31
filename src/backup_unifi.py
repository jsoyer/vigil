"""UniFi config backup -- upload latest .unf to remote storage via rclone.

Optional module: inert if UNIFI_BACKUP_DIR is not configured.
Only runs on the machine hosting the UniFi Network Server.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from config import (
    UNIFI_BACKUP_DIR,
    UNIFI_BACKUP_RCLONE_DEST,
    UNIFI_BACKUP_RETENTION_DAYS,
    UNIFI_BACKUP_MAX_AGE_HOURS,
)


def is_configured() -> bool:
    """Check if UniFi backup is configured."""
    return bool(UNIFI_BACKUP_DIR)


@dataclass(frozen=True)
class BackupResult:
    """Result of a backup operation."""
    ok: bool
    filename: str = ""
    size_bytes: int = 0
    destination: str = ""
    error: str = ""
    stale: bool = False
    stale_hours: int = 0

    def to_dict(self) -> dict:
        d: dict = {
            "ok": self.ok,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 1) if self.size_bytes > 0 else 0,
            "destination": self.destination,
        }
        if self.error:
            d["error"] = self.error
        if self.stale:
            d["stale"] = True
            d["stale_hours"] = self.stale_hours
        return d

    def summary(self) -> str:
        if not self.ok:
            return f"Backup echoue : {self.error}"
        size_mb = round(self.size_bytes / (1024 * 1024), 1)
        return f"Backup OK : {self.filename} ({size_mb} MB) -> {self.destination}"


def find_latest_backup() -> Path | None:
    """Find the most recent .unf file in the backup directory.

    Returns Path or None. Never raises.
    """
    if not UNIFI_BACKUP_DIR:
        return None

    backup_dir = Path(UNIFI_BACKUP_DIR)
    if not backup_dir.is_dir():
        logging.warning("Backup UniFi: repertoire introuvable : %s", UNIFI_BACKUP_DIR)
        return None

    unf_files = sorted(backup_dir.glob("*.unf"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not unf_files:
        logging.warning("Backup UniFi: aucun fichier .unf dans %s", UNIFI_BACKUP_DIR)
        return None

    return unf_files[0]


def check_backup_age(backup_path: Path) -> tuple[bool, int]:
    """Check if the backup file is too old.

    Returns (is_stale, age_hours).
    """
    age_seconds = time.time() - backup_path.stat().st_mtime
    age_hours = int(age_seconds / 3600)
    is_stale = age_hours > UNIFI_BACKUP_MAX_AGE_HOURS
    return is_stale, age_hours


def check_backup_size(backup_path: Path) -> tuple[bool, int]:
    """Check if the backup file size is suspicious.

    Returns (is_suspicious, size_bytes).
    A file < 1KB is considered suspicious (empty or corrupted).
    """
    size = backup_path.stat().st_size
    return size < 1024, size


def upload_backup(backup_path: Path, destination: str = UNIFI_BACKUP_RCLONE_DEST) -> bool:
    """Upload a backup file via rclone.

    Returns True on success. Never raises.
    """
    try:
        result = subprocess.run(
            ["rclone", "copy", str(backup_path), destination,
             "--checksum", "--transfers", "1"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logging.error("Backup rclone echoue : %s", result.stderr[:500])
            return False
        logging.info("Backup upload OK : %s -> %s", backup_path.name, destination)
        return True
    except FileNotFoundError:
        logging.error("Commande 'rclone' introuvable -- installer rclone")
        return False
    except subprocess.TimeoutExpired:
        logging.error("Backup rclone timeout (300s)")
        return False
    except Exception as e:
        logging.error("Backup rclone erreur : %s", e)
        return False


def prune_old_backups(destination: str = UNIFI_BACKUP_RCLONE_DEST) -> bool:
    """Delete backups older than RETENTION_DAYS from remote.

    Returns True on success. Never raises.
    """
    try:
        result = subprocess.run(
            ["rclone", "delete", destination,
             "--min-age", f"{UNIFI_BACKUP_RETENTION_DAYS}d",
             "--include", "*.unf"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logging.warning("Prune rclone echoue : %s", result.stderr[:200])
            return False
        logging.info("Prune OK : backups > %d jours supprimes de %s", UNIFI_BACKUP_RETENTION_DAYS, destination)
        return True
    except Exception as e:
        logging.warning("Prune rclone erreur : %s", e)
        return False


def run_backup(source: str = "scheduled") -> BackupResult:
    """Run the full backup pipeline: find, validate, upload, prune.

    Args:
        source: trigger source for logging ("scheduled", "pre_reboot", "api")

    Returns BackupResult. Never raises.
    """
    if not is_configured():
        return BackupResult(ok=False, error="not configured")

    # Find latest backup
    backup_path = find_latest_backup()
    if backup_path is None:
        return BackupResult(ok=False, error="aucun fichier .unf trouve")

    filename = backup_path.name

    # Check age
    is_stale, age_hours = check_backup_age(backup_path)
    if is_stale:
        logging.warning(
            "Backup UniFi perime : %s date de %dh (max %dh)",
            filename, age_hours, UNIFI_BACKUP_MAX_AGE_HOURS,
        )

    # Check size
    is_suspicious, size_bytes = check_backup_size(backup_path)
    if is_suspicious:
        logging.error("Backup UniFi suspect : %s fait %d bytes (< 1KB)", filename, size_bytes)
        return BackupResult(
            ok=False,
            filename=filename,
            size_bytes=size_bytes,
            error=f"fichier suspect ({size_bytes} bytes < 1KB)",
            stale=is_stale,
            stale_hours=age_hours,
        )

    # Upload
    logging.info("Backup UniFi [%s] : upload %s (%d bytes)", source, filename, size_bytes)
    if not upload_backup(backup_path):
        return BackupResult(
            ok=False,
            filename=filename,
            size_bytes=size_bytes,
            error="rclone upload echoue",
            stale=is_stale,
            stale_hours=age_hours,
        )

    # Prune old backups
    prune_old_backups()

    return BackupResult(
        ok=True,
        filename=filename,
        size_bytes=size_bytes,
        destination=UNIFI_BACKUP_RCLONE_DEST,
        stale=is_stale,
        stale_hours=age_hours,
    )
