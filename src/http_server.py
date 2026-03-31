"""Background HTTP server exposing watchdog state, health, and event history."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from state import StateHolder, CMD_PAUSE, CMD_RESUME, CMD_REBOOT
from events import EventLog
from dashboard import DASHBOARD_HTML
from report import generate_daily_report, calculate_monthly_sla
from metrics import render_metrics
from history import HistoryBuffer
from pwa import MANIFEST_JSON, SERVICE_WORKER_JS

import config as _config


def _make_handler_class(
    holder: StateHolder,
    event_log: EventLog | None = None,
    history: HistoryBuffer | None = None,
) -> type:
    """Create a request handler class with access to shared state."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                if self.path == "/" or self.path == "/dashboard":
                    self._handle_dashboard()
                elif self.path == "/manifest.json":
                    self._respond_text("application/manifest+json", MANIFEST_JSON)
                elif self.path == "/sw.js":
                    self._respond_text("application/javascript", SERVICE_WORKER_JS)
                elif self.path == "/health":
                    self._handle_health()
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
                elif self.path == "/api/backup/config":
                    self._handle_export_config()
                elif self.path == "/metrics":
                    self._handle_metrics()
                elif self.path == "/api/report":
                    self._handle_report()
                else:
                    self._respond_json(404, {"error": "not found"})
            except Exception:
                self._respond_json(500, {"error": "internal error"})

        def _check_auth(self) -> bool:
            """Check API token if configured. Returns True if authorized."""
            if not _config.API_TOKEN:
                return True  # no auth configured
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {_config.API_TOKEN}":
                return True
            self._respond_json(401, {"error": "unauthorized"})
            return False

        def do_POST(self) -> None:
            try:
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
                elif self.path == "/api/backup/unifi":
                    self._handle_backup_unifi()
                elif self.path == "/api/maintenance":
                    self._handle_post_maintenance()
                elif self.path == "/api/config/reload":
                    self._handle_config_reload()
                else:
                    self._respond_json(404, {"error": "not found"})
            except Exception:
                self._respond_json(500, {"error": "internal error"})

        def _handle_dashboard(self) -> None:
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_health(self) -> None:
            snapshot = holder.state
            if snapshot is None:
                self._respond_json(503, {"status": "starting"})
                return

            # Determine overall status
            if snapshot.surveillance_only:
                status = "surveillance"
            elif snapshot.failure_score >= snapshot.threshold:
                status = "critical"
            elif snapshot.failure_score > 0:
                status = "degraded"
            else:
                status = "healthy"

            health = {
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
                    "gateway_ms": round(snapshot.gateway_rtt_ms, 1) if snapshot.gateway_rtt_ms is not None else None,
                    "internet_avg_ms": round(snapshot.internet_avg_rtt_ms, 1) if snapshot.internet_avg_rtt_ms is not None else None,
                    "degraded": snapshot.latency_degraded,
                },
                "version": snapshot.version,
                "peer": {
                    "status": snapshot.peer_status,
                    "score": snapshot.peer_score,
                    "gateway": snapshot.peer_gateway,
                    "internet": snapshot.peer_internet,
                },
            }
            self._respond_json(200, health)

        def _handle_state(self) -> None:
            snapshot = holder.state
            if snapshot is None:
                self._respond_json(503, {"error": "not ready"})
                return
            self._respond_json(200, snapshot.to_dict())

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
            self._respond_json(200, {
                "configured": True,
                "latest": latest.name,
                "size_bytes": latest.stat().st_size,
                "size_mb": round(latest.stat().st_size / (1024 * 1024), 1),
                "age_hours": age_hours,
                "stale": is_stale,
            })

        def _handle_backup_unifi(self) -> None:
            """Force a backup via API."""
            from backup_unifi import is_configured, run_backup
            if not is_configured():
                self._respond_json(200, {"ok": False, "error": "not configured"})
                return
            result = run_backup(source="api")
            self._respond_json(200, {"ok": result.ok, **result.to_dict()})

        _EXPORT_SAFE_KEYS = frozenset({
            "CHECK_INTERVAL", "REBOOT_SCORE_THRESHOLD", "MAX_SCORE",
            "SCORE_GATEWAY_DOWN", "SCORE_INTERNET_ALL_DOWN", "SCORE_INTERNET_PARTIAL",
            "SCORE_DECAY_OK", "SCORE_DECAY_PARTIAL", "POST_REBOOT_GRACE",
            "REBOOT_COOLDOWN", "MAX_REBOOT_COOLDOWN", "MAX_REBOOTS_PER_DAY",
            "PING_TARGETS", "PING_TIMEOUT", "INSTANCE_PRIORITY",
            "HTTP_PORT", "PEER_PORT", "PEER_TAKEOVER_DELAY",
            "DAILY_REPORT_HOUR", "WEEKLY_REPORT_DAY",
            "DDNS_CHECK_INTERVAL", "LOG_LEVEL",
            "ISP_OUTAGE_DETECTION_DELAY", "ALERT_ESCALATION_DELAY",
        })

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

        _SAFE_RELOAD_KEYS = frozenset({
            "CHECK_INTERVAL", "REBOOT_SCORE_THRESHOLD", "MAX_SCORE",
            "SCORE_GATEWAY_DOWN", "SCORE_INTERNET_ALL_DOWN", "SCORE_INTERNET_PARTIAL",
            "SCORE_DECAY_OK", "SCORE_DECAY_PARTIAL", "POST_REBOOT_GRACE",
            "REBOOT_COOLDOWN", "MAX_REBOOT_COOLDOWN", "MAX_REBOOTS_PER_DAY",
            "LOG_LEVEL", "DAILY_REPORT_HOUR", "WEEKLY_REPORT_DAY",
            "DDNS_CHECK_INTERVAL", "PING_TIMEOUT",
        })

        def _handle_config_reload(self) -> None:
            """Reload safe tuning parameters from .env file."""
            import importlib
            try:
                env_path = "/opt/usg-watchdog/.env"
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
                                    os.environ[key] = value.strip().strip('"').strip("'")
                                    reloaded.append(key)
                importlib.reload(_config)
                self._respond_json(200, {"ok": True, "reloaded": reloaded})
            except Exception:
                self._respond_json(500, {"ok": False, "error": "reload failed"})

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
                "info": "POST /api/maintenance avec JSON {\"duration_minutes\": N} pour programmer une pause",
            }
            self._respond_json(200, maint)

        def _handle_post_maintenance(self) -> None:
            """Schedule a maintenance pause."""
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                data = json.loads(body)
                duration_min = int(data.get("duration_minutes", 60))
                duration_min = max(1, min(duration_min, 1440))  # 1 min to 24h
            except (json.JSONDecodeError, ValueError, TypeError):
                self._respond_json(400, {"error": "JSON invalide. Format: {\"duration_minutes\": 60}"})
                return

            # Send pause command + schedule resume via a maintenance command
            holder.send_command(f"maintenance:{duration_min}")
            self._respond_json(200, {
                "ok": True,
                "command": "maintenance",
                "duration_minutes": duration_min,
            })

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
                event_log=event_log if event_log else EventLog(max_events=0, persist_path="/dev/null"),
                uptime_seconds=snapshot.uptime_seconds if snapshot else 0,
                current_score=snapshot.failure_score if snapshot else 0,
                peer_status=snapshot.peer_status if snapshot else "unknown",
            )
            self._respond_json(200, report)

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
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            logging.debug("HTTP: %s", format % args)

    return Handler


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
        server = HTTPServer(("0.0.0.0", port), handler_class)
    except OSError as e:
        logging.error(
            "HTTP server: impossible de binder le port %d -- %s "
            "(watchdog continue en mode standalone)", port, e
        )
        return None

    thread = threading.Thread(
        target=server.serve_forever,
        name="http-state-server",
        daemon=True,
    )
    thread.start()
    logging.info("HTTP state server demarre sur le port %d", port)
    return thread
