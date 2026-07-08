"""Control the Tapo smart plugs declared in ``device_list.md``.

All device logic lives in a single self-contained :class:`SmartPlug
Controller` class so the command-line front end (``main.py``) can stay thin.
The class knows how to load its own configuration (credentials and the device
list), authenticate, reach each plug, read its status and energy, and switch it
on or off. Callers work with the plain data objects defined here
(:class:`DeviceReport`, :class:`SwitchResult`) and never touch the kasa API
directly.

Tapo devices speak the encrypted SMART protocol, so a TP-Link cloud account is
required. Credentials are read from the ``KASA_USERNAME`` and ``KASA_PASSWORD``
environment variables -- the same names the ``kasa`` CLI uses -- falling back
to the ``secure.env`` file beside this module. Credential values are never
printed.
"""

from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass
from pathlib import Path

from kasa import Credentials, Device, Discover, Module
from kasa.exceptions import KasaException

# Decorators used in this module. A decorator is the ``@name`` line written
# just above a class, function, or method ("external" annotation): Python
# applies ``name`` to the object below it and uses whatever ``name`` returns.
#   @dataclass            -- auto-generates ``__init__``/``__repr__``/``__eq__``
#       from the annotated fields, so the small data carriers below need no
#       boilerplate. ``@dataclass(frozen=True)`` also makes instances immutable
#       (used for ``DeviceEntry``).
#   @property             -- exposes a no-argument method as a read-only
#       attribute, so callers read ``report.ok`` / ``controller.entries`` like a
#       field instead of calling a method.
#   @staticmethod         -- a method that takes neither ``self`` nor ``cls``; a
#       plain function grouped under the class (e.g. ``read_energy``).
#   @classmethod          -- a method that receives the class as ``cls`` instead
#       of an instance (used by ``from_files`` and ``_read_credentials``).


class ControllerError(RuntimeError):
    """A configuration error that prevents the controller from running.

    Raised for missing credentials, a missing or empty device list, or a
    control target that matches no device. The CLI turns this into a clean
    error message instead of a traceback.
    """


@dataclass(frozen=True)
class DeviceEntry:
    """A single device as declared in ``device_list.md``.

    Attributes:
        device_type: The device family label, e.g. ``"tapo p110m"``.
        name: The human-friendly label, e.g. ``"plug1"``.
        mac: The MAC address exactly as written in the list (dash form).
        ip: The IPv4 address used to reach the device.
    """

    device_type: str
    name: str
    mac: str
    ip: str


@dataclass
class EnergyReading:
    """A snapshot of a plug's power and energy usage.

    All values are already unit-converted by the library and may be ``None``
    when the device does not report that measurement.

    Attributes:
        power_w: Instantaneous power draw, in watts.
        today_kwh: Energy used so far today, in kilowatt-hours.
        month_kwh: Energy used so far this month, in kilowatt-hours.
        voltage_v: Line voltage, in volts.
        current_a: Line current, in amperes.
    """

    power_w: float | None = None
    today_kwh: float | None = None
    month_kwh: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None


@dataclass
class DeviceReport:
    """The status read back from a device, or the error that prevented it.

    Attributes:
        entry: The source row this report corresponds to.
        is_on: The on/off state; ``None`` on failure.
        energy: The power/energy snapshot, or ``None`` if unsupported.
        serial: The device unique id (``device_id``); ``None`` on failure.
        firmware: The running firmware version; ``None`` on failure.
        model: The reported model name; ``None`` on failure.
        mac: The MAC address reported by the device (colon form).
        error: A human-readable failure reason, or ``None`` on success.
    """

    entry: DeviceEntry
    is_on: bool | None = None
    energy: EnergyReading | None = None
    serial: str | None = None
    firmware: str | None = None
    model: str | None = None
    mac: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether the device was read successfully."""
        return self.error is None


@dataclass
class SwitchResult:
    """The outcome of switching a plug on or off.

    Attributes:
        entry: The device that was switched.
        before: The on/off state observed before switching.
        after: The on/off state observed after switching.
        error: A human-readable failure reason, or ``None`` on success.
    """

    entry: DeviceEntry
    before: bool | None = None
    after: bool | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether the switch completed successfully."""
        return self.error is None


