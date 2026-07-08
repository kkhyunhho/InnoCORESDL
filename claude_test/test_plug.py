# test_plug.py
# Standalone smart-plug (Tapo P110M) test — independent of the motor, pump,
# and hotplate. Exercises the vendor.SmartPlugController path end to end:
#   credentials → device_list.md → reach the plug → read status → (optional) toggle.
#
# PREREQUISITES (the plug is a LAN device, not USB):
#   * TP-Link cloud credentials, EITHER:
#       - export KASA_USERNAME=... KASA_PASSWORD=...   (same names as the kasa CLI)
#       - or create vendor/SmartPlugController/secure.env with:
#           KASA_USERNAME=you@example.com
#           KASA_PASSWORD=yourpassword
#     They must be the TP-Link account the plugs are registered to.
#   * The plug must be reachable on the LAN (this bench: plug2 = 192.168.1.79).
#
# Run (ics env, or any env with python-kasa):
#   /opt/conda/envs/ics/bin/python claude_test/test_plug.py

import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
if os.path.isdir(_REPO_ROOT) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from vendor.SmartPlugController.smartplugcontroller import (  # noqa: E402
    ControllerError,
    SmartPlugController,
)

# ── Configuration ───────────────────────────────────────────────────────────
PLUG_TARGET = "plug1"    # device name / IP / "all" from device_list.md
# True  → read status only (safe: nothing is energized).
# False → also run a switch test: turn ON, read back, wait, turn OFF, read back.
READ_ONLY = False
TOGGLE_PAUSE_S = 2.0     # how long to leave the plug ON during the switch test
# ────────────────────────────────────────────────────────────────────────────


def _print_report(r):
    if r.ok:
        state = "ON" if r.is_on else "OFF"
        print(f"  {r.entry.name} @ {r.entry.ip}: {state}  "
              f"(model={r.model}, fw={r.firmware}, mac={r.mac})")
    else:
        print(f"  {r.entry.name} @ {r.entry.ip}: [ERROR] {r.error}")


def _print_switch(r):
    if r.ok:
        print(f"  {r.entry.name}: {r.before} -> {r.after}")
    else:
        print(f"  {r.entry.name}: [ERROR] {r.error}")


def main():
    print("Building smart-plug controller (credentials + device_list.md)...")
    try:
        ctrl = SmartPlugController.from_files()
    except ControllerError as exc:
        print(f"[FAIL] {exc}")
        print("  → set KASA_USERNAME / KASA_PASSWORD (or create "
              "vendor/SmartPlugController/secure.env) and re-run.")
        return

    entries = ctrl.resolve_targets(PLUG_TARGET)
    if not entries:
        print(f"[FAIL] no plug matches {PLUG_TARGET!r} in device_list.md")
        return
    print(f"Target(s): {', '.join(e.name + ' @ ' + e.ip for e in entries)}")

    print("\nReading current status...")
    reports = asyncio.run(
        _gather(ctrl.read(e) for e in entries)
    )
    for r in reports:
        _print_report(r)
    if any(not r.ok for r in reports):
        print("[FAIL] could not read the plug — check credentials / network.")
        return

    if READ_ONLY:
        print("\nREAD_ONLY=True — status read OK, no switching performed.")
        return

    # State-preserving toggle: flip to the opposite state, then restore the
    # original — proves switching works both ways and leaves the plug as found.
    original_on = reports[0].is_on
    print(f"\nSwitch test (state-preserving): plug is currently "
          f"{'ON' if original_on else 'OFF'}")
    print(f"  → switching {'OFF' if original_on else 'ON'} ...")
    flip = asyncio.run(ctrl.switch_many(entries, turn_on=not original_on))
    for r in flip:
        _print_switch(r)

    print(f"  holding for {TOGGLE_PAUSE_S:.0f} s...")
    _sleep(TOGGLE_PAUSE_S)

    print(f"  → restoring {'ON' if original_on else 'OFF'} ...")
    restore = asyncio.run(ctrl.switch_many(entries, turn_on=original_on))
    for r in restore:
        _print_switch(r)

    ok = all(r.ok for r in flip + restore)
    print(f"\n{'[PASS]' if ok else '[FAIL]'} switch test "
          f"{'completed (plug restored to original state)' if ok else 'had errors'}.")


async def _gather(coros):
    return await asyncio.gather(*coros)


def _sleep(seconds):
    # time.sleep would work too; asyncio.run keeps everything on one loop-free path.
    import time
    time.sleep(seconds)


if __name__ == "__main__":
    main()
