import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Appear, Cursor, Terminal} from '../components/Terminal';
import {C, MONO, NOLIG, SANS} from '../theme';
import {rise, typed} from '../utils';

export const Review: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const diffCmd = typed('aegis diff', f, 14, 0.9);
  const applyCmd = typed('aegis apply', f, 92, 0.9);
  const points: [string, string][] = [
    ['Risky files (hooks, CI, .mcp.json) need a yes', C.yellow],
    ['No writes through symlinks or outside the project', C.blue],
    ['A run that tripped a wire is always reviewed', C.red],
  ];
  return (
    <AbsoluteFill style={{padding: '0 110px', fontFamily: SANS, justifyContent: 'center'}}>
      <div style={{display: 'flex', gap: 80, alignItems: 'center'}}>
        <div style={{width: 780}}>
          <div style={{...rise(f, fps, 4, 40), fontSize: 112, fontWeight: 800, letterSpacing: -3.5, color: '#fff', lineHeight: 1.02}}>You review.</div>
          <div style={{...rise(f, fps, 16, 40), fontSize: 112, fontWeight: 800, letterSpacing: -3.5, color: C.blue, lineHeight: 1.02}}>You decide.</div>
          <div style={{...rise(f, fps, 34, 26), marginTop: 30, fontSize: 36, color: C.dim, lineHeight: 1.45}}>
            Your real project stays untouched until you run <span style={{color: C.text, fontFamily: MONO, ...NOLIG}}>aegis apply</span>.
          </div>
          <div style={{marginTop: 34}}>
            {points.map(([t, color], i) => (
              <div key={t} style={{...rise(f, fps, 58 + i * 12, 20), display: 'flex', alignItems: 'center', gap: 16, fontSize: 27, color: C.text, margin: '15px 0'}}>
                <span style={{width: 14, height: 14, borderRadius: 7, background: color, boxShadow: `0 0 14px ${color}`, flexShrink: 0}} />
                {t}
              </div>
            ))}
          </div>
        </div>

        <div style={{flex: 1, ...rise(f, fps, 6, 40)}}>
          <Terminal title="~/shop" style={{height: 660}} fontSize={28} lineHeight={48}>
            <div>
              <span style={{color: C.green}}>$ </span>
              {diffCmd}
              {f < 92 && f < 30 && <Cursor />}
            </div>
            <Appear at={34} style={{color: C.dim}}>--- a/src/calc.py</Appear>
            <Appear at={38} style={{color: C.dim}}>+++ b/src/calc.py</Appear>
            <Appear at={44} style={{color: C.dim}}>{'@@ def add(a, b):'}</Appear>
            <Appear at={52} style={{color: C.red, background: 'rgba(248,81,73,.10)'}}>-    return a - b  # BUG</Appear>
            <Appear at={60} style={{color: C.green, background: 'rgba(63,185,80,.12)'}}>+    return a + b</Appear>
            <div style={{marginTop: 14}}>
              <span style={{color: C.green}}>$ </span>
              {applyCmd}
              {f >= 92 && f < 112 && <Cursor />}
            </div>
            <Appear at={118} style={{color: C.green, fontWeight: 700}}>✓ Applied 1 change to ~/shop</Appear>
          </Terminal>
        </div>
      </div>
    </AbsoluteFill>
  );
};
