"""Dashboard HTML template -- inline HTML/CSS/JS, zero external dependencies."""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>USG Watchdog</title>
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
</style>
</head>
<body>
<div class="container">
  <h1>USG Watchdog</h1>
  <div id="error-banner" class="error-banner"></div>

  <div class="controls">
    <button id="btn-pause" class="btn" onclick="sendCommand('pause')">Pause</button>
    <button id="btn-resume" class="btn" onclick="sendCommand('resume')" style="display:none">Resume</button>
    <button id="btn-reboot" class="btn btn-danger" onclick="confirmReboot()">Reboot USG</button>
    <span id="cmd-feedback" class="btn-feedback"></span>
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
  </div>

  <div class="footer">
    Auto-refresh 30s | <span id="last-update">-</span>
  </div>
</div>

<script>
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

    // Events
    var ul = document.getElementById('events-list');
    if (events.length === 0) {
      ul.innerHTML = '<li><span class="event-data">Aucun evenement</span></li>';
    } else {
      ul.innerHTML = events.reverse().map(function(e) {
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

  } catch(err) {
    banner.textContent = 'Erreur de connexion : ' + err.message;
    banner.style.display = 'block';
  }
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

async function sendCommand(cmd) {
  var feedback = document.getElementById('cmd-feedback');
  try {
    var res = await fetch('/api/' + cmd, { method: 'POST' });
    var data = await res.json();
    if (data.ok) {
      feedback.textContent = cmd + ' OK';
      feedback.style.display = 'inline';
      setTimeout(function() { feedback.style.display = 'none'; }, 3000);
      setTimeout(refresh, 1000);
    }
  } catch(err) {
    feedback.textContent = 'Erreur: ' + err.message;
    feedback.style.color = '#f85149';
    feedback.style.display = 'inline';
  }
}

function confirmReboot() {
  if (confirm('Rebooter le USG maintenant ?')) {
    sendCommand('reboot');
  }
}

refresh();
refreshCharts();
setInterval(refresh, 30000);
setInterval(refreshCharts, 30000);

// Register service worker for PWA
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(function() {});
}
</script>
</body>
</html>
"""
