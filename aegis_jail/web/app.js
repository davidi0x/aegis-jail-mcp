/* Aegis dashboard. Plain JS, no dependencies. Text that came from agents, MCP servers or configs is always
   inserted with textContent (see h()); the only markup built from strings is the constant artwork below. */
"use strict";

const PAGES = ["overview", "activity", "agents", "mcp", "boundaries", "autopilot", "setup"];
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
let S = null;
let seenEvents = null;
let filter = "open";
const counted = new Set();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ icons
const ICONS = {
  play: "M7 4.6v14.8L19 12z", arrow: "M7 17 17 7M8.5 7H17v8.5", refresh: "M20 11.5a8 8 0 1 1-2.4-5.7M20 4v6h-6",
  command: "M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z",
  sparkle: "M12 2.5c.7 5 3.5 8 9.5 9.5-6 1.5-8.8 4.5-9.5 9.5-.7-5-3.5-8-9.5-9.5 6-1.5 8.8-4.5 9.5-9.5z",
  box: "M12 2.8 3.5 7.4v9.2l8.5 4.6 8.5-4.6V7.4zM3.5 7.4 12 12l8.5-4.6M12 12v9.2",
  "check-dot": "M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9zM8 12.4l2.8 2.8 5.4-5.6",
  "check-circle": "M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9zM8 12.4l2.8 2.8 5.4-5.6",
  "x-circle": "M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9zM9 9l6 6M15 9l-6 6",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1", layers: "M12 2.5 2.5 7.5l9.5 5 9.5-5zM2.5 12l9.5 5 9.5-5M2.5 16.5l9.5 5 9.5-5",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18",
  lock: "M5.5 11h13v10h-13zM8.5 11V8a3.5 3.5 0 0 1 7 0v3", user: "M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM4 21c1-4.2 4.2-6.5 8-6.5s7 2.3 8 6.5",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.6v.4",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  bell: "M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 21h4", search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20.5 20.5l-4.5-4.5",
  zap: "M13 2 4 14h7l-1 8 9-12h-7z", clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.2 2",
  shield: "M12 2.8 4.5 5.8v6c0 4.5 3.2 8.4 7.5 9.4 4.3-1 7.5-4.9 7.5-9.4v-6zM8.7 12l2.3 2.3 4.4-4.6",
  alert: "M12 3.2 1.8 20.8h20.4zM12 9.8v5.2M12 17.6v.3", ban: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM5.6 5.6l12.8 12.8",
  terminal: "M4 6.5l6 5.5-6 5.5M12.5 18H20", code: "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM10 9l-3 3 3 3M14 9l3 3-3 3",
  file: "M6 2.8h8.2L19 7.6v13.6H6zM14 2.8v5h5", book: "M3 5c3-1 6-1 9 1v14c-3-2-6-2-9-1zM21 5c-3-1-6-1-9 1v14c3-2 6-2 9-1z",
  cloud: "M7 18.5a4.5 4.5 0 0 1-.6-9 6 6 0 0 1 11.6 1.6 3.9 3.9 0 0 1-.4 7.4z", folder: "M3 5.5h6.5l2 2.5H21v11.5H3z",
  database: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  plug: "M9 2.5v5M15 2.5v5M6 7.5h12v4a6 6 0 0 1-12 0zM12 17.5v4", x: "M6 6l12 12M18 6 6 18", check: "M5 12.5l4.5 4.5L19 7.5",
  eye: "M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4", send: "M7 17 17 7M8.5 7H17v8.5",
  linux: "M12 3c2.2 0 3.4 1.8 3.4 4.4 0 1.6.6 2.7 1.6 4 1.3 1.6 2.2 3.4 2.2 5.2 0 1.6-1 2.4-2.3 2.4-.9 0-1.6-.4-2.2-.9-.8.6-1.7.9-2.7.9s-1.9-.3-2.7-.9c-.6.5-1.3.9-2.2.9-1.3 0-2.3-.8-2.3-2.4 0-1.8.9-3.6 2.2-5.2 1-1.3 1.6-2.4 1.6-4C8.6 4.8 9.8 3 12 3zM10.4 7.6h.1M13.6 7.6h.1",
  apple: "M16 3c0 1.7-1.3 3.3-3 3.3-.2-1.7 1.2-3.3 3-3.3zM12.2 7.6c1 0 2.1-.8 3.4-.8 1.6 0 3 .9 3.8 2.2-3.2 1.8-2.6 6.2.6 7.4-.8 2-2.2 4.4-4 4.4-1.3 0-1.7-.8-3.3-.8s-2.1.8-3.4.8C7 20.8 4 16.5 4 12.4c0-3.2 2-5.6 4.7-5.6 1.4 0 2.6.8 3.5.8z",
  windows: "M3.5 5.2l7-1v7.3h-7zM12 4l8.5-1.2v8.7H12zM3.5 12.5h7v7.3l-7-1zM12 12.5h8.5v8.7L12 20z",
};
const FILLED = new Set(["play", "sparkle", "zap", "apple", "windows"]);
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "ico");
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICONS[name] || ICONS.box);
  if (FILLED.has(name)) { p.setAttribute("fill", "currentColor"); p.setAttribute("stroke", "none"); }
  svg.append(p);
  return svg;
}
function paintIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.querySelector(":scope > svg")) return;
    el.prepend(icon(el.dataset.icon));
  });
}
function ic(name, cls) { const s = document.createElement("span"); s.dataset.icon = name; if (cls) s.className = cls; s.append(icon(name)); return s; }

