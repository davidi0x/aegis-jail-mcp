import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {Background} from './components/Background';
import {Brand} from './scenes/Brand';
import {Cta} from './scenes/Cta';
import {Demo} from './scenes/Demo';
import {Features} from './scenes/Features';
import {Hook} from './scenes/Hook';
import {Review} from './scenes/Review';
import {fade} from './utils';

const OVERLAP = 12;
const SCENES: {Component: React.FC; frames: number}[] = [
  {Component: Hook, frames: 150},
  {Component: Brand, frames: 120},
  {Component: Demo, frames: 570},
  {Component: Review, frames: 180},
  {Component: Features, frames: 240},
  {Component: Cta, frames: 180},
];

export const TOTAL_FRAMES = SCENES.reduce((sum, s) => sum + s.frames, 0) - OVERLAP * (SCENES.length - 1);

const SceneFade: React.FC<{frames: number; first: boolean; last: boolean; children: React.ReactNode}> = ({frames, first, last, children}) => {
  const f = useCurrentFrame();
  const fadeIn = first ? 1 : fade(f, 0, OVERLAP);
  const fadeOut = last ? 1 : 1 - fade(f, frames - OVERLAP, OVERLAP);
  return <AbsoluteFill style={{opacity: Math.min(fadeIn, fadeOut)}}>{children}</AbsoluteFill>;
};

export const AegisDemo: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill>
      <Background />
      {SCENES.map((s, i) => {
        const start = from;
        from += s.frames - OVERLAP;
        return (
          <Sequence key={i} from={start} durationInFrames={s.frames}>
            <SceneFade frames={s.frames} first={i === 0} last={i === SCENES.length - 1}>
              <s.Component />
            </SceneFade>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
