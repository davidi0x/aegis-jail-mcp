import {CSSProperties} from 'react';
import {Easing, interpolate, spring} from 'remotion';

export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export const easeOut = Easing.out(Easing.cubic);

/** 0 -> 1 between `start` and `start + dur` (frames). */
export const fade = (frame: number, start: number, dur = 12) =>
  interpolate(frame, [start, start + dur], [0, 1], clamp);

/** A calm spring (no bounce) that starts at `start`. */
export const calm = (frame: number, fps: number, start: number) =>
  spring({frame: Math.max(0, frame - start), fps, config: {damping: 200}});

/** A springy pop that starts at `start`. */
export const pop = (frame: number, fps: number, start: number) =>
  spring({frame: Math.max(0, frame - start), fps, config: {damping: 12, stiffness: 140, mass: 0.7}});

/** Entrance: fade + rise. */
export const rise = (frame: number, fps: number, start: number, dist = 36): CSSProperties => {
  const s = calm(frame, fps, start);
  return {opacity: s, transform: `translateY(${(1 - s) * dist}px)`};
};

/** The first `chars-per-frame * (frame - start)` characters of `text`. */
export const typed = (text: string, frame: number, start: number, cpf = 1.2) =>
  text.slice(0, Math.max(0, Math.min(text.length, Math.floor((frame - start) * cpf))));