// ------------------------------------------------------------------ dom helper
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
const $ = (s) => document.querySelector(s);
function ago(t) {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 50) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
function when(t) { return t ? new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""; }
function dur(s) { if (!s && s !== 0) return ""; if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`; return `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`; }
function shortPath(p) { const parts = String(p || "").split(/[\\/]/).filter(Boolean); return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : String(p || ""); }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 3400); }
async function api(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) throw new Error("Session expired: open the link that `aegis dashboard` prints.");
  return r.json();
}
async function post(body) {
  const r = await fetch("/api/action", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({ error: "Unexpected response" }));
  if (!r.ok || data.error) throw new Error(data.error || "Action failed");
  return data;
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); } catch { toast(text); }
}

// ------------------------------------------------------------------ mascot (the logo arch, with eyes)
let artId = 0;
function mascot(variant) {
  const u = "m" + (++artId);
  const ink = "#0e0c15";
  const cube = (glyph) => `
    <g class="m-prop">
      <ellipse class="m-glow" cx="214" cy="188" rx="64" ry="58" fill="#e7dcff" opacity=".7" filter="url(#${u}-blur)"/>
      <path d="M214 138 L258 161 L214 184 L170 161 Z" fill="url(#${u}-top)" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M170 161 L214 184 L214 234 L170 211 Z" fill="url(#${u}-left)" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M214 184 L258 161 L258 211 L214 234 Z" fill="url(#${u}-right)" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/>
      ${glyph}
    </g>`;
  const glyphs = {
    lock: `<g transform="translate(236 199)" fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round"><path d="M-7 -2v-6a7 7 0 0 1 14 0v6"/><rect x="-11" y="-2" width="22" height="17" rx="4" fill="#fff" stroke="none"/></g>`,
    code: `<g transform="translate(236 205)" fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"><path d="M-6 -9l-8 8 8 8M6 -9l8 8-8 8M3 -12l-6 22"/></g>`,
    spark: `<path transform="translate(224 186) scale(1.05)" d="M12 1c.7 5 3.5 8 9.5 9.5-6 1.5-8.8 4.5-9.5 9.5-.7-5-3.5-8-9.5-9.5C8.5 9 11.3 6 12 1z" fill="#fff"/>`,
  };
  let prop = "";
  let extra = "";
  if (variant === "laptop") {
    prop = `<g class="m-prop">
      <ellipse class="m-glow" cx="220" cy="176" rx="74" ry="56" fill="#e7dcff" opacity=".6" filter="url(#${u}-blur)"/>
      <path d="M176 130 L266 116 L262 196 L172 210 Z" fill="url(#${u}-screen)" stroke="#f3eeff" stroke-width="4" stroke-linejoin="round"/>
      <path class="m-screen" transform="translate(203 150)" d="M2 34V18a16 16 0 0 1 32 0v16H24V20a6 6 0 0 0-12 0v14z" fill="#fff"/>
      <path d="M146 220 L262 198 L286 214 L170 238 Z" fill="#e3d8ff" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>
    </g>`;
  } else {
    prop = cube(glyphs[variant] || glyphs.lock);
  }
  if (variant === "orbit") {
    extra = `<g class="m-speed" fill="none" stroke="${ink}" stroke-width="7" stroke-linecap="round"><path d="M44 118h56"/><path d="M26 146h64"/><path d="M48 174h40"/></g>
      <ellipse class="m-orbit" cx="160" cy="214" rx="146" ry="30" fill="none" stroke="#fff" stroke-width="4" opacity=".9" filter="url(#${u}-soft)"/>`;
  }
  const lines = variant === "orbit" ? "" : `<g class="m-lines" fill="none" stroke="${ink}" stroke-width="8" stroke-linecap="round"><path d="M224 40 L208 66"/><path d="M252 70 L226 84"/><path d="M262 106 L232 106"/></g>`;
  return `<svg class="mascot" viewBox="0 0 320 270" role="img" aria-label="The Aegis mascot ${variant === "laptop" ? "at a laptop" : "holding a locked cube"}">
    <defs>
      <linearGradient id="${u}-body" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2d2840"/><stop offset=".5" stop-color="${ink}"/></linearGradient>
      <linearGradient id="${u}-top" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset="1" stop-color="#d9cbff" stop-opacity=".9"/></linearGradient>
      <linearGradient id="${u}-left" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#cdbbff"/><stop offset="1" stop-color="#9a7dff"/></linearGradient>
      <linearGradient id="${u}-right" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a68cff"/><stop offset="1" stop-color="#7552ff"/></linearGradient>
      <linearGradient id="${u}-screen" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#b9a2ff"/><stop offset="1" stop-color="#6c48ff"/></linearGradient>
      <filter id="${u}-blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
      <filter id="${u}-soft" x="-20%" y="-60%" width="140%" height="220%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <ellipse cx="150" cy="256" rx="112" ry="10" fill="#1d0f66" opacity=".28"/>
    ${extra}
    <g class="m-body">
      <path d="M58 254 C54 144 84 50 150 48 C216 46 244 144 240 254 Z" fill="url(#${u}-body)"/>
      <path d="M92 96 C104 70 124 60 144 58" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width="8" stroke-linecap="round"/>
      <g class="m-eyes">
        <ellipse cx="132" cy="120" rx="13" ry="17" fill="#fff"/><ellipse cx="170" cy="120" rx="13" ry="17" fill="#fff"/>
        <ellipse class="m-pupil" cx="135" cy="124" rx="6" ry="9" fill="${ink}"/><ellipse class="m-pupil" cx="173" cy="124" rx="6" ry="9" fill="${ink}"/>
      </g>
      ${variant === "laptop" ? `<path d="M96 206 C124 226 160 228 196 214" fill="none" stroke="${ink}" stroke-width="32" stroke-linecap="round"/>` : `<path d="M88 198 C118 224 160 228 192 208" fill="none" stroke="${ink}" stroke-width="34" stroke-linecap="round"/>`}
    </g>
    ${lines}
    ${prop}
  </svg>`;
}
function paintMascots(root = document) {
  root.querySelectorAll("[data-mascot]").forEach((el) => {
    if (el.dataset.done === el.dataset.mascot) return;
    el.innerHTML = mascot(el.dataset.mascot);  // constant artwork, no external data
    el.dataset.done = el.dataset.mascot;
    if (REDUCED) el.querySelectorAll("svg").forEach((s) => s.pauseAnimations && s.pauseAnimations());
  });
}
let lookRaf = 0;
window.addEventListener("pointermove", (e) => {
  if (REDUCED || lookRaf) return;
  lookRaf = requestAnimationFrame(() => {
    lookRaf = 0;
    document.querySelectorAll(".page:not([hidden]) .mascot").forEach((svg) => {
      const r = svg.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width * 0.47), dy = e.clientY - (r.top + r.height * 0.44);
      const d = Math.hypot(dx, dy) || 1, k = Math.min(1, d / 400);
      svg.querySelectorAll(".m-pupil").forEach((p) => { p.style.transform = `translate(${(dx / d) * 4 * k}px, ${(dy / d) * 5 * k}px)`; });
    });
  });
});

