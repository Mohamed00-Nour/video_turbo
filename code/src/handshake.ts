/**
 * Organic handheld camera shake (handshake effect)
 * Generates continuous multi-frequency translation and rotation
 */
export const getHandshake = (frame: number, seed: number = 0) => {
  const t = (frame + seed * 43.7) / 30;

  // Multi-frequency harmonic wiggle:
  // Combines slow organic breathing, medium camera sway, and micro-tremor
  const dx =
    Math.sin(t * 2.1) * 7.5 +
    Math.sin(t * 5.3) * 4.2 +
    Math.cos(t * 11.7) * 1.8;

  const dy =
    Math.cos(t * 1.8) * 6.5 +
    Math.cos(t * 4.7) * 3.8 +
    Math.sin(t * 10.3) * 1.5;

  const rot =
    Math.sin(t * 1.6) * 0.8 +
    Math.cos(t * 4.9) * 0.35;

  return { dx, dy, rot };
};
