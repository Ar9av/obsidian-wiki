"""Render the session graph as a self-contained interactive HTML page.

Built on the same vis.js template `wiki-export` emits for the vault graph — same
dark theme, same palette, same force layout, same physics-off-after-stabilize
trick — with the deltas a *session* graph needs that a page graph does not:

  * time is a first-class axis (a slider, and recency drives node brightness)
  * two tiers of node, since a thin session can be found but never loaded
  * a search box, because 1000+ nodes is past the point of visual scanning
  * the sidebar hands off a ready-to-paste load command for the selected session

Everything is inlined except the vis-network CDN script, so the file can be
opened straight from disk with no server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VIS_URL = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"
VIS_CACHE = "vis-network.min.js"
VIS_MIN_BYTES = 200_000          # sanity floor: a truncated download is worse than none


def vis_library(out_dir: Path | None) -> str:
    """Return a <script> block with the graph library inlined if possible.

    The page is opened straight off disk as a file:// URL, where a remote script
    is the one thing that can silently fail — offline, blocked, or restricted by
    the browser's file:// policy — leaving a page that renders its whole chrome
    and no graph. Inlining removes that failure mode entirely; the CDN tag stays
    as a fallback for the first run on a machine that has never fetched it.
    """
    if out_dir is not None:
        cache = Path(out_dir).expanduser() / VIS_CACHE
        if not cache.is_file() or cache.stat().st_size < VIS_MIN_BYTES:
            try:
                from urllib.request import urlopen
                with urlopen(VIS_URL, timeout=30) as response:
                    payload = response.read()
                if len(payload) >= VIS_MIN_BYTES:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(payload)
            except Exception:
                pass                                  # fall through to the CDN tag
        if cache.is_file() and cache.stat().st_size >= VIS_MIN_BYTES:
            source = cache.read_text(encoding="utf-8", errors="replace")
            # Guard against the library's own text closing our script element.
            source = source.replace("</script", "<\\/script")
            return f"<script>{source}</script>"
    return f'<script src="{VIS_URL}"></script>'

COMMUNITY_COLORS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
]

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Session Brain</title>
/* VIS_LIBRARY */
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: flex; }
  /* min-height/min-width:0 are load-bearing. A flex item defaults to
     min-height:auto, so it cannot shrink below its content — and vis.js sizes
     its canvas from the container, which then grows to fit the canvas, which
     grows the container. The pair runs away to thousands of pixels tall and the
     graph renders far below the viewport, looking like an empty page. */
  #graph { flex: 1 1 0; min-width: 0; min-height: 0; overflow: hidden; }
  #loading { position: absolute; inset: 48px 0 0 0; display: flex; flex-direction: column;
             align-items: center; justify-content: center; gap: 6px;
             color: #8a8aa0; font-size: 14px; text-align: center; pointer-events: none; }
  #loading span { color: #55556a; font-size: 12px; }
  #sidebar { width: 300px; background: #1a1a2e; border-left: 1px solid #2a2a4e; padding: 14px; overflow-y: auto; font-size: 13px; }
  #sidebar h3 { color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin: 14px 0 8px; }
  #sidebar h3:first-child { margin-top: 0; }
  #info { line-height: 1.6; color: #ccc; word-break: break-word; }
  #info b { color: #fff; }
  .meta { color: #8a8aa0; font-size: 12px; }
  .cmd { display: block; margin-top: 8px; padding: 6px 8px; background: #0f0f1a; border: 1px solid #2a2a4e; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #76B7B2; user-select: all; word-break: break-all; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; cursor: pointer; }
  .legend-item:hover { color: #fff; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .tag { display: inline-block; background: #2a2a4e; border-radius: 3px; padding: 1px 6px; margin: 2px 3px 0 0; font-size: 11px; }
  #controls { padding: 10px 14px; background: #16162a; border-bottom: 1px solid #2a2a4e; display: flex; gap: 12px; align-items: center; }
  #wrap { flex: 1 1 0; display: flex; flex-direction: column;
          min-width: 0; min-height: 0; position: relative; overflow: hidden; }
  input[type=search] { flex: 0 0 240px; background: #0f0f1a; border: 1px solid #2a2a4e; border-radius: 4px; color: #e0e0e0; padding: 6px 10px; font-size: 12px; }
  input[type=range] { flex: 1; accent-color: #4E79A7; }
  #stats { margin-top: 14px; color: #555; font-size: 11px; line-height: 1.5; }
  #cutoff { color: #8a8aa0; font-size: 12px; min-width: 190px; text-align: right; }
</style>
</head>
<body>
<div id="wrap">
  <div id="controls">
    <input type="search" id="search" placeholder="Search title, project, terms…" autocomplete="off">
    <input type="range" id="time" min="0" max="100" value="0">
    <span id="cutoff"></span>
  </div>
  <div id="graph"></div>
  <!-- Sibling, not a child: vis.js replaces its container's innerHTML on init,
       which would silently delete this overlay. -->
  <div id="loading">laying out the graph…<span>a few seconds for a large history</span></div>
</div>
<div id="sidebar">
  <h3>Session Brain</h3>
  <div id="info">Click a session to inspect it.</div>
  <h3>Topics</h3>
  <div id="legend"></div>
  <div id="stats"></div>
</div>
<script>
// If the library is missing, say so loudly. A blank canvas is otherwise
// indistinguishable from "you have no sessions", which is a lie.
if (typeof vis === 'undefined') {
  document.getElementById('loading').innerHTML =
    'graph library failed to load<span>the page could not fetch vis-network. ' +
    'Rebuild with <code>obsidian-wiki sessions-build</code> while online to embed it.</span>';
  throw new Error('vis-network unavailable');
}

const NODES_DATA = /* NODES_JSON */;
const EDGES_DATA = /* EDGES_JSON */;
const CLUSTERS   = /* CLUSTERS_JSON */;
const HALF_LIFE  = /* HALF_LIFE */;
const STATS      = /* STATS_JSON */;
const COMMUNITY_COLORS = /* COLORS_JSON */;
const UNCLUSTERED = "#4a4a5e";

const clusterById = {};
CLUSTERS.forEach(c => clusterById[c.id] = c);
const nodeById = {};
NODES_DATA.forEach(n => nodeById[n.id] = n);

const NOW = Date.now();
const times = NODES_DATA.map(n => n.end_ms).filter(t => t > 0);
const T_MIN = times.length ? Math.min(...times) : NOW;
const T_MAX = times.length ? Math.max(...times) : NOW;

function clusterColor(n) {
  return n.cluster < 0 ? UNCLUSTERED : COMMUNITY_COLORS[n.cluster % COMMUNITY_COLORS.length];
}

// Recency is rendered as brightness, not size: size already carries session
// weight, and fading is the honest visual for "this is still here, just old".
function recency(n) {
  if (!n.end_ms) return 0;
  return Math.pow(0.5, ((NOW - n.end_ms) / 86400000) / HALF_LIFE);
}

function mix(hex, target, t) {
  const h = hex.replace('#', '');
  const g = target.replace('#', '');
  const out = [0, 1, 2].map(i => {
    const a = parseInt(h.substr(i * 2, 2), 16);
    const b = parseInt(g.substr(i * 2, 2), 16);
    return Math.round(a + (b - a) * t).toString(16).padStart(2, '0');
  });
  return '#' + out.join('');
}

function styleOf(n) {
  const base = clusterColor(n);
  const faded = mix(base, '#1a1a2e', 1 - Math.max(0.12, recency(n)));
  const bookmarked = !!n.bookmark;
  return {
    background: n.tier === 'thin' ? 'rgba(0,0,0,0)' : faded,
    border: bookmarked ? '#EDC948' : faded,
  };
}

const visNodes = NODES_DATA.map(n => {
  const c = styleOf(n);
  const cl = clusterById[n.cluster];
  const tip = [
    n.title || '(untitled)',
    n.project ? 'project: ' + n.project : '',
    cl ? 'topic: ' + (cl.name || cl.label) : '',
    n.end_ts ? n.end_ts.slice(0, 10) : '',
    n.tier === 'thin' ? 'prompts only — no transcript on disk' : n.n_turns + ' turns',
  ].filter(Boolean).join('\\n');
  return {
    id: n.id,
    label: (n.title || n.id.slice(0, 8)).slice(0, 40),
    title: tip,
    size: Math.min(8 + n.n_turns * 0.35, 50),
    color: { background: c.background, border: c.border,
             highlight: { background: clusterColor(n), border: '#fff' } },
    borderWidth: n.bookmark ? 3 : (n.tier === 'thin' ? 2 : 1),
    font: { size: 11, color: '#9a9ab0' },
  };
});

const visEdges = EDGES_DATA.map((e, i) => ({
  id: i, from: e.source, to: e.target,
  width: 1 + e.weight * 4,
  color: { color: e.cross_cluster ? '#6a5a7a' : '#3a3a5e',
           opacity: Math.min(0.9, 0.15 + e.weight) },
  title: e.shared.join(', '),
}));

const nodes = new vis.DataSet(visNodes);
const edges = new vis.DataSet(visEdges);
const network = new vis.Network(document.getElementById('graph'), { nodes, edges }, {
  // vis.js's improvedLayout runs a Kamada-Kawai pre-pass that silently gives up
  // above ~150 nodes and leaves the canvas blank. A session graph is always far
  // past that, so the force solver does the positioning on its own.
  layout: { improvedLayout: false },
  physics: { solver: 'forceAtlas2Based',
             forceAtlas2Based: { gravitationalConstant: -60, springLength: 120 },
             stabilization: { iterations: 200 } },
  interaction: { hover: true, tooltipDelay: 100 },
  nodes: { shape: 'dot' },
  edges: { smooth: { type: 'continuous' }, arrows: { to: { enabled: false } } },
});
network.once('stabilizationIterationsDone', () => {
  network.setOptions({ physics: { enabled: false } });
  // Turning physics off stops vis.js's render loop, and it stops it *before*
  // painting a frame — leaving a blank canvas with a perfectly good layout
  // behind it. fit() then redraw() forces the one frame that never came.
  network.fit();
  network.redraw();
  const el = document.getElementById('loading');
  if (el) el.style.display = 'none';
});

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

network.on('click', ({ nodes: sel }) => {
  const box = document.getElementById('info');
  if (!sel.length) { box.innerHTML = 'Click a session to inspect it.'; return; }
  const n = nodeById[sel[0]];
  if (!n) return;
  const cl = clusterById[n.cluster];
  const tags = (n.bookmark && n.bookmark.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  box.innerHTML = [
    `<b>${esc(n.title || '(untitled)')}</b>`,
    `<div class="meta">${esc(n.project || '—')} · ${esc((n.end_ts || '').slice(0, 10))}</div>`,
    cl ? `<div class="meta">topic: ${esc(cl.name || cl.label)}</div>` : '',
    `<div class="meta">${n.tier === 'thin' ? 'prompts only — transcript pruned' : n.n_turns + ' turns · ' + n.n_user_prompts + ' prompts'}</div>`,
    tags ? `<div>${tags}</div>` : '',
    n.tier === 'full'
      ? `<span class="cmd">/claude-session-load ${esc(n.id)}</span><span class="cmd">${esc(n.transcript || '')}</span>`
      : `<span class="cmd">${esc(n.id)}</span>`,
  ].filter(Boolean).join('');
});

// --- Filtering: time slider AND search are combined, never independent -----
let cutoff = T_MIN;
let term = '';

function matches(n) {
  if ((n.end_ms || 0) < cutoff) return false;
  if (!term) return true;
  const hay = [n.title, n.project, (n.top_terms || []).join(' ')].join(' ').toLowerCase();
  return hay.includes(term);
}

function applyFilter() {
  const updates = NODES_DATA.map(n => {
    const ok = matches(n);
    const c = styleOf(n);
    return {
      id: n.id,
      hidden: (n.end_ms || 0) < cutoff,
      opacity: ok ? 1 : 0.15,
      color: { background: c.background, border: term && ok ? '#fff' : c.border,
               highlight: { background: clusterColor(n), border: '#fff' } },
    };
  });
  nodes.update(updates);
  const shown = NODES_DATA.filter(n => (n.end_ms || 0) >= cutoff).length;
  document.getElementById('cutoff').textContent =
    new Date(cutoff).toISOString().slice(0, 10) + ' → now · ' + shown + ' sessions';
}

document.getElementById('time').addEventListener('input', ev => {
  cutoff = T_MIN + (T_MAX - T_MIN) * (ev.target.value / 100);
  applyFilter();
});
document.getElementById('search').addEventListener('input', ev => {
  term = ev.target.value.trim().toLowerCase();
  applyFilter();
  if (term) {
    const hit = NODES_DATA.find(matches);
    if (hit) network.focus(hit.id, { scale: 1.1, animation: true });
  }
});

// --- Legend: clicking a topic zooms to it ---------------------------------
const legend = document.getElementById('legend');
CLUSTERS.slice(0, 24).forEach(c => {
  const color = COMMUNITY_COLORS[c.id % COMMUNITY_COLORS.length];
  const flag = c.dormant ? ' <span class="meta">· dormant</span>'
             : (c.momentum >= 2 ? ' <span class="meta">· hot</span>' : '');
  const el = document.createElement('div');
  el.className = 'legend-item';
  el.innerHTML = `<div class="dot" style="background:${color}"></div>${esc(c.name || c.label)} (${c.size})${flag}`;
  el.onclick = () => network.fit({ nodes: c.sessions, animation: true });
  legend.appendChild(el);
});

document.getElementById('stats').innerHTML =
  `${STATS.sessions} sessions · ${STATS.edges} links · ${STATS.clusters} topics<br>` +
  `${STATS.full} with transcripts · ${STATS.thin} history-only<br>` +
  `half-life ${HALF_LIFE}d`;

applyFilter();
</script>
</body>
</html>
"""


