/* Aegis dashboard. Plain JS, no dependencies. Everything that came from an agent or an MCP server is
   inserted with textContent (see h()), never as HTML. */
"use strict";

const PAGES = ["overview", "activity", "runs", "mcp", "boundaries", "autopilot", "setup"];
let S = null;               // last /api/state
let seenEvents = null;      // ids rendered before, to animate only new ones
let filter = "open";
const counted = new Set();  // tiles already animated

// ------------------------------------------------------------------ helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const NS = "http://www.w3.org/2000/svg";
function icon(d) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); s.append(p);
  return s;
}
const ICONS = {
  shield: "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6l-8-3z",
  block: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM5.6 5.6l12.8 12.8",
  alert: "M12 4 2.5 20h19L12 4zM12 10v4M12 17.2v.1",
  plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0V8zM12 17v4",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4l2-2zM10 21h4",
  check: "m5 12 4.5 4.5L19 7",
  server: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
};
function ago(t) {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 50) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
function when(t) {
  return t ? new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
}
function shortPath(p) {
  if (!p) return "";
  const parts = String(p).split(/[\\/]/).filter(Boolean);
  return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : String(p);
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 3200);
}
async function api(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) throw new Error("Session expired: open the link that `aegis dashboard` prints.");
  return r.json();
}
async function post(body) {
  const r = await fetch("/api/action", {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({ error: "Unexpected response" }));
  if (!r.ok || data.error) throw new Error(data.error || "Action failed");
  return data;
}
async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); }
  catch { toast(text); }
  if (btn) { btn.classList.add("copied"); setTimeout(() => btn.classList.remove("copied"), 900); }
}

// ------------------------------------------------------------------ art (SVG templates, colors from tokens)
function paintArt() {
  const cs = getComputedStyle(document.documentElement);
  document.querySelectorAll("[data-art]").forEach((host) => {
    const vertical = host.dataset.art === "flow" && (host.clientWidth || innerWidth) < 520;
    host.classList.toggle("vertical", vertical);
    host.replaceChildren(document.getElementById("tpl-" + host.dataset.art + (vertical ? "-v" : "")).content.cloneNode(true));
    const uid = "a" + Math.random().toString(36).slice(2, 8);  // gradient ids must be unique per copy
    host.querySelectorAll("[id]").forEach((el) => { el.id = `${el.id}-${uid}`; });
    host.querySelectorAll("[fill^='url(#']").forEach((el) => { el.setAttribute("fill", el.getAttribute("fill").replace(/\)$/, `-${uid})`)); });
    host.querySelectorAll("[fill^='var('],[stroke^='var('],[stop-color^='var(']").forEach((el) => {
      for (const a of ["fill", "stroke", "stop-color"]) {
        const v = el.getAttribute(a);
        const m = v && v.match(/^var\((--[\w-]+)\)$/);
        if (m) el.setAttribute(a, cs.getPropertyValue(m[1]).trim());
      }
    });
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) host.querySelectorAll("svg").forEach((s) => s.pauseAnimations && s.pauseAnimations());
  });
}

// ------------------------------------------------------------------ status
function renderStatus() {
  const w = S.watch;
  for (const id of ["#pill-autopilot", "#ap-pill"]) {
    const p = $(id); if (!p) continue;
    p.classList.toggle("on", w.running); p.classList.toggle("off", !w.running);
    p.lastElementChild.textContent = w.running ? "Autopilot on" : "Autopilot off";
    p.title = w.running ? `Last check ${ago(w.last_pass)}` : "Start it with: aegis watch";
  }
  const n = S.counts.open, tc = $("#tab-open");
  tc.hidden = !n; tc.textContent = n > 99 ? "99+" : n;
}

