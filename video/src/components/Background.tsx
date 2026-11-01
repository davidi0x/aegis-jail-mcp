import React from 'react';
import {AbsoluteFill, interpolateColors, useCurrentFrame} from 'remotion';
import {C} from '../theme';

// Glow colour over the whole film: alarm red at the start, brand blue from the logo on.
const GLOW_FRAMES = [0, 120, 165, 1250, 1290];
const GLOW_COLORS = [
  'rgba(248,81,73,0.34)',
  'rgba(248,81,73,0.34)',
  'rgba(31,111,235,0.38)',
  'rgba(31,111,235,0.38)',
  'rgba(63,185,80,0.20)',
];

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const glow = interpolateColors(frame, GLOW_FRAMES, GLOW_COLORS);
  const drift = (frame * 0.4) % 64;
  return (
    <AbsoluteFill style={{background: `linear-gradient(135deg, ${C.bg} 0%, ${C.navy} 100%)`}}>
      <AbsoluteFill style={{background: `radial-gradient(ellipse 62% 52% at 50% 36%, ${glow} 0%, transparent 70%)`}} />
      <AbsoluteFill
        style={{
          opacity: 0.07,
          backgroundImage: `linear-gradient(${C.blue} 1px, transparent 1px), linear-gradient(90deg, ${C.blue} 1px, transparent 1px)`,
          backgroundSize: '64px 64px',
          backgroundPosition: `${drift}px ${drift}px`,
        }}
      />
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, transparent 52%, rgba(0,0,0,0.6) 100%)'}} />
    </AbsoluteFill>
  );
};
