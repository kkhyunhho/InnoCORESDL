# sdl_analyzing.py
# Bench scenario driving FOUR devices in one config-driven run:
#   * a single Z-axis MKS SERVO57D motor (its own USB2CAN adapter),
#   * the SY-01B syringe pump,
#   * the IKA RCT digital hotplate (vendor/HotplateController), and
#   * a Tapo smart plug (vendor/SmartPlugController) that powers the heat step.
#
# Scenario (each step toggled by a RUN_* flag in the Configuration block):
#   STEP 1  Home the Z motor            (home_sync → origin switch, arms limits)
#   STEP 2  Initialize the pump         (plunger + valve home; required before dispense)
#   STEP 3  Prime the line              (PRIME_CYCLES × reservoir→aspirate→tip→dispense)
#   STEP 4  Move Z to the target mm     (F5 absolute move — NO jog)
#   STEP 5  Dispense DISPENSE_UL µL     (valve→reservoir, aspirate, valve→tip, dispense)
#   STEP 6  Heat & hold                 (plug ON → hotplate to HOTPLATE_TARGET_C, hold, OFF)
#   STEP 7  Return Z to origin          (F5 move to 0; optional)
#
# Motor motion is ABSOLUTE-move only (F5) — no jog path.
#
# SAFETY — moves a real motor, pump, AND a hotplate (heat!):
#   * Keep a hardware e-stop / power cut within reach; clear the Z travel path.
#   * Steps are selected in the Configuration block (RUN_* flags) — there are
#     NO runtime prompts. Review those flags before running; an enabled step
#     acts on hardware as soon as the scenario reaches it.
#   * The hotplate gets HOT. On ANY exit (normal, error, Ctrl-C) the heater is
#     stopped and the smart plug is switched OFF in the finally block.
#   * Any CAN link drop hard-stops the motor and aborts the scenario.
#   * Z motion uses only the group helpers (home_sync / move_sync) — never
#     MKSMotor._send directly (that bypasses the limit + interlock guards).
#   * VALVE PORT MAPPING (SyringePumpController ESP UI — the operator's
#     intuitive layout): firmware ports 1 & 3 are the SAME fluid state and
#     2 & 4 the other, so source and sink must be 90° apart. reservoir = port
#     1, tip = port 2 (see the table below). Verify with the eye which tube
#     moves liquid — NOT the ?6 digit.
#
# Run (in the InnoCORESDL `sdl` conda env, or any env with pyftdi + pyserial
# + ika + python-kasa):
#   python claude_test/sdl_analyzing.py

import asyncio
import os
import signal
import stat
import sys
import time
from contextlib import suppress

# ── Make the vendored drivers importable ────────────────────────────────────
# All drivers live in THIS repo under vendor/ (vendor.mks_motor, vendor.sy01b
# are copied packages; vendor.HotplateController, vendor.SmartPlugController
# are git submodules) and are imported as vendor.<name>. Put the repo root on
# sys.path so a directly-run bench script resolves them without an install.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
if os.path.isdir(_REPO_ROOT) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from vendor.HotplateController.hotplate_controller import (  # noqa: E402
    RctDigital,
    find_rct_port,
)
from vendor.mks_motor import (  # noqa: E402
    MKSMotor,
    prepare_usb_nodes,
    release_ftdi_sio,
    set_group_fault_hook,
)
from vendor.SmartPlugController.smartplugcontroller import (  # noqa: E402
    ControllerError,
    SmartPlugController,
)
from vendor.sy01b import SyringePumpController  # noqa: E402

# ── Configuration ───────────────────────────────────────────────────────────
# Z-axis motor -------------------------------------------------------------
SERIAL_Z = "NTB3EP5R"          # FTDI chip serial of the single-Z USB2CAN adapter
# F5 absolute-move direction. move_to(+mm) must travel AWAY from home. True
# matches this bench's Z convention (encoder-positive points into the home
# limit, so the sign is flipped). This is a NEW motor: if STEP 4 does not
# reach the target (read-back stays ~0), flip this and re-run.
Z_COORD_INVERT = True
HOME_DIR_Z = 0x00              # 0x90 home direction; flip 0x00<->0x01 for the other end
TARGET_MM = 400                 # STEP 4 absolute target (max travel 400 mm)
MOVE_SPEED_PCT = 15            # % of max RPM (conservative first run)
MOVE_ACCEL_PCT = 40

