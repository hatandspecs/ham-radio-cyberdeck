"""The pairing screen: what it shows, and that it degrades off a deck.

The BlueZ conversation itself cannot be tested here — there is no way to
synthesise "a keyboard bonded successfully" — so `tools/bt_agent_probe.py`
measured the one property the design rests on instead, against real hardware
(platform_design.md section 16). What IS testable is everything around it: the
screen, the device model, and the refusal on a machine that cannot pair.

That refusal matters as much as the feature. The application runs on ordinary
laptops, and `btpair` needs Linux, BlueZ and PyGObject. None of it may be
imported at startup, and asking for it where it cannot work has to produce a
sentence rather than a traceback.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import btpair
import render


def dev(addr, name="Pebble K380s", icon="input-keyboard", **props):
    return btpair.Device(f"/org/bluez/hci0/dev_{addr.replace(':', '_')}",
                         {"Address": addr, "Alias": name, "Icon": icon, **props})


def text(lines):
    return "\n".join("".join(t for t, _k in ln) for ln in lines)


if __name__ == "__main__":
    print("Pairing")

    # -- the device model, against what the deck actually saw ---------------
    # A K380 has three channel buttons and advertises one address per channel,
    # all under the same name. On the deck: button 1 bonded to a phone, button
    # 3 bonded here, button 2 held in pairing mode — two entries, one name.
    here = dev("DF:3C:77:61:6C:22", RSSI=-54)
    bonded = dev("DF:3C:77:61:6C:21", Paired=True)
    tv = dev("BC:45:5B:76:BC:65", name="Samsung CU7000 75 TV", icon="video-display")

    check("a keyboard is recognised by BlueZ's own icon", here.is_keyboard)
    check("a television is not", not tv.is_keyboard)
    equals("the address tail distinguishes two channels of one keyboard",
           (here.tail, bonded.tail), ("6C:22", "6C:21"))
    check("which is the only thing that does",
          here.name == bonded.name, (here.name, bonded.name))

    order = sorted([bonded, here], key=lambda d: d.sort_key())
    equals("the one being heard sorts first", order[0].tail, "6C:22")

    # -- the screen ---------------------------------------------------------
    body = text(render.pair_screen("scanning", [here, bonded], 66, 20))
    check("both channels are listed", body.count("Pebble K380s") == 2, body)
    check("with their addresses", "6C:22" in body and "6C:21" in body, body)
    check("the bonded one is marked", "paired" in body, body)
    check("the advertising one is marked", "here" in body, body)
    check("and the reason two appear is explained on screen",
          "channel" in body, body)
    check("it is framed", "┌" in body and "└" in body, body[:80])

    empty = text(render.pair_screen("scanning", [], 66, 20))
    check("with nothing found, it says what to do",
          "pairing key" in empty, empty)

    # The passkey is the one number read off this panel and typed elsewhere,
    # against a timeout. It is set in block characters for that reason.
    key = text(render.pair_screen("passkey", [], 66, 20, passkey="482190"))
    check("the passkey is drawn large", "█" in key, key)
    check("and says where to type it", "KEYBOARD" in key.upper(), key)
    rows = render.big_number("482190", 62)
    equals("six digits occupy five rows", len(rows), render.BIG_ROWS)
    check("a passkey with no block glyph still renders",
          render.big_number("ab-12", 40) != [], "")

    failed = text(render.pair_screen("failed", [], 66, 20,
                                     error="org.bluez.Error.AuthenticationFailed"))
    check("a failure shows the reason", "AuthenticationFailed" in failed, failed)
    check("and how to retry", "blinks" in failed, failed)

    ok = text(render.pair_screen("paired", [], 66, 20))
    check("success says it is trusted too", "TRUSTED" in ok.upper(), ok)

    # Every state must fit the panel exactly.
    for state in ("scanning", "pairing", "passkey", "paired", "failed"):
        lines = render.pair_screen(state, [here], 66, 20, passkey="482190")
        equals(f"{state} fills 20 rows", len(lines), 20)
        widest = max(len("".join(t for t, _k in ln)) for ln in lines)
        check(f"{state} stays within 66 columns", widest <= 66, widest)

    # -- the tap mapping ----------------------------------------------------
    # A tap is how a device is chosen when no keyboard is attached, so the row
    # it lands on has to agree with where the renderer put the list.
    lines = render.pair_screen("scanning", [here, bonded], 66, 20)
    first = text([lines[render.PAIR_ROW0]])
    check("PAIR_ROW0 is the first device row", "6C:22" in first, first)
    second = text([lines[render.PAIR_ROW0 + 1]])
    check("and the next row is the next device", "6C:21" in second, second)

    # -- the no-keyboard screen ---------------------------------------------
    #
    # The screen that exists for the moment the deck cannot be told anything.
    # Its bootstrap problem is the point: pairing lives behind F1, and F1
    # needs the keyboard that is missing.
    off = text(render.no_keyboard_screen([bonded], 66, 20))
    check("it names the keyboard already bonded", "Pebble K380s" in off, off)
    check("with the address, since channels share a name", "6C:21" in off, off)
    check("and says to switch it on", "Switch it on" in off, off)
    check("offering pairing as the second answer, not the only one",
          "TAP THE SCREEN TO PAIR" in off, off)
    check("it is framed like the pairing screen", "┌" in off, off[:80])

    none_bonded = text(render.no_keyboard_screen([], 66, 20))
    check("with nothing bonded it says so instead",
          "Nothing is paired" in none_bonded, none_bonded)
    check("and explains how to put a keyboard into pairing mode",
          "blinks" in none_bonded, none_bonded)

    cannot = text(render.no_keyboard_screen([bonded], 66, 20, can_pair=False))
    check("where pairing is impossible it does not offer it",
          "TAP THE SCREEN" not in cannot, cannot)
    check("and says why the offer is missing",
          "not available" in cannot, cannot)

    for label, arg in (("with bonds", [bonded]), ("without", [])):
        lines = render.no_keyboard_screen(arg, 66, 20)
        equals(f"no-keyboard screen fills 20 rows {label}", len(lines), 20)
        widest = max(len("".join(t for t, _k in ln)) for ln in lines)
        check(f"and stays within 66 columns {label}", widest <= 66, widest)

    # -- degrading off a deck -----------------------------------------------
    ok_here, why = btpair.available()
    check("available() answers without raising, whatever this machine is",
          isinstance(ok_here, bool) and isinstance(why, str), (ok_here, why))
    if not ok_here:
        check("and gives a reason when it cannot", bool(why), why)

    source = open(os.path.join(os.path.dirname(_HERE), "src", "cyberdeck.py")).read()
    check("btpair is never imported at startup",
          "import btpair" in source and "\nimport btpair" not in source,
          "it must be imported inside the pairing entry point only")

    sys.exit(report())
