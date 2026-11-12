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

const RTL_LETTER = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/;

/**
 * Split a line into words for word-by-word animation. Runs of non-Arabic words (e.g. "Claude Desktop")
 * inside Arabic text stay together as one group: animating them separately in right-to-left layout reverses
 * their order. Lines without Arabic are split into single words.
 */
export const wordGroups = (line: string) => {
  const words = line.trim().split(/\s+/).filter(Boolean);
  if (!RTL_LETTER.test(line)) return words;
  const groups: string[] = [];
  let latin = false;
  for (const word of words) {
    const isLatin = !RTL_LETTER.test(word);
    if (isLatin && latin && groups.length) groups[groups.length - 1] += ' ' + word;
    else groups.push(word);
    latin = isLatin;
  }
  return groups;
};