// rings artwork: horizontal on wide screens, vertical on narrow ones, always fully visible
function paintArt() {
  document.querySelectorAll("[data-art]").forEach((host) => {
    const vertical = host.clientWidth > 0 && host.clientWidth < 560;
    const want = host.dataset.art + (vertical ? "-v" : "");
    if (host.dataset.done === want) return;
    host.replaceChildren(document.getElementById("tpl-" + want).content.cloneNode(true));
    const u = "r" + (++artId);
    host.querySelectorAll("[id]").forEach((el) => { el.id = `${el.id}-${u}`; });
    host.querySelectorAll("[fill^='url(#'],[filter^='url(#']").forEach((el) => {
      for (const a of ["fill", "filter"]) { const v = el.getAttribute(a); if (v && v.startsWith("url(#")) el.setAttribute(a, v.replace(/\)$/, `-${u})`)); }
    });
    host.dataset.done = want;
    if (REDUCED) host.querySelectorAll("svg").forEach((s) => s.pauseAnimations && s.pauseAnimations());
  });
}

// ------------------------------------------------------------------ shared bits
const AGENT_CLASS = { "claude-code": "chip-claude", codex: "chip-codex", gemini: "chip-gemini", aider: "chip-aider" };
const AGENT_CARD = { "claude-code": "c-lav", codex: "c-yellow", gemini: "c-coral", aider: "c-lime" };
const AGENT_ART = { "claude-code": "lock", codex: "code", gemini: "spark", aider: "lock" };
const AGENT_MONO = { "claude-code": "C", codex: "Cx", gemini: "G", aider: "A", command: ">_" };
function agentName(id) { const a = (S.agents || []).find((x) => x.id === id); return a ? a.name : id === "command" ? "Script" : id || "agent"; }
function agentState(a) {
  if (!a.installed) return { cls: "", text: "Not installed" };
  if (a.end_to_end_tested) return { cls: "ok", text: "Ready" };
  return { cls: "warn", text: "Untested" };
}
function runBadge(r, small) {
  const c = small ? " b-sm" : "";
  if (r.tripwires.length) return h("span", { class: "badge b-info" + c }, "Tripwire");
  if (r.status === "discarded") return h("span", { class: "badge b-mute" + c }, "Discarded");
  if (r.status === "applied") return h("span", { class: "badge b-ok" + c }, "Applied");
  return r.ok ? h("span", { class: "badge b-ok" + c }, "Passed") : h("span", { class: "badge b-crit" + c }, "Failed");
}
function emptyState(title, text) { return h("div", { class: "empty" }, h("b", {}, title), h("span", {}, text)); }
function countUp(el, value, key) {
  if (REDUCED || counted.has(key) || !(value > 0)) { el.textContent = String(value); return; }
  counted.add(key);
  const t0 = performance.now();
  const step = (t) => { const k = Math.min(1, (t - t0) / 900); el.textContent = String(Math.round(value * (1 - Math.pow(1 - k, 3)))); if (k < 1) requestAnimationFrame(step); };
  el.textContent = "0"; requestAnimationFrame(step);
}
function tile(key, cls, label, iconName, value, suffix, sub, meter) {
  const num = h("span", {});
  const big = h("div", { class: "tile-num" }, num, suffix ? h("small", {}, suffix) : null);
  countUp(num, value, key);
  const el = h("div", { class: `card tile ${cls}` },
    h("div", { class: "tile-top" }, h("span", { class: "label" }, label), ic(iconName, "tile-icon")),
    big, meter != null ? h("div", { class: "meter" }, h("i", {})) : null, h("div", { class: "tile-sub" }, sub));
  if (meter != null) requestAnimationFrame(() => requestAnimationFrame(() => { el.querySelector(".meter i").style.width = `${Math.round(meter * 100)}%`; }));
  return el;
}
function selectedProject() {
  const saved = store.get("aegis.project");
  return (S.projects || []).find((p) => p.path === saved) || (S.projects || [])[0] || null;
}