// ------------------------------------------------------------------ overview
function tile(key, label, value, note, cls, ico, of) {
  const num = h("div", { class: "tile-num" }, String(value));
  if (of != null) num.append(h("small", {}, ` / ${of}`));
  if (!counted.has(key) && typeof value === "number" && value > 0 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    counted.add(key);
    const t0 = performance.now(), dur = 700;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), v = Math.round(value * (1 - Math.pow(1 - k, 3)));
      num.firstChild.textContent = String(v);
      if (k < 1) requestAnimationFrame(step);
    };
    num.firstChild.textContent = "0"; requestAnimationFrame(step);
  }
  return h("div", { class: "tile " + cls },
    h("div", { class: "tile-label" }, label), num, h("div", { class: "tile-note" }, note),
    h("div", { class: "tile-icon" }, icon(ICONS[ico])));
}
function renderOverview() {
  const c = S.counts;
  $("#ov-meta").replaceChildren(
    h("div", { class: "meta-chip" }, h("small", {}, "Sandbox"), h("b", {}, S.backend)),
    h("div", { class: "meta-chip" }, h("small", {}, "Last check"), h("b", {}, ago(S.watch.last_pass))));
  $("#ov-tiles").replaceChildren(
    tile("open", "Open events", c.open, c.open_high ? `${c.open_high} high severity` : c.open ? "Nothing critical" : "All clear",
      c.open_high ? "t-crit" : c.open ? "t-signal" : "", "bell"),
    tile("blocked", "Blocked", c.blocked, "Connections and tool calls stopped", "", "block"),
    tile("trip", "Tripwires", c.tripwires, c.tripwires ? "Decoy keys were touched" : "No decoy touched", c.tripwires ? "t-signal" : "t-moss", "alert"),
    tile("servers", "MCP servers jailed", c.jailed, c.servers ? `${c.servers - c.jailed} with full user rights` : "No local servers found",
      c.servers && c.jailed < c.servers ? "t-signal" : "t-moss", "plug", c.servers));
  const rank = { high: 0, medium: 1, info: 2 };
  const open = S.events.filter((e) => e.status === "open" && e.severity !== "info")
    .sort((a, b) => rank[a.severity] - rank[b.severity] || b.time - a.time).slice(0, 4);
  $("#ov-events").replaceChildren(...(open.length ? open.map((e) => eventCard(e, true)) : [emptyState("Nothing needs you right now",
    S.watch.running ? "Autopilot is watching in the background." : "Start Autopilot with `aegis watch` to keep checking.")]));
  const runs = S.runs.slice(0, 4);
  $("#ov-runs").replaceChildren(...(runs.length ? runs.map(runRow) : [emptyState("No runs yet", "Try `aegis demo` for a 60-second example.")]));
}
function emptyState(title, text) {
  return h("div", { class: "empty" }, icon(ICONS.check), h("b", {}, title), h("span", {}, text));
}
function runBadge(r) {
  if (r.tripwires.length) return h("span", { class: "badge b-crit" }, "Tripwire");
  if (r.status === "applied") return h("span", { class: "badge b-ok" }, "Applied");
  if (r.status === "discarded") return h("span", { class: "badge b-mute" }, "Discarded");
  return r.ok ? h("span", { class: "badge b-ok" }, "Passed") : h("span", { class: "badge b-warn" }, "Failed");
}
function runRow(r) {
  const play = h("span", { class: "play" }); const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); const p = document.createElementNS(NS, "path"); p.setAttribute("d", "M8 5v14l11-7z"); s.append(p); play.append(s);
  return h("button", { class: "row-run", type: "button", onclick: () => openRun(r) }, play,
    h("span", {}, h("div", { class: "run-id" }, r.id), h("div", { class: "run-sub" }, `${r.agent || "agent"} · ${shortPath(r.project)} · ${ago(r.started)}`)),
    runBadge(r));
}

