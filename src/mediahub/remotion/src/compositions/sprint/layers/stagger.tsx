// layers/stagger.tsx
//
// R1.25 — Multi-part stagger sequences (component-group cascades).
//
// The per-word reveal — kinetic_type's `wordAt` channel, the `word-cascade`
// effect — staggers individual WORDS. This additive overlay is its MACRO
// companion: it cascades the card's component GROUPS — name → event → result
// → chips — as a deliberate multi-part sequence, "beyond per-word".
//
// It is an additive overlay (it paints OVER the scene and never edits a shared
// scene component) and is gated on the brief's chosen motion language: it
// activates ONLY for the `kinetic_type` intent — the one whose whole point is
// type-carried energy — and returns null for every other intent, so every
// other card renders byte-identically to before this layer landed.
//
// The cascade is drawn as a left-margin "cascade rail" (the same side-rule
// accent vocabulary the still + motion engines already use): one accent
// segment per PRESENT group, absent groups skipped so the rail never implies
// content the card doesn't carry. Each segment fills top-down in sequence with
// a small node popping at its head — the macro beat that lands the groups one
// after another. The rail sits in the platform-safe left margin, so it never
// collides with the scene's own text on any archetype. Pure function of the
// frame, deterministic, painted in the resolved brand accent role.

import React from "react";
import { Easing, interpolate, spring } from "remotion";
import type { SceneComponent, SceneCtx } from "../registry";

// The component-group cascade order. A group contributes a rail segment ONLY
// when the card actually carries that group's content, so the rail length is
// always the number of real groups (2–4) — never an invented one.
function presentGroups(ctx: SceneCtx): string[] {
  const groups: Array<[string, boolean]> = [
    ["name", Boolean(ctx.firstName || ctx.surnameText)],
    ["event", Boolean(ctx.event)],
    ["result", Boolean(ctx.resultFinal)],
    ["chips", Boolean(ctx.label || ctx.meet || ctx.club)],
  ];
  return groups.filter(([, present]) => present).map(([id]) => id);
}

const START = 5; // first beat at 0.17s @30fps — never frame 0 (jump-cut guard)
const STAGGER = 5; // group-scale cascade step — coarser than the per-word 2–4f
const FILL = 10; // each segment fills over ~0.33s — the workhorse range

const Layer: SceneComponent = ({ ctx }) => {
  // Gate: the group cascade is the macro companion to the per-word reveal, so
  // it rides ONLY on kinetic_type. Every other intent stays byte-identical.
  if ((ctx.card.motionIntent || "") !== "kinetic_type") {
    return null;
  }

  const groups = presentGroups(ctx);
  // A lone group can't "cascade" — stay inert rather than draw a single tick.
  if (groups.length < 2) {
    return null;
  }

  const { frame, fps, roles, ts, width, height } = ctx;
  const accent = roles.accent || roles.onGround;

  // The rail spans the central safe band (clear of the platform chrome zones),
  // divided into one slice per present group.
  const top = height * 0.2;
  const bottom = height * 0.8;
  const slice = (bottom - top) / groups.length;
  const railLeft = Math.max(24, Math.round(width * 0.035));
  const railW = Math.max(4, Math.round(6 * ts));
  const nodeD = Math.max(12, Math.round(18 * ts));

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      {groups.map((id, i) => {
        const start = START + i * STAGGER;
        const local = Math.max(0, frame - start);
        // Connective fill: scaleY 0→1 from the top — the workhorse easing.
        const fill = interpolate(local, [0, FILL], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        // Arrival node: a physical spring pop — a second, percussive easing
        // that differentiates each group's landing from the connective fill.
        const pop = spring({
          frame: local,
          fps,
          config: { damping: 14, stiffness: 170, mass: 0.6 },
        });
        const nodeScale = interpolate(pop, [0, 1], [0.4, 1], {
          extrapolateRight: "clamp",
        });
        const nodeOpacity = interpolate(local, [0, 4], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const segTop = top + i * slice;
        return (
          <React.Fragment key={id}>
            {/* Connective rail segment */}
            <div
              style={{
                position: "absolute",
                left: railLeft,
                top: segTop,
                width: railW,
                height: Math.round(slice * 0.82),
                background: accent,
                opacity: 0.85,
                transform: `scaleY(${fill})`,
                transformOrigin: "top center",
              }}
            />
            {/* Arrival node at the segment head */}
            <div
              style={{
                position: "absolute",
                left: railLeft + railW / 2 - nodeD / 2,
                top: segTop - nodeD / 2,
                width: nodeD,
                height: nodeD,
                borderRadius: "50%",
                background: accent,
                opacity: nodeOpacity,
                transform: `scale(${nodeScale})`,
              }}
            />
          </React.Fragment>
        );
      })}
    </div>
  );
};

export default { Layer, order: 30 };
