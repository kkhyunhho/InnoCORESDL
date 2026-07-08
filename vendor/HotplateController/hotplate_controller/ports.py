"""Locate the RCT digital's serial port by USB hardware id.

On Linux the RCT digital enumerates as an STM32 virtual COM port
(``/dev/ttyACM*``) whose number is not stable when other USB serial
devices are present. Matching on the USB VID:PID is therefore more
reliable than a hard-coded path. ``ika`` requires an explicit port
string, so this fills that gap.
"""

from typing import Optional

from serial.tools import list_ports

from .limits import RCT_USB_PID, RCT_USB_VID


def find_rct_port() -> Optional[str]:
    """Return the device path of the connected RCT digital, if any.

    Scans the system serial ports for one whose USB vendor and product
    ids match the RCT digital's STM32 virtual COM port.

    Returns:
        The port path (e.g. ``"/dev/ttyACM1"``) of the first match, or
        ``None`` when no matching device is found.
    """
    for port in list_ports.comports():
        if port.vid == RCT_USB_VID and port.pid == RCT_USB_PID:
            return port.device
    return None
