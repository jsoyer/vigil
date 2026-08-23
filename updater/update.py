#!/usr/bin/env python3
"""
USG Watchdog Auto-Updater

Checks GitHub for new tagged releases, downloads, validates, and applies
updates with automatic rollback on failure.

This script runs as a separate systemd one-shot service (not inside the watchdog).
It has write access to /opt/usg-watchdog/ while the watchdog itself has read-only.

Usage:
  python3 updater/update.py              # check + apply if available
  python3 updater/update.py --check      # check only, no apply
  python3 updater/update.py --force      # skip version comparison
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# ===================================================================
# Configuration
# ===================================================================

GITHUB_REPO = os.getenv("UPDATER_GITHUB_REPO", "jsoyer/usg-watchdog")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "stable")  # stable or dev
INSTALL_DIR = Path(os.getenv("UPDATER_INSTALL_DIR", "/opt/usg-watchdog"))
SERVICE_NAME = "usg-watchdog"
HEALTH_CHECK_URL = os.getenv("UPDATER_HEALTH_URL", "http://localhost:9000/health")
HEALTH_CHECK_TIMEOUT = 60  # seconds to wait for healthy after restart
RELEASES_KEEP = 3
VENV_PIP = INSTALL_DIR / "venv" / "bin" / "pip"
PIP_INSTALL_TIMEOUT = 300  # seconds -- installation de dependances peut etre lente

# ===================================================================
# Logging
# ===================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("updater")

# ===================================================================
# Version helpers
# ===================================================================


def read_current_version() -> str:
    """Read the current version from the VERSION file."""
    version_file = INSTALL_DIR / "current" / "VERSION"
    if not version_file.exists():
        # Fallback: try repo root
        version_file = INSTALL_DIR / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    return version_file.read_text().strip()


def parse_version(v: str) -> tuple[int, ...]:
    """Parse semver string to comparable tuple."""
    clean = v.lstrip("v").split("-")[0]  # strip v prefix and pre-release
    try:
        return tuple(int(x) for x in clean.split("."))
    except ValueError:
        return (0, 0, 0)


def is_stable_tag(tag_name: str) -> bool:
    """Check if a tag matches the stable channel (vX.Y.Z, no suffix)."""
    import re

    return bool(re.match(r"^v\d+\.\d+\.\d+$", tag_name))


def is_dev_tag(tag_name: str) -> bool:
    """Check if a tag matches the dev channel (vX.Y.Z-dev.N or -rc.N)."""
    import re

    return bool(re.match(r"^v\d+\.\d+\.\d+-(dev|rc)\.\d+$", tag_name))


# ===================================================================
# GitHub API
# ===================================================================


def fetch_tags() -> list[dict]:
    """Fetch tags from GitHub API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=20"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "usg-watchdog-updater",
        },
    )

    # Add auth token if available
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log.error("Impossible de contacter GitHub : %s", e)
        return []
    except json.JSONDecodeError:
        log.error("Reponse GitHub invalide")
        return []


def find_latest_tag(tags: list[dict]) -> dict | None:
    """Find the latest tag matching the configured channel."""
    filter_fn = is_stable_tag if UPDATE_CHANNEL == "stable" else is_dev_tag

    matching = [t for t in tags if filter_fn(t["name"])]
    if not matching:
        return None

    matching.sort(key=lambda t: parse_version(t["name"]), reverse=True)
    return matching[0]


def download_tarball(tag_name: str, dest: Path) -> bool:
    """Download the source tarball for a given tag."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/tarball/{tag_name}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "usg-watchdog-updater",
        },
    )
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
        log.info("Tarball telecharge : %s (%d bytes)", tag_name, dest.stat().st_size)
        return True
    except urllib.error.URLError as e:
        log.error("Echec telechargement : %s", e)
        return False


# ===================================================================
# Validation pipeline
# ===================================================================


def extract_tarball(tarball: Path, dest: Path) -> bool:
    """Extract tarball to destination directory."""
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            # GitHub tarballs have a top-level directory like owner-repo-hash/
            members = tar.getmembers()
            if not members:
                log.error("Tarball vide")
                return False

            # Find the top-level directory prefix
            prefix = members[0].name.split("/")[0]

            dest.mkdir(parents=True, exist_ok=True)
            for member in members:
                # Strip the prefix directory
                if "/" not in member.name:
                    continue
                member.name = member.name[len(prefix) + 1 :]
                if not member.name:
                    continue
                # Path traversal protection
                if ".." in member.name or member.name.startswith("/"):
                    log.warning("Tarball: path suspect ignore: %s", member.name)
                    continue
                if member.issym() or member.islnk():
                    log.warning("Tarball: symlink ignore: %s", member.name)
                    continue
                tar.extract(member, dest)

        log.info("Extrait dans %s", dest)
        return True
    except (tarfile.TarError, OSError) as e:
        log.error("Erreur extraction : %s", e)
        return False


def validate_syntax(staged_src: Path) -> bool:
    """Validate Python syntax via py_compile."""
    py_files = list(staged_src.rglob("*.py"))
    if not py_files:
        log.error("Aucun fichier Python trouve dans %s", staged_src)
        return False

    for py_file in py_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(py_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error("Erreur syntaxe %s : %s", py_file.name, result.stderr)
            return False

    log.info("Syntaxe OK (%d fichiers)", len(py_files))
    return True


def validate_imports(staged_src: Path) -> bool:
    """Validate that core modules can be imported."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import watchdog; import config; import connectivity; import usg",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(staged_src)},
    )
    if result.returncode != 0:
        log.error("Erreur import : %s", result.stderr[:500])
        return False

    log.info("Imports OK")
    return True


