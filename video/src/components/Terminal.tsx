import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, MONO, SANS} from '../theme';
import {clamp} from '../utils';

export const Terminal: React.FC<{title: string; style?: React.CSSProperties; fontSize?: number; children: React.ReactNode}> = ({
  title,
  style,
  fontSize = 25,
  children,
}) => (
  <div
    style={{
      background: C.bg,
      border: `1px solid ${C.border}`,
      borderRadius: 18,
      overflow: 'hidden',
      boxShadow: '0 40px 120px rgba(0,0,0,.6), 0 0 0 1px rgba(88,166,255,.10)',
      ...style,
    }}
  >
    <div
      style={{
        height: 56,
        background: C.panel,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex',
        alignItems: 'center',
        padding: '0 22px',
        position: 'relative',
      }}
    >
      {['#ff5f56', '#ffbd2e', '#27c93f'].map((c) => (
        <div key={c} style={{width: 14, height: 14, borderRadius: 7, background: c, marginRight: 10}} />
      ))}
      <div style={{position: 'absolute', left: 0, right: 0, textAlign: 'center', color: C.dim, fontFamily: SANS, fontSize: 20}}>
        {title}
      </div>
    </div>
    <div style={{padding: '26px 34px', fontFamily: MONO, fontSize, lineHeight: '44px', color: C.text}}>{children}</div>
  </div>
);

/** Fades a row in at local frame `at`. Rows keep their space before that, so the layout never jumps. */
export const Appear: React.FC<{at: number; style?: React.CSSProperties; children: React.ReactNode}> = ({at, style, children}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [at, at + 6], [0, 1], clamp);
  const x = interpolate(f, [at, at + 9], [14, 0], clamp);
  return <div style={{opacity: o, transform: `translateX(${x}px)`, whiteSpace: 'pre', ...style}}>{children}</div>;
};

export const Cursor: React.FC<{color?: string}> = ({color = C.text}) => {
  const f = useCurrentFrame();
  return <span style={{display: 'inline-block', width: 14, height: 26, background: color, opacity: Math.floor(f / 12) % 2 ? 0 : 0.85, verticalAlign: -4, marginLeft: 2}} />;
};

export const Badge: React.FC<{color: string; children: React.ReactNode; scale?: number}> = ({color, children, scale = 1}) => (
  <span
    style={{
      display: 'inline-block',
      transform: `scale(${scale})`,
      transformOrigin: 'left center',
      padding: '0 12px',
      lineHeight: '34px',
      borderRadius: 8,
      background: `${color}26`,
      border: `1.5px solid ${color}`,
      color,
      fontWeight: 800,
      fontSize: 21,
      letterSpacing: 1.2,
      marginRight: 14,
    }}
  >
    {children}
  </span>
);