// ------------------------------------------------------------------ prompt bar
let promptAgent = store.get("aegis.agent") || "claude-code";
function buildPromptBars() {
  document.querySelectorAll("[data-prompt]").forEach((form) => {
    const active = document.activeElement && form.contains(document.activeElement) ? document.activeElement : null;
    if (active && active.tagName === "INPUT") return;  // do not rebuild while someone types
    const draft = form.querySelector("input")?.value || "";
    const projects = S.projects || [];
    const sel = h("select", { "aria-label": "Project", name: "project" }, ...projects.map((p) => h("option", { value: p.path }, p.name)));
    const cur = selectedProject(); if (cur) sel.value = cur.path;
    sel.disabled = !projects.length;
    sel.addEventListener("change", () => { store.set("aegis.project", sel.value); render(); });
    const chips = h("div", { class: "agent-chips", role: "group", "aria-label": "Agent" }, ...(S.agents || []).filter((a) => a.id !== "aider" || a.installed).map((a) => {
      const st = agentState(a);
      const sub = a.runs ? `${a.passed}/${a.runs} verified` : st.text.toLowerCase();
      return h("button", {
        type: "button", class: `agent-chip ${AGENT_CLASS[a.id] || ""}`, "aria-pressed": String(promptAgent === a.id), disabled: !a.installed,
        title: a.installed ? `${a.name} ${a.version}` : `${a.name} is not installed`, onclick: () => { promptAgent = a.id; store.set("aegis.agent", a.id); buildPromptBars(); },
      }, h("span", { class: "mono-badge" }, AGENT_MONO[a.id] || "?"), h("span", {}, h("b", {}, a.name.toLowerCase()), h("small", {}, sub)), h("i", { class: "st" + (a.installed ? " ok" : "") }));
    }));
    form.replaceChildren(
      ic("sparkle", "spark"), h("span", { class: "sep", "aria-hidden": "true" }),
      h("input", { type: "text", name: "prompt", placeholder: projects.length ? "What should we run next?" : "Open a project in Claude Code or run aegis once to start", "aria-label": "Task for the agent", value: draft, maxlength: "4000", autocomplete: "off" }),
      sel, chips, h("button", { class: "send", type: "submit", "aria-label": "Run in the sandbox", title: "Run in the sandbox" }, icon("send")));
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      const input = form.querySelector("input"), btn = form.querySelector(".send");
      if (!input.value.trim()) { input.focus(); toast("Describe the task first"); return; }
      btn.disabled = true;
      try { const r = await post({ kind: "run", project: sel.value, agent: promptAgent, prompt: input.value }); input.value = ""; toast(r.message); await refresh(); }
      catch (err) { toast(err.message); }
      btn.disabled = false;
    };
  });
}

// ------------------------------------------------------------------ status
function renderStatus() {
  const w = S.watch, p = $("#pill-autopilot");
  p.classList.toggle("on", w.running); p.classList.toggle("off", !w.running);
  p.lastElementChild.textContent = w.running ? "Autopilot on" : "Autopilot off";
  p.title = w.running ? `Last check ${ago(w.last_pass)}` : "Start it with: aegis watch install";
  const t = $("#tab-open"); t.hidden = !S.counts.open; t.textContent = S.counts.open > 99 ? "99+" : String(S.counts.open);
}

// ------------------------------------------------------------------ overview
function renderOverview() {
  const c = S.counts, p = selectedProject(), card = $("#ov-project");
  const head = h("div", { class: "card-head" }, h("span", { class: "label" }, "Your project"), h("a", { href: "#agents", "aria-label": "Runs of this project", class: "mini-link" }, ic("arrow")));
  if (p) {
    const name = (S.projects.length > 1)
      ? h("select", { class: "proj-select proj-name", "aria-label": "Project", onchange: (e) => { store.set("aegis.project", e.target.value); render(); } },
        ...S.projects.map((x) => h("option", { value: x.path, selected: x.path === p.path ? "" : null }, x.name)))
      : h("div", { class: "proj-name" }, p.name);
    card.replaceChildren(head, h("div", {}, name, h("div", { class: "run-sub", style: null }, shortPath(p.path))),
      h("div", { class: "chips" }, h("span", { class: "chip" }, ic("box"), `${c.jailed} / ${c.servers} jailed`),
        h("span", { class: "chip" }, ic("shield"), `${p.profiles.length} ${p.profiles.length === 1 ? "profile" : "profiles"}`),
        h("span", { class: "chip" }, ic("plug"), `${c.servers} MCP`)));
  } else {
    card.replaceChildren(head, h("div", { class: "proj-name" }, "No project yet"), h("p", {}, "Open a folder in Claude Code or run aegis in it, and it shows up here."));
  }
  const runs = S.runs, passed = runs.filter((r) => r.ok).length, failed = runs.length - passed;
  $("#ov-tiles").replaceChildren(
    tile("ov-ver", "c-lav", "Verified runs", "shield", runs.length ? Math.round((passed / runs.length) * 100) : 0, "%",
      runs.length ? `${passed} of ${runs.length} passed · ${failed} failed` : "No runs yet", runs.length ? passed / runs.length : 0),
    tile("ov-blk", "c-yellow", "Blocked", "ban", c.blocked, "", "Connections and tool calls stopped"),
    tile("ov-trip", "c-coral", "Tripwires", "alert", c.tripwires, "", c.tripwires ? "Decoy keys were touched" : "No decoy key touched"),
    tile("ov-mcp", "c-lime", "MCP servers", "box", c.jailed, c.servers ? ` / ${c.servers}` : "", c.servers ? `${c.servers - c.jailed} with full user rights` : "None configured yet"));
  const list = runs.slice(0, 3);
  $("#ov-runs").replaceChildren(...(list.length ? list.map(runRow) : [emptyState("No runs yet", "Type a task in the bar below to run your first agent in the sandbox.")]));
}
function runRow(r) {
  return h("button", { class: "run-row", type: "button", onclick: () => openRun(r) },
    h("span", { class: "play" }, icon("play")),
    h("span", {}, h("div", { class: "run-title" }, r.id), h("div", { class: "run-sub" }, `${agentName(r.agent)} · ${shortPath(r.project)} · ${ago(r.started)}`)),
    runBadge(r));
}

