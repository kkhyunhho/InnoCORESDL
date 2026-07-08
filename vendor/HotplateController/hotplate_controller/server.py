"""FastAPI server for monitoring and controlling the RCT digital.

The server exposes the hotplate's temperature and stirring speed over
HTTP on port 17048 so a remote client (for example an ESP32) or a web
browser can read live status and drive the setpoints, heater, and motor.

:class:`RctDigital` is synchronous and blocking and handles one serial
command at a time. To keep that serial port safe under concurrent HTTP
requests, a single background poller thread owns every read and refreshes
an immutable snapshot; GET handlers return that cached snapshot without
touching the port, and control handlers take the same lock the poller
uses. See :class:`DeviceMonitor`.

Run it with::

    python3 -m hotplate_controller.server [PORT]

where ``PORT`` is the serial device path; it defaults to auto-detection
by USB VID:PID and then ``$RCT_PORT``.
"""

import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .errors import RctCommError, RctError, RctRangeError
from .ports import find_rct_port
from .rct_digital import RctDigital

# Bind on all interfaces so an ESP32 on the same network can reach the
# server; the port is fixed by the task.
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 17048

# How often the background thread reads the device, in seconds.
POLL_INTERVAL_S = 1.0


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string (second
    resolution)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_port(explicit: Optional[str] = None) -> Optional[str]:
    """Decide which serial port to open.

    Mirrors the resolution order used by ``main.py``: an explicit value
    wins, otherwise auto-detect by USB VID:PID, otherwise ``$RCT_PORT``.

    Args:
        explicit: A port path supplied on the command line, or ``None``.

    Returns:
        The chosen port path, or ``None`` if nothing could be resolved.
    """
    if explicit:
        return explicit
    return find_rct_port() or os.environ.get("RCT_PORT")


class DeviceMonitor:
    """Own an :class:`RctDigital` and serialize all access to it.

    A background thread polls the device every ``poll_interval`` seconds
    and stores the result in an immutable snapshot dict. Reads of the
    snapshot are lock-free because the reference is replaced atomically;
    every call that touches the serial port -- the poller and all control
    methods -- holds ``self._lock`` so commands never interleave.
    """

    def __init__(
        self,
        controller: RctDigital,
        poll_interval: float = POLL_INTERVAL_S,
    ):
        """Wrap ``controller`` without starting the poller yet.

        Args:
            controller: The connected device wrapper to drive.
            poll_interval: Seconds between background reads.
        """
        self._controller = controller
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_poll_monotonic = time.monotonic()
        self._snapshot = self._disconnected_snapshot("no reading yet")

    # -- snapshot ---------------------------------------------------

    @staticmethod
    def _disconnected_snapshot(error: str) -> dict:
        """Build a snapshot with no readings and an error message."""
        return {
            "connected": False,
            "plate_temperature_c": None,
            "probe_temperature_c": None,
            "speed_rpm": None,
            "target_temperature_c": None,
            "target_speed_rpm": None,
            "safety_temperature_c": None,
            "timestamp": utc_now_iso(),
            "error": error,
        }

    def poll_once(self) -> dict:
        """Read every monitored value once and refresh the snapshot.

        A failure of the optional external probe is tolerated (its field
        becomes ``None``); any other serial failure marks the snapshot
        disconnected so the server stays up while the device is absent.

        Returns:
            The snapshot dict that was just stored.
        """
        with self._lock:
            try:
                plate = self._controller.read_plate_temperature()
                speed = self._controller.read_speed()
                target_temp = self._controller.read_target_temperature()
                target_speed = self._controller.read_target_speed()
                safety = self._controller.read_safety_temperature()
                try:
                    probe = self._controller.read_probe_temperature()
                except RctError:
                    # No external probe attached is a normal condition.
                    probe = None
                snapshot = {
                    "connected": True,
                    "plate_temperature_c": plate,
                    "probe_temperature_c": probe,
                    "speed_rpm": speed,
                    "target_temperature_c": target_temp,
                    "target_speed_rpm": target_speed,
                    "safety_temperature_c": safety,
                    "timestamp": utc_now_iso(),
                    "error": None,
                }
            except (RctError, OSError) as exc:
                snapshot = self._disconnected_snapshot(str(exc))
        self._snapshot = snapshot
        self._last_poll_monotonic = time.monotonic()
        return snapshot

    @property
    def snapshot(self) -> dict:
        """The most recent snapshot dict (replaced atomically)."""
        return self._snapshot

    def current_status(self) -> dict:
        """Return the snapshot plus the age of its reading in seconds."""
        snapshot = self._snapshot
        age = round(time.monotonic() - self._last_poll_monotonic, 2)
        return {**snapshot, "age_seconds": age}

    # -- background poller -----------------------------------------

    def start(self) -> None:
        """Start the background polling thread if it is not running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="rct-poller", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """Poll forever until stopped, surviving unexpected errors."""
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                # poll_once maps known failures; this is a last-resort
                # guard so the poller thread can never die silently.
                pass
            self._stop_event.wait(self._poll_interval)

    def stop(self) -> None:
        """Signal the poller to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval + 1.0)

    # -- control (serialized writes) -------------------------------

    def set_target_temperature(self, celsius: float) -> float:
        """Set the temperature setpoint, holding the serial lock."""
        with self._lock:
            return self._controller.set_target_temperature(celsius)

    def set_target_speed(self, rpm: float) -> float:
        """Set the stirring-speed setpoint, holding the serial lock."""
        with self._lock:
            return self._controller.set_target_speed(rpm)

    def start_heater(self) -> None:
        """Start heating toward the temperature setpoint."""
        with self._lock:
            self._controller.start_heater()

    def stop_heater(self) -> None:
        """Stop heating."""
        with self._lock:
            self._controller.stop_heater()

    def start_motor(self) -> None:
        """Start stirring toward the speed setpoint."""
        with self._lock:
            self._controller.start_motor()

    def stop_motor(self) -> None:
        """Stop stirring."""
        with self._lock:
            self._controller.stop_motor()

    def reset(self) -> None:
        """Return the device to its normal operating mode."""
        with self._lock:
            self._controller.reset()


