// Rig constants, unit conversions, and motion-timing helpers. Display units
// are unified (see SDLClaude DESIGN_SYSTEM.md): length mm, speed mm/s, volume
// µL, flow µL/s, weight g, time s. Native units (RPM, pulses/s) live here and
// are converted before display.

export const SYRINGE_UL = 125
export const X_MAX_MM = 450 // per-axis travel on this rig
export const Z_MAX_MM = 450
export const LEAD_MM = 10 // ball-screw lead (mks_motor _mm_per_turn)
export const MAX_RPM = 3000 // SR_vFOC max
export const MAX_MM_S = (MAX_RPM * LEAD_MM) / 60 // 500 mm/s at 100% speed
export const AMBIENT_LEVELS = ["very_stable", "stable", "unstable", "very_unstable"]

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
export const clamp = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), hi)

// ── Pump plunger speed (SY-01B manual §4.5.3) ──────────────────────────────
// Top speed V is in pulses/sec (guaranteed range 1–6000); seconds-per-stroke
// at default ramping ≈ STROKE_PULSES / V (from the S-code table: 6000→2 s,
// 4000→3 s, 2000→6 s, 1000→12 s). So flow = SYRINGE_UL / (STROKE_PULSES / V).
export const PUMP_VMAX = 6000 // V command guaranteed max (pulses/sec)
export const STROKE_PULSES = 12000 // sec/stroke ≈ STROKE_PULSES / V
export const MAX_UL_S = (SYRINGE_UL * PUMP_VMAX) / STROKE_PULSES // 62.5 µL/s
// Time (ms) to move `uL` of plunger travel at `pct`% of top speed.
export function plungerMs(uL: number, pct: number): number {
  const flow = (MAX_UL_S * clamp(pct, 1, 100)) / 100
  return (clamp(uL, 0, SYRINGE_UL) / flow) * 1000
}

// ── Valve rotor (M05 bi-pass) ──────────────────────────────────────────────
// Two parallel channels, two states 90° apart; the rotor takes the shortest
// path and switching between adjacent states is ≤640 ms (manual spec sheet).
export const VALVE_MS = 640

// Homing runs at a fixed slow speed (xz_stage.HOMING_SPEED_RPM); accel uses a
// gentle default. Z homes first (up), then X — both back to the 0 origin.
export const HOME_RPM = 180
export const HOME_ACC = 150
export const HOME_MM_S = (HOME_RPM * LEAD_MM) / 60 // 30 mm/s

// Real move time (ms) for a trapezoidal profile, per the MKS manual §9.1:
// linear speed = rpm*lead/60 mm/s; speed steps 1 RPM every (256-acc)*50µs,
// so a = [1/((256-acc)*50µs)] RPM/s → mm/s². acc=0 = no ramp.
export function moveTimeMs(distMm: number, rpm: number, acc: number): number {
  const d = Math.abs(distMm)
  const vmax = (rpm * LEAD_MM) / 60
  if (d === 0 || vmax <= 0) return 0
  if (acc <= 0) return (d / vmax) * 1000
  const aRpmPerS = 1 / (((256 - acc) * 50) / 1e6)
  const aMm = (aRpmPerS * LEAD_MM) / 60
  const tRamp = vmax / aMm
  const dRamp = 0.5 * aMm * tRamp * tRamp
  const t =
    2 * dRamp <= d ? 2 * tRamp + (d - 2 * dRamp) / vmax : 2 * Math.sqrt(d / aMm)
  return t * 1000
}

// Status palette (Okabe-Ito) for inline SVG fills/strokes.
export const OK = "var(--color-status-ok)" // blue
export const WARN = "var(--color-status-warn)" // orange