// ------------------------------------------------------------------ activity
const KIND = {
  project_risk: ["c-lav", "file", "Project scan"], mcp_unjailed: ["c-yellow", "box", "MCP config"], mcp_remote: ["c-coral", "cloud", "MCP config"],
  mcp_rug_pull: ["c-lime", "layers", "Rug pull"], mcp_tool_hidden: ["c-lime", "layers", "Poisoned tool"], mcp_blocked_call: ["c-yellow", "ban", "Tool firewall"],
  tripwire: ["c-coral", "alert", "Tripwire"], network_blocked: ["c-lime", "globe", "Network"], run_review: ["c-lav", "eye", "Review"],
  mcp_sampling_blocked: ["c-yellow", "zap", "Sampling"], mcp_invisible_text_stripped: ["c-lav", "search", "Hidden text"], autopilot: ["c-lav", "info", "Autopilot"],
};
const ACTION = { jail: ["Jail it", "lock"], discard: ["Discard run", "x-circle"], review_pins: ["How to review", "arrow"] };
function eventCard(e) {
  const [color, iconName, kindLabel] = KIND[e.kind] || ["c-lav", "info", e.kind];
  const fresh = seenEvents && !seenEvents.has(e.id);
  const lines = String(e.detail || "").split("\n").filter(Boolean).slice(0, 8);
  const code = h("div", { class: "ev-code" }, h("ol", {}, ...lines.map((l) => h("li", {}, l))));
  const acts = h("div", { class: "ev-actions" });
  if (e.status === "open") {
    const primary = (e.actions || [])[0];
    if (primary) {
      const [label, ico] = ACTION[primary] || [primary, "arrow"];
      acts.append(h("button", { class: "btn btn-dark btn-sm", type: "button", onclick: (ev) => doAct(e, primary, ev.currentTarget) }, ic(ico), label));
    }
    acts.append(h("button", { class: "btn btn-outline btn-sm", type: "button", onclick: (ev) => doResolve(e, "resolved", ev.currentTarget) }, "Mark handled", ic("check")));
    acts.append(h("button", { class: primary ? "text-btn" : "btn btn-outline btn-sm", type: "button", onclick: (ev) => doResolve(e, "ignored", ev.currentTarget) }, "Ignore"));
  } else {
    acts.append(h("button", { class: "btn btn-outline btn-sm", type: "button", onclick: (ev) => doResolve(e, "open", ev.currentTarget) }, "Reopen"));
  }
  const res = e.resolution ? h("div", { class: "resolution" }, `${e.status === "ignored" ? "Ignored" : "Handled"} by ${e.resolution.by} ${ago(e.resolution.time)}${e.resolution.note ? ": " + e.resolution.note : ""}`) : null;
  return h("article", { class: `event ${color}${fresh ? " fresh" : ""}${e.status !== "open" ? " done" : ""}` },
    h("div", { class: "ev-icon" }, icon(iconName)),
    h("div", { class: "ev-main" },
      h("div", { class: "ev-title-row" }, h("h3", { class: "ev-title" }, e.title), h("span", { class: "sev sev-" + e.severity }, e.severity)),
      h("div", { class: "ev-meta" }, h("span", {}, kindLabel), h("span", {}, ago(e.time)), h("span", {}, e.id)), res),
    code, acts);
}
async function doAct(e, action, btn) {
  if (action === "review_pins") {
    openInfo("Review a changed tool", [
      h("p", {}, "The server changed a tool after you approved it, so Aegis hid it. Look at what changed before you trust it again."),
      h("div", { class: "terminal" }, h("pre", {}, `$ aegis mcp-pins ${e.data?.server || "<server>"}`)),
      h("p", {}, "If the new definition is safe, reset its pin. The tool comes back on the next start of the server."),
      h("div", { class: "terminal" }, h("pre", {}, `$ aegis mcp-pins ${e.data?.server || "<server>"} --reset ${e.data?.tool || "<tool>"}`)),
    ]);
    return;
  }
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
  $("#act-list").replaceChildren(...(list.length ? list.map(eventCard) : [h("div", { class: "card c-white" }, emptyState(filter === "all" ? "No events yet" : "Nothing open", "Autopilot adds events here as soon as it finds something."))]));
}

