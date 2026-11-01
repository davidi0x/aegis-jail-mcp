import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, MONO, SANS} from '../theme';
import {calm, rise} from '../utils';

const CARDS = [
  {word: 'Prove it.', cmd: 'aegis probe', title: 'Check that the walls hold', result: '15 / 15 checks pass', color: C.green},
  {word: 'Shrink it.', cmd: 'aegis optimize', title: 'Find the smallest permissions', result: 'no home dir · no ~/.ssh · no internet', color: C.blue},
  {word: 'Jail it.', cmd: 'aegis mcp-jail -- npx …', title: 'Sandbox any MCP server', result: 'rug-pull protection · tool firewall', color: C.purple},
  {word: 'Scan it.', cmd: 'aegis scan ./repo', title: 'Check a repo before you trust it', result: '9 high-risk findings in a hostile repo', color: C.yellow},
];

export const Features: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{fontFamily: SANS, alignItems: 'center', justifyContent: 'center'}}>
      <div style={{display: 'flex', gap: 28, fontSize: 84, fontWeight: 800, letterSpacing: -2.5, marginBottom: 54}}>
        {CARDS.map((c, i) => (
          <span key={c.word} style={{...rise(f, fps, 6 + i * 12, 30), color: c.color}}>
            {c.word}
          </span>
        ))}
      </div>
      <div style={{display: 'grid', gridTemplateColumns: '820px 820px', gap: 36}}>
        {CARDS.map((c, i) => {
          const s = calm(f, fps, 34 + i * 26);
          const float = Math.sin((f + i * 17) / 24) * 4;
          return (
            <div
              key={c.cmd}
              style={{
                opacity: s,
                transform: `translateY(${(1 - s) * 50 + float}px) scale(${0.96 + 0.04 * s})`,
                background: C.panel,
                border: `1.5px solid ${c.color}66`,
                borderRadius: 22,
                padding: '30px 36px',
                boxShadow: `0 24px 70px rgba(0,0,0,.45), 0 0 0 1px ${c.color}22, 0 0 50px ${c.color}14`,
              }}
            >
              <div style={{fontFamily: MONO, fontSize: 25, color: c.color, marginBottom: 14}}>$ {c.cmd}</div>
              <div style={{fontSize: 42, fontWeight: 800, color: '#fff', letterSpacing: -1}}>{c.title}</div>
              <div style={{fontSize: 28, color: C.dim, marginTop: 10}}>
                <span style={{color: c.color, fontWeight: 700}}>→ </span>
                {c.result}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