# Syringe pump -------------------------------------------------------------
PUMP_PORT = "1A86:7523"        # SY-01B CH340 USB-serial (VID:PID)
SYRINGE_UL = 125               # installed syringe size
PUMP_INIT_FORCE = 2            # Z-init force (2 = one-third, for small syringes)
# Valve port mapping — the number below is the move_valve_to_port() argument
# (the pump valve COMMAND / firmware position, NOT the physical tube label).
# This bi-pass valve connects the syringe common C to only two physical tubes,
# so commands 1 & 3 both hit tube 1 and commands 2 & 4 both hit tube 3 — the
# 3 o'clock tube is therefore reached by command 2, not 3. Verified from the
# SyringePumpController ESP UI (firmware main/ui.c):
#
#   arg  pump cmd  ESP UI label         C → physical port   compass
#   ---  --------  -------------------  -----------------   ---------
#    1     I1      "Port 1 to Path 1"   Port 1              9 o'clock
#    2     I2      "Port 3 to Path 1"   Port 3              3 o'clock
#    3     I3      "Port 1 to Path 2"   Port 1              9 o'clock
#    4     I4      "Port 3 to Path 2"   Port 3              3 o'clock
#
# So: aspirate FROM Port 1 (9 o'clock) → arg 1; dispense TO Port 3 (3 o'clock)
# → arg 2. Source & sink must be opposite parity (90° apart) for a real
# transfer — same parity = same tube (InnoCORESDL LearnedPatterns #1).
RESERVOIR_PORT = 1             # source: aspirate FROM Port 1 (9 o'clock) → I1
TIP_PORT = 2                   # sink:   dispense TO Port 3 (3 o'clock) → I2
DISPENSE_UL = 23.0             # volume to dispense
# Priming — flush the reservoir→tip line before dosing. Each cycle:
# valve→reservoir, aspirate PRIME_VOLUME_UL, valve→tip, dispense→0. Mirrors
# the SyringePumpController ESP prime tab (and server /v1/prime) sequence.
PRIME_CYCLES = 3               # number of aspirate/dispense flush cycles
PRIME_VOLUME_UL = float(SYRINGE_UL)  # per-cycle volume (full stroke flushes best)

# Hotplate (IKA RCT digital) ------------------------------------------------
HOTPLATE_PORT = None           # None → auto-detect by USB VID:PID (0483:5740)
HOTPLATE_TARGET_C = 30.0       # heat setpoint for STEP 5
HEAT_HOLD_S = 60.0             # hold time at the setpoint (seconds)
TEMP_POLL_S = 5.0              # temperature print interval during the hold

# Smart plug (Tapo via python-kasa) -----------------------------------------
# Powers the heat step. Credentials come from KASA_USERNAME / KASA_PASSWORD or
# vendor/SmartPlugController/secure.env; the device map is device_list.md.
# Missing credentials are NOT fatal — plug toggles are skipped with a notice
# and STEP 5 still drives the hotplate over serial.
PLUG_TARGET = "plug1"          # device name / IP / "all" from device_list.md

# Step selection ------------------------------------------------------------
# Enable/disable each step HERE (config-driven; no runtime prompts). The
# scenario runs top-to-bottom; a step left False is skipped with a note.
# Dependencies: PRIME/DISPENSE need the pump initialized (RUN_INIT_PUMP=True),
# DISPENSE assumes the line is primed, and STEP 7 only makes sense after a move.
RUN_HOME_MOTOR = True          # STEP 1  home the Z motor
RUN_INIT_PUMP = True           # STEP 2  initialize the pump (plunger + valve home)
RUN_PRIME = False              # STEP 3  prime the reservoir→tip line
RUN_MOVE_MOTOR = True          # STEP 4  move Z to TARGET_MM
RUN_DISPENSE = True            # STEP 5  dispense DISPENSE_UL
RUN_HEAT_HOLD = True           # STEP 6  plug ON + hotplate heat & hold + OFF
RUN_MOVE_HOME = False          # STEP 7  return Z to origin (0 mm)
# ────────────────────────────────────────────────────────────────────────────