// ------------------------------------------------------------------ agents
function renderAgents() {
  const cards = (S.agents || []).filter((a) => a.id !== "aider" || a.installed).slice(0, 3);
  $("#ag-cards").replaceChildren(...cards.map((a) => {
    const st = agentState(a);
    return h("div", { class: `card agent-card ${AGENT_CARD[a.id] || "c-lav"}` },
      h("div", { class: "ac-head" }, h("div", { class: "ac-name" }, h("span", { class: "mono-badge" }, AGENT_MONO[a.id]), h("div", {}, h("h3", {}, a.name), h("small", {}, `${a.vendor}`))),
        h("span", { class: "state " + st.cls, title: a.version }, h("i", {}), st.text)),
      h("div", { class: "mascot-host", "data-mascot": AGENT_ART[a.id] || "lock" }));
  }));
  paintMascots($("#ag-cards"));
  // current or last run
  const cur = $("#ag-current"), act = (S.active || [])[0], last = S.runs[0];
  if (act) {
    const el = Math.max(0, Date.now() / 1000 - act.started);
    cur.replaceChildren(h("div", { class: "card-head" }, h("span", { class: "label" }, "Current agent run"), h("span", { class: "state ok" }, h("i", {}), "Running")),
      h("h2", { class: "card-title" }, `${agentName(act.agent)}: ${act.prompt}`),
      h("div", { class: "current-row" }, h("span", { class: "chip" }, h("span", { class: "mono-badge" }, AGENT_MONO[act.agent] || "?"), agentName(act.agent)), h("span", { class: "chip" }, ic("box"), "Profile: default"), h("span", { class: "chip" }, ic("folder"), shortPath(act.project))),
      h("div", { class: "progress indef" }, h("i", {})), h("div", { class: "tile-sub" }, `Working in the sandbox for ${dur(el)}. Its changes will wait for your review.`));
  } else if (last) {
    cur.replaceChildren(h("div", { class: "card-head" }, h("span", { class: "label" }, "Latest agent run"), runBadge(last)),
      h("h2", { class: "card-title" }, `${agentName(last.agent)}: ${last.prompt || last.id}`),
      h("div", { class: "current-row" }, h("span", { class: "chip" }, h("span", { class: "mono-badge" }, AGENT_MONO[last.agent] || "?"), agentName(last.agent)), h("span", { class: "chip" }, ic("shield"), `Profile: ${last.profile || "default"}`), h("span", { class: "chip" }, ic("clock"), dur(last.duration))),
      h("div", { class: "tile-sub" }, "No agent is running now. Describe a task in the bar below to start one."));
  } else {
    cur.replaceChildren(h("span", { class: "label" }, "Current agent run"), h("h2", { class: "card-title" }, "Nothing running"), h("div", { class: "tile-sub" }, "Describe a task in the bar below to start an agent in the sandbox."));
  }
  const recent = S.runs.slice(0, 50), passed = recent.filter((r) => r.ok).length;
  const pct = recent.length ? Math.round((passed / recent.length) * 100) : 0;
  const pn = h("span", {}); countUp(pn, pct, "ag-perf");
  $("#ag-perf").replaceChildren(h("span", { class: "label" }, "Performance"),
    h("div", { class: "perf" }, h("div", {}, h("div", { class: "perf-num" }, pn, "%"), h("div", { class: "meter" }, h("i", { style: null })), h("div", { class: "tile-sub" }, recent.length ? `Success rate (last ${recent.length} runs)` : "No runs yet")),
      h("div", { class: "perf-side" }, h("div", {}, ic("check-circle"), `${passed} passed`), h("div", {}, ic("x-circle"), `${recent.length - passed} failed`))));
  requestAnimationFrame(() => requestAnimationFrame(() => { const m = $("#ag-perf .meter i"); if (m) m.style.width = `${pct}%`; }));
  const body = $("#ag-table tbody");
  body.replaceChildren(...S.runs.slice(0, 8).map((r) => h("tr", { class: "clickable", tabindex: "0", onclick: () => openRun(r), onkeydown: (e) => { if (e.key === "Enter") openRun(r); } },
    h("td", {}, h("span", { class: "play" }, icon("play"))),
    h("td", {}, h("span", { class: "who" }, h("span", { class: "mono-badge" }, AGENT_MONO[r.agent] || "?"), agentName(r.agent))),
    h("td", {}, r.prompt || r.id), h("td", {}, h("span", { class: "pill-prof" }, r.profile || "default")),
    h("td", { class: "nowrap" }, dur(r.duration)), h("td", {}, runBadge(r, true)))));
  $("#ag-table").parentElement.hidden = !S.runs.length;
  $("#ag-count").textContent = S.runs.length ? `${S.runs.length} total` : "";
  const em = $("#ag-empty"); em.hidden = !!S.runs.length;
  if (!S.runs.length) em.replaceChildren(emptyState("No runs yet", "Runs from the bar below, from aegis run, or from an agent calling aegis_run land here."));
  $("#ag-profiles").replaceChildren(h("div", { class: "card-head" }, h("span", { class: "label" }, "Profiles per project"), h("span", { class: "dots", "aria-hidden": "true" }, h("i", {}), h("i", {}), h("i", {}))),
    h("div", { class: "prof-list" }, ...(S.projects.length ? S.projects.slice(0, 5).map((p) => h("div", { class: "prof-row" }, h("b", {}, p.name), h("span", { class: "chip" }, ic("shield"), `${p.profiles.length} ${p.profiles.length === 1 ? "profile" : "profiles"}`)))
      : [emptyState("No projects yet", "Profiles live in .aegis/profiles of each project.")])));
}

// ------------------------------------------------------------------ mcp
const SRV_ICON = (n) => /file|fs|disk/i.test(n) ? "folder" : /git|hub|code/i.test(n) ? "code" : /sql|postgres|db|mongo|redis/i.test(n) ? "database" : /weather|cloud/i.test(n) ? "cloud" : /doc|note|wiki/i.test(n) ? "file" : "box";
function renderMcp() {
  const all = S.servers, local = all.filter((s) => !s.remote), jailed = local.filter((s) => s.jailed).length, clients = new Set(all.map((s) => s.client));
  $("#mcp-tiles").replaceChildren(
    tile("m-all", "c-lav", "MCP servers", "box", all.length, "", `Across ${clients.size} ${clients.size === 1 ? "client" : "clients"} · ${jailed} jailed`),
    tile("m-pct", "c-yellow", "Jailed", "lock", local.length ? Math.round((jailed / local.length) * 100) : 0, "%", `${jailed} of ${local.length} local servers`),
    tile("m-full", "c-coral", "Full user rights", "user", local.length - jailed, "", "Running outside the jail"),
    tile("m-rem", "c-lime", "Remote", "cloud", all.length - local.length, "", "Run on another machine"));
  const groups = {};
  for (const s of all) (groups[s.client] ||= []).push(s);
  const cards = Object.entries(groups).map(([client, list]) => h("div", { class: "card c-white client-card" },
    h("div", { class: "client-head" }, h("span", { class: "client-icon" }, icon(/project/i.test(client) ? "folder" : "terminal")), h("h3", {}, client), h("span", { class: "muted" }, `${list.length} ${list.length === 1 ? "server" : "servers"}`)),
    ...list.map((s) => {
      const state = s.remote ? h("span", { class: "srv-state st-remote" }, ic("cloud"), "Remote")
        : s.jailed ? h("span", { class: "srv-state st-jailed" }, ic("lock"), "Jailed") : h("span", { class: "srv-state st-full" }, ic("user"), "Full user rights");
      let btn = h("span", {});
      if (!s.remote && !s.jailed && s.editable) btn = h("button", { class: "srv-btn primary", type: "button", onclick: (e) => jail(s, e.currentTarget) }, "Jail it");
      else if (s.jailed && s.restorable) btn = h("button", { class: "srv-btn", type: "button", onclick: (e) => unjail(s, e.currentTarget) }, "Undo");
      const cmd = s.remote ? s.url : [s.command, ...s.args].join(" ");
      return h("div", { class: "srv-row" }, ic(SRV_ICON(s.name)), h("div", { class: "srv-main" }, h("div", { class: "srv-name" }, s.name), h("div", { class: "srv-cmd", title: cmd }, cmd)), h("div", { class: "srv-actions" }, state, btn));
    })));
  $("#mcp-clients").replaceChildren(...(cards.length ? cards : [h("div", { class: "card c-white s-12" }, emptyState("No MCP servers found", "Aegis reads the configs of Claude Code, Claude Desktop, Cursor, Windsurf, VS Code and Codex."))]));
  const rows = S.activity.slice(0, 80);
  $("#mcp-act-count").textContent = rows.length ? `${rows.length} recent entries` : "";
  $("#mcp-activity tbody").replaceChildren(...rows.map((e) => {
    let label = e.event, detail = "", cls = "b-mute";
    if (e.event === "tool_call") { label = e.allowed === false ? "Blocked" : "Call"; cls = e.allowed === false ? "b-crit" : "b-ok"; detail = `${e.tool} ${e.arguments ? JSON.stringify(e.arguments) : ""}`; }
    else if (e.event === "tool_hidden") { label = "Hidden"; cls = "b-warn"; detail = `${e.tool}: ${e.reason || ""}`; }
    else if (e.event === "start") { label = "Started"; cls = "b-info"; detail = `${(e.command || []).join(" ")} · network ${e.network}`; }
    else { cls = /blocked|stripped/.test(e.event) ? "b-crit" : "b-mute"; detail = JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => !["time", "event", "server"].includes(k)))); }
    return h("tr", {}, h("td", { class: "nowrap" }, ago(e.time)), h("td", { class: "nowrap" }, h("span", { class: "who" }, ic(SRV_ICON(e.server)), e.server)),
      h("td", { class: "nowrap" }, h("span", { class: "badge b-sm " + cls }, label)), h("td", { class: "mono" }, detail.slice(0, 300)));
  }));
  $("#mcp-activity").parentElement.hidden = !rows.length;
  const em = $("#mcp-act-empty"); em.hidden = !!rows.length;
  if (!rows.length) em.replaceChildren(emptyState("No jailed traffic yet", "Calls through aegis mcp-jail are logged here."));
}
async function jail(s, btn) { btn.disabled = true; try { toast((await post({ kind: "jail", file: s.file, jsonpath: s.jsonpath })).message); await refresh(); } catch (e) { toast(e.message); btn.disabled = false; } }
async function unjail(s, btn) { btn.disabled = true; try { toast((await post({ kind: "unjail", file: s.file, jsonpath: s.jsonpath })).message); await refresh(); } catch (e) { toast(e.message); btn.disabled = false; } }

