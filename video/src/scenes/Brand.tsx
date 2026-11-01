import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Shield} from '../components/Shield';
import {C, SANS} from '../theme';
import {fade, pop, rise} from '../utils';

export const Brand: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const chips: [string, string][] = [
    ['Linux · macOS · Windows', C.blue],
    ['Open source', C.green],
    ['Zero dependencies', C.purple],
  ];
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: SANS}}>
      <div style={{transform: `scale(${0.72 + 0.28 * pop(frame, fps, 0)})`}}>
        <Shield size={250} draw={fade(frame, 0, 36)} />
      </div>
      <div style={{marginTop: 38, fontSize: 142, fontWeight: 800, letterSpacing: -4.5, color: '#fff', ...rise(frame, fps, 26, 44)}}>
        Aegis <span style={{color: C.blue}}>Jail MCP</span>
      </div>
      <div style={{marginTop: 14, fontSize: 48, color: '#c9d1d9', ...rise(frame, fps, 44, 30)}}>
        Give AI agents a task, not your whole computer.
      </div>
      <div style={{marginTop: 46, display: 'flex', gap: 18}}>
        {chips.map(([label, color], i) => (
          <div
            key={label}
            style={{
              ...rise(frame, fps, 64 + i * 8, 24),
              padding: '0 26px',
              lineHeight: '56px',
              borderRadius: 28,
              border: `1.5px solid ${color}`,
              background: `${color}1f`,
              color,
              fontSize: 25,
              fontWeight: 600,
            }}
          >
            {label}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