class TargetValue(BaseModel):
    """Request body for a setpoint command."""

    value: float


def get_monitor(request: Request) -> DeviceMonitor:
    """Return the app's :class:`DeviceMonitor` or fail with 503."""
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise RctCommError("device monitor is not initialized")
    return monitor


def render_dashboard(status: dict) -> str:
    """Render the monitoring snapshot as a self-refreshing HTML page.

    Args:
        status: A snapshot dict from :meth:`DeviceMonitor.current_status`.

    Returns:
        A complete HTML document that reloads every two seconds.
    """

    def cell(value, suffix=""):
        if value is None:
            return "--"
        return f"{value}{suffix}"

    connected = "yes" if status["connected"] else "no"
    error = status.get("error")
    error_row = ""
    if error:
        error_row = f"<p class='err'>error: {escape(str(error))}</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="2">
  <title>RCT digital monitor</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    h1 {{ font-size: 1.3rem; }}
    table {{ border-collapse: collapse; }}
    td {{ padding: 0.3rem 1rem; border-bottom: 1px solid #ddd; }}
    .label {{ color: #555; }}
    .val {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
    .err {{ color: #b00; }}
  </style>
</head>
<body>
  <h1>RCT digital monitor</h1>
  <table>
    <tr><td class="label">connected</td>
        <td class="val">{connected}</td></tr>
    <tr><td class="label">plate temperature</td>
        <td class="val">{cell(status["plate_temperature_c"], " C")}</td></tr>
    <tr><td class="label">probe temperature</td>
        <td class="val">{cell(status["probe_temperature_c"], " C")}</td></tr>
    <tr><td class="label">speed</td>
        <td class="val">{cell(status["speed_rpm"], " rpm")}</td></tr>
    <tr><td class="label">target temperature</td>
        <td class="val">{cell(status["target_temperature_c"], " C")}</td></tr>
    <tr><td class="label">target speed</td>
        <td class="val">{cell(status["target_speed_rpm"], " rpm")}</td></tr>
    <tr><td class="label">safety temperature</td>
        <td class="val">{cell(status["safety_temperature_c"], " C")}</td></tr>
  </table>
  {error_row}
  <p class="label">updated {escape(status["timestamp"])}
     (age {status.get("age_seconds", "?")} s)</p>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the device on startup and close it on shutdown.

    If a monitor was injected onto ``app.state`` (the tests do this), it
    is used as-is and no real serial device is opened.
    """
    monitor = getattr(app.state, "monitor", None)
    controller: Optional[RctDigital] = None
    if monitor is None:
        port = resolve_port(getattr(app.state, "port", None))
        if not port:
            raise RuntimeError(
                "no RCT digital found; pass a port or set $RCT_PORT"
            )
        controller = RctDigital(port)
        monitor = DeviceMonitor(controller)
        app.state.monitor = monitor
    monitor.start()
    try:
        yield
    finally:
        monitor.stop()
        if controller is not None:
            controller.close()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="RCT digital monitor",
        description="Monitor and control an IKA RCT digital hotplate.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RctRangeError)
    async def _range_error(request: Request, exc: RctRangeError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(RctCommError)
    async def _comm_error(request: Request, exc: RctCommError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(monitor: DeviceMonitor = Depends(get_monitor)):
        """Serve the self-refreshing HTML monitoring dashboard."""
        return render_dashboard(monitor.current_status())

    @app.get("/health")
    async def health(monitor: DeviceMonitor = Depends(get_monitor)):
        """Report server liveness and device connection state."""
        return {"status": "ok", "connected": monitor.snapshot["connected"]}

    @app.get("/status")
    async def status(monitor: DeviceMonitor = Depends(get_monitor)):
        """Return the full latest snapshot plus its reading age."""
        return monitor.current_status()

    @app.get("/temperature")
    async def temperature(monitor: DeviceMonitor = Depends(get_monitor)):
        """Return plate, probe, and target temperatures in Celsius."""
        snapshot = monitor.snapshot
        return {
            "plate": snapshot["plate_temperature_c"],
            "probe": snapshot["probe_temperature_c"],
            "target": snapshot["target_temperature_c"],
            "unit": "C",
            "connected": snapshot["connected"],
            "timestamp": snapshot["timestamp"],
        }

    @app.get("/speed")
    async def speed(monitor: DeviceMonitor = Depends(get_monitor)):
        """Return actual and target stirring speeds in rpm."""
        snapshot = monitor.snapshot
        return {
            "actual": snapshot["speed_rpm"],
            "target": snapshot["target_speed_rpm"],
            "unit": "rpm",
            "connected": snapshot["connected"],
            "timestamp": snapshot["timestamp"],
        }

    @app.post("/control/target/temperature")
    def set_temperature(
        body: TargetValue,
        monitor: DeviceMonitor = Depends(get_monitor),
    ):
        """Set the temperature setpoint in Celsius."""
        return {"target": monitor.set_target_temperature(body.value)}

    @app.post("/control/target/speed")
    def set_speed(
        body: TargetValue,
        monitor: DeviceMonitor = Depends(get_monitor),
    ):
        """Set the stirring-speed setpoint in rpm."""
        return {"target": monitor.set_target_speed(body.value)}

    @app.post("/control/heater/start")
    def heater_start(monitor: DeviceMonitor = Depends(get_monitor)):
        """Start heating toward the temperature setpoint."""
        monitor.start_heater()
        return {"ok": True}

    @app.post("/control/heater/stop")
    def heater_stop(monitor: DeviceMonitor = Depends(get_monitor)):
        """Stop heating."""
        monitor.stop_heater()
        return {"ok": True}

    @app.post("/control/motor/start")
    def motor_start(monitor: DeviceMonitor = Depends(get_monitor)):
        """Start stirring toward the speed setpoint."""
        monitor.start_motor()
        return {"ok": True}

    @app.post("/control/motor/stop")
    def motor_stop(monitor: DeviceMonitor = Depends(get_monitor)):
        """Stop stirring."""
        monitor.stop_motor()
        return {"ok": True}

    @app.post("/control/reset")
    def reset(monitor: DeviceMonitor = Depends(get_monitor)):
        """Return the device to its normal operating mode."""
        monitor.reset()
        return {"ok": True}

    return app


app = create_app()


def main(argv: Optional[list] = None) -> int:
    """Resolve the serial port and run the server with uvicorn.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv``.

    Returns:
        A process exit code (``0`` on a clean run, ``1`` if no device
        could be resolved).
    """
    argv = sys.argv if argv is None else argv
    explicit = argv[1] if len(argv) > 1 else None
    port = resolve_port(explicit)
    if not port:
        print("no RCT digital found (set PORT arg or $RCT_PORT).")
        return 1
    app.state.port = port
    print(
        f"serving RCT digital on http://{SERVER_HOST}:{SERVER_PORT} "
        f"(device {port}) ..."
    )
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