// ------------------------------------------------------------------ autopilot, boundaries, setup
function renderAutopilot() {
  const cfg = S.watch.config;
  document.querySelectorAll("#ap-form [data-key]").forEach((el) => {
    if (document.activeElement === el) return;
    const v = cfg[el.dataset.key];
    if (el.type === "checkbox") el.checked = !!v; else el.value = String(v);
  });
}
$("#ap-form").addEventListener("change", async (ev) => {
  const el = ev.target; if (!el.dataset.key) return;
  const value = el.type === "checkbox" ? el.checked : el.dataset.key === "interval" ? Number(el.value) : el.value;
  try { await post({ kind: "config", updates: { [el.dataset.key]: value } }); toast("Saved"); await refresh(); } catch (err) { toast(err.message); }
});
function renderSetup() {
  const s = S.setup;
  $("#b-backend").textContent = s.backend;
  $("#setup-current").replaceChildren(h("span", { class: "label" }, "Current setup"),
    h("div", {},
      h("div", { class: "setup-row" }, h("span", { class: "set-icon" }, icon("box")), h("div", {}, h("b", {}, "Sandbox backend"), h("small", {}, `${s.backend} · ${s.system} ${s.machine}`)), h("span", { class: "badge b-sm " + (s.backend_ok ? "b-ok" : "b-crit") }, s.backend_ok ? "Detected" : "Missing")),
      h("div", { class: "setup-row" }, h("span", { class: "set-icon" }, icon("shield")), h("div", {}, h("b", {}, "Aegis"), h("small", {}, `${s.version} · Python ${s.python}`)), h("span", { class: "badge b-sm b-ok" }, "Installed")),
      h("div", { class: "setup-row" }, h("span", { class: "set-icon" }, icon("zap")), h("div", {}, h("b", {}, "Autopilot"), h("small", {}, S.watch.running ? `last check ${ago(S.watch.last_pass)}` : "aegis watch install")), h("span", { class: "badge b-sm " + (S.watch.running ? "b-ok" : "b-warn") }, S.watch.running ? "Running" : "Off"))));
  const os = [["Linux", "linux", "bubblewrap + seccomp"], ["Darwin", "apple", "Seatbelt"], ["Windows", "windows", "AppContainer"]];
  $("#setup-os").replaceChildren(...os.map(([sys, ico, how]) => h("div", { class: "os" + (s.system === sys ? " current" : "") }, ic(ico), h("b", {}, sys === "Darwin" ? "macOS" : sys), h("small", {}, how + (s.system === sys ? " · this machine" : "")))));
}

// ------------------------------------------------------------------ drawer & palette
function openInfo(title, nodes) {
  $("#drawer-title").textContent = title; $("#drawer-body").replaceChildren(...nodes); paintIcons($("#drawer-body")); $("#drawer").hidden = false; $("#drawer-close").focus();
}
async function openRun(r) {
  const dl = h("dl", { class: "kv" });
  const add = (k, v) => dl.append(h("dt", {}, k), h("dd", {}, v));
  add("Task", r.prompt || "(none)"); add("Project", r.project); add("Agent", agentName(r.agent)); add("Profile", r.profile || "default");
  add("Sandbox", r.backend); add("Started", when(r.started)); add("Duration", dur(r.duration)); add("Status", r.status);
  const parts = [dl];
  if (r.tripwires.length) parts.push(h("h3", {}, "Tripwire"), h("div", { class: "terminal" }, h("pre", {}, r.tripwires.join("\n"))));
  if (r.blocked.length || r.denials.length) parts.push(h("h3", {}, "Blocked"), h("div", { class: "terminal" }, h("pre", {}, [...r.blocked, ...r.denials].join("\n"))));
  const pre = h("pre", { class: "diff" }, "Loading the diff…");
  parts.push(h("h3", {}, "Changes"), pre);
  if (r.status === "pending" && r.workspace && r.changes.length) {
    const cmd = `aegis apply ${r.id} --project ${r.project}`;
    parts.push(h("p", {}, "Applying writes to your real project, so it stays a command you run after reading the diff."),
      h("div", { class: "terminal inline" }, h("pre", {}, "$ " + cmd), h("button", { class: "btn btn-ghost-dark btn-sm", type: "button", onclick: () => copy(cmd) }, ic("copy"), "Copy")));
  }
  openInfo(`Run ${r.id}`, parts);
  try {
    const d = await api(`/api/diff?key=${encodeURIComponent(r.key)}&run=${encodeURIComponent(r.id)}`);
    pre.replaceChildren(...String(d.diff || d.error || "").split("\n").map((l) => {
      const cls = l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : null;
      return h("span", cls ? { class: cls } : {}, l + "\n");
    }));
  } catch (err) { pre.textContent = err.message; }
}
const closeDrawer = () => { $("#drawer").hidden = true; };
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });

