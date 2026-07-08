# Vendored drivers

All hardware drivers are copied in-repo so InnoCORESDL runs
standalone (**copied, never git submodules** — no pip-git, no sibling
clones). Imported as `vendor.<name>` (e.g.
`from vendor.sy01b import SyringePumpController`). Core-cell runtime deps
(`pyserial`, `pyftdi`) plus demo-only deps (`ika`, `python-kasa`) are in
`requirements.txt`.

| Vendored path | Upstream | Commit | Local changes |
|---|---|---|---|
| `sy01b/` | kkhyunhho/SyringePumpController (`src/sy01b`) | `5ae0d56` | `__init__.py`: absolute self-import → relative (`from .syringe_pump_controller`). `cli/` left verbatim (not on the cell's import path). |
| `entris_ii/` | kkhyunhho/PrecisionScaleController (`src/entris_ii`) | `ad85d6c` | `__init__.py`: absolute self-import → relative (`from .precision_scale_controller`). `cli/` left verbatim. **`precision_scale_controller.py`: `calibrate_internal_very_unstable` sends `Esc s3_` (CANCEL) on failure/timeout so an aborted internal cal doesn't leave the balance beeping until a power cycle (re-apply on re-vendor; upstream to PrecisionScaleController).** |
| `mks_motor/` | kkhyunhho/ESP32S3BOX3MotorController (`src/mks_motor`) | `c156a37` | none — already uses relative imports. |
| `lmc/linear_motor_controller.py` | coport-uni/LinearMotorController (`LinearMotorController.py`) | `98d5ccc` | `# ruff: noqa` header. Raw MINAS standard-protocol RS485 driver (Pr5.37=0); verbatim. Includes the `PIDController` speed-control loop (`move_to_mm`). **cell4 uses this.** |
| `lmc/__init__.py` | (ours, not vendored) | — | Thin codename shim over `linear_motor_controller.py` adding VID:PID port resolution (the one driver whose upstream lacks it). Imported as `vendor.lmc`. |
| `HotplateController/hotplate_controller/` | coport-uni/HotplateController (`hotplate_controller/`) | `d37bfbb` | **Demo only** (`demo_scenario/`). Copied the `hotplate_controller` package (dropped `main.py`, `claude_test/`); added `HotplateController/__init__.py`. Needs `ika`. Imported as `vendor.HotplateController.hotplate_controller` (CamelCase dir kept so `demo_scenario` matches the upstream layout). |
| `SmartPlugController/smartplugcontroller.py` | coport-uni/SmartPlugController (`smartplugcontroller.py`) | `51eb6a2` | **Demo only.** Copied the flat driver module only (dropped `plug_server/`, `docs/esp32s3/`, `main.py`); added `SmartPlugController/__init__.py`. Needs `python-kasa`. Reads credentials from `vendor/SmartPlugController/secure.env` (gitignored). |

## Updating a driver

1. Re-copy the package/module from its upstream source into `vendor/`.
2. Re-apply the "Local changes" above (the relative-import fix for the
   package `__init__.py` files).
3. Bump the commit in this table.

Keep `cli/` subpackages as-is — they aren't on the cell's import path, so
their unmodified absolute self-imports never execute.