def ensure_ttyusb_nodes():
    """Rebuild /dev/ttyUSB* nodes from sysfs for CH340 (pump) serial ports.

    prepare_usb_nodes() covers FTDI raw-USB and ttyACM but not ttyUSB, and
    the container's /dev is a private tmpfs, so the CH340 pump's node can be
    missing after a re-enumeration. Idempotent; root-only (os.mknod).
    """
    tty_root = "/sys/class/tty"
    for name in sorted(os.listdir(tty_root)):
        if not name.startswith("ttyUSB"):
            continue
        dev_attr = f"{tty_root}/{name}/dev"
        if not os.path.exists(dev_attr):
            continue
        major, minor = (int(x) for x in open(dev_attr).read().strip().split(":"))
        node = f"/dev/{name}"
        if not os.path.exists(node):
            os.mknod(node, 0o666 | stat.S_IFCHR, os.makedev(major, minor))
            os.chmod(node, 0o666)
            print(f"created {node} ({major}:{minor})")


# ── Hotplate / smart-plug helpers ───────────────────────────────────────────

def open_hotplate():
    """Open the IKA RCT digital, auto-detecting the port by USB VID:PID."""
    port = HOTPLATE_PORT or find_rct_port()
    if port is None:
        raise RuntimeError(
            "RCT digital not found by USB VID:PID (0483:5740); "
            "set HOTPLATE_PORT explicitly."
        )
    return RctDigital(port)


def plug_controller():
    """Build the Tapo plug controller, or None when credentials are missing.

    A None controller makes every plug_switch() a no-op, so the heat step
    still runs (hotplate over serial) without the plug.
    """
    try:
        return SmartPlugController.from_files()
    except ControllerError as exc:
        print(f"[plug] unavailable, skipping plug toggles: {exc}")
        return None


def plug_switch(ctrl, target, *, on):
    """Switch the plug(s) matching `target` on/off (blocking, None = no-op).

    Sync façade over the async kasa API so the scenario stays synchronous.
    """
    if ctrl is None:
        return
    entries = ctrl.resolve_targets(target)
    if not entries:
        raise RuntimeError(f"no plug matches {target!r} in device_list.md")
    results = asyncio.run(ctrl.switch_many(entries, turn_on=on))
    failed = [r for r in results if not r.ok]
    if failed:
        raise RuntimeError(
            "plug switch failed: "
            + "; ".join(f"{r.entry.name}: {r.error}" for r in failed)
        )
    for result in results:
        print(f"[plug] {result.entry.name} -> {'ON' if result.after else 'OFF'}")


# ── Steps ───────────────────────────────────────────────────────────────────

def step_home_motor(motor):
    print("\n" + "=" * 62)
    print("STEP 1 — Home the Z motor")
    print(f"  home_sync travels dir=0x{HOME_DIR_Z:02X} to the origin switch, "
          f"zeroes there, then arms the limit switches.")
    print("=" * 62)
    MKSMotor.home_sync([motor], direction=HOME_DIR_Z)
    print(f"  post-home Z = {motor.read_position_mm():.2f} mm (expect ~0.0)")


def step_init_pump(pump):
    print("\n" + "=" * 62)
    print("STEP 2 — Initialize the pump (plunger + valve home)")
    print("  Required before any aspirate/dispense (else the pump errors 7).")
    print("  The plunger travels the full stroke — make sure that is safe.")
    print("=" * 62)
    pump.initialize(force=PUMP_INIT_FORCE)
    print(f"  pump initialized. valve now at port '{pump.query_valve_position()}'")


def _valve_ports_same_state():
    """True if reservoir & tip resolve to the SAME valve fluid state.

    On this bi-pass valve the common C reaches the same physical tube for
    firmware ports of equal parity (I1/I3 → one tube, I2/I4 → the other),
    so an odd/odd or even/even source→sink pair aspirates and dispenses at
    the SAME tube — no real transfer (InnoCORESDL LearnedPatterns #1). A
    valid pair is 90° apart = opposite parity.
    """
    return RESERVOIR_PORT % 2 == TIP_PORT % 2


