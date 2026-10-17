"""Pairing a Bluetooth keyboard from the deck, with no SSH.

The crux is not the interface. An LE keyboard will not deliver input over an
unbonded link, and bonding needs a passkey **displayed by the host and typed
on the keyboard being paired** — which is why a `NoInputNoOutput` agent fails
and `KeyboardDisplay` works. The deck has a screen and the keyboard being
paired types, so SSH was never fundamentally required, only convenient at 2am.

What makes this delicate is lifetime. BlueZ tracks an agent, and discovery,
**per D-Bus connection**. The original pairing script ran each `bluetoothctl`
command as its own process, so the agent it registered was gone before pairing
began: BlueZ had nowhere to send the passkey and the script reported success
on a keyboard that could not type a character. The same rule was demonstrated
from the command line later — `StartDiscovery` in one `busctl` call and
`StopDiscovery` in another fails with "No discovery started".

So everything here happens on ONE connection held open for the whole
operation, and `tools/bt_agent_probe.py` measured that this works: an agent
registered by the deck as its own user survived a thirty-second discovery
(platform_design.md section 16).

Nothing in this module is imported until the operator asks to pair. `gi` is
not present on every machine the terminal runs on — it is a Linux, BlueZ and
PyGObject stack, and the application is also run on laptops and on machines
with no Bluetooth at all — so the import is deliberately late and its failure
is a message rather than a traceback.
"""

AGENT_PATH = "/org/cyberdeck/agent"
ADAPTER = "/org/bluez/hci0"
# Not NoInputNoOutput. The passkey has to be shown here and typed there, and
# the capability is what tells BlueZ that is possible.
CAPABILITY = "KeyboardDisplay"
KEYBOARD_ICON = "input-keyboard"

# The states the screen renders. A small set on purpose: anything the operator
# cannot act on differently does not need its own state.
IDLE, SCANNING, PAIRING, PASSKEY, PAIRED, FAILED = (
    "idle", "scanning", "pairing", "passkey", "paired", "failed")


def available():
    """(True, "") if this machine can pair, or (False, why not).

    Asked before the menu entry is drawn, so a deck that cannot pair says so
    in place rather than failing when the entry is pressed.
    """
    try:
        import gi
    except ImportError:
        return False, "python3-gi is not installed"
    try:
        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except (ValueError, ImportError) as exc:
        return False, f"GLib bindings unusable: {exc}"
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as exc:
        return False, f"no system bus: {exc.message}"
    try:
        bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.Peer", "Ping",
                      None, GLib.VariantType.new("()"),
                      Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.Error:
        return False, "BlueZ is not running"
    return True, ""


