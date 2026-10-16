"""WiFi, through nmcli.

The deck's networks are NetworkManager keyfiles, written into the card by
`build_deck_image.sh` from `deck.secrets`. That is the right arrangement for a
deck that has just been flashed and the wrong one everywhere else: joining a
network at a park, or a friend's house, or a hotel, meant editing a file on a
laptop and reflashing. This is the same job done from the panel.

`nmcli` rather than NetworkManager's D-Bus API, which is the opposite of the
choice `btpair` made. Bluetooth pairing needed a D-Bus connection held open
for the whole operation, because BlueZ ties an agent's lifetime to the
connection that registered it — a subprocess per command could not work, and
that defect was what made the first pairing script report success on a
keyboard that could not type. WiFi has no agent and no such requirement. Each
of these commands is complete in itself, so the simple mechanism is also the
correct one, and it keeps the module importable on a machine with no
PyGObject.

Nothing here blocks the interface. Joining a network takes seconds to tens of
seconds, and the terminal polls every 200 ms; a synchronous call would freeze
the panel mid-contact. Long operations are `Op` objects, started and then
asked whether they have finished.
"""
import os
import shutil
import subprocess


NMCLI = "nmcli"

# Long enough for a scan or a query, short enough that a wedged NetworkManager
# does not hold the panel. Joining a network is not run this way; see Op.
TIMEOUT = 8


