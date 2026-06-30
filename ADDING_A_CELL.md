# Adding a new cell

This repo is the SDLClaude **reference implementation** of a cell. To bring a
new hardware cell onto the same `/v1` web + server, copy the patterns here.
For the *why* (Level/Phase/cell terminology, the recursive HTTP substrate,
port-allocation rule) see SDLClaude `ARCHITECTURE.md`; this doc is the *how*.

A "cell" = the devices that must be **coordinated to move together** (the cell
boundary rule). Each cell is one process: a FastAPI `/v1` server wrapping one
`Cell` implementation that drives the devices.

## Steps

### 1. Vendor your driver
Copy the device's L0 driver into `vendor/<codename>/` (a package) — same as
`vendor/sy01b/`, `vendor/mks_motor/`, etc. Keep the upstream files verbatim;
put any local shim (e.g. VID:PID resolution like `vendor/lmc/`) in a separate
module. Record the source repo + commit + any local change in
`vendor/VENDORED.md`. Add the driver's runtime deps to `requirements.txt`.

### 2. Write `cell/<your>_cell.py`
Copy `cell/pump_gantry_cell.py` (or `balance_linear_cell.py`) as a template
and implement the `Cell` protocol (`cell/cell_protocol.py`):

| Group | Methods |
|---|---|
| Discovery | `diagnose() -> dict`, `status() -> dict` |
| Balance | `tare()`, `read_weight()`, `set_ambient(level)` |
| Pump | `initialize()`, `move_valve()`, `aspirate()`, `dispense()`, `cycle()` |
| Stage | `home_stage()`, `move_stage(x, z, *, speed_pct, accel_pct)` |
| Lifecycle | `stop()`, `close()`, classmethod `open(config)` |

Rules:
- **Implement every method.** For a device this cell does NOT have, `raise`
  `WrongStateError(...)` (see how `PumpGantryCell` raises for the balance,
  `BalanceLinearCell` for the pump). The web greys out what isn't present.
- `open(config)` is the **composition root**: open the drivers, run any
  one-time setup, return the instance. Hold drivers as attributes (`has-a`);
  translate name/unit/order in the method bodies (Adapter pattern).
- Intra-cell imports are relative (`from .cell_protocol import ...`); driver
  imports are absolute (`from vendor.<codename> import ...`).

### 3. Raise the right `CellError` — it maps to HTTP automatically
`server/errors.py` maps each subclass to a status code, so just raise the
correct one and the web gets a stable error envelope:

| Exception | HTTP | When |
|---|---|---|
| `InvalidArgError` | 400 | bad argument (out of range, unknown level) |
| `WrongStateError` | 409 | not initialized / device absent / wrong order |
| `DeviceFaultError` | 500 | hardware fault (overload, init failure) |
| `TransportError` | 503 | serial/CAN link down |
| `CellTimeoutError` | 504 | device didn't respond in time |

### 4. Add a config + loader
- Define a `@dataclass(frozen=True, slots=True)` config (ports, serials) in
  your cell module, like `Config` / `BalanceLinearConfig`.
- Add a `_load_<shape>()` in `server/__main__.py` that parses the TOML tables
  into that config (mirror `_load` / `_load_balance_linear`).
- Add a `server/cell<N>.toml.example` (real `.toml` is gitignored). Resolve
  device addresses by **VID:PID**, not `/dev/ttyUSBn` (renumbers).

### 5. Wire the `--cell` flag
In `server/__main__.py`: add your shape to the `--cell` `choices`, and a
branch that calls your `_load_<shape>()` + `YourCell.open(cfg)` as the
factory passed to `create_app`.

### 6. Assign a port
Per the SDLClaude port table, one port per `/v1` server (cell1=17054,
cell2=17056, …). Put it in your `[server] port`.

### 7. Test with no hardware
`FakeCell` (`cell/fake_cell.py`) + the route tests in `tests/server/` exercise
the whole `/v1` contract without hardware. Add/adjust tests, then:
```bash
python -m pytest tests/server/
ruff check cell/ server/
```

### 8. Register in the web (when wiring the UI)
Add the cell to the web's cell registry (`web/src/lib/cells.ts`) with its
base URL; the operator web's switcher picks it up. Adding a cell = a registry
entry, not a new site.

## Checklist
- [ ] driver in `vendor/<codename>/` + `VENDORED.md` + `requirements.txt`
- [ ] `cell/<your>_cell.py` implements all `Cell` methods (absent → raise)
- [ ] correct `CellError` subclasses raised
- [ ] config dataclass + `_load_<shape>()` + `cell<N>.toml.example`
- [ ] `--cell` choice + factory branch in `server/__main__.py`
- [ ] port assigned
- [ ] `pytest tests/server/` + `ruff` pass
- [ ] cell registered in `web/src/lib/cells.ts`
