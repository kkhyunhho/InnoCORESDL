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