def _run(args, timeout=TIMEOUT, stdin_text=None):
    """Run nmcli and return (ok, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run([NMCLI] + list(args), capture_output=True,
                              text=True, timeout=timeout, input=stdin_text)
        return proc.returncode == 0, proc.stdout, proc.stderr.strip()
    except FileNotFoundError:
        return False, "", "nmcli is not installed"
    except subprocess.TimeoutExpired:
        return False, "", "nmcli did not answer"
    except OSError as exc:
        return False, "", str(exc)


def _split_terse(line):
    r"""Split one line of `nmcli -t` output.

    Terse output is colon-separated with literal colons backslash-escaped,
    and SSIDs contain colons often enough to matter — every SSID that is a MAC
    address, for one. Splitting on ":" alone mangles those into two fields and
    silently shifts every column after them.
    """
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def available():
    """Is there an nmcli, and is NetworkManager answering it?

    Both halves matter. A laptop running this terminal may have nmcli and no
    running NetworkManager, or neither; in both cases the WiFi screen should
    say so rather than offer controls that do nothing.
    """
    if not shutil.which(NMCLI):
        return False
    ok, out, _err = _run(["-t", "-f", "RUNNING", "general"], timeout=4)
    return ok and "running" in out.lower()


def radio():
    """'on', 'off', or '' when it cannot be determined.

    nmcli takes `on` and `off` as arguments and answers `enabled` and
    `disabled`, which is not a symmetry anyone would expect. Reading only the
    words it accepts gave "RADIO STATE UNKNOWN" on a deck whose radio was
    plainly working — and since a state of '' also drives what the `w` key
    offers to do, the toggle would have been mislabeled too. Both spellings
    are accepted here, and the fallback stays for a version that invents a
    third.
    """
    ok, out, _err = _run(["-t", "radio", "wifi"], timeout=4)
    if not ok:
        return ""
    value = out.strip().lower()
    if value in ("on", "enabled"):
        return "on"
    if value in ("off", "disabled"):
        return "off"
    return ""


def set_radio(on):
    """Switch the WiFi radio. Returns (ok, error)."""
    ok, _out, err = _run(["radio", "wifi", "on" if on else "off"], timeout=10)
    return ok, _explain(err)


def active_ssid():
    """The SSID currently connected, or ''."""
    ok, out, _err = _run(["-t", "-f", "ACTIVE,SSID", "device", "wifi"], timeout=6)
    if not ok:
        return ""
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 2 and parts[0] == "yes":
            return parts[1]
    return ""


def saved_ssids():
    """SSIDs NetworkManager already holds a profile for."""
    ok, out, _err = _run(["-t", "-f", "NAME,TYPE", "connection", "show"], timeout=6)
    names = set()
    if not ok:
        return names
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 2 and "wireless" in parts[1]:
            names.add(parts[0])
    return names


class Network:
    """One entry in the list of visible networks."""

    def __init__(self, ssid, signal=0, security="", in_use=False, known=False):
        self.ssid = ssid
        self.signal = signal
        self.security = security
        self.in_use = in_use
        self.known = known

    @property
    def secured(self):
        return bool(self.security) and self.security != "--"

    def bars(self):
        """Signal as four blocks, which reads at a glance from a foot away
        better than a percentage does.

        Built from U+2588 and a middle dot rather than the geometric shapes
        U+25AE/U+25AF that this first used. The panel runs a console font, not
        a desktop one, and a glyph it lacks is a blank column — so the only
        safe characters are the ones already proven on a shipped screen. The
        full block is what draws the pairing passkey; the middle dot is in the
        hint lines.
        """
        filled = 0 if self.signal <= 0 else min(4, 1 + self.signal // 26)
        return "█" * filled + "·" * (4 - filled)

    def security_tag(self):
        """A short name for the security, or '' for an open network.

        This replaced a padlock, which was U+1F512 — an emoji, and emoji are
        not in console fonts at any size. It would have been a blank column
        on the panel saying nothing, with a legend line explaining a symbol
        that was not there. The tag is better than the symbol it replaced
        anyway: WPA3 and WPA2 are worth telling apart, and a padlock cannot.
        """
        if not self.secured:
            return ""
        return self.security.split()[0][:4] if self.security.split() else "WPA"

    def label(self, width=40):
        # A tick for connected: also proven, also already means "this one is
        # done" on the pairing screen.
        mark = "✓" if self.in_use else ("·" if self.known else " ")
        room = max(8, width - 12)
        name = self.ssid or "(hidden)"
        if len(name) > room:
            name = name[:room - 1] + "…"
        return f"{mark} {name:<{room}} {self.bars()} {self.security_tag():<4}"

    def sort_key(self):
        # Connected first, then known, then by signal. Someone looking at this
        # screen is usually looking for one of the first two.
        return (not self.in_use, not self.known, -self.signal, self.ssid.lower())


def scan(rescan=False):
    """Visible networks strongest first, and why the list is empty if it is.

    Returns (networks, error). The error half is not decoration: a rescan is a
    privileged action, and when it was refused this returned a bare empty list
    that the screen drew as "Nothing found yet" — a permissions failure
    presented as a quiet band, which is the least useful thing it could have
    said.
    """
    # ACTIVE, not IN-USE. IN-USE is the column that carries the "*" in
    # nmcli's human output, and the obvious field to ask for — but in terse
    # mode it comes back empty for every row, connected or not, so the
    # connected marker could never appear. ACTIVE answers yes/no and is right
    # on the same rows.
    args = ["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
    # A rescan is a radio operation and takes several seconds; the cached list
    # is what the screen shows between explicit refreshes.
    args += ["--rescan", "yes" if rescan else "no"]
    ok, out, err = _run(args, timeout=20 if rescan else TIMEOUT)
    if not ok:
        return [], _explain(err)
    known = saved_ssids()
    by_ssid = {}
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        active, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        if not ssid:
            continue            # a hidden network; joined by name, not picked
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        # "yes" is what ACTIVE says; "*" is accepted too, so a version that
        # fills IN-USE-style values into this column still marks the row.
        is_active = active.strip() in ("yes", "*")

        # One row per access point, so a network on two bands from a mesh of
        # three appears six times. They are merged rather than deduplicated by
        # first-seen, which is what this did at first and which broke the
        # connected marker: the rows are ordered by signal, the associated one
        # is whichever band the radio settled on, and that is frequently not
        # the strongest. Keeping the first row threw away the only row marked
        # active, so the network the deck was connected to through showed as
        # merely known.
        existing = by_ssid.get(ssid)
        if existing is None:
            by_ssid[ssid] = Network(ssid, strength, security,
                                    is_active, ssid in known)
        else:
            existing.signal = max(existing.signal, strength)
            existing.in_use = existing.in_use or is_active
            if not existing.secured and security:
                existing.security = security
    nets = sorted(by_ssid.values(), key=Network.sort_key)
    return nets, ""


def permitted():
    """Which of the actions the screen needs are actually allowed.

    Asking beforehand rather than discovering it on the operator's first
    keystroke. NetworkManager will happily list networks for anyone — that
    needs no authorisation — so a screen that looks entirely normal can refuse
    every single thing it offers.
    """
    ok, out, _err = _run(["-t", "-f", "PERMISSION,VALUE", "general",
                          "permissions"], timeout=6)
    if not ok:
        return {}
    allowed = {}
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 2:
            allowed[parts[0]] = parts[1]
    return allowed


def blocked_reason():
    """A sentence to put on the screen when nothing will work, or ''."""
    allowed = permitted()
    if not allowed:
        return ""           # could not ask; do not invent a problem
    needed = ("org.freedesktop.NetworkManager.enable-disable-wifi",
              "org.freedesktop.NetworkManager.settings.modify.system")
    if all(allowed.get(k) == "yes" for k in needed):
        return ""
    return "not permitted — install polkit/10-cyberdeck-networkmanager.rules"


def forget(ssid):
    """Delete the saved profile. Returns (ok, error)."""
    ok, _out, err = _run(["connection", "delete", ssid], timeout=10)
    return ok, _explain(err)


class Op:
    """A command that takes too long to wait for.

    Joining a network is seconds at best and can be most of a minute when the
    access point is marginal — the case the operator is most likely to be in
    when using this screen. The terminal polls every 200 ms and must keep
    drawing, so this starts the process and is asked afterwards whether it has
    finished.
    """

    def __init__(self, args, label="", stdin_text=None):
        self.label = label
        self.error = ""
        self.ok = None              # None while running
        self._proc = None
        try:
            self._proc = subprocess.Popen(
                [NMCLI] + list(args),
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except (FileNotFoundError, OSError) as exc:
            self.ok = False
            self.error = str(exc)
            return
        if stdin_text is not None:
            try:
                self._proc.stdin.write(stdin_text)
                self._proc.stdin.close()
            except OSError:
                pass

    @property
    def done(self):
        return self.ok is not None

    def poll(self):
        """True once it has finished. Safe to call every tick."""
        if self.ok is not None or self._proc is None:
            return True
        if self._proc.poll() is None:
            return False
        _out, err = self._proc.communicate()
        self.ok = self._proc.returncode == 0
        self.error = _explain((err or "").strip())
        return True

    def cancel(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.ok is None:
            self.ok = False
            self.error = "cancelled"


def connect(ssid, psk=""):
    """Join a network, creating the profile if needed. Returns an Op.

    The passphrase goes on nmcli's command line, where it is briefly visible
    in the process list. That is a real exposure and it is not the weak point
    here: the same passphrase is already in `deck.secrets` and in the
    NetworkManager keyfile on a card with no encryption that, as the design
    doc puts it, pulls out with a fingernail. Anything that could read the
    process list on this deck already has the account that owns those files.
    Worth knowing rather than worth solving with a more fragile mechanism.
    """
    args = ["device", "wifi", "connect", ssid]
    if psk:
        args += ["password", psk]
    return Op(args, label=f"joining {ssid}")


def connect_saved(ssid):
    """Bring up a profile that already exists. Returns an Op."""
    return Op(["connection", "up", ssid], label=f"joining {ssid}")


def _explain(err):
    """Turn nmcli's stderr into something worth putting on a five inch panel."""
    if not err:
        return ""
    low = err.lower()
    if "not authorized" in low or "access denied" in low:
        # The one failure that is about the deck rather than the network, and
        # the one nobody guesses from the raw message. It is NOT about group
        # membership, which is what this used to say and what cost an evening:
        # the stock policy grants these actions to an active local session,
        # and the terminal is a systemd service with no seat and no session,
        # so polkit falls through to auth_admin and finds no agent to ask.
        # polkit/10-cyberdeck-networkmanager.rules is the answer.
        return "not permitted — install polkit/10-cyberdeck-networkmanager.rules"
    if "secrets were required" in low or "no secrets" in low:
        return "wrong passphrase"
    if "802-11-wireless-security.psk" in low:
        return "passphrase too short (8 characters minimum)"
    if "timeout" in low or "timed out" in low:
        return "timed out — out of range, or the wrong passphrase"
    if "not found" in low or "unknown connection" in low:
        return "no such network"
    # nmcli prefixes its own errors; the prefix is noise on a narrow screen.
    for prefix in ("Error: ", "error: "):
        if err.startswith(prefix):
            err = err[len(prefix):]
    return err.splitlines()[0][:60]