// ------------------------------------------------------------------ events
const KIND = {
  mcp_unjailed: "MCP config", mcp_remote: "MCP config", mcp_rug_pull: "Rug pull", mcp_tool_hidden: "Poisoned tool",
  mcp_blocked_call: "Tool firewall", tripwire: "Tripwire", network_blocked: "Network", run_review: "Review",
  project_risk: "Project scan", mcp_sampling_blocked: "Sampling", mcp_invisible_text_stripped: "Hidden text", autopilot: "Autopilot",
};
const ACTION_LABEL = { jail: "Jail it", discard: "Discard run", review_pins: "How to review" };
function eventCard(e, compact) {
  const fresh = seenEvents && !seenEvents.has(e.id);
  const actions = h("div", { class: "event-actions" });
  if (e.status === "open") {
    for (const a of e.actions || []) actions.append(h("button", { class: "btn btn-sm", type: "button", onclick: (ev) => doAct(e, a, ev.currentTarget) }, ACTION_LABEL[a] || a));
    actions.append(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: (ev) => doResolve(e, "resolved", ev.currentTarget) }, "Mark handled"));
    actions.append(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: (ev) => doResolve(e, "ignored", ev.currentTarget) }, "Ignore"));
  } else {
    actions.append(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: (ev) => doResolve(e, "open", ev.currentTarget) }, "Reopen"));
  }
  const res = e.resolution ? h("div", { class: "resolution" },
    `${e.status === "ignored" ? "Ignored" : "Handled"} by ${e.resolution.by} ${ago(e.resolution.time)}${e.resolution.note ? ": " + e.resolution.note : ""}`) : null;
  return h("article", { class: "event" + (fresh ? " fresh" : "") + (e.status !== "open" ? " done" : "") },
    h("span", { class: "sev sev-" + e.severity }, e.severity),
    h("div", { class: "event-main" },
      h("div", { class: "event-title" }, e.title),
      h("div", { class: "event-meta" }, h("span", {}, KIND[e.kind] || e.kind), h("span", {}, ago(e.time)), h("span", { class: "mono" }, e.id)),
      e.detail ? h("div", { class: "event-detail" + (compact ? " clamp" : "") }, e.detail) : null, res, actions));
}
async function doAct(e, action, btn) {
  btn.disabled = true;
  try { const r = await post({ kind: "event", id: e.id, action }); toast(r.message || "Done"); await refresh(); }
  catch (err) { toast(err.message); btn.disabled = false; }
}
async function doResolve(e, status, btn) {
  btn.disabled = true;
  try { const r = await post({ kind: "resolve", id: e.id, status }); toast(r.message); await refresh(); }
  catch (err) { toast(err.message); btn.disabled = false; }
}
function renderActivity() {
  let list = S.events;
  if (filter === "open") list = list.filter((e) => e.status === "open");
  if (filter === "high") list = list.filter((e) => e.severity === "high");
  $("#act-list").replaceChildren(...(list.length ? list.map(eventCard) : [h("div", { class: "panel" }, emptyState(
    filter === "all" ? "No events yet" : "No open events", "Autopilot adds them here as soon as it finds something."))]));
}

// ------------------------------------------------------------------ runs
function renderRuns() {
  const body = $("#runs-table tbody");
  body.replaceChildren(...S.runs.map((r) => h("tr", { class: "clickable", tabindex: "0", onclick: () => openRun(r), onkeydown: (ev) => { if (ev.key === "Enter") openRun(r); } },
    h("td", {}, h("div", { class: "run-id" }, r.id), h("div", { class: "run-sub" }, when(r.started))),
    h("td", {}, h("div", {}, shortPath(r.project)), h("div", { class: "run-sub" }, r.profile ? `profile ${r.profile}` : "")),
    h("td", {}, r.agent || "agent"),
    h("td", {}, runBadge(r)),
    h("td", {}, String(r.blocked.length + r.denials.length)),
    h("td", {}, String(r.changes.length)),
    h("td", {}, h("span", { class: "badge " + (r.status === "pending" ? "b-info" : "b-mute") }, r.status)))));
  $("#runs-table").parentElement.hidden = !S.runs.length;
  const empty = $("#runs-empty"); empty.hidden = !!S.runs.length;
  if (!S.runs.length) empty.replaceChildren(emptyState("No runs yet", "Run `aegis demo`, or let an agent call aegis_run."));
}
async function openRun(r) {
  const body = $("#drawer-body");
  $("#drawer-title").textContent = `Run ${r.id}`;
  const dl = h("dl", { class: "kv" });
  const add = (k, v) => dl.append(h("dt", {}, k), h("dd", {}, v));
  add("Project", r.project); add("Agent", r.agent || "agent"); add("Profile", r.profile || "default");
  add("Sandbox", r.backend); add("Started", when(r.started)); add("Status", r.status);
  add("Phases", r.phases.map((p) => `${p.name} ${p.ok ? "ok" : "failed"} (${p.duration}s, network ${p.network})`).join("; "));
  const parts = [dl];
  if (r.tripwires.length) parts.push(section("Tripwire", h("div", { class: "event-detail" }, r.tripwires.join("\n"))));
  if (r.blocked.length || r.denials.length) parts.push(section("Blocked", h("div", { class: "event-detail" }, [...r.blocked, ...r.denials].join("\n"))));
  if (r.changes.length) parts.push(section("Changed files", h("div", { class: "chips" }, r.changes.map((c) => h("span", { class: "badge " + (c.risk ? "b-warn" : "b-mute") }, `${c.kind} ${c.path}`)))));
  const pre = h("pre", { class: "diff" }, "Loading the diff…");
  parts.push(section("Diff", pre));
  if (r.status === "pending" && r.workspace && r.changes.length) {
    const cmd = `aegis apply ${r.id} --project ${r.project}`;
    parts.push(section("Apply", h("p", { class: "muted small" }, "Applying writes to your real project, so it stays a command you run after reading the diff."),
      h("div", { class: "cmd" }, h("code", {}, cmd), h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: (ev) => copy(cmd, ev.currentTarget) }, "Copy"))));
  }
  body.replaceChildren(...parts);
  $("#drawer").hidden = false; $("#drawer-close").focus();
  try {
    const d = await api(`/api/diff?key=${encodeURIComponent(r.key)}&run=${encodeURIComponent(r.id)}`);
    pre.replaceChildren(...String(d.diff || d.error || "").split("\n").map((line) => {
      const cls = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : null;
      return h("span", cls ? { class: cls } : {}, line + "\n");
    }));
  } catch (err) { pre.textContent = err.message; }
}
function section(title, ...kids) { return h("section", { class: "stack" }, h("h3", {}, title), ...kids); }

