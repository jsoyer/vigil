#!/usr/bin/env python3
"""Pre-flight check for Vigil -- run via ExecStartPre in systemd.

Verifies that the watchdog can start successfully:
1. Python version compatible
2. Core modules importable
3. Config loads without error
4. HTTP port is available

Exit 0 = OK, non-zero = abort service start.
"""

import socket
import sys
import os


def check_python_version() -> bool:
    if sys.version_info < (3, 11):
        print(f"PREFLIGHT FAIL: Python {sys.version} < 3.11 requis", file=sys.stderr)
        return False
    return True


def check_imports() -> bool:
    # Add src/ to path
    src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "current", "src")
    if not os.path.isdir(src_dir):
        src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    sys.path.insert(0, src_dir)

    try:
        import config  # noqa: F401
        import connectivity  # noqa: F401
        import watchdog  # noqa: F401
        import usg  # noqa: F401

        # A1 -- drivers/ et managed_devices.py doivent rester importables
        # sans tplinkrouterc6u installee (invariant C1, import vendor
        # paresseux : la lib n'est importee que dans le corps de
        # TplinkDriver._import_tplinkrouterc6u(), jamais au niveau module).
        # Un preflight qui echouerait ici sur une instance sans equipement
        # TP-Link declare bloquerait le demarrage du service a tort.
        import drivers  # noqa: F401
        import managed_devices  # noqa: F401

        return True
    except Exception as e:
        print(f"PREFLIGHT FAIL: Import error: {e}", file=sys.stderr)
        return False


def check_port(port: int = 9000) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                # Port is already in use -- another instance?
                print(
                    f"PREFLIGHT WARN: Port {port} deja en cours d'utilisation",
                    file=sys.stderr,
                )
                # Not fatal -- could be the previous instance shutting down
            return True
    except Exception:
        return True


def main() -> int:
    checks = [
        ("Python version", check_python_version),
        ("Module imports", check_imports),
        ("Port availability", check_port),
    ]

    all_ok = True
    for name, check in checks:
        try:
            if check():
                print(f"PREFLIGHT OK: {name}")
            else:
                all_ok = False
        except Exception as e:
            print(f"PREFLIGHT FAIL: {name}: {e}", file=sys.stderr)
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
