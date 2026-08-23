"""Background HTTP server exposing watchdog state, health, and event history."""

import hmac
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config as _config
from state import StateHolder, CMD_PAUSE, CMD_RESUME, CMD_REBOOT
from events import EventLog
from report import generate_daily_report, calculate_monthly_sla
from metrics import render_metrics
from history import HistoryBuffer

# D4 -- masque le jeton de confirmation dans les journaux, y compris en
# LOG_LEVEL=DEBUG (log_message() journalise sinon la requete brute, donc le
# chemin complet, donc le jeton en clair). Applique dans log_message() lui
# meme (pas chez l'appelant) pour couvrir tous les chemins d'acces.
_CONFIRM_LOG_MASK_RE = re.compile(r"(/api/confirm/[^/\s\"]+/)[^/\s\"?]+")


def _configured_notification_channels() -> list[str]:
    """Liste des canaux de notification effectivement configures.

    Duplique volontairement notifier._dispatch (read-only pour ce sprint) --
    petite fonction pure sans dependance vers watchdog.py pour eviter un
    import circulaire (watchdog importe start_http_server).
    """
    from notifier import _ntfy, _email
    import mqtt_publisher

    channels: list[str] = []
    if _ntfy.is_configured():
        channels.append("ntfy")
    if _email.is_configured():
        channels.append("email")
    if mqtt_publisher.is_configured():
        channels.append("mqtt")
    return channels


# Lazy-loaded at first HTTP request to avoid paying the parse cost at startup.
_dashboard_html: str | None = None
_manifest_json: str | None = None
_service_worker_js: str | None = None


def _get_dashboard_html() -> str:
    global _dashboard_html
    if _dashboard_html is None:
        from dashboard import DASHBOARD_HTML

        _dashboard_html = DASHBOARD_HTML
    return _dashboard_html


def _get_manifest_json() -> str:
    global _manifest_json
    if _manifest_json is None:
        from pwa import MANIFEST_JSON

        _manifest_json = MANIFEST_JSON
    return _manifest_json


def _get_service_worker_js() -> str:
    global _service_worker_js
    if _service_worker_js is None:
        from pwa import SERVICE_WORKER_JS

        _service_worker_js = SERVICE_WORKER_JS
    return _service_worker_js