def _epoch_ms(iso: str | None) -> int:
    """vis.js filters on numbers, so timestamps are pre-converted here."""
    from obsidian_wiki.session_graph import parse_ts
    parsed = parse_ts(iso)
    return int(parsed.timestamp() * 1000) if parsed else 0


def render_html(graph: dict, clusters_doc: dict, *, half_life_days: float,
                out_dir: Path | None = None) -> str:
    """Render a complete, self-contained HTML page for a built session graph."""
    nodes = []
    for node in graph.get("nodes", []):
        nodes.append({
            "id": node["id"],
            "title": node.get("title") or "",
            "project": node.get("project") or "",
            "tier": node.get("tier", "full"),
            "cluster": node.get("cluster", -1),
            "n_turns": node.get("n_turns", 0),
            "n_user_prompts": node.get("n_user_prompts", 0),
            "end_ts": node.get("end_ts") or "",
            "end_ms": _epoch_ms(node.get("end_ts")),
            "transcript": node.get("transcript") or "",
            "top_terms": node.get("top_terms") or [],
            "bookmark": node.get("bookmark"),
        })

    clusters = [
        {
            "id": c["id"], "size": c["size"], "label": c.get("label") or "",
            "name": c.get("name"), "sessions": c.get("sessions") or [],
            "dormant": bool(c.get("dormant")), "momentum": c.get("momentum", 0),
        }
        for c in clusters_doc.get("clusters", [])
    ]

    replacements = {
        "/* NODES_JSON */": json.dumps(nodes),
        "/* EDGES_JSON */": json.dumps(graph.get("edges", [])),
        "/* CLUSTERS_JSON */": json.dumps(clusters),
        "/* STATS_JSON */": json.dumps(graph.get("stats", {})),
        "/* COLORS_JSON */": json.dumps(COMMUNITY_COLORS),
        "/* HALF_LIFE */": json.dumps(half_life_days),
    }
    html = _TEMPLATE
    for placeholder, payload in replacements.items():
        html = html.replace(placeholder, payload)
    # Last, so the library's own contents can never be scanned for placeholders.
    return html.replace("/* VIS_LIBRARY */", vis_library(out_dir))
