import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, SANS} from '../theme';
import {rise} from '../utils';

const Hot: React.FC<{children: React.ReactNode}> = ({children}) => (
  <span style={{color: C.red, fontWeight: 800, textShadow: '0 0 28px rgba(248,81,73,.55)'}}>{children}</span>
);

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const lines: [string, string, string][] = [
    ['…with your ', 'SSH keys', '.'],
    ['…your ', 'cloud credentials', '.'],
    ['…every ', 'token', ' in your shell.'],
  ];
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: SANS}}>
      <div style={{width: 1500}}>
        <div style={{...rise(frame, fps, 6, 50), fontSize: 120, fontWeight: 800, color: '#fff', letterSpacing: -3.5, lineHeight: 1.04}}>
          Your AI agent
          <br />
          runs <Hot>as you.</Hot>
        </div>
        <div style={{marginTop: 56}}>
          {lines.map(([a, b, c], i) => (
            <div key={b} style={{...rise(frame, fps, 56 + i * 20, 30), fontSize: 60, fontWeight: 500, color: C.dim, lineHeight: 1.42}}>
              {a}
              <Hot>{b}</Hot>
              {c}
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
