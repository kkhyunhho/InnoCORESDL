"""High-level controller for the IKA Plate (RCT digital).

This is a thin domain wrapper around ``ika.magnetic_stirrer``. The
``ika`` package does the serial work; this wrapper adds the parts the
manual requires but the package omits:

* a pyserial read timeout (``ika`` leaves it unset, so reads can block
  forever),
* setpoint range validation (see :mod:`hotplate_controller.limits`),
* a robust :meth:`read_name` that tolerates the trailing carriage
  return ``ika.read_device_name`` does not strip.
"""

from typing import Callable, Optional

from ika.abc import IKADevice
from ika.magnetic_stirrer import MagneticStirrer

from .errors import RctCommError
from .limits import (
    DEFAULT_READ_TIMEOUT_S,
    validate_speed,
    validate_temperature,
    validate_watchdog_time,
)


class RctDigital:
    """Control an IKA RCT digital over its USB virtual COM port."""

    def __init__(
        self,
        port: str,
        read_timeout: float = DEFAULT_READ_TIMEOUT_S,
        dummy: bool = False,
    ):
        """Open a connection to the device.

        Args:
            port: Serial port path, e.g. ``"/dev/ttyACM1"``.
            read_timeout: pyserial read timeout in seconds, applied to
                work around ``ika`` leaving the timeout unset.
            dummy: Forwarded to ``ika`` for offline construction; the
                wrapper does not exercise this mode.
        """
        self._port = port
        self._device = MagneticStirrer(port, dummy=dummy)
        if not self._device.dummy:
            self._device._ser.timeout = read_timeout

    @property
    def port(self) -> str:
        """The serial port path the device is connected on."""
        return self._port

    @property
    def device(self) -> MagneticStirrer:
        """The underlying ``ika`` ``MagneticStirrer`` instance."""
        return self._device

    # -- internal helpers ------------------------------------------

    def _query_raw(self, command: str) -> str:
        """Send ``command`` and return its raw, stripped text response.

        Bypasses ``ika``'s numeric/equality post-processing so it is
        robust to the trailing ``\\r`` the device appends.
        """
        raw = IKADevice._send_and_receive(self._device, command)
        return raw.strip() if raw else ""

    def _read_number(self, reader: Callable[[], float]) -> float:
        """Call an ``ika`` numeric reader, mapping failures to errors."""
        try:
            return float(reader())
        except (ValueError, IndexError, TypeError) as exc:
            raise RctCommError(
                f"no numeric response from {reader.__name__}; "
                "check 7E1 framing, wiring, and port"
            ) from exc

    # -- read (non-actuating) --------------------------------------

    def read_name(self) -> str:
        """Return the device identifier, e.g. ``"RCT digital"``."""
        name = self._query_raw(MagneticStirrer.READ_THE_DEVICE_NAME)
        if not name:
            raise RctCommError(
                "no response to IN_NAME; check 7E1 framing, wiring, and port"
            )
        return name

    def read_plate_temperature(self) -> float:
        """Return the hotplate surface temperature in degrees C."""
        return self._read_number(self._device.hotplate_sensor_temperature)

    def read_probe_temperature(self) -> float:
        """Return the external probe temperature in degrees C."""
        return self._read_number(self._device.probe_temperature)

    def read_speed(self) -> float:
        """Return the actual stirring speed in rpm."""
        return self._read_number(self._device.stir_rate)

    def read_target_temperature(self) -> float:
        """Return the temperature setpoint in degrees C."""
        return self._read_number(self._device.target_temperature)

    def read_target_speed(self) -> float:
        """Return the stirring-speed setpoint in rpm."""
        return self._read_number(self._device.target_stir_rate)

    def read_safety_temperature(self) -> float:
        """Return the configured safety temperature in degrees C."""
        return self._read_number(self._device.hardware_safety_temperature)

    # -- write (actuating) -----------------------------------------

    def set_target_temperature(self, celsius: float) -> float:
        """Set the temperature setpoint after range validation.

        Note: this changes the setpoint only; call :meth:`start_heater`
        to actually heat.
        """
        value = validate_temperature(celsius)
        self._device.set_target_temperature(value)
        return value

    def set_target_speed(self, rpm: float) -> float:
        """Set the stirring-speed setpoint after range validation."""
        value = validate_speed(rpm)
        self._device.set_target_stir_rate(value)
        return value

    def start_heater(self) -> None:
        """Start heating toward the temperature setpoint."""
        self._device.start_heating()

    def stop_heater(self) -> None:
        """Stop heating."""
        self._device.stop_heating()

    def start_motor(self) -> None:
        """Start stirring toward the speed setpoint."""
        self._device.start_stirring()

    def stop_motor(self) -> None:
        """Stop stirring."""
        self._device.stop_stirring()

    def reset(self) -> None:
        """Return the device to normal operating mode (RESET)."""
        self._device.switch_to_normal_operating_mode()

    # -- watchdog --------------------------------------------------

    def enable_watchdog_mode_1(self, seconds: int) -> None:
        """Arm watchdog mode 1 (all output off on timeout)."""
        value = validate_watchdog_time(seconds)
        self._device.watchdog_mode_1(str(value))

    def enable_watchdog_mode_2(self, seconds: int) -> None:
        """Arm watchdog mode 2 (fall back to safe limits on timeout)."""
        value = validate_watchdog_time(seconds)
        self._device.watchdog_mode_2(str(value))

    # -- lifecycle -------------------------------------------------

    def close(self) -> None:
        """Close the serial port if it is open."""
        if not self._device.dummy:
            serial_handle: Optional[object] = getattr(
                self._device, "_ser", None
            )
            if serial_handle is not None:
                serial_handle.close()

    def __enter__(self) -> "RctDigital":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