def validate_tests(staged_dir: Path) -> bool:
    """Run unit tests on staged code."""
    staged_src = staged_dir / "src"
    staged_tests = staged_dir / "tests"

    if not staged_tests.exists():
        log.warning("Pas de dossier tests/ -- skip validation tests")
        return True

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(staged_tests),
            "-x",
            "-q",
            "--timeout=120",
            "--tb=line",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(staged_src)},
        timeout=180,
    )
    if result.returncode != 0:
        log.error("Tests echoues :\n%s", result.stdout[-500:])
        return False

    log.info("Tests OK")
    return True


def install_requirements(staged_dir: Path) -> bool:
    """Installe les dependances de la release stagee, si presentes.

    Execute `<venv>/bin/pip install -r <staged>/requirements.txt` -- appele
    apres validation de la release stagee et avant la bascule du symlink.
    Un echec ici doit interrompre la mise a jour AVANT toute bascule : pas
    de swap, pas de restart, pas de rollback (rien n'a encore change pour
    l'instance en cours).
    """
    requirements_file = staged_dir / "requirements.txt"
    if not requirements_file.exists():
        log.info("Pas de requirements.txt dans la release -- rien a installer")
        return True

    log.info("Installation des dependances : %s", requirements_file)
    try:
        result = subprocess.run(
            [str(VENV_PIP), "install", "-r", str(requirements_file)],
            capture_output=True,
            text=True,
            timeout=PIP_INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error(
            "Installation des dependances : delai depasse (%ds)",
            PIP_INSTALL_TIMEOUT,
        )
        return False
    except OSError as e:
        log.error("Impossible d'executer pip (%s) : %s", VENV_PIP, e)
        return False

    if result.returncode != 0:
        log.error("Installation des dependances echouee :\n%s", result.stderr[-1000:])
        return False

    log.info("Dependances installees :\n%s", result.stdout[-500:])
    return True


# ===================================================================
# Apply + Rollback
# ===================================================================


def apply_update(version: str, staged_dir: Path) -> bool:
    """Apply staged update via symlink swap."""
    releases_dir = INSTALL_DIR / "releases"
    release_dir = releases_dir / f"v{version}"
    current_link = INSTALL_DIR / "current"

    # Move staged dir to releases
    releases_dir.mkdir(parents=True, exist_ok=True)
    if release_dir.exists():
        shutil.rmtree(release_dir)
    shutil.move(str(staged_dir), str(release_dir))

    # Create new symlink atomically
    new_link = INSTALL_DIR / "current.new"
    new_link.unlink(missing_ok=True)
    new_link.symlink_to(release_dir)

    # Atomic swap
    new_link.rename(current_link)

    log.info("Symlink mis a jour : current -> releases/v%s", version)
    return True


def restart_service() -> bool:
    """Restart the watchdog service."""
    result = subprocess.run(
        ["systemctl", "restart", SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("Echec restart service : %s", result.stderr)
        return False

    log.info("Service redemarre")
    return True


def health_check(target_version: str) -> bool:
    """Wait for the watchdog to become healthy after restart.

    Compare aussi le champ 'version' du JSON /health a la version cible de
    la mise a jour : un mismatch signifie que le service redemarre sert
    encore l'ancien code (layout casse, symlink 'current' non lu par le
    unit systemd, etc.) -- c'est traite comme un echec de mise a jour au
    meme titre qu'un statut non healthy (rollback + notification).
    """
    deadline = time.time() + HEALTH_CHECK_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_CHECK_URL, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status = data.get("status", "")
                reported_version = data.get("version", "")
                if status in ("healthy", "degraded"):
                    if reported_version != target_version:
                        log.error(
                            "Health check : version annoncee '%s' != version cible '%s' "
                            "-- le service redemarre ne sert pas le code attendu",
                            reported_version,
                            target_version,
                        )
                        return False
                    log.info(
                        "Health check OK : status=%s version=%s",
                        status,
                        reported_version,
                    )
                    return True
                log.info("Health check : status=%s (attente...)", status)
        except Exception:
            pass
        time.sleep(5)

    log.error("Health check echoue apres %ds", HEALTH_CHECK_TIMEOUT)
    return False


def rollback(previous_version: str) -> bool:
    """Rollback to a previous version."""
    releases_dir = INSTALL_DIR / "releases"
    previous_dir = releases_dir / f"v{previous_version}"
    current_link = INSTALL_DIR / "current"

    if not previous_dir.exists():
        log.error("Version precedente introuvable : %s", previous_dir)
        return False

    new_link = INSTALL_DIR / "current.new"
    new_link.unlink(missing_ok=True)
    new_link.symlink_to(previous_dir)
    new_link.rename(current_link)

    log.warning("Rollback vers v%s", previous_version)
    restart_service()
    return True


def prune_old_releases() -> None:
    """Keep only the N most recent releases."""
    releases_dir = INSTALL_DIR / "releases"
    if not releases_dir.exists():
        return

    releases = sorted(
        [d for d in releases_dir.iterdir() if d.is_dir() and d.name.startswith("v")],
        key=lambda d: parse_version(d.name),
        reverse=True,
    )

    for old in releases[RELEASES_KEEP:]:
        log.info("Pruning old release : %s", old.name)
        shutil.rmtree(old)


# ===================================================================
# Notification helper
# ===================================================================


def notify_watchdog(message: str) -> None:
    """Send a notification via the watchdog's HTTP API (if available)."""
    try:
        # Le suivi se fait via l'API /api/events du watchdog (endpoint
        # informatif ici) -- la notification effective sera envoyee par le
        # watchdog lui-meme au prochain demarrage.
        log.info("Notification : %s", message)
    except Exception:
        pass


# ===================================================================
# Main
# ===================================================================


def main() -> int:
    check_only = "--check" in sys.argv
    force = "--force" in sys.argv

    log.info("=" * 50)
    log.info("USG Watchdog Updater")
    log.info("  Repo    : %s", GITHUB_REPO)
    log.info("  Channel : %s", UPDATE_CHANNEL)
    log.info("  Install : %s", INSTALL_DIR)
    log.info("=" * 50)

    # Check watchdog health first -- don't update during an outage
    if not check_only:
        try:
            with urllib.request.urlopen(HEALTH_CHECK_URL, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status = data.get("status", "")
                if status not in ("healthy", "degraded"):
                    log.warning(
                        "Watchdog non healthy (status=%s) -- MAJ reportee", status
                    )
                    return 0
        except Exception:
            log.warning("Watchdog injoignable -- MAJ reportee")
            return 0

    # Fetch available versions
    current = read_current_version()
    log.info("Version actuelle : %s", current)

    tags = fetch_tags()
    if not tags:
        log.info("Aucun tag disponible ou GitHub injoignable")
        return 0

    latest = find_latest_tag(tags)
    if latest is None:
        log.info("Aucun tag correspondant au canal '%s'", UPDATE_CHANNEL)
        return 0

    latest_name = latest["name"]
    latest_version = latest_name.lstrip("v")
    log.info("Derniere version disponible : %s", latest_name)

    if not force and parse_version(latest_version) <= parse_version(current):
        log.info("Deja a jour")
        return 0

    log.info("Mise a jour disponible : %s -> %s", current, latest_version)

    if check_only:
        print(
            json.dumps(
                {
                    "available": True,
                    "current": current,
                    "latest": latest_version,
                    "tag": latest_name,
                }
            )
        )
        return 0

    # ===== Stage =====
    with tempfile.TemporaryDirectory(prefix="usg-update-") as tmpdir:
        tmppath = Path(tmpdir)
        tarball = tmppath / "source.tar.gz"
        staged = tmppath / "staged"

        # Download
        if not download_tarball(latest_name, tarball):
            return 1

        # Extract
        if not extract_tarball(tarball, staged):
            return 1

        # Validate syntax
        staged_src = staged / "src"
        if not staged_src.exists():
            log.error("Pas de dossier src/ dans le tarball")
            return 1

        if not validate_syntax(staged_src):
            log.error("Validation syntaxe echouee -- MAJ annulee")
            return 1

        if not validate_imports(staged_src):
            log.error("Validation imports echouee -- MAJ annulee")
            return 1

        # Copy VERSION file
        version_file = staged / "VERSION"
        if not version_file.exists():
            version_file.write_text(latest_version + "\n")

        # Installer les dependances de la release stagee (si requirements.txt
        # est present) -- dernier controle avant la bascule du symlink.
        if not install_requirements(staged):
            log.error("Installation des dependances echouee -- MAJ annulee")
            notify_watchdog(
                f"Mise a jour v{latest_version} annulee : echec de "
                "l'installation des dependances (pip install)"
            )
            return 1

        # ===== Apply =====
        log.info("Application de la mise a jour v%s...", latest_version)

        if not apply_update(latest_version, staged):
            log.error("Echec application -- MAJ annulee")
            return 1

        # Restart service
        if not restart_service():
            log.error("Echec restart -- rollback...")
            rollback(current)
            return 1

        # Health check
        if not health_check(latest_version):
            log.error("Health check echoue -- rollback vers v%s", current)
            rollback(current)
            return 1

        log.info("Mise a jour v%s -> v%s reussie", current, latest_version)
        prune_old_releases()

    return 0


if __name__ == "__main__":
    sys.exit(main())
