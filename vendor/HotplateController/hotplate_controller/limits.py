"""Device limits and value validation for the IKA RCT digital.

These constants and helpers come from the device manual
(``docs/EN_IKA Plate_RCT 5 digital -english.pdf``), which the ``ika``
package does not enforce. They are kept as pure functions so they can be
unit tested without any serial hardware or ``ika`` instance.
"""

from .errors import RctRangeError

# USB identifiers of the RCT digital's STM32 virtual COM port. Used to
# locate the device by hardware id instead of a fragile /dev path.
RCT_USB_VID = 0x0483
RCT_USB_PID = 0x5740

# Setpoint ranges from the NAMUR command table (OUT_SP_1 / OUT_SP_4).
TEMP_MIN_C = 0
TEMP_MAX_C = 310
# OUT_SP_4 accepts 0..1500; 0 stops the motor and 50 is the lowest
# effective stirring speed per the data sheet.
SPEED_MIN_RPM = 0
SPEED_MAX_RPM = 1500
SPEED_MIN_EFFECTIVE_RPM = 50

# Watchdog time bounds in seconds (OUT_WD1@m / OUT_WD2@m).
WATCHDOG_MIN_S = 20
WATCHDOG_MAX_S = 1500

# Default pyserial read timeout (seconds). ika leaves this unset, which
# lets reads block forever; the wrapper applies this value instead.
DEFAULT_READ_TIMEOUT_S = 2.0


def validate_temperature(celsius: float) -> float:
    """Return ``celsius`` if it is a legal setpoint, else raise.

    Args:
        celsius: Target hotplate temperature in degrees Celsius.

    Returns:
        The validated temperature as a float.

    Raises:
        RctRangeError: If the value is outside ``TEMP_MIN_C`` ..
            ``TEMP_MAX_C``.
    """
    value = float(celsius)
    if not TEMP_MIN_C <= value <= TEMP_MAX_C:
        raise RctRangeError(
            f"temperature {value} C is outside {TEMP_MIN_C}..{TEMP_MAX_C} C"
        )
    return value


def validate_speed(rpm: float) -> float:
    """Return ``rpm`` if it is a legal stir-rate setpoint, else raise.

    Args:
        rpm: Target stirring speed in revolutions per minute.

    Returns:
        The validated speed as a float.

    Raises:
        RctRangeError: If the value is outside ``SPEED_MIN_RPM`` ..
            ``SPEED_MAX_RPM``.
    """
    value = float(rpm)
    if not SPEED_MIN_RPM <= value <= SPEED_MAX_RPM:
        raise RctRangeError(
            f"speed {value} rpm is outside {SPEED_MIN_RPM}..{SPEED_MAX_RPM} rpm"
        )
    return value


def validate_watchdog_time(seconds: int) -> int:
    """Return ``seconds`` if it is a legal watchdog time, else raise.

    Args:
        seconds: Watchdog timeout in seconds.

    Returns:
        The validated time as an int.

    Raises:
        RctRangeError: If the value is outside ``WATCHDOG_MIN_S`` ..
            ``WATCHDOG_MAX_S``.
    """
    value = int(seconds)
    if not WATCHDOG_MIN_S <= value <= WATCHDOG_MAX_S:
        raise RctRangeError(
            f"watchdog time {value} s is outside "
            f"{WATCHDOG_MIN_S}..{WATCHDOG_MAX_S} s"
        )
    return value