class SmartPlugController:
    """Read and control a fleet of Tapo plugs defined by a device list.

    Construct one with :meth:`from_files` (the usual path) and then call the
    high-level coroutines: :meth:`read_all` for status, and :meth:`switch_many`
    (with :meth:`resolve_targets`) to switch plugs on or off. Configuration
    loading -- credentials and the device list -- is handled by the class
    itself.
    """

    # Environment-variable names shared with the kasa CLI.
    username_env = "KASA_USERNAME"
    password_env = "KASA_PASSWORD"

    # Default input files live beside this module (the project root).
    default_device_list_path = Path(__file__).resolve().parent / "device_list.md"
    default_secret_env_path = Path(__file__).resolve().parent / "secure.env"

    def __init__(self, entries: list[DeviceEntry], credentials: Credentials) -> None:
        """Store the device list and credentials to operate on.

        Args:
            entries: The devices this controller manages.
            credentials: TP-Link cloud credentials for authentication.
        """
        self._entries = entries
        self._credentials = credentials

    @classmethod
    def from_files(
        cls,
        device_list_path: Path = default_device_list_path,
        secret_env_path: Path = default_secret_env_path,
    ) -> SmartPlugController:
        """Build a controller from the device list and credentials files.

        Args:
            device_list_path: The ``device_list.md`` to parse.
            secret_env_path: The ``secure.env`` to load credentials from.

        Returns:
            A controller ready to read and switch the listed devices.

        Raises:
            ControllerError: If credentials or the device list are unusable.
        """
        credentials = cls._read_credentials(secret_env_path)
        entries = cls._parse_device_list(device_list_path)
        return cls(entries, credentials)

    @property
    def entries(self) -> list[DeviceEntry]:
        """Return the managed devices, in list order."""
        return list(self._entries)

    @property
    def credentials(self) -> Credentials:
        """Return the credentials used to authenticate the devices."""
        return self._credentials

    def resolve_targets(self, target: str) -> list[DeviceEntry]:
        """Select the devices a control command applies to.

        Args:
            target: ``"all"`` (case-insensitive), or a device name or IP.

        Returns:
            The matching devices, in list order; empty if nothing matches.
        """
        if target.lower() == "all":
            return list(self._entries)
        return [entry for entry in self._entries if target in (entry.name, entry.ip)]

    async def read(self, entry: DeviceEntry) -> DeviceReport:
        """Connect to one device and read its full status.

        Args:
            entry: The device to query.

        Returns:
            A :class:`DeviceReport` with the status, or an error message if the
            device could not be reached or authenticated.
        """
        dev: Device | None = None
        try:
            dev = await Discover.discover_single(
                entry.ip, credentials=self._credentials
            )
            if dev is None:
                return DeviceReport(
                    entry=entry, error="Device not found or unsupported."
                )
            await dev.update()
            return DeviceReport(
                entry=entry,
                is_on=dev.is_on,
                energy=self.read_energy(dev),
                serial=dev.device_id,
                firmware=self.read_firmware(dev),
                model=dev.model,
                mac=dev.mac,
            )
        except (KasaException, OSError) as error:
            return DeviceReport(entry=entry, error=f"{type(error).__name__}: {error}")
        finally:
            if dev is not None:
                await dev.disconnect()

    async def read_all(self) -> list[DeviceReport]:
        """Read every managed device concurrently.

        Returns:
            One report per device, in list order.
        """
        return await asyncio.gather(*(self.read(entry) for entry in self._entries))

    async def switch(self, entry: DeviceEntry, *, turn_on: bool) -> SwitchResult:
        """Switch one device on or off and re-read the resulting state.

        ``turn_on``/``turn_off`` only send the command; the cached state is not
        refreshed, so ``update`` is awaited again before reading ``is_on`` back.

        Args:
            entry: The device to switch.
            turn_on: ``True`` to turn the plug on, ``False`` to turn it off.

        Returns:
            A :class:`SwitchResult` with the before/after state, or an error.
        """
        dev: Device | None = None
        try:
            dev = await Discover.discover_single(
                entry.ip, credentials=self._credentials
            )
            if dev is None:
                return SwitchResult(
                    entry=entry, error="Device not found or unsupported."
                )
            await dev.update()
            before = dev.is_on
            await (dev.turn_on() if turn_on else dev.turn_off())
            await dev.update()
            return SwitchResult(entry=entry, before=before, after=dev.is_on)
        except (KasaException, OSError) as error:
            return SwitchResult(entry=entry, error=f"{type(error).__name__}: {error}")
        finally:
            if dev is not None:
                await dev.disconnect()

    async def switch_many(
        self, entries: list[DeviceEntry], *, turn_on: bool
    ) -> list[SwitchResult]:
        """Switch several devices concurrently.

        Args:
            entries: The devices to switch.
            turn_on: ``True`` to turn the plugs on, ``False`` to turn them off.

        Returns:
            One result per device, in the given order.
        """
        return await asyncio.gather(
            *(self.switch(entry, turn_on=turn_on) for entry in entries)
        )

    @staticmethod
    def read_firmware(dev: Device) -> str | None:
        """Return the running firmware version string of an updated device.

        Prefers the Firmware module's ``current_firmware`` (the full version
        including the build suffix) and falls back to the raw ``sw_ver`` in
        ``hw_info``. Neither path performs a cloud update check.

        Args:
            dev: A device on which ``update`` has already been awaited.

        Returns:
            The firmware version, or ``None`` if it cannot be determined.
        """
        if Module.Firmware in dev.modules:
            firmware = dev.modules[Module.Firmware].current_firmware
            if firmware is not None:
                return str(firmware)
        return dev.hw_info.get("sw_ver")

    @staticmethod
    def read_energy(dev: Device) -> EnergyReading | None:
        """Return the power/energy snapshot of an updated device.

        The Energy module is present only on energy-monitoring plugs, so a
        device without it yields ``None``. Each measurement is read defensively
        because some are unsupported on certain models (e.g. lifetime total on
        the P110M).

        Args:
            dev: A device on which ``update`` has already been awaited.

        Returns:
            An :class:`EnergyReading`, or ``None`` if the device has no meter.
        """
        if Module.Energy not in dev.modules:
            return None
        energy = dev.modules[Module.Energy]
        values: dict[str, float | None] = {}
        for name in (
            "current_consumption",
            "consumption_today",
            "consumption_this_month",
            "voltage",
            "current",
        ):
            try:
                values[name] = getattr(energy, name)
            except KasaException:
                values[name] = None
        return EnergyReading(
            power_w=values["current_consumption"],
            today_kwh=values["consumption_today"],
            month_kwh=values["consumption_this_month"],
            voltage_v=values["voltage"],
            current_a=values["current"],
        )

    @staticmethod
    def _load_secret_env(path: Path) -> None:
        """Load ``export KEY=VALUE`` pairs from a file into the environment.

        Variables already present in the environment win, so credentials
        exported in the shell are not overwritten. A missing file is ignored,
        which lets the controller run when credentials are supplied another way.

        Args:
            path: The ``secure.env`` file to read.
        """
        if not path.is_file():
            return
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip().removeprefix("export ").strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                continue
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

    @classmethod
    def _read_credentials(cls, secret_env_path: Path) -> Credentials:
        """Build TP-Link cloud credentials from the environment.

        Loads ``secure.env`` first so no manual ``source`` step is needed, then
        mirrors the kasa CLI rule that the username and password are supplied
        together.

        Args:
            secret_env_path: The ``secure.env`` to load before reading vars.

        Returns:
            The credentials used to authenticate the Tapo devices.

        Raises:
            ControllerError: If the username and password are not both present.
        """
        cls._load_secret_env(secret_env_path)
        username = os.environ.get(cls.username_env)
        password = os.environ.get(cls.password_env)
        if bool(username) != bool(password):
            raise ControllerError(
                f"Set both {cls.username_env} and {cls.password_env}, not just one."
            )
        if not username:
            raise ControllerError(
                f"Missing credentials: set {cls.username_env} and "
                f"{cls.password_env} (e.g. in {secret_env_path.name})."
            )
        return Credentials(username=username, password=password)

    @staticmethod
    def _parse_device_list(path: Path) -> list[DeviceEntry]:
        """Parse the comma-separated device table in ``device_list.md``.

        The header row (``devicetype, name, mac_address, ip_address``) is
        skipped and surrounding whitespace is stripped from every field.

        Args:
            path: The ``device_list.md`` file to read.

        Returns:
            One :class:`DeviceEntry` per data row, in file order.

        Raises:
            ControllerError: If the file is missing or contains no data rows.
        """
        if not path.is_file():
            raise ControllerError(f"Device list not found: {path}")
        entries: list[DeviceEntry] = []
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                cells = [cell.strip() for cell in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if len(cells) < 4 or cells[0].lower() == "devicetype":
                    continue
                device_type, name, mac, ip = cells[:4]
                entries.append(DeviceEntry(device_type, name, mac, ip))
        if not entries:
            raise ControllerError(f"No devices found in {path}.")
        return entries
