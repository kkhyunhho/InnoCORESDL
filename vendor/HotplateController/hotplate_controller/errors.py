"""Exceptions and device error-code descriptions for the RCT digital.

The ``Er..`` codes and their meanings are taken from the device manual
(``docs/EN_IKA Plate_RCT 5 digital -english.pdf``), which the ``ika``
package does not interpret. ``describe_error_code`` turns a code the
device may report into a human-readable explanation.
"""


class RctError(Exception):
    """Base class for every RCT digital controller error."""


class RctRangeError(RctError, ValueError):
    """A setpoint or watchdog value is outside the allowed range."""


class RctCommError(RctError):
    """A serial exchange failed, timed out, or returned no data."""


# Device fault codes shown on the display, from the manual's
# "Error codes" section.
ERROR_CODES = {
    "Er02": "Watchdog timeout: no data within the set watchdog time; "
    "heating and motor switched off.",
    "Er03": "Temperature inside the device higher than 80 C; "
    "heating switched off.",
    "Er04": "Motor control unavailable: motor blocked or overloaded.",
    "Er05": "No temperature increase measured by the sensor "
    "within the selected time.",
    "Er06": "Interruption of the safety circuit (check plug / PT 1000 sensor).",
    "Er13": "Hotplate safety sensor open-circuit.",
    "Er14": "External temperature sensor short-circuit.",
    "Er21": "Fault during heating plate safety test "
    "(safety relay did not open).",
    "Er22": "Fault during heating plate safety test "
    "(S_CHECK cannot generate H_S_TEMP).",
    "Er24": "Heating plate temperature higher than the set safety temperature.",
    "Er25": "Heating switching element monitoring fail.",
    "Er26": "Plate temperature exceeds plate safety temperature "
    "by more than 40 K.",
    "Er31": "Fault in the heater switch element.",
    "Er44": "Heating plate safety temperature higher than the set "
    "safety temperature.",
    "Er46": "Plate safety temperature exceeds plate temperature "
    "by more than 40 K.",
}


def describe_error_code(code: str) -> str:
    """Return a human-readable description for a device error code.

    Args:
        code: A code such as ``"Er02"`` (case-insensitive).

    Returns:
        The manual's description, or a generic message for an
        unknown code.
    """
    normalized = code.strip().capitalize()
    return ERROR_CODES.get(normalized, f"Unknown device error code: {code}")