def bonded_keyboards():
    """Keyboards BlueZ already has a bond with, or [] if it cannot be asked.

    Read without registering an agent or starting discovery: this answers
    "which keyboard should the operator switch on", which is a different and
    much cheaper question than pairing a new one.
    """
    ok, _why = available()
    if not ok:
        return []
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        managed = bus.call_sync(
            "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects", None,
            GLib.VariantType.new("(a{oa{sa{sv}}})"),
            Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    except GLib.Error:
        return []
    out = [Device(path, ifaces["org.bluez.Device1"])
           for path, ifaces in managed.items()
           if "org.bluez.Device1" in ifaces]
    return sorted((d for d in out if d.is_keyboard and d.paired),
                  key=lambda d: (d.name or "").lower())


class Device:
    """One candidate, as the pairing screen needs to show it."""

    def __init__(self, path, props):
        self.path = path
        self.address = props.get("Address", "")
        self.name = props.get("Alias") or props.get("Name") or ""
        self.paired = bool(props.get("Paired", False))
        self.connected = bool(props.get("Connected", False))
        self.icon = props.get("Icon", "")
        # Present on a device being heard, absent on one BlueZ merely
        # remembers. Used only to sort and to label, never to hide something:
        # if that reading is wrong, the list is still complete.
        self.rssi = props.get("RSSI")

    @property
    def is_keyboard(self):
        return self.icon == KEYBOARD_ICON

    @property
    def tail(self):
        """The last two octets, which is what distinguishes one channel of a
        multi-channel keyboard from another under an identical name."""
        parts = self.address.split(":")
        return ":".join(parts[-2:]) if len(parts) >= 2 else self.address

    def label(self, width=40):
        name = (self.name or "(unnamed)")[:width]
        marks = []
        if self.paired:
            marks.append("paired")
        if self.connected:
            marks.append("connected")
        if self.rssi is not None:
            marks.append("here")
        return f"{name}  {self.tail}" + (f"  [{' '.join(marks)}]" if marks else "")

    def sort_key(self):
        # Advertising now first, then unpaired, then by name: the device the
        # operator just put into pairing mode should be at the top, and a
        # channel already bonded to something else should not be.
        return (self.rssi is None, self.paired, (self.name or "").lower())


class Pairing:
    """One pairing session, on one D-Bus connection.

    Driven from the terminal's own loop: `pump()` is called every poll and
    services whatever D-Bus has ready without blocking. There is no thread and
    no nested main loop, because a curses application already has a main loop
    and two of them is how an interface stops repainting.
    """

    def __init__(self, adapter=ADAPTER):
        self.adapter = adapter
        self.state = IDLE
        self.error = ""
        self.passkey = ""
        self.target = None          # the Device being paired
        self.devices = []
        self._bus = None
        self._gi = None
        self._reg_id = None
        self._registered = False
        self._discovering = False

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Connect, export and register the agent, begin discovery."""
        ok, why = available()
        if not ok:
            self.state, self.error = FAILED, why
            return False
        import gi
        from gi.repository import Gio, GLib
        self._gi = (Gio, GLib)
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self._export_agent()
            self._call_sync("/org/bluez", "org.bluez.AgentManager1",
                            "RegisterAgent",
                            GLib.Variant("(os)", (AGENT_PATH, CAPABILITY)))
            self._registered = True
            self._call_sync("/org/bluez", "org.bluez.AgentManager1",
                            "RequestDefaultAgent",
                            GLib.Variant("(o)", (AGENT_PATH,)))
            self._call_sync(self.adapter, "org.bluez.Adapter1", "StartDiscovery")
            self._discovering = True
        except GLib.Error as exc:
            self.state, self.error = FAILED, exc.message
            self.stop()
            return False
        self.state = SCANNING
        return True

    def stop(self):
        """Undo everything, in the reverse order it was done. Safe twice."""
        if self._bus is None:
            self.state = IDLE
            return
        Gio, GLib = self._gi
        for path, iface, method, params in (
                (self.adapter, "org.bluez.Adapter1", "StopDiscovery", None),
                ("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                 GLib.Variant("(o)", (AGENT_PATH,)))):
            if method == "StopDiscovery" and not self._discovering:
                continue
            if method == "UnregisterAgent" and not self._registered:
                continue
            try:
                self._call_sync(path, iface, method, params)
            except GLib.Error:
                pass        # going away anyway; a failure here helps nobody
        self._discovering = self._registered = False
        if self._reg_id is not None:
            try:
                self._bus.unregister_object(self._reg_id)
            except Exception:
                pass
            self._reg_id = None
        self._bus = None
        self.state = IDLE

    # -- the loop ----------------------------------------------------------

    def pump(self, limit=20):
        """Service pending D-Bus work without blocking.

        Called from the terminal's poll. `limit` bounds the work done in one
        pass so that a busy bus cannot starve the screen — the remainder is
        simply serviced on the next poll, a fifth of a second later.
        """
        if self._bus is None:
            return
        _Gio, GLib = self._gi
        context = GLib.MainContext.default()
        for _ in range(limit):
            if not context.pending():
                break
            context.iteration(False)

    def refresh(self):
        """Re-read the device list from BlueZ."""
        if self._bus is None:
            return
        Gio, GLib = self._gi
        try:
            managed = self._bus.call_sync(
                "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                "GetManagedObjects", None,
                GLib.VariantType.new("(a{oa{sa{sv}}})"),
                Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        except GLib.Error as exc:
            self.error = exc.message
            return
        found = [Device(path, ifaces["org.bluez.Device1"])
                 for path, ifaces in managed.items()
                 if "org.bluez.Device1" in ifaces]
        # Keyboards only. BlueZ's own Icon does this well enough that no
        # heuristic of ours is needed: on the deck it reduced ten visible
        # devices to the two channels of the keyboard in the room.
        self.devices = sorted((d for d in found if d.is_keyboard),
                              key=lambda d: d.sort_key())

    # -- pairing -----------------------------------------------------------

    def pair(self, device):
        """Begin pairing. Returns immediately; watch `state`.

        Asynchronous on purpose. `Pair` does not return until the passkey has
        been typed on the keyboard or the attempt times out, which is tens of
        seconds — a synchronous call would freeze the panel for all of it,
        including the part where it is supposed to be showing the passkey.
        """
        if self._bus is None:
            return
        Gio, GLib = self._gi
        self.target, self.passkey, self.error = device, "", ""
        self.state = PAIRING

        def done(bus, result):
            try:
                bus.call_finish(result)
                self.state = PAIRED
                self._trust(device)
            except GLib.Error as exc:
                self.state, self.error = FAILED, exc.message

        self._bus.call("org.bluez", device.path, "org.bluez.Device1", "Pair",
                       None, GLib.VariantType.new("()"),
                       Gio.DBusCallFlags.NONE, 120000, None, done)

    def _trust(self, device):
        """Mark a freshly bonded keyboard trusted so it reconnects by itself.

        Without this the bond exists and the deck still asks about the device
        every time it comes back — which on a deck with no other input is the
        same as not being paired at all.
        """
        Gio, GLib = self._gi
        try:
            self._bus.call_sync(
                "org.bluez", device.path, "org.freedesktop.DBus.Properties",
                "Set", GLib.Variant("(ssv)", ("org.bluez.Device1", "Trusted",
                                              GLib.Variant("b", True))),
                GLib.VariantType.new("()"), Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as exc:
            self.error = f"paired, but could not set trusted: {exc.message}"

    def forget(self, device):
        """Remove a bond, so a keyboard can be paired again from scratch."""
        if self._bus is None:
            return False
        Gio, GLib = self._gi
        try:
            self._call_sync(self.adapter, "org.bluez.Adapter1", "RemoveDevice",
                            GLib.Variant("(o)", (device.path,)))
            return True
        except GLib.Error as exc:
            self.error = exc.message
            return False

    # -- the agent ---------------------------------------------------------

    _AGENT_XML = """
    <node>
      <interface name='org.bluez.Agent1'>
        <method name='Release'/>
        <method name='RequestPinCode'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='pincode' direction='out'/>
        </method>
        <method name='DisplayPinCode'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='pincode' direction='in'/>
        </method>
        <method name='RequestPasskey'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='out'/>
        </method>
        <method name='DisplayPasskey'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='in'/>
          <arg type='q' name='entered' direction='in'/>
        </method>
        <method name='RequestConfirmation'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='in'/>
        </method>
        <method name='RequestAuthorization'>
          <arg type='o' name='device' direction='in'/>
        </method>
        <method name='AuthorizeService'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='uuid' direction='in'/>
        </method>
        <method name='Cancel'/>
      </interface>
    </node>"""

    def _export_agent(self):
        Gio, _GLib = self._gi
        node = Gio.DBusNodeInfo.new_for_xml(self._AGENT_XML)
        # register_object is deprecated in newer PyGObject and its replacement
        # is absent in older ones; the deck runs Debian's build and this is
        # developed against Fedora's.
        register = (getattr(self._bus, "register_object_with_closures2", None)
                    or getattr(self._bus, "register_object_with_closures", None)
                    or self._bus.register_object)
        self._reg_id = register(AGENT_PATH, node.interfaces[0],
                                self._on_agent_call, None, None)

    def _on_agent_call(self, _conn, _sender, _path, _iface, method, params,
                       invocation):
        _Gio, GLib = self._gi
        args = params.unpack() if params else ()

        if method == "DisplayPasskey":
            # The whole reason this is a KeyboardDisplay agent. BlueZ hands
            # over six digits; they go on the panel and the operator types
            # them on the keyboard being paired.
            self.passkey = f"{args[1]:06d}"
            self.state = PASSKEY
            invocation.return_value(None)
        elif method == "DisplayPinCode":
            self.passkey = str(args[1])
            self.state = PASSKEY
            invocation.return_value(None)
        elif method == "RequestConfirmation":
            # Numeric comparison: both ends show the same number. There is
            # nothing to type, so showing it and accepting is correct.
            self.passkey = f"{args[1]:06d}"
            self.state = PASSKEY
            invocation.return_value(None)
        elif method == "RequestAuthorization":
            invocation.return_value(None)
        elif method == "AuthorizeService":
            invocation.return_value(None)
        elif method == "RequestPasskey":
            # The far end wants US to type a passkey, which a keyboard being
            # paired cannot ask for. Refuse rather than invent one.
            invocation.return_error_literal(
                GLib.quark_from_string("org.bluez.Error"), 0,
                "org.bluez.Error.Rejected")
        elif method == "RequestPinCode":
            invocation.return_value(GLib.Variant("(s)", ("0000",)))
        else:
            invocation.return_value(None)

    # -- plumbing ----------------------------------------------------------

    def _call_sync(self, path, iface, method, params=None, timeout=10000):
        Gio, GLib = self._gi
        return self._bus.call_sync("org.bluez", path, iface, method, params,
                                   GLib.VariantType.new("()"),
                                   Gio.DBusCallFlags.NONE, timeout, None)