// ------------------------------------------------------------------ mcp
function renderMcp() {
  const groups = {};
  for (const s of S.servers) (groups[s.client] ||= []).push(s);
  const els = Object.entries(groups).map(([client, list]) => h("div", { class: "client-group" },
    h("div", { class: "client-name" }, client),
    ...list.map((s) => {
      const right = h("div", { class: "server-right" });
      if (s.remote) right.append(h("span", { class: "badge b-info" }, "Remote"));
      else if (s.jailed) right.append(h("span", { class: "badge b-ok" }, "Jailed"));
      else right.append(h("span", { class: "badge b-warn" }, "Full user rights"));
      if (!s.remote && !s.jailed && s.editable) right.append(h("button", { class: "btn btn-sm", type: "button", onclick: (ev) => jail(s, ev.currentTarget) }, "Jail it"));
      if (s.jailed && s.editable && s.name !== "aegis") right.append(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: (ev) => unjail(s, ev.currentTarget) }, "Undo"));
      const cmd = s.remote ? s.url : [s.command, ...s.args].join(" ");
      return h("div", { class: "server" },
        h("div", { class: "server-icon" + (s.jailed || s.remote ? "" : " bad") }, icon(ICONS.server)),
        h("div", { class: "event-main" }, h("div", { class: "server-name" }, s.name + (s.project ? `  ·  ${shortPath(s.project)}` : "")),
          h("div", { class: "server-cmd" }, cmd), h("div", { class: "run-sub" }, shortPath(s.file) + (S.pins[s.name] ? ` · ${S.pins[s.name]} tool(s) pinned` : ""))),
        right);
    })));
  $("#mcp-servers").replaceChildren(...(els.length ? els : [h("div", { class: "panel" }, emptyState("No MCP servers found",
    "Aegis reads the configs of Claude Code, Claude Desktop, Cursor, Windsurf, VS Code and Codex."))]));
  const rows = S.activity.slice(0, 120);
  $("#mcp-act-count").textContent = rows.length ? `${rows.length} recent entries` : "";
  $("#mcp-activity tbody").replaceChildren(...rows.map((e) => {
    let detail = "", label = e.event;
    if (e.event === "tool_call") { label = e.allowed === false ? "blocked call" : "call"; detail = `${e.tool} ${e.arguments ? JSON.stringify(e.arguments) : ""}`; }
    else if (e.event === "tool_hidden") { label = "tool hidden"; detail = `${e.tool}: ${e.reason || ""}`; }
    else if (e.event === "start") { label = "server start"; detail = `${(e.command || []).join(" ")} · network ${e.network}`; }
    else detail = JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => !["time", "event", "server"].includes(k))));
    const bad = e.event === "tool_hidden" || e.allowed === false || /blocked|stripped/.test(e.event);
    return h("tr", {}, h("td", { class: "mono nowrap" }, when(e.time)), h("td", { class: "nowrap" }, e.server),
      h("td", { class: "nowrap" }, h("span", { class: "badge " + (bad ? "b-crit" : "b-mute") }, label)), h("td", { class: "mono" }, detail.slice(0, 400)));
  }));
  $("#mcp-activity").parentElement.hidden = !rows.length;
  const empty = $("#mcp-act-empty"); empty.hidden = !!rows.length;
  if (!rows.length) empty.replaceChildren(emptyState("No jailed traffic yet", "Calls through `aegis mcp-jail` are logged here."));
}
async function jail(s, btn) {
  btn.disabled = true;
  try { const r = await post({ kind: "jail", file: s.file, jsonpath: s.jsonpath }); toast(r.message); await refresh(); }
  catch (err) { toast(err.message); btn.disabled = false; }
}
async function unjail(s, btn) {
  btn.disabled = true;
  try { const r = await post({ kind: "unjail", file: s.file, jsonpath: s.jsonpath }); toast(r.message); await refresh(); }
  catch (err) { toast(err.message); btn.disabled = false; }
}