def step_prime(pump):
    print("\n" + "=" * 62)
    print(f"STEP 3 — Prime the line ({PRIME_CYCLES} cycles)")
    print(f"  Each cycle: valve→reservoir(port {RESERVOIR_PORT}), aspirate "
          f"{PRIME_VOLUME_UL:.0f} µL, valve→tip(port {TIP_PORT}), dispense→0.")
    print("  Flushes air / old fluid from the reservoir→tip path before dosing.")
    print("=" * 62)
    if _valve_ports_same_state():
        print(f"  [WARN] reservoir(port {RESERVOIR_PORT}) and tip(port "
              f"{TIP_PORT}) are the SAME valve fluid state (equal parity) — "
              f"priming would move liquid at ONE tube only. Use a 90°-apart "
              f"tip (opposite parity, e.g. TIP_PORT=2) for a real transfer.")
    # Precondition (mirrors server /v1/prime): valve on the tip and plunger
    # emptied, so the first aspirate draws cleanly from the reservoir and any
    # residual is expelled to the tip rather than back out the reservoir.
    pump.move_valve_to_port(TIP_PORT)
    pump.dispense_uL(0)
    for i in range(1, PRIME_CYCLES + 1):
        print(f"  cycle {i}/{PRIME_CYCLES}: reservoir → aspirate "
              f"{PRIME_VOLUME_UL:.0f} µL → tip → dispense")
        pump.move_valve_to_port(RESERVOIR_PORT)
        pump.aspirate_uL(PRIME_VOLUME_UL)
        pump.move_valve_to_port(TIP_PORT)
        pump.dispense_uL(0)
    print(f"  primed. valve at port '{pump.query_valve_position()}', "
          f"plunger={pump.query_plunger_position()} steps (expect ~0)")


def step_move_motor(motor):
    print("\n" + "=" * 62)
    print("STEP 4 — Move Z to target (absolute F5)")
    print(f"  move_sync to {TARGET_MM} mm (speed={MOVE_SPEED_PCT}%, "
          f"accel={MOVE_ACCEL_PCT}%). Should travel AWAY from home.")
    print("  If the read-back stays near 0, direction is inverted — flip "
          "Z_COORD_INVERT and re-run.")
    print("=" * 62)
    MKSMotor.move_sync([motor],
                       [(TARGET_MM, MOVE_SPEED_PCT, MOVE_ACCEL_PCT)])
    pos = motor.read_position_mm()
    print(f"  target={TARGET_MM} mm  ->  read-back={pos:.2f} mm  "
          f"(err={pos - TARGET_MM:+.2f} mm)")


def step_heat_hold(rct, plug):
    print("\n" + "=" * 62)
    print(f"STEP 6 — Heat & hold ({HOTPLATE_TARGET_C:.0f} °C for {HEAT_HOLD_S:.0f} s)")
    print("  Plug ON powers the hotplate, then heat to target and hold; the "
          "heater + plug are switched OFF at the end of the step.")
    print("=" * 62)
    # Plug powers the hotplate — turn it on before heating (no-op if no creds).
    plug_switch(plug, PLUG_TARGET, on=True)
    print(f"  plate {rct.read_plate_temperature():.1f} °C, heating to "
          f"{HOTPLATE_TARGET_C:.0f} °C for {HEAT_HOLD_S:.0f} s")
    rct.set_target_temperature(HOTPLATE_TARGET_C)
    rct.start_heater()
    deadline = time.monotonic() + HEAT_HOLD_S
    while time.monotonic() < deadline:
        time.sleep(TEMP_POLL_S)
        print(f"  plate {rct.read_plate_temperature():.1f} °C")
    rct.stop_heater()
    plug_switch(plug, PLUG_TARGET, on=False)
    print("  heat/hold complete — heater + plug OFF")


def step_dispense(pump):
    print("\n" + "=" * 62)
    print(f"STEP 5 — Dispense {DISPENSE_UL} µL")
    print(f"  valve→reservoir(port {RESERVOIR_PORT}), aspirate {DISPENSE_UL} µL, "
          f"valve→tip(port {TIP_PORT}), dispense.")
    print("  Watch which tube actually moves liquid (valve bi-pass gotcha).")
    print("=" * 62)
    print(f"  valve → reservoir (port {RESERVOIR_PORT}) ...")
    pump.move_valve_to_port(RESERVOIR_PORT)
    print(f"  aspirating {DISPENSE_UL} µL ...")
    pump.aspirate_uL(DISPENSE_UL)
    print(f"  valve → tip (port {TIP_PORT}) ...")
    pump.move_valve_to_port(TIP_PORT)
    print("  dispensing ...")
    pump.dispense_uL(0)
    print(f"  done. valve at port '{pump.query_valve_position()}', "
          f"plunger={pump.query_plunger_position()} steps (expect ~0)")