const COMMANDS = () => [
  ...PAGES.map((p) => ({ label: `Go to ${document.getElementById("page-" + p).dataset.title}`, icon: "arrow", hint: "page", run: () => { location.hash = p; } })),
  { label: "Check now", icon: "refresh", hint: "action", run: () => $("#btn-refresh").click() },
  { label: "Run an agent", icon: "play", hint: "action", run: () => { location.hash = "overview"; setTimeout(focusPrompt, 60); } },
  { label: "Copy: aegis watch install", icon: "copy", hint: "copy", run: () => copy("aegis watch install") },
  { label: "Copy: aegis probe", icon: "copy", hint: "copy", run: () => copy("aegis probe") },
  { label: "Copy: aegis scan", icon: "copy", hint: "copy", run: () => copy("aegis scan") },
];
let palIndex = 0;
function renderPalette() {
  const q = $("#palette-q").value.toLowerCase();
  const items = COMMANDS().filter((c) => c.label.toLowerCase().includes(q));
  palIndex = Math.min(palIndex, Math.max(0, items.length - 1));
  $("#palette-list").replaceChildren(...items.map((c, i) => h("li", { role: "option", "aria-selected": String(i === palIndex), onclick: () => { closePalette(); c.run(); }, onmousemove: () => { if (palIndex !== i) { palIndex = i; renderPalette(); } } }, ic(c.icon), c.label, h("small", {}, c.hint))));
  return items;
}
function openPalette() { $("#palette").hidden = false; $("#palette-q").value = ""; palIndex = 0; renderPalette(); $("#palette-q").focus(); }
function closePalette() { $("#palette").hidden = true; }
$("#btn-palette").addEventListener("click", openPalette);
$("#palette").addEventListener("click", (e) => { if (e.target.id === "palette") closePalette(); });
$("#palette-q").addEventListener("input", () => { palIndex = 0; renderPalette(); });
$("#palette-q").addEventListener("keydown", (e) => {
  const items = renderPalette();
  if (e.key === "ArrowDown") { palIndex = Math.min(items.length - 1, palIndex + 1); renderPalette(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { palIndex = Math.max(0, palIndex - 1); renderPalette(); e.preventDefault(); }
  else if (e.key === "Enter" && items[palIndex]) { closePalette(); items[palIndex].run(); }
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#palette").hidden ? openPalette() : closePalette(); }
  if (e.key === "Escape") { closeDrawer(); closePalette(); }
});
function focusPrompt() { const i = document.querySelector(".page:not([hidden]) [data-prompt] input"); if (i) { i.focus(); i.scrollIntoView({ block: "center", behavior: REDUCED ? "auto" : "smooth" }); } }

// ------------------------------------------------------------------ routing & refresh
function route() {
  const page = PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  for (const p of PAGES) document.getElementById("page-" + p).hidden = p !== page;
  const el = document.getElementById("page-" + page);  // entrance plays on navigation only, never on live refresh
  el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter");
  clearTimeout(route.t); route.t = setTimeout(() => el.classList.remove("enter"), 900);
  document.querySelectorAll(".tabs a").forEach((a) => { if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  document.querySelector(`.tabs a[data-page="${page}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  document.title = `${document.getElementById("page-" + page).dataset.title} · Aegis Jail MCP`;
  window.scrollTo({ top: 0 });
  requestAnimationFrame(paintArt);
}
function render() {
  if (!S) return;
  renderStatus(); renderOverview(); renderActivity(); renderAgents(); renderMcp(); renderAutopilot(); renderSetup(); buildPromptBars();
  paintIcons(); paintMascots();
  seenEvents = new Set(S.events.map((e) => e.id));
}
async function refresh() { try { S = await api("/api/state"); render(); } catch (err) { toast(err.message); } }

document.addEventListener("click", (e) => {
  const c = e.target.closest(".copy"); if (c) copy(c.dataset.copy);
  if (e.target.closest("[data-focus-prompt]")) focusPrompt();
});
document.querySelectorAll(".filter button").forEach((b) => b.addEventListener("click", () => {
  filter = b.dataset.filter;
  document.querySelectorAll(".filter button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  renderActivity(); paintIcons($("#act-list"));
}));
$("#btn-refresh").addEventListener("click", async (e) => {
  const b = e.currentTarget; b.classList.remove("spin"); void b.offsetWidth; b.classList.add("spin");
  try { toast((await post({ kind: "scan" })).message); await refresh(); } catch (err) { toast(err.message); }
});
window.addEventListener("hashchange", route);
let resizeT;
window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(paintArt, 150); });

paintIcons(); paintMascots(); route(); refresh();
try {
  let deb;
  const es = new EventSource("/api/stream");
  es.onmessage = () => { clearTimeout(deb); deb = setTimeout(refresh, 250); };
} catch { setInterval(refresh, 5000); }
setInterval(() => { if (S && (S.active || []).length) refresh(); else if (S) renderStatus(); }, 15000);
