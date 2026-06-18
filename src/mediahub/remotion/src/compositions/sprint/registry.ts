/**
 * Sprint extension registries — auto-discovered at build time.
 *
 * The generator-upgrade sprint (roadmap `R1.*`) lets every parallel session add
 * a new motion capability as its OWN file in one of the folders below, with NO
 * edits to `StoryCard.tsx` / `MeetReel.tsx`. Remotion's bundler is webpack-based,
 * so `require.context` enumerates each folder at build time: a new file is picked
 * up automatically and two sessions never touch the same file. That is what makes
 * the 60-session sprint merge-conflict-free on the motion side.
 *
 * Drop-in contract — each module DEFAULT-exports exactly one of:
 *
 *   intents/<name>.ts   →  { name: string; program: IntentProgram }
 *   patterns/<name>.ts  →  { name: string; pattern: (roles: Roles) => string }
 *   accents/<name>.tsx  →  { name: string; decoration: AccentDecoration }
 *   springs/<name>.ts   →  { name: string; config: SpringConfig }
 *   scenes/<name>.tsx   →  { archetype: string; Scene: SceneComponent }
 *   layers/<name>.tsx   →  { Layer: SceneComponent; order?: number }
 *
 * `name` MUST equal the brief token the still engine emits for that capability
 * (intent / background_style / accent_style / mood) or, for scenes, the archetype
 * id — so motion stays in lock-step with the approved still. The motion-parity
 * test scans these folders too, so a registered intent counts as "executed".
 *
 * Everything here is additive: with the folders empty (today) every registry is
 * empty and the compositions render byte-identically to before the seam landed.
 */
import type { ComponentType, ReactNode } from "react";
import type { AnimChannels, Roles, SceneCtx } from "../StoryCard";

// Re-exported so every sprint module imports its types from one place
// (`../registry`) regardless of which subfolder it lives in.
export type { AnimChannels, Roles, SceneCtx } from "../StoryCard";

export type IntentProgram = (
  frame: number,
  fps: number,
  durationInFrames: number,
  mood: string,
  base: AnimChannels,
) => AnimChannels;

export type SpringConfig = { damping: number; stiffness: number; mass: number };

export type AccentDecoration = (
  roles: Roles,
  opacity: number,
  width: number,
  height: number,
) => ReactNode;

export type SceneComponent = ComponentType<{ ctx: SceneCtx }>;

// webpack injects require.context at build time; tsc only needs the symbol to
// exist. Outside webpack (e.g. a bare ts-node import) the try/catch below yields
// empty registries rather than throwing.
declare const require: {
  context: (
    dir: string,
    recursive: boolean,
    regExp: RegExp,
  ) => { keys(): string[]; (id: string): Record<string, unknown> };
};

function load(dir: () => { keys(): string[]; (id: string): Record<string, unknown> }): Record<string, unknown>[] {
  try {
    const ctx = dir();
    return ctx.keys().map((k) => {
      const m = ctx(k) as Record<string, unknown>;
      return (m && (m.default as Record<string, unknown>)) || m;
    });
  } catch {
    return [];
  }
}

const intentMods = load(() => require.context("./intents", false, /\.tsx?$/));
const patternMods = load(() => require.context("./patterns", false, /\.tsx?$/));
const accentMods = load(() => require.context("./accents", false, /\.tsx?$/));
const springMods = load(() => require.context("./springs", false, /\.tsx?$/));
const sceneMods = load(() => require.context("./scenes", false, /\.tsx?$/));
const layerMods = load(() => require.context("./layers", false, /\.tsx?$/));

function byName<T>(mods: Record<string, unknown>[], key: string): Record<string, T> {
  const out: Record<string, T> = {};
  for (const m of mods) {
    const name = m?.name;
    if (typeof name === "string" && m[key] != null) out[name] = m[key] as T;
  }
  return out;
}

export const EXTRA_INTENTS = byName<IntentProgram>(intentMods, "program");
export const EXTRA_PATTERNS = byName<(roles: Roles) => string>(patternMods, "pattern");
export const EXTRA_ACCENTS = byName<AccentDecoration>(accentMods, "decoration");
export const EXTRA_SPRINGS = byName<SpringConfig>(springMods, "config");

export const EXTRA_SCENES: Record<string, SceneComponent> = (() => {
  const out: Record<string, SceneComponent> = {};
  for (const m of sceneMods) {
    const arch = m?.archetype;
    if (typeof arch === "string" && m.Scene) out[arch] = m.Scene as SceneComponent;
  }
  return out;
})();

export const EXTRA_LAYERS: { Layer: SceneComponent; order: number }[] = layerMods
  .filter((m) => m && m.Layer)
  .map((m) => ({
    Layer: m.Layer as SceneComponent,
    order: typeof m.order === "number" ? (m.order as number) : 0,
  }))
  .sort((a, b) => a.order - b.order);
