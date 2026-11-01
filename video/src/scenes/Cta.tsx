import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Cursor} from '../components/Terminal';
import {Shield} from '../components/Shield';
import {C, MONO, NOLIG, SANS} from '../theme';
import {fade, pop, rise, typed} from '../utils';

const INSTALL = 'pip install git+https://github.com/davidi0x/aegis-jail-mcp';

export const Cta: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t1 = typed(INSTALL, f, 34, 1.6);
  const t2 = typed('aegis demo', f, 92, 0.9);
  return (
    <AbsoluteFill style={{fontFamily: SANS, alignItems: 'center', justifyContent: 'center'}}>
      <div style={{transform: `scale(${0.8 + 0.2 * pop(f, fps, 0)})`}}>
        <Shield size={150} draw={fade(f, 0, 20)} />
      </div>
      <div style={{...rise(f, fps, 8, 36), marginTop: 26, fontSize: 88, fontWeight: 800, letterSpacing: -2.8, color: '#fff', textAlign: 'center', lineHeight: 1.06}}>
        Give AI agents a task,
        <br />
        <span style={{color: C.blue}}>not your whole computer.</span>
      </div>
      <div
        style={{
          ...rise(f, fps, 26, 30),
          marginTop: 46,
          background: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          padding: '22px 36px',
          fontFamily: MONO,
          ...NOLIG,
          color: C.text,
          fontSize: 31,
          lineHeight: '52px',
          width: 1230,
          boxShadow: '0 30px 90px rgba(0,0,0,.55)',
        }}
      >
        <div>
          <span style={{color: C.green}}>$ </span>
          {t1}
          {t1.length < INSTALL.length && <Cursor />}
        </div>
        <div>
          <span style={{color: C.green}}>$ </span>
          {t2}
          {f >= 92 && <Cursor />}
        </div>
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 26, marginTop: 40, ...rise(f, fps, 110, 20)}}>
        <span style={{fontSize: 34, color: C.text, fontWeight: 600}}>github.com/davidi0x/aegis-jail-mcp</span>
        <span style={{width: 6, height: 6, borderRadius: 3, background: C.dim}} />
        <span style={{fontSize: 28, color: C.dim}}>Linux · macOS · Windows · AGPL-3.0</span>
      </div>
    </AbsoluteFill>
  );
};
