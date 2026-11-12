// Shared contract between Video Turbo and scenes that Claude writes.
// Scene files may import only from 'react', 'remotion' and this file.

export type SceneWord = {text: string; frame: number};

export type SceneProps = {
  /** Length of the scene; the component may be shown a few frames longer during transitions. */
  durationInFrames: number;
  fps: number;
  text: {title: string; emphasis: string; label: string; details: string[]};
  /** Words spoken during this scene; frame is relative to the scene start. */
  words: SceneWord[];
  palette: {background: string; backgroundEnd: string; ink: string; accent: string; muted: string; contrast: string};
  fonts: {heading: string; body: string; italic: boolean};
  /** Image id -> ready-to-use URL for <Img src>. */
  images: Record<string, string>;
  /** Keep content above this y position (px); captions are drawn below it. */
  captionTop: number;
};

/** 0 -> 1 progress between two frames, clamped. */
export const progress = (frame: number, start: number, length: number) =>
  Math.max(0, Math.min(1, (frame - start) / Math.max(1, length)));

/** Frame at which a spoken phrase starts in this scene, or the fallback. */
export const wordFrame = (words: SceneWord[], phrase: string, fallback = 0) => {
  const target = phrase.trim().split(/\s+/)[0];
  const hit = words.find((word) => word.text.replace(/[^\p{L}\p{N}]/gu, '') === target.replace(/[^\p{L}\p{N}]/gu, ''));
  return hit ? hit.frame : fallback;
};
