/**
 * Sprint reel-overlay registry — auto-discovered at build time.
 *
 * The reel-side analogue of `registry.ts`. Capabilities that *augment* the whole
 * meet reel (decorative cover/outro flourishes, progress rails, lower-thirds,
 * watermarks) are additive overlays — add each as its **own file** under
 * `sprint/reel/`, with NO edits to `MeetReel.tsx`. webpack's `require.context`
 * enumerates the folder at build time, so parallel sessions never collide.
 *
 * The structural reel surfaces stay single-owner (each lives in a distinct region
 * of `MeetReel.tsx`, so they never conflict with one another either): beat-rhythm
 * carving (R1.12), `reelStats`/`StatChips` (R1.13), `transitionFor` + transition
 * impls (R1.14), and `CoverScreen`/`OutroScreen` (R1.30).
 *
 * Drop-in contract — each module DEFAULT-exports:
 *   reel/<name>.tsx  →  { Layer: ReelLayer; order?: number }
 *
 * With the folder empty (today) the registry is empty and `MeetReel` renders
 * byte-identically to before the seam landed.
 */
import type { ComponentType } from "react";

export type ReelCtx = {
  frame: number;
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
  cardCount: number;
  meetName: string;
};

export type ReelLayer = ComponentType<{ ctx: ReelCtx }>;

declare const require: {
  context: (
    dir: string,
    recursive: boolean,
    regExp: RegExp,
  ) => { keys(): string[]; (id: string): Record<string, unknown> };
};

function load(): Record<string, unknown>[] {
  try {
    const ctx = require.context("./reel", false, /\.tsx?$/);
    return ctx.keys().map((k) => {
      const m = ctx(k) as Record<string, unknown>;
      return (m && (m.default as Record<string, unknown>)) || m;
    });
  } catch {
    return [];
  }
}

export const REEL_LAYERS: { Layer: ReelLayer; order: number }[] = load()
  .filter((m) => m && m.Layer)
  .map((m) => ({
    Layer: m.Layer as ReelLayer,
    order: typeof m.order === "number" ? (m.order as number) : 0,
  }))
  .sort((a, b) => a.order - b.order);
