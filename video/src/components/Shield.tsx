import React from 'react';
import {C} from '../theme';

/** The Aegis shield. `draw` (0..1) animates the outline, then the fill fades in. */
export const Shield: React.FC<{size: number; draw?: number; glow?: boolean}> = ({size, draw = 1, glow = true}) => {
  const outline = 'M0,-52 L44,-38 L44,6 C44,30 24,46 0,58 C-24,46 -44,30 -44,6 L-44,-38 Z';
  const fillOpacity = Math.max(0, Math.min(1, (draw - 0.55) / 0.45));
  return (
    <svg
      width={size}
      height={size * 1.04}
      viewBox="-52 -60 104 124"
      style={{filter: glow ? `drop-shadow(0 0 ${size * 0.18}px rgba(88,166,255,0.55))` : undefined, overflow: 'visible'}}
    >
      <path d={outline} fill={C.accent} fillOpacity={fillOpacity} />
      <path
        d={outline}
        fill="none"
        stroke={C.blue}
        strokeWidth={3.2}
        strokeLinejoin="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - Math.min(1, draw * 1.5)}
      />
      <g opacity={fillOpacity}>
        <circle cx="0" cy="-8" r="11" fill={C.bg} />
        <rect x="-5" y="-4" width="10" height="26" rx="2" fill={C.bg} />
      </g>
    </svg>
  );
};
