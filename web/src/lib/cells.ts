// The Phase's cell registry: what the unified web shows as selectable cells.
// `mock` cells run against an in-memory client (no backend yet). When a cell's
// hardware + /v1 server exist, set mock:false and point `base` at its server
// (e.g. via the orchestrator), and the shell will use the real api client.

export interface CellDef {
  id: string
  name: string
  /** one-line device summary shown under the name */
  sub: string
  /** dispensing cell (XZ + pump) or weighing cell (linear Y + balance) */
  kind: "dispense" | "weigh"
  /** true → in-memory mock client; false → real /v1 via the orchestrator */
  mock: boolean
}

// Phase-1 (this NUC). Balance lives on cell4 (shuttles under cell1–3).
// Everything is mock for now — hardware for cell2–4 isn't wired, and even
// cell1 runs against the dev fake until it's at the bench.
export const CELLS: CellDef[] = [
  { id: "cell1", name: "Cell 1", sub: "XZ gantry + pump", kind: "dispense", mock: true },
  { id: "cell2", name: "Cell 2", sub: "XZ gantry + pump", kind: "dispense", mock: true },
  { id: "cell3", name: "Cell 3", sub: "XZ gantry + pump", kind: "dispense", mock: true },
  { id: "cell4", name: "Cell 4", sub: "Linear Y + balance", kind: "weigh", mock: true },
]
