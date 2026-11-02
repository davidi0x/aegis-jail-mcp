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
