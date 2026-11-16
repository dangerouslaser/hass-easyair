"""Minimal BlueZ pairing agent that answers passkey/PIN requests (Linux only).

Bleak cannot answer a passkey prompt on its own. Registering this agent as the
default BlueZ agent lets Device1.Pair() complete with the unit's 6-digit PIN.
"""
import logging

from dbus_fast import BusType, DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

_LOGGER = logging.getLogger(__name__)
AGENT_PATH = "/com/github/hass_easyair/agent"


class _Agent(ServiceInterface):
    def __init__(self, pin, allowed_address):
        super().__init__("org.bluez.Agent1")
        self._pin = pin
        self._allowed = allowed_address.upper().replace(":", "_") if allowed_address else None

    def _check(self, device: str) -> None:
        if self._allowed and not device.upper().endswith(self._allowed):
            raise DBusError("org.bluez.Error.Rejected", "Not our device")

    @method()
    def Release(self):  # noqa: N802
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: F821,N802
        self._check(device)
        _LOGGER.debug("PIN code requested by %s", device)
        return self._pin

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: F821,N802
        self._check(device)
        _LOGGER.debug("Passkey requested by %s", device)
        return int(self._pin)

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: F821,N802
        pass

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821,N802
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821,N802
        self._check(device)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: F821,N802
        self._check(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821,N802
        self._check(device)

    @method()
    def Cancel(self):  # noqa: N802
        pass


class PasskeyAgent:
    """Context manager: register a passkey agent for the duration of a pairing."""

    def __init__(self, pin, address=None):
        self._pin = pin
        self._address = address
        self._bus = None

    async def __aenter__(self) -> "PasskeyAgent":
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus.export(AGENT_PATH, _Agent(self._pin, self._address))
        intro = await self._bus.introspect("org.bluez", "/org/bluez")
        mgr = self._bus.get_proxy_object("org.bluez", "/org/bluez", intro).get_interface(
            "org.bluez.AgentManager1"
        )
        await mgr.call_register_agent(AGENT_PATH, "KeyboardOnly")
        await mgr.call_request_default_agent(AGENT_PATH)
        self._mgr = mgr
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self._mgr.call_unregister_agent(AGENT_PATH)
        except Exception:  # noqa: BLE001
            pass
        if self._bus:
            self._bus.disconnect()
