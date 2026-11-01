import React from 'react';
import {Composition} from 'remotion';
import {AegisDemo, TOTAL_FRAMES} from './AegisDemo';
import {FPS, H, W} from './theme';

export const Root: React.FC = () => (
  <Composition id="AegisDemo" component={AegisDemo} durationInFrames={TOTAL_FRAMES} fps={FPS} width={W} height={H} />
);
