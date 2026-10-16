"""The WiFi screen and the nmcli parsing under it.

No network is touched here. What is tested is the part that is wrong quietly:
parsing nmcli's terse output, turning its errors into something readable on a
five inch panel, and the row arithmetic that turns a tap into a network.

That last one has a precedent. PAIR_ROW0 carries a comment saying it must
track the renderer rather than be guessed at, because a tap landing one row
out selects the wrong device and looks like a touchscreen fault. WIFI_ROW0 is
the same constant for the same reason, and this asserts it against the
renderer instead of trusting it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

from harness import check, equals, report
from test_screen import run
import render
import menus
import wifi

F1 = "\x1bOP"
# The deck's own settings are an area of their own now: ^B ^B reaches its
# screen, F1 opens its menu, and System is the fourth line. WiFi, pairing, the
# transmit inhibit and quit are all behind it.
DECK_SYSTEM = ["\x0f", "\x0f", F1, "4"]


def plain(segments):
    return "".join(text for text, _kind in segments)


if __name__ == "__main__":
    print("nmcli terse output")
    equals("a plain line splits on colons",
           wifi._split_terse("*:HomeNet:72:WPA2"),
           ["*", "HomeNet", "72", "WPA2"])
    # An SSID that is a MAC address is the common case, and splitting on ":"
    # alone turns one field into seven and shifts every column after it.
    equals("an escaped colon stays inside its field",
           wifi._split_terse(r" :aa\:bb\:cc:64:WPA2"),
           [" ", "aa:bb:cc", "64", "WPA2"])
    equals("a trailing empty field is kept",
           wifi._split_terse("x::"), ["x", "", ""])
    equals("an escaped backslash is one backslash",
           wifi._split_terse(r"a\\b:2"), ["a\\b", "2"])

    print("\nNetworks")
    open_net = wifi.Network("Cafe", 40, "", False, False)
    wpa = wifi.Network("Home", 88, "WPA2", True, True)
    equals("an empty security field means open", open_net.secured, False)
    equals("'--' also means open",
           wifi.Network("x", 1, "--").secured, False)
    equals("WPA2 means secured", wpa.secured, True)
    check("a strong signal fills every block", wpa.bars() == "████", wpa.bars())
    check("a dead signal fills none",
          wifi.Network("x", 0).bars() == "····", wifi.Network("x", 0).bars())
    check("a weak signal still shows one",
          wifi.Network("x", 1).bars().startswith("█"), wifi.Network("x", 1).bars())
    check("the connected network sorts first",
          sorted([open_net, wpa], key=wifi.Network.sort_key)[0] is wpa, "")
    check("the label marks the connected one", "✓" in wpa.label(40), wpa.label(40))
    check("and names the security of a secured one",
          "WPA2" in wpa.label(40), wpa.label(40))
    check("an open network gets no security tag",
          "WPA" not in open_net.label(40), open_net.label(40))
    equals("a multi-word security is shortened to its first word",
           wifi.Network("x", 50, "WPA2 WPA3").security_tag(), "WPA2")

    # The panel runs a console font, so a glyph it lacks is a blank column.
    # Only characters already proven on a shipped screen may appear here.
    PROVEN = set(" ·—↑↓─│┌┐└┘├┤█▸●✓✗…")
    for net in (wpa, open_net, wifi.Network("x", 0, "WPA3", False, True)):
        bad = {c for c in net.label(40) if ord(c) > 127} - PROVEN
        check(f"no unrenderable glyph in {net.ssid!r}'s row", not bad,
              sorted(f"U+{ord(c):04X}" for c in bad))

    print("\nMerging the rows nmcli gives per access point")
    real_run = wifi._run
    try:
        # A mesh or a dual-band router produces one row per radio, ordered by
        # signal, and the associated one is whichever band was settled on —
        # frequently not the strongest. Keeping the first row discarded the
        # only row marked active, so the connected network showed as merely
        # known. This is that output verbatim.
        rows = ("no:Archer:99:WPA2\n"
                "no:Archer:72:WPA2\n"
                "yes:Archer:62:WPA2\n"
                "no:Archer:47:WPA2\n"
                "no:Other:80:WPA2\n")
        calls = []

        def fake(args, **kwargs):
            calls.append(args)
            if "connection" in args:
                return True, "Archer:802-11-wireless\n", ""
            return True, rows, ""

        wifi._run = fake
        nets_got, err = wifi.scan()
        equals("six rows for two networks become two", len(nets_got), 2)
        archer = [n for n in nets_got if n.ssid == "Archer"][0]
        check("the connected row is not lost to a stronger one",
              archer.in_use, "in_use was False")
        equals("and the strongest signal is the one kept", archer.signal, 99)
        check("the connected network sorts to the top",
              nets_got[0].ssid == "Archer", [n.ssid for n in nets_got])
        check("its label carries the connected mark",
              "✓" in archer.label(40), archer.label(40))

        # The field asked for matters: IN-USE is the column carrying "*" in
        # nmcli's human output and comes back empty for every row in terse
        # mode, so the marker could never appear.
        scan_args = [a for a in calls if "list" in a][0]
        check("the scan asks for ACTIVE, not IN-USE",
              "ACTIVE,SSID,SIGNAL,SECURITY" in scan_args, scan_args)
    finally:
        wifi._run = real_run

    print("\nErrors worth reading on a panel")
    # This used to name the netdev group, which was wrong and cost real time:
    # the account was already in netdev. The stock policy grants these actions
    # to an active local session, and the terminal is a systemd service with
    # neither seat nor session, so the answer is a polkit rule.
    denied = wifi._explain("Error: not authorized to control networking.")
    check("an authorisation failure names the polkit rule", "polkit" in denied, denied)
    check("and does not send anyone to check groups", "netdev" not in denied, denied)
    equals("a missing secret is called what it is",
           wifi._explain("Error: Secrets were required, but not provided."),
           "wrong passphrase")
    equals("nothing in, nothing out", wifi._explain(""), "")
    check("an unrecognised error keeps its text and loses the prefix",
          wifi._explain("Error: something else entirely")
          .startswith("something else"),
          wifi._explain("Error: something else entirely"))

    print("\nThe screen")
    nets = [wifi.Network("Home", 88, "WPA2", True, True),
            wifi.Network("Cafe", 40, "", False, False)]
    lines = render.wifi_screen("list", nets, 66, 20, radio="on")
    equals("it fills the height", len(lines), 20)
    check("every row fits the width",
          all(len(plain(l)) <= 66 for l in lines),
          max(len(plain(l)) for l in lines))
    body = "\n".join(plain(l) for l in lines)
    check("both networks are shown", "Home" in body and "Cafe" in body, body[:200])
    check("the radio state is shown", "RADIO ON" in body, body[:120])
    PROVEN_SCREEN = set(" ·—↑↓─│┌┐└┘├┤█▸●✓✗…§")
    for state, kw in (("list", {}), ("failed", {"error": "wrong passphrase",
                                                "ssid": "X", "retry": True}),
                      ("joined", {"ssid": "X"}), ("working", {"message": "j"}),
                      ("unavailable", {"error": "no"})):
        rows = render.wifi_screen(state, nets, 66, 20, radio="on", **kw)
        bad = {c for l in rows for c in plain(l) if ord(c) > 127} - PROVEN_SCREEN
        check(f"the {state} screen uses no glyph the panel lacks", not bad,
              sorted(f"U+{ord(c):04X} {c}" for c in bad))
    # s scans, r toggles the radio — s for scan and r for radio, rather than
    # the r/w pair they started as, which named neither thing.
    check("the radio line names the key that toggles it",
          "r turns it off" in body, body[:200])

    # The constant a tap is resolved through, checked against the renderer.
    first = next(i for i, l in enumerate(lines) if "Home" in plain(l))
    equals("WIFI_ROW0 is the row of the first network", render.WIFI_ROW0, first)

    off = "\n".join(plain(l) for l in render.wifi_screen("list", [], 66, 20,
                                                        radio="off"))
    check("with the radio off it says so rather than showing an empty list",
          "RADIO OFF" in off and "radio is off" in off, off[:300])

    failed = "\n".join(plain(l) for l in render.wifi_screen(
        "failed", [], 66, 20, error="wrong passphrase"))
    check("a failure shows the reason", "wrong passphrase" in failed, failed[:200])

    working = "\n".join(plain(l) for l in render.wifi_screen(
        "working", [], 66, 20, message="joining Home"))
    check("working says what it is doing", "joining Home" in working, working[:200])

    unavailable = "\n".join(plain(l) for l in render.wifi_screen(
        "unavailable", [], 66, 20, error="NetworkManager is not answering"))
    check("an unusable WiFi says so instead of offering controls",
          "cannot be controlled" in unavailable, unavailable[:200])

    # A phone-narrow panel is not a supported size, but the renderer must not
    # produce rows wider than it is asked for at any size.
    for w in (40, 52, 66, 80):
        rows = render.wifi_screen("list", nets, w, 20, radio="on")
        check(f"width {w} is respected",
              all(len(plain(l)) <= w for l in rows),
              max(len(plain(l)) for l in rows))

    print("\nA scan says why it failed")
    real_run = wifi._run
    try:
        wifi._run = lambda *a, **k: (False, "", "Error: not authorized to control networking.")
        nets_got, err = wifi.scan()
        equals("a refused scan returns no networks", nets_got, [])
        check("and says it was refused, not that the band was empty",
              "not permitted" in err, err)
        check("the reason names the rule file, not a group",
              "polkit" in err and "netdev" not in err, err)
        wifi._run = lambda *a, **k: (True, "no:Home:72:WPA2\n", "")
        nets_got, err = wifi.scan()
        equals("a good scan reports no error", err, "")
        equals("and parses the network", [n.ssid for n in nets_got], ["Home"])

        # Listing networks needs no authorisation, so a screen that works
        # perfectly can still refuse every key on it.
        wifi._run = lambda *a, **k: (
            True,
            "org.freedesktop.NetworkManager.enable-disable-wifi:no\n"
            "org.freedesktop.NetworkManager.settings.modify.system:no\n", "")
        check("a deck that may not control WiFi says so up front",
              "polkit" in wifi.blocked_reason(), wifi.blocked_reason())
        wifi._run = lambda *a, **k: (
            True,
            "org.freedesktop.NetworkManager.enable-disable-wifi:yes\n"
            "org.freedesktop.NetworkManager.settings.modify.system:yes\n", "")
        equals("and stays quiet when it may", wifi.blocked_reason(), "")
        wifi._run = lambda *a, **k: (False, "", "boom")
        equals("an unanswerable question invents no problem",
               wifi.blocked_reason(), "")
    finally:
        wifi._run = real_run

    print("\nThe radio state, as nmcli actually words it")
    # nmcli takes "on" and "off" and answers "enabled" and "disabled". Reading
    # only the words it accepts put "RADIO STATE UNKNOWN" on a working deck.
    real_run = wifi._run
    try:
        for said, want in (("enabled", "on"), ("disabled", "off"),
                           ("on", "on"), ("off", "off")):
            wifi._run = lambda *a, _s=said, **k: (True, _s + "\n", "")
            equals(f"nmcli saying {said!r} reads as {want!r}", wifi.radio(), want)
        wifi._run = lambda *a, **k: (True, "who knows\n", "")
        equals("an unrecognised answer is unknown, not a guess", wifi.radio(), "")
        wifi._run = lambda *a, **k: (False, "", "boom")
        equals("a failed call is unknown too", wifi.radio(), "")
    finally:
        wifi._run = real_run

    print("\nThe footer fits the panel")
    # 66 columns is the deck. The renderer truncates rather than wrapping, so
    # a footer one character too long silently loses its last key — which is
    # how the radio key became "w rad" and the least guessable key disappeared.
    foot = plain(render.wifi_screen("list", nets, 66, 20, radio="on")[-1])
    for key in ("Esc back", "Enter join", "f forget", "s scan", "r radio"):
        check(f"the footer keeps {key!r} whole", key in foot, foot)

    print("\nThe menu")
    keys = [k for k, _label in menus.SYSTEM["items"]]
    check("the System menu offers WiFi", "w" in keys, keys)
    check("and still offers pairing", "b" in keys, keys)
    equals("no key is duplicated", len(keys), len(set(keys)))

    # ---- the real application -------------------------------------------
    #
    # Everything above is the module and the renderer. The fault that reached
    # the deck was in neither: the passphrase editor opens with key=None,
    # because a passphrase has no config field to be written to, and
    # _draw_edit called .startswith on it. That raised on the first draw, so
    # the terminal crashed the instant the editor appeared and systemd
    # restarted it - from the panel, a pause and then the conversation screen,
    # which looks like a menu closing rather than a crash.
    #
    # `n` (join by name) opens the same editor by the same path and needs no
    # network in range, so it is the deterministic way to press this.
    print("\nA failed join offers a retry")
    failed_retry = "\n".join(plain(l) for l in render.wifi_screen(
        "failed", [], 66, 20, error="wrong passphrase", ssid="Pixel", retry=True))
    check("it names the network that failed", "Pixel" in failed_retry,
          failed_retry[:300])
    check("it offers to retype the passphrase",
          "Enter" in failed_retry and "passphrase again" in failed_retry,
          failed_retry[:400])
    check("and says nothing was kept, since a wrong key would otherwise "
          "be saved and silently reused",
          "Nothing was kept" in failed_retry, failed_retry[:400])

    failed_open = "\n".join(plain(l) for l in render.wifi_screen(
        "failed", [], 66, 20, error="timed out", ssid="Cafe", retry=False))
    check("an open network is offered no passphrase retry",
          "passphrase again" not in failed_open, failed_open[:400])

    print("\nThe editor hint line")
    equals("an ordinary field gets the ordinary hint",
           render.edit_hint(False, False), render.EDIT_HINT)
    check("a masked field says how to show it",
          "^R" in render.edit_hint(True, False)
          and "show" in render.edit_hint(True, False),
          render.edit_hint(True, False))
    check("and once shown, how to hide it again",
          "hide" in render.edit_hint(True, True), render.edit_hint(True, True))
    for secret, revealed in ((False, False), (True, False), (True, True)):
        h = render.edit_hint(secret, revealed)
        check(f"the hint fits the panel ({secret}, {revealed})", len(h) <= 65, len(h))

    print("\nOpening the by-name editor in the real application")
    screen = run(keys=DECK_SYSTEM + ["w", "n"], settle=2.0, settle_s="600")
    body = "\n".join(screen.display)
    check("it exited cleanly rather than crashing", screen.exited_cleanly,
          body[:200])
    if "cannot be controlled" in body:
        check("WiFi is unavailable here, so the editor was not reachable",
              True, "skipped")
    else:
        check("the editor opened instead of the deck restarting",
              "network name" in body, body[:300])
        check("and it is the editor, not the conversation screen",
              "EDIT" in body, body[:300])

    # Typing a name and pressing Enter reaches the passphrase editor with no
    # network anywhere in range, which is the only deterministic way to get a
    # masked field in front of the real application.
    print("\nThe passphrase field masks, and Ctrl-R reveals")
    screen = run(keys=DECK_SYSTEM + ["w", "n", "H", "i", "\r",
                       "s", "e", "c", "r", "3", "t"],
                 settle=2.0, settle_s="600")
    body = "\n".join(screen.display)
    if "cannot be controlled" in body:
        check("WiFi is unavailable here, so the field was not reachable",
              True, "skipped")
    else:
        check("the passphrase field opened", "passphrase for Hi" in body, body[:300])
        check("what was typed is not on the screen", "secr3t" not in body, body[:300])
        check("bullets are", "••••••" in body, body[:300])
        check("and the hint offers to show it", "^R" in body, body[:400])

    screen = run(keys=DECK_SYSTEM + ["w", "n", "H", "i", "\r",
                       "s", "e", "c", "r", "3", "t", "\x12"],
                 settle=2.0, settle_s="600")
    body = "\n".join(screen.display)
    if "cannot be controlled" not in body:
        check("Ctrl-R shows the passphrase", "secr3t" in body, body[:300])
        check("and the hint now offers to hide it", "hide" in body, body[:400])

    report()
