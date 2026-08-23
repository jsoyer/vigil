"""Dashboard HTML template -- inline HTML/CSS/JS, zero external dependencies."""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#58a6ff">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
  background: #0f1117;
  color: #e1e4e8;
  min-height: 100vh;
  padding: 1rem;
}
.container { max-width: 800px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin-bottom: 1rem; color: #58a6ff; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1rem; }
@media (max-width: 500px) { .grid { grid-template-columns: 1fr; } }
.card {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 1rem;
}
.card-title { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
.card-value { font-size: 1.8rem; font-weight: 700; }
.card-sub { font-size: 0.8rem; color: #8b949e; margin-top: 0.25rem; }

/* Score gauge */
.gauge-wrap { text-align: center; }
.gauge-bar {
  width: 100%;
  height: 12px;
  background: #21262d;
  border-radius: 6px;
  overflow: hidden;
  margin-top: 0.5rem;
}
.gauge-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.5s ease, background 0.5s ease;
}

/* Status badge */
.badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 600;
}
.badge-healthy { background: #238636; color: #fff; }
.badge-degraded { background: #d29922; color: #000; }
.badge-critical { background: #da3633; color: #fff; }
.badge-surveillance { background: #6e40c9; color: #fff; }
.badge-starting { background: #30363d; color: #8b949e; }
.badge-ok { background: #238636; color: #fff; }
.badge-ko { background: #da3633; color: #fff; }

/* Events table */
.events-card { grid-column: 1 / -1; }
.events-list { list-style: none; max-height: 400px; overflow-y: auto; }
.events-list li {
  padding: 0.5rem 0;
  border-bottom: 1px solid #21262d;
  font-size: 0.85rem;
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
}
.events-list li:last-child { border-bottom: none; }
.event-time { color: #8b949e; font-size: 0.75rem; white-space: nowrap; min-width: 5.5rem; }
.event-type {
  display: inline-block;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  min-width: 5rem;
  text-align: center;
}
.event-type-reboot { background: #da363322; color: #f85149; }
.event-type-reboot_failed { background: #da363322; color: #f85149; }
.event-type-recovery { background: #23863622; color: #3fb950; }
.event-type-isp_outage { background: #d2992222; color: #d29922; }
.event-type-isp_recovery { background: #23863622; color: #3fb950; }
.event-type-peer_standdown { background: #6e40c922; color: #bc8cff; }
.event-type-ssh_backoff { background: #d2992222; color: #d29922; }
.event-type-max_reboots { background: #da363322; color: #f85149; }
.event-type-startup { background: #58a6ff22; color: #58a6ff; }
.event-type-shutdown { background: #30363d; color: #8b949e; }
.event-type-divergence { background: #d2992222; color: #d29922; }
.event-type-surveillance_off { background: #23863622; color: #3fb950; }
.event-type-api_pause { background: #6e40c922; color: #bc8cff; }
.event-type-api_resume { background: #23863622; color: #3fb950; }
.event-type-api_reboot { background: #da363322; color: #f85149; }
.event-data { color: #8b949e; font-size: 0.8rem; }

.chart { background: #0d1117; border-radius: 4px; }

.controls { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
.btn {
  padding: 0.5rem 1rem;
  border: 1px solid #30363d;
  border-radius: 6px;
  background: #21262d;
  color: #e1e4e8;
  cursor: pointer;
  font-size: 0.85rem;
  font-family: inherit;
  transition: background 0.2s;
}
.btn:hover { background: #30363d; }
.btn-danger { border-color: #da3633; color: #f85149; }
.btn-danger:hover { background: #da363333; }
.btn-active { border-color: #d29922; color: #d29922; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-feedback {
  font-size: 0.75rem;
  color: #3fb950;
  margin-left: 0.5rem;
  display: none;
}

.footer { text-align: center; color: #484f58; font-size: 0.75rem; margin-top: 1rem; }
.conn-badge {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 8px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  vertical-align: middle;
  margin-left: 0.4rem;
}
.conn-live { background: #23863644; color: #3fb950; border: 1px solid #238636; }
.conn-polling { background: #d2992222; color: #d29922; border: 1px solid #d29922; }
.error-banner {
  background: #da363322;
  border: 1px solid #da3633;
  color: #f85149;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  display: none;
  font-size: 0.85rem;
}

.token-prompt {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}
.token-prompt-msg {
  width: 100%;
  color: #f85149;
  font-size: 0.85rem;
  display: none;
}
.token-input {
  flex: 1;
  min-width: 200px;
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  border: 1px solid #30363d;
  background: #0d1117;
  color: #e1e4e8;
  font-family: inherit;
  font-size: 0.85rem;
}

.tplink-item { padding: 0.6rem 0; border-bottom: 1px solid #21262d; }
.tplink-item:last-child { border-bottom: none; }
.tplink-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.tplink-label { font-weight: 600; margin-right: 0.25rem; }
</style>
</head>
<body>
<div class="container">
  <h1>Vigil</h1>
  <div id="error-banner" class="error-banner"></div>

  <div id="token-prompt" class="token-prompt" style="display:none">
    <div id="token-prompt-msg" class="token-prompt-msg"></div>
    <input type="password" id="api-token-input" class="token-input" placeholder="Jeton API (Authorization Bearer)">
    <button id="btn-save-token" class="btn" onclick="saveTokenFromInput()">Enregistrer le jeton</button>
  </div>

  <div class="controls">
    <button id="btn-pause" class="btn" onclick="sendCommand('pause')">Pause</button>
    <button id="btn-resume" class="btn" onclick="sendCommand('resume')" style="display:none">Resume</button>
    <button id="btn-reboot" class="btn btn-danger" onclick="confirmReboot()">Reboot USG</button>
    <span id="cmd-feedback" class="btn-feedback"></span>
  </div>

  <div class="controls" id="actions-section">
    <button id="btn-ddns" class="btn" onclick="runAction('/api/ddns/update', 'action-feedback', 'DDNS')">DDNS</button>
    <button id="btn-backup" class="btn" onclick="runAction('/api/backup/unifi', 'action-feedback', 'Backup UniFi')">Backup UniFi</button>
    <button id="btn-tailscale" class="btn" onclick="runAction('/api/tailscale/sync', 'action-feedback', 'Sync Tailscale')">Sync Tailscale</button>
    <button id="btn-maintenance" class="btn" onclick="runAction('/api/maintenance', 'action-feedback', 'Maintenance')">Maintenance</button>
    <span id="action-feedback" class="btn-feedback"></span>
  </div>

  <div class="grid">
    <!-- Status -->
    <div class="card">
      <div class="card-title">Status</div>
      <div class="card-value"><span id="status-badge" class="badge badge-starting">...</span></div>
      <div class="card-sub">Priority <span id="priority">-</span> | Uptime <span id="uptime">-</span></div>
    </div>

    <!-- Score gauge -->
    <div class="card gauge-wrap">
      <div class="card-title">Score</div>
      <div class="card-value"><span id="score">-</span> / <span id="threshold">-</span></div>
      <div class="gauge-bar"><div id="gauge-fill" class="gauge-fill" style="width:0%"></div></div>
    </div>

    <!-- Gateway -->
    <div class="card">
      <div class="card-title">Gateway</div>
      <div class="card-value"><span id="gateway-badge" class="badge badge-starting">...</span></div>
    </div>

    <!-- Internet -->
    <div class="card">
      <div class="card-title">Internet</div>
      <div class="card-value"><span id="internet">-</span></div>
    </div>

    <!-- Reboots -->
    <div class="card">
      <div class="card-title">Reboots aujourd'hui</div>
      <div class="card-value"><span id="reboots-today">-</span></div>
      <div class="card-sub">Consecutifs: <span id="consecutive-reboots">-</span></div>
    </div>

    <!-- ISP -->
    <div class="card">
      <div class="card-title">ISP</div>
      <div class="card-value"><span id="isp-badge" class="badge badge-ok">OK</span></div>
    </div>

    <!-- Peer -->
    <div class="card" id="peer-card" style="display:none">
      <div class="card-title">Peer</div>
      <div class="card-value"><span id="peer-badge" class="badge badge-starting">...</span></div>
      <div class="card-sub">Score <span id="peer-score">-</span> | GW <span id="peer-gw">-</span> | Net <span id="peer-inet">-</span></div>
    </div>

    <!-- Charts -->
    <div class="card events-card">
      <div class="card-title">Score (2h)</div>
      <svg id="chart-score" width="100%" height="120" class="chart"></svg>
    </div>
    <div class="card events-card">
      <div class="card-title">Latence (2h)</div>
      <svg id="chart-latency" width="100%" height="120" class="chart"></svg>
    </div>

    <!-- Events -->
    <div class="card events-card">
      <div class="card-title">Evenements recents</div>
      <ul id="events-list" class="events-list">
        <li><span class="event-data">Chargement...</span></li>
      </ul>
    </div>

    <!-- TP-Link -->
    <div class="card events-card" id="tplink-card">
      <div class="card-title">TP-Link</div>
      <ul id="tplink-list" class="events-list">
        <li><span class="event-data">Chargement...</span></li>
      </ul>
    </div>
  </div>

  <div class="footer">
    <span id="conn-badge" class="conn-badge conn-polling">POLLING</span> | <span id="last-update">-</span>
  </div>
</div>

<script>
// Note: innerHTML is used only for rendering server-controlled event data
// from our own trusted API -- all fields are typed (event type enum,
// ISO timestamps, numeric/boolean values). No user-supplied input reaches
// these templates. This mirrors the pre-existing pattern in this codebase.
function formatUptime(seconds) {
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'min';
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  return h + 'h' + (m ? (m < 10 ? '0' : '') + m : '');
}

function formatEventTime(ts) {
  try {
    var d = new Date(ts);
    var hh = String(d.getHours()).padStart(2, '0');
    var mm = String(d.getMinutes()).padStart(2, '0');
    var dd = String(d.getDate()).padStart(2, '0');
    var mo = String(d.getMonth() + 1).padStart(2, '0');
    return dd + '/' + mo + ' ' + hh + ':' + mm;
  } catch(e) { return ts; }
}

function formatEventData(data) {
  if (!data || Object.keys(data).length === 0) return '';
  return Object.entries(data).map(function(e) { return e[0] + '=' + e[1]; }).join(' ');
}

function getScoreColor(score, threshold) {
  var pct = score / threshold;
  if (pct >= 1) return '#da3633';
  if (pct >= 0.5) return '#d29922';
  if (pct > 0) return '#58a6ff';
  return '#238636';
}

function getStatusClass(status) {
  return 'badge-' + (status || 'starting');
}

// Update pause/resume buttons based on status
function updateControls(status) {
  var btnPause = document.getElementById('btn-pause');
  var btnResume = document.getElementById('btn-resume');
  if (status === 'surveillance') {
    btnPause.style.display = 'none';
    btnResume.style.display = '';
  } else {
    btnPause.style.display = '';
    btnResume.style.display = 'none';
  }
}

// Set connection indicator badge to LIVE or POLLING
function setConnBadge(live) {
  var badge = document.getElementById('conn-badge');
  if (!badge) return;
  if (live) {
    badge.textContent = 'LIVE';
    badge.className = 'conn-badge conn-live';
  } else {
    badge.textContent = 'POLLING';
    badge.className = 'conn-badge conn-polling';
  }
}

// Core DOM update -- called by both SSE path and polling fallback
function updateDashboard(health, events) {
  var banner = document.getElementById('error-banner');
  banner.style.display = 'none';

  // Status
  var sb = document.getElementById('status-badge');
  sb.textContent = health.status;
  sb.className = 'badge ' + getStatusClass(health.status);

  // Priority + uptime
  document.getElementById('priority').textContent = health.instance_priority;
  document.getElementById('uptime').textContent = formatUptime(health.uptime);

  // Score
  var score = health.score || 0;
  var threshold = health.threshold || 10;
  document.getElementById('score').textContent = score;
  document.getElementById('threshold').textContent = threshold;
  var pct = Math.min(100, Math.round((score / threshold) * 100));
  var fill = document.getElementById('gauge-fill');
  fill.style.width = pct + '%';
  fill.style.background = getScoreColor(score, threshold);

  // Gateway
  var gb = document.getElementById('gateway-badge');
  gb.textContent = health.gateway;
  gb.className = 'badge ' + (health.gateway === 'OK' ? 'badge-ok' : 'badge-ko');

  // Internet
  document.getElementById('internet').textContent = health.internet;

  // Reboots
  document.getElementById('reboots-today').textContent = health.reboots_today;
  document.getElementById('consecutive-reboots').textContent = health.consecutive_reboots;

  // ISP
  var ib = document.getElementById('isp-badge');
  if (health.isp_outage) {
    ib.textContent = 'PANNE';
    ib.className = 'badge badge-critical';
  } else {
    ib.textContent = 'OK';
    ib.className = 'badge badge-ok';
  }

  // Peer
  var peer = health.peer;
  var peerCard = document.getElementById('peer-card');
  if (peer && peer.status !== 'standalone' && peer.status !== 'unknown') {
    peerCard.style.display = '';
    var pb = document.getElementById('peer-badge');
    pb.textContent = peer.status;
    pb.className = 'badge ' + getStatusClass(
      peer.status === 'unreachable' ? 'critical' : peer.status
    );
    document.getElementById('peer-score').textContent = peer.score;
    document.getElementById('peer-gw').textContent = peer.gateway || '-';
    document.getElementById('peer-inet').textContent = peer.internet || '-';
  } else {
    peerCard.style.display = 'none';
  }

  // Events list (server-controlled data only, no user input reaches this path)
  var ul = document.getElementById('events-list');
  if (!events || events.length === 0) {
    ul.innerHTML = '<li><span class="event-data">Aucun evenement</span></li>';
  } else {
    ul.innerHTML = events.slice().reverse().map(function(e) {
      var dataStr = formatEventData(e.data);
      return '<li>' +
        '<span class="event-time">' + formatEventTime(e.ts) + '</span>' +
        '<span class="event-type event-type-' + e.type + '">' + e.type.replace('_', ' ') + '</span>' +
        (dataStr ? '<span class="event-data">' + dataStr + '</span>' : '') +
        '</li>';
    }).join('');
  }

  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('fr-FR');
  updateControls(health.status);
}

// Polling fallback -- fetches /health + /api/events then calls updateDashboard()
async function refresh() {
  var banner = document.getElementById('error-banner');
  try {
    var [healthRes, eventsRes] = await Promise.all([
      fetch('/health'),
      fetch('/api/events?count=30')
    ]);

    if (!healthRes.ok) throw new Error('health ' + healthRes.status);

    var health = await healthRes.json();
    var events = await eventsRes.json();

    updateDashboard(health, events);

  } catch(err) {
    banner.textContent = 'Erreur de connexion : ' + err.message;
    banner.style.display = 'block';
  }
}

// --- SSE connection with automatic reconnection and polling fallback ---
var evtSource = null;
var sseConnected = false;
var pollTimer = null;

function startSSE() {
  if (evtSource) {
    evtSource.close();
    evtSource = null;
  }

  evtSource = new EventSource('/api/stream');

  evtSource.onmessage = function(event) {
    // SSE working -- cancel polling fallback if active
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (!sseConnected) {
      sseConnected = true;
      setConnBadge(true);
    }
    try {
      var payload = JSON.parse(event.data);
      updateDashboard(payload.health, payload.events);
    } catch(e) {
      // Ignore malformed SSE frames
    }
  };

  evtSource.onerror = function() {
    sseConnected = false;
    setConnBadge(false);
    evtSource.close();
    evtSource = null;

    // Activate polling fallback at 5s intervals
    if (!pollTimer) {
      pollTimer = setInterval(refresh, 5000);
    }

    // Retry SSE after 30s
    setTimeout(startSSE, 30000);
  };
}

// --- SVG Chart rendering ---
function drawChart(svgId, data, valueKey, color, maxVal) {
  var svg = document.getElementById(svgId);
  if (!svg || !data.length) return;
  var w = svg.clientWidth || 700;
  var h = 120;
  var pad = 2;
  var n = data.length;
  if (n < 2) return;

  // Auto-scale max
  var vals = data.map(function(d) { return d[valueKey] !== null ? d[valueKey] : 0; });
  var autoMax = Math.max.apply(null, vals);
  var yMax = maxVal || Math.max(autoMax * 1.2, 1);

  var stepX = (w - pad * 2) / (n - 1);

  // Build polyline points
  var points = vals.map(function(v, i) {
    var x = pad + i * stepX;
    var y = h - pad - ((v / yMax) * (h - pad * 2));
    return x + ',' + y;
  }).join(' ');

  // Threshold line for score chart
  var threshLine = '';
  if (svgId === 'chart-score') {
    var ty = h - pad - ((10 / yMax) * (h - pad * 2));
    threshLine = '<line x1="' + pad + '" y1="' + ty + '" x2="' + (w-pad) + '" y2="' + ty + '" stroke="#da3633" stroke-width="1" stroke-dasharray="4,4" opacity="0.5"/>';
  }

  svg.innerHTML =
    '<rect width="100%" height="100%" fill="#0d1117" rx="4"/>' +
    threshLine +
    '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="1.5" opacity="0.8"/>';
}

async function refreshCharts() {
  try {
    var res = await fetch('/api/history');
    var data = await res.json();
    if (!data.length) return;
    drawChart('chart-score', data, 'score', '#58a6ff', 15);
    drawChart('chart-latency', data, 'inet_rtt', '#3fb950', null);
  } catch(e) {}
}

// --- API token capture: entered once by the operator, kept in the
// browser tab's short-lived session store ONLY -- no persistence past
// tab close, explicit requirement. The server never embeds the secret in
// this HTML: it is generic/static regardless of the configured value on
// the server side, and is only ever known client-side once typed here.
var TOKEN_STORAGE_KEY = 'vigil_api_token';

function getApiToken() {
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
  } catch(e) {
    return '';
  }
}

function setApiToken(token) {
  try {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch(e) {}
}

function clearApiToken() {
  try {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch(e) {}
}

function showTokenPrompt(message) {
  var wrap = document.getElementById('token-prompt');
  var msg = document.getElementById('token-prompt-msg');
  if (!wrap || !msg) return;
  if (message) {
    msg.textContent = message;
    msg.style.display = 'block';
  } else {
    msg.style.display = 'none';
  }
  wrap.style.display = '';
}

function hideTokenPrompt() {
  var wrap = document.getElementById('token-prompt');
  if (wrap) wrap.style.display = 'none';
}

function saveTokenFromInput() {
  var input = document.getElementById('api-token-input');
  if (!input) return;
  var val = (input.value || '').trim();
  if (!val) return;
  setApiToken(val);
  input.value = '';
  hideTokenPrompt();
  refreshTplink();
}

// Authenticated fetch wrapper used by every POST/GET command on this
// dashboard -- injects Authorization: Bearer <token> on every call, and
// surfaces a clear, visible message (never a silent failure) on 401.
async function apiRequest(path, method, body) {
  var token = getApiToken();
  if (!token) {
    showTokenPrompt('Jeton API requis -- saisissez-le ci-dessus pour utiliser les commandes.');
    throw new Error('jeton API manquant');
  }
  var opts = {
    method: method || 'POST',
    headers: { 'Authorization': 'Bearer ' + token }
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  var res = await fetch(path, opts);
  if (res.status === 401) {
    clearApiToken();
    showTokenPrompt('Jeton invalide ou expire (401) -- merci de le re-saisir ci-dessus.');
    throw new Error('non autorise (401) -- jeton invalide ou expire');
  }
  var data = {};
  try { data = await res.json(); } catch(e) {}
  return { res: res, data: data };
}

async function sendCommand(cmd) {
  await runAction('/api/' + cmd, 'cmd-feedback', cmd);
}

// Generic authenticated action runner -- shared by pause/resume/reboot
// (via sendCommand) and the newer Actions section buttons (DDNS, backup,
// tailscale, maintenance). Always goes through apiRequest() so the
// Authorization header and 401 handling are applied uniformly.
async function runAction(path, feedbackId, label) {
  var feedback = document.getElementById(feedbackId);
  try {
    var result = await apiRequest(path, 'POST');
    var data = result.data;
    if (feedback) {
      if (data && data.ok) {
        feedback.textContent = label + ' OK';
        feedback.style.color = '';
      } else {
        feedback.textContent = label + ': ' + ((data && data.error) || 'echec');
        feedback.style.color = '#f85149';
      }
      feedback.style.display = 'inline';
      setTimeout(function() { feedback.style.display = 'none'; }, 3000);
    }
    setTimeout(refresh, 1000);
  } catch(err) {
    if (feedback) {
      feedback.textContent = 'Erreur: ' + err.message;
      feedback.style.color = '#f85149';
      feedback.style.display = 'inline';
    }
  }
}

function confirmReboot() {
  if (confirm('Rebooter le USG maintenant ?')) {
    sendCommand('reboot');
  }
}

// --- TP-Link section: list + per-device status, check, reboot. Reboot
// reuses the existing two-step confirmation flow already shipped server
// side (POST /reboot then POST /reboot/confirm with the returned token) --
// no new confirmation mechanism is introduced here.
function tplinkFeedbackId(deviceId) {
  return 'tplink-feedback-' + deviceId;
}

function renderTplinkList(devices) {
  var container = document.getElementById('tplink-list');
  if (!container) return;
  if (!devices || !devices.length) {
    container.innerHTML = '<li><span class="event-data">Aucun equipement TP-Link configure</span></li>';
    return;
  }
  container.innerHTML = devices.map(function(d) {
    var id = d.id;
    var reachable = !!d.reachable;
    var badgeClass = reachable ? 'badge-ok' : 'badge-ko';
    var badgeText = reachable ? 'OK' : 'KO';
    return '<li class="tplink-item" id="tplink-item-' + id + '">' +
      '<div class="tplink-row">' +
      '<span class="tplink-label">' + d.label + '</span>' +
      '<span class="badge ' + badgeClass + '">' + badgeText + '</span>' +
      '<button class="btn" onclick="tplinkCheck(\'' + id + '\')">Verifier</button>' +
      '<button class="btn btn-danger" onclick="tplinkReboot(\'' + id + '\')">Redemarrer</button>' +
      '<span id="' + tplinkFeedbackId(id) + '" class="btn-feedback"></span>' +
      '</div>' +
      '</li>';
  }).join('');
}

async function refreshTplink() {
  if (!getApiToken()) return;
  try {
    var result = await apiRequest('/api/tplink', 'GET');
    renderTplinkList(Array.isArray(result.data) ? result.data : []);
  } catch(err) {
    // apiRequest() already surfaced a clear message via showTokenPrompt()
    // on 401; other errors are transient and covered by the next refresh.
  }
}

async function tplinkCheck(deviceId) {
  await runAction('/api/tplink/' + deviceId + '/check', tplinkFeedbackId(deviceId), 'Verifier');
  refreshTplink();
}

async function tplinkReboot(deviceId) {
  var feedback = document.getElementById(tplinkFeedbackId(deviceId));
  try {
    var result = await apiRequest('/api/tplink/' + deviceId + '/reboot', 'POST');
    var data = result.data;
    if (data && data.token) {
      var msg = 'Confirmer le reboot de ' + (data.label || deviceId) + ' ?';
      if (data.warning && data.warning_reason) {
        msg += '\n' + data.warning_reason;
      }
      if (confirm(msg)) {
        await tplinkConfirmReboot(deviceId, data.token);
      }
    } else if (feedback) {
      feedback.textContent = 'Erreur: ' + ((data && data.error) || 'echec');
      feedback.style.color = '#f85149';
      feedback.style.display = 'inline';
    }
  } catch(err) {
    if (feedback) {
      feedback.textContent = 'Erreur: ' + err.message;
      feedback.style.color = '#f85149';
      feedback.style.display = 'inline';
    }
  }
}

async function tplinkConfirmReboot(deviceId, token) {
  var feedback = document.getElementById(tplinkFeedbackId(deviceId));
  try {
    var result = await apiRequest(
      '/api/tplink/' + deviceId + '/reboot/confirm', 'POST', { token: token }
    );
    var data = result.data;
    if (feedback) {
      if (data && data.executed) {
        feedback.textContent = 'Reboot OK';
        feedback.style.color = '';
      } else {
        feedback.textContent = 'Erreur: ' + ((data && data.error) || 'echec');
        feedback.style.color = '#f85149';
      }
      feedback.style.display = 'inline';
      setTimeout(function() { feedback.style.display = 'none'; }, 3000);
    }
    refreshTplink();
  } catch(err) {
    if (feedback) {
      feedback.textContent = 'Erreur: ' + err.message;
      feedback.style.color = '#f85149';
      feedback.style.display = 'inline';
    }
  }
}

// Start SSE connection (primary real-time update path)
startSSE();

// Prompt for the API token up front if not already captured this tab
// session -- every command button needs it (fail-closed server side).
if (!getApiToken()) {
  showTokenPrompt();
}

// Initial data load via polling while SSE handshake is in progress
refresh();
refreshCharts();
refreshTplink();

// TP-Link status polls every 60s -- same cadence as charts, no need for
// real-time updates on router metrics.
setInterval(refreshTplink, 60000);

// Charts poll every 60s -- historical data does not need real-time updates
setInterval(refreshCharts, 60000);

// Register service worker for PWA
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(function() {});
}
</script>
</body>
</html>
"""