def step_move_home(motor):
    print("\n" + "=" * 62)
    print("STEP 7 — Return Z to origin (absolute F5 → 0 mm)")
    print("=" * 62)
    MKSMotor.move_sync([motor], [(0, MOVE_SPEED_PCT, MOVE_ACCEL_PCT)])
    print(f"  back at {motor.read_position_mm():.2f} mm (expect ~0.0)")


def main():
    print("Refreshing USB device nodes (FTDI + ttyACM)...")
    prepare_usb_nodes()
    print("Rebuilding ttyUSB nodes (CH340 pump)...")
    ensure_ttyusb_nodes()
    print("Releasing ftdi_sio from FTDI adapters...")
    release_ftdi_sio()

    need_motor = RUN_HOME_MOTOR or RUN_MOVE_MOTOR or RUN_MOVE_HOME
    need_pump = RUN_INIT_PUMP or RUN_PRIME or RUN_DISPENSE
    need_heat = RUN_HEAT_HOLD

    motor = pump = rct = plug = None
    try:
        if need_motor:
            print(f"Opening Z motor (serial={SERIAL_Z}, "
                  f"coord_invert={Z_COORD_INVERT})...")
            motor = MKSMotor.open(serial=SERIAL_Z, coord_invert=Z_COORD_INVERT)

            # Any CAN link drop hard-stops the motor and aborts the scenario.
            def on_fault(reason):
                print(f"\n[FATAL] CAN link fault: {reason}", flush=True)
                MKSMotor.stop_group_hard([motor])
                os._exit(1)

            set_group_fault_hook(on_fault)

            def on_sigint(signum, frame):
                print("\n[SIGINT] emergency-stopping motor...")
                with suppress(Exception):
                    MKSMotor.stop_group_hard([motor])
                os._exit(0)

            signal.signal(signal.SIGINT, on_sigint)

            print("Setting up Z motor (SR_vFOC mode)...")
            if not motor.setup():
                print("[WARN] motor setup did not fully confirm — check power "
                      "/ CAN termination (~60 ohm) / wiring before moving.")

        if need_pump:
            print(f"Opening pump ({PUMP_PORT}, syringe={SYRINGE_UL} µL)...")
            pump = SyringePumpController.open(
                SyringePumpController.Config(
                    port=PUMP_PORT,
                    syringe_uL=SYRINGE_UL,
                    reply_timeout_s=2.0,
                )
            )

        if need_heat:
            print("Opening hotplate (IKA RCT digital)...")
            rct = open_hotplate()
            print("Building smart-plug controller...")
            plug = plug_controller()

        # (flag, label, thunk) — each step runs only if its RUN_* flag is True.
        steps = [
            (RUN_HOME_MOTOR, "STEP 1 home Z motor", lambda: step_home_motor(motor)),
            (RUN_INIT_PUMP, "STEP 2 init pump", lambda: step_init_pump(pump)),
            (RUN_PRIME, "STEP 3 prime", lambda: step_prime(pump)),
            (RUN_MOVE_MOTOR, "STEP 4 move Z", lambda: step_move_motor(motor)),
            (RUN_DISPENSE, "STEP 5 dispense", lambda: step_dispense(pump)),
            (RUN_HEAT_HOLD, "STEP 6 heat & hold", lambda: step_heat_hold(rct, plug)),
            (RUN_MOVE_HOME, "STEP 7 move Z home", lambda: step_move_home(motor)),
        ]
        for enabled, label, run_step in steps:
            if enabled:
                run_step()
            else:
                print(f"\n[skip] {label} — disabled in config")
        print("\nScenario complete.")
    finally:
        # Safety cleanup, in priority order: heater OFF, plug OFF, motor stopped.
        if rct is not None:
            with suppress(Exception):
                rct.stop_heater()
        if plug is not None:
            with suppress(Exception):
                plug_switch(plug, PLUG_TARGET, on=False)
        if motor is not None:
            with suppress(Exception):
                MKSMotor.stop_group_hard([motor])
            with suppress(Exception):
                motor.close()
        if pump is not None:
            with suppress(Exception):
                pump.close()
        if rct is not None:
            with suppress(Exception):
                rct.close()
        print("Devices closed.")


if __name__ == "__main__":
    main()