def _make_handler_class(
    holder: StateHolder,
    event_log: EventLog | None = None,
    history: HistoryBuffer | None = None,
) -> type:
    """Create a request handler class with access to shared state."""

    # D3 -- rate limiting de /api/confirm/* : compteur en memoire simple,
    # dict IP -> horodatages des tentatives echouees. Ferme sur la classe
    # Handler (une instance par requete, un seul jeu de compteurs par
    # serveur) plutot que module-level, pour la meme raison que `holder`/
    # `event_log` : isolation naturelle entre serveurs (tests) sans etat
    # partage accidentel entre deux instances de Vigil dans le meme process.
    # Purge paresseuse (a la lecture) plutot que par tache periodique
    # dediee -- suffisant vu le volume attendu (endpoint non public, cf.
    # Q7/INVARIANTS.md) et deja le style de `confirm.py` (`_purge_expired_locked`).
    _confirm_rate_lock = threading.Lock()
    _confirm_failures: dict[str, list[float]] = {}

    def _confirm_prune_and_count(ip: str) -> int:
        now = time.monotonic()
        window = _config.CONFIRM_RATE_LIMIT_WINDOW
        with _confirm_rate_lock:
            recent = [t for t in _confirm_failures.get(ip, []) if now - t < window]
            _confirm_failures[ip] = recent
            return len(recent)

    def _confirm_record_failure(ip: str) -> None:
        with _confirm_rate_lock:
            _confirm_failures.setdefault(ip, []).append(time.monotonic())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                if self.path == "/" or self.path == "/dashboard":
                    self._handle_dashboard()
                elif self.path == "/manifest.json":
                    self._respond_text(
                        "application/manifest+json", _get_manifest_json()
                    )
                elif self.path == "/sw.js":
                    self._respond_text(
                        "application/javascript", _get_service_worker_js()
                    )
                elif self.path == "/health":
                    self._handle_health()
                elif self.path == "/api/stream":
                    self._handle_sse_stream()
                elif self.path == "/api/state":
                    self._handle_state()
                elif self.path == "/api/events" or self.path.startswith("/api/events?"):
                    self._handle_events()
                elif self.path == "/api/config":
                    self._handle_config()
                elif self.path == "/api/maintenance":
                    self._handle_get_maintenance()
                elif self.path == "/api/backup/unifi":
                    self._handle_get_backup_unifi()
                elif self.path == "/api/history":
                    self._respond_json(200, history.get_all() if history else [])
                elif self.path == "/api/sla":
                    if event_log:
                        self._respond_json(200, calculate_monthly_sla(event_log))
                    else:
                        self._respond_json(200, {})
                elif self.path == "/api/isp":
                    self._handle_isp_status()
                elif self.path == "/api/backup/config":
                    self._handle_export_config()
                elif self.path == "/metrics":
                    self._handle_metrics()
                elif self.path == "/api/report":
                    self._handle_report()
                elif self.path == "/api/tplink" or self.path.startswith("/api/tplink/"):
                    self._handle_tplink_get()
                else:
                    self._respond_json(404, {"error": "not found"})
            except Exception:
                self._respond_json(500, {"error": "internal error"})

        def _check_auth(self) -> bool:
            """Check API token. Returns True if authorized."""
            if not _config.API_TOKEN:
                self._respond_json(
                    403, {"error": "API_TOKEN non configure -- POST desactive"}
                )
                return False
            auth = self.headers.get("Authorization", "")
            # D2 -- comparaison en temps constant (dette existante, corrigee
            # au passage avec la meme durcissement que confirm.validate()).
            if hmac.compare_digest(auth, f"Bearer {_config.API_TOKEN}"):
                return True
            self._respond_json(401, {"error": "unauthorized"})
            return False

        def do_POST(self) -> None:
            try:
                # /api/confirm/<action>/<jeton> -- seul endpoint POST exempte
                # de _check_auth() : l'autorisation est le jeton de
                # confirmation lui-meme (URL de capacite, PRD Ntfy-first
                # S4.2.2). Doit etre route AVANT tout appel a _check_auth().
                if self.path.split("?", 1)[0].startswith("/api/confirm/"):
                    self._handle_confirm_action()
                    return
                if not self._check_auth():
                    return
                if self.path == "/api/pause":
                    holder.send_command(CMD_PAUSE)
                    self._respond_json(200, {"ok": True, "command": "pause"})
                elif self.path == "/api/resume":
                    holder.send_command(CMD_RESUME)
                    self._respond_json(200, {"ok": True, "command": "resume"})
                elif self.path == "/api/reboot":
                    holder.send_command(CMD_REBOOT)
                    self._respond_json(200, {"ok": True, "command": "reboot"})
                elif self.path == "/api/ddns/update":
                    self._handle_ddns_update()
                elif self.path == "/api/tailscale/sync":
                    self._handle_tailscale_sync()
                elif self.path == "/api/backup/unifi":
                    self._handle_backup_unifi()
                elif self.path == "/api/maintenance":
                    self._handle_post_maintenance()
                elif self.path == "/api/config/reload":
                    self._handle_config_reload()
                elif self.path.startswith("/api/tplink/"):
                    self._handle_tplink_post()
                else:
                    self._respond_json(404, {"error": "not found"})
            except Exception:
                self._respond_json(500, {"error": "internal error"})

        def _handle_dashboard(self) -> None:
            body = _get_dashboard_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _build_health_dict(self, snapshot: object) -> dict:
            """Build the health response dict from a WatchdogState snapshot."""
            if snapshot.surveillance_only:
                status = "surveillance"
            elif snapshot.failure_score >= snapshot.threshold:
                status = "critical"
            elif snapshot.failure_score > 0:
                status = "degraded"
            else:
                status = "healthy"

            return {
                "status": status,
                "score": snapshot.failure_score,
                "threshold": snapshot.threshold,
                "gateway": "OK" if snapshot.gateway_ok else "KO",
                "internet": f"{snapshot.internet_ok_count}/{snapshot.internet_total}",
                "instance_priority": snapshot.instance_priority,
                "consecutive_reboots": snapshot.consecutive_reboots,
                "reboots_today": snapshot.reboots_today,
                "isp_outage": snapshot.isp_outage_detected,
                "uptime": int(snapshot.uptime_seconds),
                "latency": {
                    "gateway_ms": round(snapshot.gateway_rtt_ms, 1)
                    if snapshot.gateway_rtt_ms is not None
                    else None,
                    "internet_avg_ms": round(snapshot.internet_avg_rtt_ms, 1)
                    if snapshot.internet_avg_rtt_ms is not None
                    else None,
                    "degraded": snapshot.latency_degraded,
                },
                "version": snapshot.version,
                "peer": {
                    "status": snapshot.peer_status,
                    "score": snapshot.peer_score,
                    "gateway": snapshot.peer_gateway,
                    "internet": snapshot.peer_internet,
                },
                "notification_channels": _configured_notification_channels(),
            }

        def _handle_health(self) -> None:
            snapshot = holder.state
            if snapshot is None:
                self._respond_json(503, {"status": "starting"})
                return
            self._respond_json(200, self._build_health_dict(snapshot))

        def _handle_sse_stream(self) -> None:
            """SSE endpoint: streams health + events updates to connected clients.

            Each SSE message contains a JSON payload with health and events data.
            A keepalive comment is sent every 15 seconds when state is unchanged.
            The loop exits cleanly on client disconnect (BrokenPipeError /
            ConnectionResetError).
            """
            SSE_POLL_INTERVAL = 5  # seconds between state checks
            SSE_KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments

            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                return

            last_sent_score: float | None = None
            last_sent_uptime: int | None = None
            last_keepalive = time.monotonic()

            while True:
                try:
                    snapshot = holder.state

                    if snapshot is not None:
                        current_score = snapshot.failure_score
                        current_uptime = int(snapshot.uptime_seconds)

                        state_changed = (
                            current_score != last_sent_score
                            or current_uptime != last_sent_uptime
                        )

                        if state_changed:
                            health = self._build_health_dict(snapshot)
                            events = event_log.get_recent(30) if event_log else []
                            payload = json.dumps({"health": health, "events": events})
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            last_sent_score = current_score
                            last_sent_uptime = current_uptime
                            last_keepalive = time.monotonic()

                    # Send keepalive comment if no data was sent recently
                    now = time.monotonic()
                    if now - last_keepalive >= SSE_KEEPALIVE_INTERVAL:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_keepalive = now

                    time.sleep(SSE_POLL_INTERVAL)

                except (BrokenPipeError, ConnectionResetError):
                    # Client disconnected cleanly
                    break
                except Exception as exc:
                    logging.debug("SSE stream: fermeture inattendue -- %s", exc)
                    break

        def _handle_state(self) -> None:
            snapshot = holder.state
            if snapshot is None:
                self._respond_json(503, {"error": "not ready"})
                return
            data = snapshot.to_dict()
            data["notification_channels"] = _configured_notification_channels()
            self._respond_json(200, data)

        def _handle_events(self) -> None:
            if event_log is None:
                self._respond_json(200, [])
                return

            # Parse optional query params
            count = 50
            event_type = None
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for param in query.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        if key == "count":
                            try:
                                count = min(int(value), 100)
                            except ValueError:
                                pass
                        elif key == "type":
                            event_type = value

            if event_type:
                events = event_log.get_by_type(event_type)
            else:
                events = event_log.get_recent(count)

            self._respond_json(200, events)

        def _handle_config(self) -> None:
            """Return active config (no secrets)."""
            # Expose tuning parameters only, never tokens/passwords/keys
            cfg = {
                "check_interval": _config.CHECK_INTERVAL,
                "reboot_score_threshold": _config.REBOOT_SCORE_THRESHOLD,
                "max_score": _config.MAX_SCORE,
                "score_gateway_down": _config.SCORE_GATEWAY_DOWN,
                "score_internet_all_down": _config.SCORE_INTERNET_ALL_DOWN,
                "score_internet_partial": _config.SCORE_INTERNET_PARTIAL,
                "score_decay_ok": _config.SCORE_DECAY_OK,
                "score_decay_partial": _config.SCORE_DECAY_PARTIAL,
                "post_reboot_grace": _config.POST_REBOOT_GRACE,
                "reboot_cooldown": _config.REBOOT_COOLDOWN,
                "max_reboot_cooldown": _config.MAX_REBOOT_COOLDOWN,
                "max_reboots_per_day": _config.MAX_REBOOTS_PER_DAY,
                "usg_reboot_wait": _config.USG_REBOOT_WAIT,
                "usg_ip": _config.USG_IP,
                "instance_priority": _config.INSTANCE_PRIORITY,
                "peer_ip": _config.PEER_IP or "(standalone)",
                "peer_port": _config.PEER_PORT,
                "http_port": _config.HTTP_PORT,
                "peer_takeover_delay": _config.PEER_TAKEOVER_DELAY,
                "ping_targets": _config.PING_TARGETS,
                "ping_timeout": _config.PING_TIMEOUT,
                "isp_outage_detection_delay": _config.ISP_OUTAGE_DETECTION_DELAY,
            }
            self._respond_json(200, cfg)

        def _handle_isp_status(self) -> None:
            """Return latest ISP status check results."""
            snapshot = holder.state
            if snapshot is None:
                self._respond_json(503, {"error": "not ready"})
                return
            self._respond_json(
                200,
                {
                    "checked": snapshot.isp_status_checked,
                    "any_incident": snapshot.isp_status_any_incident,
                    "summary": snapshot.isp_status_summary,
                },
            )

        def _handle_get_backup_unifi(self) -> None:
            """Return last backup info."""
            from backup_unifi import is_configured, find_latest_backup, check_backup_age

            if not is_configured():
                self._respond_json(200, {"configured": False})
                return
            latest = find_latest_backup()
            if latest is None:
                self._respond_json(200, {"configured": True, "latest": None})
                return
            is_stale, age_hours = check_backup_age(latest)
            self._respond_json(
                200,
                {
                    "configured": True,
                    "latest": latest.name,
                    "size_bytes": latest.stat().st_size,
                    "size_mb": round(latest.stat().st_size / (1024 * 1024), 1),
                    "age_hours": age_hours,
                    "stale": is_stale,
                },
            )

        def _handle_backup_unifi(self) -> None:
            """Force a backup via API."""
            from backup_unifi import is_configured, run_backup

            if not is_configured():
                self._respond_json(200, {"ok": False, "error": "not configured"})
                return
            result = run_backup(source="api")
            self._respond_json(200, {"ok": result.ok, **result.to_dict()})

        _EXPORT_SAFE_KEYS = frozenset(
            {
                "CHECK_INTERVAL",
                "REBOOT_SCORE_THRESHOLD",
                "MAX_SCORE",
                "SCORE_GATEWAY_DOWN",
                "SCORE_INTERNET_ALL_DOWN",
                "SCORE_INTERNET_PARTIAL",
                "SCORE_DECAY_OK",
                "SCORE_DECAY_PARTIAL",
                "POST_REBOOT_GRACE",
                "REBOOT_COOLDOWN",
                "MAX_REBOOT_COOLDOWN",
                "MAX_REBOOTS_PER_DAY",
                "PING_TARGETS",
                "PING_TIMEOUT",
                "INSTANCE_PRIORITY",
                "HTTP_PORT",
                "PEER_PORT",
                "PEER_TAKEOVER_DELAY",
                "DAILY_REPORT_HOUR",
                "WEEKLY_REPORT_DAY",
                "DDNS_CHECK_INTERVAL",
                "LOG_LEVEL",
                "ISP_OUTAGE_DETECTION_DELAY",
                "ALERT_ESCALATION_DELAY",
            }
        )

        def _handle_export_config(self) -> None:
            """Export safe config + events as JSON backup."""
            from datetime import datetime as dt

            snapshot = holder.state
            export = {
                "version": snapshot.version if snapshot else "unknown",
                "exported_at": dt.now().isoformat(),
                "config": {},
                "events": event_log.get_all() if event_log else [],
            }
            for key in self._EXPORT_SAFE_KEYS:
                val = getattr(_config, key, None)
                if val is not None:
                    export["config"][key] = val
            self._respond_json(200, export)

        _SAFE_RELOAD_KEYS = frozenset(
            {
                "CHECK_INTERVAL",
                "REBOOT_SCORE_THRESHOLD",
                "MAX_SCORE",
                "SCORE_GATEWAY_DOWN",
                "SCORE_INTERNET_ALL_DOWN",
                "SCORE_INTERNET_PARTIAL",
                "SCORE_DECAY_OK",
                "SCORE_DECAY_PARTIAL",
                "POST_REBOOT_GRACE",
                "REBOOT_COOLDOWN",
                "MAX_REBOOT_COOLDOWN",
                "MAX_REBOOTS_PER_DAY",
                "LOG_LEVEL",
                "DAILY_REPORT_HOUR",
                "WEEKLY_REPORT_DAY",
                "DDNS_CHECK_INTERVAL",
                "PING_TIMEOUT",
            }
        )

        def _handle_config_reload(self) -> None:
            """Reload safe tuning parameters from .env file."""
            import importlib

            try:
                env_path = _config._resolve_install_path(
                    "/opt/vigil/.env", "/opt/usg-watchdog/.env"
                )
                import os

                reloaded = []
                if os.path.exists(env_path):
                    with open(env_path) as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, _, value = line.partition("=")
                                key = key.strip()
                                if key in self._SAFE_RELOAD_KEYS:
                                    os.environ[key] = (
                                        value.strip().strip('"').strip("'")
                                    )
                                    reloaded.append(key)
                importlib.reload(_config)
                self._respond_json(200, {"ok": True, "reloaded": reloaded})
            except Exception:
                self._respond_json(500, {"ok": False, "error": "reload failed"})

        def _handle_tailscale_sync(self) -> None:
            """Force Tailscale DNS sync."""
            from tailscale_dns import sync_tailscale_dns, is_configured

            if not is_configured():
                self._respond_json(200, {"ok": False, "error": "not configured"})
                return
            result = sync_tailscale_dns(force=True)
            if result is None:
                self._respond_json(200, {"ok": False, "error": "sync failed"})
                return
            self._respond_json(200, {"ok": result.ok, **result.to_dict()})

        def _handle_ddns_update(self) -> None:
            """Force a DDNS update."""
            from ddns_cloudflare import check_and_update, is_configured

            if not is_configured():
                self._respond_json(200, {"ok": False, "error": "DDNS not configured"})
                return
            result = check_and_update(force=True)
            if result is None:
                self._respond_json(200, {"ok": False, "error": "IP detection failed"})
                return
            self._respond_json(200, {"ok": True, **result.to_dict()})

        def _handle_get_maintenance(self) -> None:
            """Return current maintenance windows."""
            snapshot = holder.state
            maint = {
                "surveillance_only": snapshot.surveillance_only if snapshot else False,
                "info": 'POST /api/maintenance avec JSON {"duration_minutes": N} pour programmer une pause',
            }
            self._respond_json(200, maint)

        def _handle_post_maintenance(self) -> None:
            """Schedule a maintenance pause."""
            try:
                MAX_BODY = 8192
                content_length = min(
                    int(self.headers.get("Content-Length", 0)), MAX_BODY
                )
                body = (
                    self.rfile.read(content_length).decode("utf-8")
                    if content_length > 0
                    else "{}"
                )
                data = json.loads(body)
                duration_min = int(data.get("duration_minutes", 60))
                duration_min = max(1, min(duration_min, 1440))  # 1 min to 24h
            except (json.JSONDecodeError, ValueError, TypeError):
                self._respond_json(
                    400, {"error": 'JSON invalide. Format: {"duration_minutes": 60}'}
                )
                return

            # Send pause command + schedule resume via a maintenance command
            holder.send_command(f"maintenance:{duration_min}")
            self._respond_json(
                200,
                {
                    "ok": True,
                    "command": "maintenance",
                    "duration_minutes": duration_min,
                },
            )

        def _handle_metrics(self) -> None:
            """Prometheus exposition format."""
            body = render_metrics(holder.state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_report(self) -> None:
            """Generate and return today's report."""
            snapshot = holder.state
            report = generate_daily_report(
                event_log=event_log
                if event_log
                else EventLog(max_events=0, persist_path="/dev/null"),
                uptime_seconds=snapshot.uptime_seconds if snapshot else 0,
                current_score=snapshot.failure_score if snapshot else 0,
                peer_status=snapshot.peer_status if snapshot else "unknown",
            )
            self._respond_json(200, report)

        # ------------------------------------------------------------------
        # /api/tplink/* -- equipements TP-Link pilotables (A1, Sprint 3).
        #
        # C19 (critique) : authentifie aussi les GET -- divergence assumee
        # avec /api/state et /api/events qui restent ouverts. Fail closed :
        # API_TOKEN absent => 403 partout, meme sans equipement declare
        # (_check_auth() le garantit deja, reutilise ici tel quel).
        # ------------------------------------------------------------------

        def _tplink_path_parts(self) -> list[str]:
            path = self.path.split("?", 1)[0]
            return [p for p in path.split("/") if p]

        def _handle_tplink_get(self) -> None:
            if not self._check_auth():
                return
            import managed_devices

            parts = self._tplink_path_parts()
            # ['api', 'tplink'] | ['api','tplink','<id>'] | ['api','tplink','<id>','status']
            if len(parts) == 2:
                self._respond_json(200, managed_devices.registry.list_devices())
                return
            if len(parts) == 3 or (len(parts) == 4 and parts[3] == "status"):
                device_id = parts[2]
                status = managed_devices.registry.get_status(device_id)
                if status is None:
                    self._respond_json(404, {"error": "equipement inconnu"})
                    return
                self._respond_json(200, status)
                return
            self._respond_json(404, {"error": "not found"})

        def _read_json_body(self, max_bytes: int = 8192) -> dict:
            try:
                content_length = min(
                    int(self.headers.get("Content-Length", 0)), max_bytes
                )
                raw = (
                    self.rfile.read(content_length).decode("utf-8")
                    if content_length > 0
                    else "{}"
                )
                data = json.loads(raw)
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, ValueError, TypeError):
                return {}

        def _handle_tplink_post(self) -> None:
            # Auth deja verifiee par do_POST (_check_auth appelle avant tout
            # dispatch) -- meme garantie fail-closed que les GET ci-dessus.
            import managed_devices

            parts = self._tplink_path_parts()
            if len(parts) == 4 and parts[3] == "check":
                device_id = parts[2]
                result = managed_devices.registry.check(device_id)
                if result is None:
                    self._respond_json(404, {"error": "equipement inconnu"})
                    return
                self._respond_json(200, result)
                return

            if len(parts) == 4 and parts[3] == "reboot":
                device_id = parts[2]
                result = managed_devices.registry.request_reboot(
                    device_id, origin="api"
                )
                if result is None:
                    self._respond_json(404, {"error": "equipement inconnu"})
                    return
                self._respond_json(
                    400,
                    {
                        "error": "confirmation requise",
                        "token": result["token"],
                        "label": result["label"],
                        "warning": result["warning"],
                        "warning_reason": result["warning_reason"],
                        "confirm_endpoint": f"/api/tplink/{device_id}/reboot/confirm",
                        "confirm_body": {"token": result["token"]},
                    },
                )
                return

            if len(parts) == 5 and parts[3] == "reboot" and parts[4] == "confirm":
                device_id = parts[2]
                body = self._read_json_body()
                token = str(body.get("token", "")).strip()
                if not token:
                    self._respond_json(
                        400,
                        {
                            "error": 'corps attendu : {"token": "<jeton recu via POST /reboot>"}'
                        },
                    )
                    return
                result = managed_devices.registry.confirm_reboot(
                    token, origin="api", expected_device_id=device_id
                )
                status_code = 200 if result.get("executed") else 400
                self._respond_json(status_code, result)
                return

            self._respond_json(404, {"error": "not found"})

        # ------------------------------------------------------------------
        # POST /api/confirm/<action>/<jeton> -- endpoint de confirmation a
        # capacite (Ntfy-first S2, coeur securite du PRD). Seul endpoint POST
        # sans _check_auth() : le jeton EST l'autorisation. Ne fait qu'une
        # chose : resoudre une confirmation deja en attente, creee par Vigil
        # lui-meme. N'expose aucun etat, n'accepte aucun parametre de
        # l'appelant au-dela de `action`/`jeton` dans le chemin (la query
        # string, si presente, est ignoree -- jamais lue).
        # ------------------------------------------------------------------

        _CONFIRM_PREFIX = "/api/confirm/"

        def _handle_confirm_action(self) -> None:
            path = self.path.split("?", 1)[0]
            remainder = path[len(self._CONFIRM_PREFIX) :]
            parts = [p for p in remainder.split("/") if p]
            client_ip = self.client_address[0]

            # Forme stricte : exactement deux segments (action, jeton). Ni
            # plus (pas de sous-ressource), ni moins.
            if len(parts) != 2:
                self._respond_json(404, {"error": "unknown or expired"})
                return

            action, token = parts

            # D3 -- rate limiting : au-dela de N echecs/minute/IP, 429 +
            # evenement `confirm_bruteforce`, sans meme tenter de valider le
            # jeton presente (evite de gaspiller un essai de bruteforce
            # supplementaire sur l'espace de jetons en attente).
            if (
                _confirm_prune_and_count(client_ip)
                >= _config.CONFIRM_RATE_LIMIT_MAX_FAILURES
            ):
                if event_log is not None:
                    event_log.record("confirm_bruteforce", action=action, ip=client_ip)
                self._respond_json(429, {"error": "too many attempts"})
                return

            import confirm as _confirm
            import managed_devices

            success = False
            if action == managed_devices.CONFIRM_ACTION_REBOOT:
                # Delegue entierement a confirm_reboot() (qui appelle
                # confirm.validate() avec l'action canonique en interne) --
                # ne PAS appeler confirm.validate() ici en plus : le pop est
                # inconditionnel (usage unique), un second appel sur le meme
                # jeton echouerait toujours a tort.
                result = managed_devices.registry.confirm_reboot(token, origin="ntfy")
                success = bool(result.get("executed")) and bool(result.get("ok"))
            else:
                # "cancel" et toute action non geree ici : aucune execution
                # possible (seul CONFIRM_ACTION_REBOOT a une contrepartie
                # d'execution aujourd'hui), mais on consomme quand meme le
                # jeton si un existe pour cette action precise -- usage
                # unique deja garanti par confirm.validate() (pop
                # inconditionnel). C'est ce qui rend le bouton "Annuler"
                # efficace : il invalide silencieusement la confirmation en
                # attente sans jamais l'executer, meme si la reponse HTTP
                # reste un echec generique (D6).
                _confirm.validate(token, action)
                success = False

            if success:
                if event_log is not None:
                    event_log.record("confirm_accepted", action=action, ip=client_ip)
                self._respond_json(200, {"ok": True})
            else:
                _confirm_record_failure(client_ip)
                if event_log is not None:
                    event_log.record("confirm_rejected", action=action, ip=client_ip)
                # D6 -- reponse muette : jamais de detail sur l'existence du
                # jeton, l'action visee ou l'equipement concerne. Meme code
                # et meme corps pour "jeton inconnu", "expire", "deja
                # utilise" et "mauvaise action" (voir PRD S4.2.2/D6 et
                # sprint spec -- 404 retenu, coherent avec les criteres
                # d'acceptation du sprint).
                self._respond_json(404, {"error": "unknown or expired"})

        def _respond_text(self, content_type: str, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _respond_json(self, status: int, data: object) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            # D4 -- le jeton de confirmation ne doit jamais atteindre un
            # fichier de log, meme en LOG_LEVEL=DEBUG : masquage applique ICI
            # (pas chez l'appelant) pour couvrir tous les chemins d'acces a
            # log_message (BaseHTTPRequestHandler l'appelle aussi pour les
            # erreurs de parsing de requete, avant tout dispatch applicatif).
            formatted = format % args
            masked = _CONFIRM_LOG_MASK_RE.sub(r"\1***", formatted)
            logging.debug("HTTP: %s", masked)

    return Handler


def _publish_confirm_actions(
    label: str,
    warning: bool,
    warning_reason: str | None,
    action: str,
    token: str,
) -> bool:
    """Pont vers `notifier._ntfy.send_confirm_actions()` -- injecte dans
    `managed_devices.registry` en tant que fonction `send` (meme pattern que
    `send=telegram_bot.send_message` pour `_adapt_for_telegram`), pour que
    `managed_devices.py` reste agnostique du canal (jamais d'import direct de
    `_ntfy` la-bas). No-op si Ntfy n'est pas configure. Ne leve jamais."""
    try:
        from notifier import _ntfy

        if not _ntfy.is_configured():
            return False
        return _ntfy.send_confirm_actions(
            label=label,
            warning=warning,
            warning_reason=warning_reason,
            action=action,
            token=token,
        )
    except Exception as e:
        logging.warning("Ntfy: echec publication des boutons de confirmation -- %s", e)
        return False


def start_http_server(
    holder: StateHolder,
    port: int,
    event_log: EventLog | None = None,
    history: HistoryBuffer | None = None,
) -> threading.Thread | None:
    """Start the HTTP state server in a background daemon thread.

    Returns the thread on success, None if the port is unavailable.
    Never raises.
    """
    try:
        handler_class = _make_handler_class(holder, event_log, history)
        server = ThreadingHTTPServer(("0.0.0.0", port), handler_class)
        server.timeout = 10
    except OSError as e:
        logging.error(
            "HTTP server: impossible de binder le port %d -- %s "
            "(watchdog continue en mode standalone)",
            port,
            e,
        )
        return None

    # D5 -- API_TOKEN vide est deja fail-closed (_check_auth renvoie 403),
    # mais si un canal a boutons d'action (Ntfy) est configure, un
    # API_TOKEN absent merite un CRITICAL au demarrage : les autres
    # endpoints POST (pause/resume/reboot/tplink/...) resteront inutilisables
    # en pratique tant qu'il n'est pas positionne. Meme esprit que le
    # garde-fou "aucun canal configure" du sprint 1 (watchdog.py, PRD S6.4),
    # branche ici plutot que duplique car watchdog.py est intouchable pour
    # ce sprint (voir INVARIANTS.md) et start_http_server() est le point
    # d'entree HTTP le plus proche d'un "demarrage".
    if not _config.API_TOKEN:
        from notifier import _ntfy

        if _ntfy.is_configured():
            logging.critical(
                "API_TOKEN non configure alors que Ntfy (boutons d'action) "
                "est actif -- les boutons de confirmation publies resteront "
                "utilisables (jeton = autorisation), mais tous les autres "
                "endpoints POST (pause/resume/reboot/tplink/...) resteront "
                "fermes (403) tant qu'API_TOKEN n'est pas positionne"
            )

    # Wiring des equipements TP-Link pilotables (A1, Sprint 3) : l'event_log
    # de production est deja disponible ici (passe par watchdog.py) --
    # c'est le seul point d'entree qui permet de le relier au registre sans
    # toucher a watchdog.py (INTOUCHABLE, voir INVARIANTS.md). Idempotent,
    # ne construit aucun driver (C1) tant qu'aucun equipement n'est declare.
    import managed_devices

    managed_devices.bootstrap(event_log)
    # Ntfy-first S2 : boutons Actions (confirmer/annuler) publies en
    # parallele du chemin Telegram existant, jamais a sa place -- voir
    # managed_devices.request_reboot().
    managed_devices.registry.set_ntfy_send(_publish_confirm_actions)

    thread = threading.Thread(
        target=server.serve_forever,
        name="http-state-server",
        daemon=True,
    )
    thread.start()
    logging.info("HTTP state server (threading) demarre sur le port %d", port)
    return thread
