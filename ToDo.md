# ToDo

Append-only task log (SDLClaude convention). Newest at the bottom.

## 2026-07-09 | Make gantry `serial_z` required once multiple gantries share a host
- [ ] Flip `[stage] serial_z` from optional to **required** for pump+gantry
      cells when more than one gantry runs on the same host.
- **Why**: `serial_z` is optional today (single-gantry convenience) — if
      omitted, `PumpGantryCell.open` falls back to `open_xz`'s "X by serial,
      the two remaining FTDI = Z" shortcut. That shortcut is safe **only** with
      one gantry's 3 adapters on the host; with several gantries it can grab
      another cell's Z adapters.
- **How**: in `server/__main__.py` `_load`, raise if a pump+gantry config has
      no `serial_z` (i.e. require the explicit two Z serials), so a
      multi-gantry host can't silently use the leftover-two fallback. Keep the
      fallback only if we ever want a documented single-gantry mode.
- See `cell/pump_gantry_cell.py` `Config.motor_serial_z` / `open()`,
      `LearnedPatterns.md`, and the caveat in `CLAUDE.md` (XZ motors row).

## 2026-07-09 | Apply the gantry e-stop smart plug to real cell.toml once installed
- [ ] Uncomment + set `[plug] estop_target` in the real `cellN.toml` for
      cell1–3 once the emergency-stop smart plugs are physically installed and
      declared in `vendor/SmartPlugController/device_list.md`.
- **Plan**: each XZ gantry's power supply gets a smart plug for hardware
      e-stop. cell1 = its own plug; cell2 + cell3 **share one PSU → one shared
      plug** (same `estop_target`, so cutting it stops both).
- **Now**: only placeholders are in the `.example` files (commented out); the
      real per-cell configs and the cell↔plug wiring come later.
- **Next (separate)**: decide *when* the plug fires (trigger situations) and
      wire `PumpGantryCell` to switch it off (`SmartPlugController.switch(
      turn_on=False)`), e.g. from `stop()` / the CAN-fault handler.

## 2026-07-09 | Gantry e-stop plug — finalized trigger list
Situations that cut the gantry PSU plug (`switch(turn_on=False)`), decided:
- [ ] **CAN fault / `stop_group_hard` fails** — the group-stop interlock can't
      reach a motor to send F7 (= a paired-Z desync it can't halt). Fire from
      the CAN-fault hook, exactly where the driver already logs "CUT POWER".
- [ ] **Web "Stop All"** — the existing button → each cell's `stop()` → software
      group stop **and** plug off.
- [ ] **Server graceful shutdown** — SIGINT / SIGTERM / uncaught exception /
      lifespan close cut the plug (signal handlers + lifespan `finally`).
      **SIGKILL / power-loss is NOT covered** — chose graceful-only, no external
      watchdog (would be heartbeat-flavored, previously rejected).

Dropped: motor stall (detection unreliable); collision / over-current (only
trips on a hard hit); serial mismatch (`MKSMotor.open` fails at startup →
nothing ever moves); Z-drop (holds fine unpowered); shared-plug collateral
(cell2 e-stop also kills cell3 — accepted).

**Implementation mapping** (build when the plugs are installed, then verify
end-to-end — decided NOT to scaffold early since it's untestable without a plug):
- **Hold the plug**: `PumpGantryCell.open()` — if `[plug] estop_target` set,
  `SmartPlugController.from_files()` + `resolve_targets(target)`; power it ON at
  open. Missing target / `device_list.md` / `secure.env` → plug = None (fully
  inert, log a notice) so plug-less cells still run.
- **Helper `_cut_power()`**: `asyncio.run(switch(entry, turn_on=False))`,
  best-effort + short timeout, never raises/blocks, idempotent.
- **Trigger 1 (CAN fault)**: register `mks_motor.set_group_fault_hook` → call
  `_cut_power()` (the point where the driver logs "CUT POWER"; mirrors ESP32
  `bridge.py` `emergency_shutdown`).
- **Trigger 2 (Stop All)**: `stop()` runs the software group stop (F7) FIRST,
  then `_cut_power()`.
- **Trigger 3 (graceful shutdown)**: SIGINT/SIGTERM handlers + lifespan
  `finally` (`cell.close()`) → `_cut_power()`. SIGKILL/power-loss uncovered.
- **Order**: soft F5/F7 is always first; the plug cut is the last-resort
  escalation.
