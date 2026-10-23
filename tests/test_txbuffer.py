"""Aborting an over must not leave its tail for the next one.

`start_over` and `send_more` both reach fldigi through `text.add_tx`, which
APPENDS to the transmit widget. `main.abort` drops the carrier and leaves
whatever had not gone out sitting in that widget -- so the next over went on
the air behind a fragment of the aborted one. Reported from the panel
2026-10-23.

What the operator saw: abort mid-over, type something new, press Ctrl-T, and
the remainder of the abandoned message goes out first.

This drives `Fldigi` against a recording stub rather than the real
application, because what has to be asserted is the ORDER of the calls --
stop the transmitter, then discard the text -- and a live fldigi would show
only the result.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import fldigi_client


class Recorder:
    """Stands in for the XML-RPC proxy and remembers what was asked."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, *args, **kw):
        self.calls.append((name, args))
        return kw.get("default", "")

    def names(self):
        return [n for n, _a in self.calls]


def client():
    f = fldigi_client.Fldigi.__new__(fldigi_client.Fldigi)
    rec = Recorder()
    f._call = rec
    f._rx_pos = 0
    # `hand_back` reports whether fldigi took the instruction; the stub is
    # always there.
    f.connected = True
    return f, rec


print("abort stops the transmitter and then discards the unsent text")
f, rec = client()
f.abort()
equals("both calls go out", rec.names(), ["main.abort", "text.clear_tx"])
check("the transmitter is stopped first — that is the order that matters",
      rec.names().index("main.abort") < rec.names().index("text.clear_tx"),
      rec.names())

print("\nso the next over carries only what was typed for it")
# The sequence the operator reported: send, abort partway, type something
# else, send again. Without the clear, fldigi's widget still holds the
# remainder and `text.add_tx` appends the new message behind it.
f, rec = client()
f.start_over("CQ CQ DE KD3CCO KD3CCO K")
f.abort()
f.start_over("SORRY ABOUT THAT")
adds = [a[0] for n, a in rec.calls if n == "text.add_tx"]
equals("each over added its own text", adds,
       ["CQ CQ DE KD3CCO KD3CCO K", "SORRY ABOUT THAT"])
# The whole sequence, in order. The clear has to fall between the abort and
# the second over's text, or that text goes out behind the first over's
# remainder.
equals("the calls, in order", rec.names(),
       ["text.add_tx", "main.tx",          # the first over
        "main.abort", "text.clear_tx",     # stopped, and the tail dropped
        "text.add_tx", "main.tx"])         # the second, on its own

print("\nhanding back does NOT clear — the buffer is what is draining")
# `hand_back` puts a "receive when drained" mark in the stream. Clearing
# there would throw away the over the operator just chose to finish.
f, rec = client()
f.start_over("TEST")
f.hand_back()
check("nothing is discarded", "text.clear_tx" not in rec.names(),
      rec.names())
check("the mark is placed instead",
      rec.calls[-1][0] == "text.add_tx", rec.calls[-1])

print("\nnor does sending more mid-over")
f, rec = client()
f.send_more(" AND MORE")
check("it only appends", rec.names() == ["text.add_tx"], rec.names())

print("\nan abort with nothing queued is still safe to send")
f, rec = client()
f.abort()
f.abort()
equals("it just clears again", rec.names().count("text.clear_tx"), 2)

sys.exit(report())