// ------------------------------------------------------------------ autopilot
function renderAutopilot() {
  const cfg = S.watch.config;
  document.querySelectorAll("#ap-form [data-key]").forEach((el) => {
    const v = cfg[el.dataset.key];
    if (document.activeElement === el) return;
    if (el.type === "checkbox") el.checked = !!v; else el.value = String(v);
  });
  $("#b-backend").textContent = S.backend;
}
$("#ap-form").addEventListener("change", async (ev) => {
  const el = ev.target; if (!el.dataset.key) return;
  const value = el.type === "checkbox" ? el.checked : el.dataset.key === "interval" ? Number(el.value) : el.value;
  try { await post({ kind: "config", updates: { [el.dataset.key]: value } }); toast("Saved"); await refresh(); }
  catch (err) { toast(err.message); }
});

// ------------------------------------------------------------------ routing & refresh
function route() {
  const page = PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  for (const p of PAGES) $("#page-" + p).hidden = p !== page;
  document.querySelectorAll(".tabs a").forEach((a) => { if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const active = document.querySelector(`.tabs a[data-page="${page}"]`);
  if (active) active.scrollIntoView({ block: "nearest", inline: "nearest" });
  window.scrollTo({ top: 0 });
}
function render() {
  if (!S) return;
  renderStatus(); renderOverview(); renderActivity(); renderRuns(); renderMcp(); renderAutopilot();
  seenEvents = new Set(S.events.map((e) => e.id));
}
async function refresh() {
  try { S = await api("/api/state"); render(); }
  catch (err) { toast(err.message); }
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".copy");
  if (b) copy(b.dataset.copy, b);
});
document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => {
  filter = b.dataset.filter;
  document.querySelectorAll(".segmented button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  renderActivity();
}));
$("#btn-refresh").addEventListener("click", async (ev) => {
  const b = ev.currentTarget; b.classList.remove("spinning"); void b.offsetWidth; b.classList.add("spinning");
  try { const r = await post({ kind: "scan" }); toast(r.message); await refresh(); } catch (err) { toast(err.message); }
});
const closeDrawer = () => { $("#drawer").hidden = true; };
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (ev) => { if (ev.target.id === "drawer") closeDrawer(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
window.addEventListener("hashchange", () => { route(); paintArt(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintArt);
let lastW = innerWidth, resizeT;
window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { if ((lastW < 640) !== (innerWidth < 640)) paintArt(); lastW = innerWidth; }, 200); });

route();
paintArt();
refresh();
let debounce;
try {
  const es = new EventSource("/api/stream");
  es.onmessage = () => { clearTimeout(debounce); debounce = setTimeout(refresh, 250); };
} catch { setInterval(refresh, 5000); }
setInterval(() => { if (S) { renderStatus(); } }, 30000);
