export const FPS = 30;
export const W = 1920;
export const H = 1080;

// Same palette as the README images, so the video and the repo look like one product.
export const C = {
  bg: '#0d1117',
  panel: '#161b22',
  border: '#30363d',
  text: '#e6edf3',
  dim: '#8b949e',
  blue: '#58a6ff',
  accent: '#1f6feb',
  green: '#3fb950',
  red: '#f85149',
  yellow: '#d29922',
  purple: '#bc8cff',
  cyan: '#39c5cf',
  navy: '#10213f',
};

// JetBrains Mono turns `-->`, `<!--` and `--` into arrows and dashes; a terminal must show them as typed.
export const NOLIG = {fontVariantLigatures: 'none', fontFeatureSettings: '"liga" 0, "calt" 0'} as const;

export const SANS = "Inter, 'SF Pro Display', -apple-system, 'Segoe UI', system-ui, sans-serif";
export const MONO = "'JetBrains Mono', 'DejaVu Sans Mono', Menlo, Consolas, monospace";
