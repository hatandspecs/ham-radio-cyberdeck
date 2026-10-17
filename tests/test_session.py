"""Behavior of the over-based transmit model (docs/digimodes_design.md §5.4)."""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
import session
from session import Session, RX, TX


def transcript(s):
    return [(e.who, e.text) for e in s.entries]

print("-- Enter composes, it does not transmit --")
s = Session(callsign="KD3CCO")
for ch in "hello there\n":
    check_out = s.type(ch)
equals("nothing went on the air", s.compose, "hello there\n")
equals("nothing in the transcript yet", transcript(s), [])
equals("indicator counts the buffer", s.buffer_indicator(), "[RX 12]")

print("\n-- Ctrl-T sends the buffer and keys --")
out = s.start_over()
equals("the buffered text is what goes out", out, "hello there\n")
equals("state is transmitting", s.state, TX)
equals("buffer is emptied", s.compose, "")
equals("transcript attributes it to us", transcript(s), [("KD3CCO", "hello there")])
equals("indicator shows TX", s.buffer_indicator(), "[TX]")

print("\n-- typing mid-over goes out live, character by character --")
sent = "".join(s.type(c) for c in "more")
equals("each character is returned for sending", sent, "more")
equals("and joins the same transcript line", transcript(s)[-1], ("KD3CCO", "more"))
equals("buffer stays empty mid-over", s.compose, "")

print("\n-- Ctrl-Y hands back --")
equals("hand_back succeeds", s.hand_back(), True)
equals("state returns to receive", s.state, RX)
equals("the line is closed", s.entries[-1].closed, True)
equals("hand_back again is a no-op", s.hand_back(), False)

print("\n-- received text is attributed to the far end --")
s.receive("NOCALL de ")
s.receive("KD3CCO copy\n")
equals("RX text accumulates into one line", transcript(s)[-1], ("RX", "NOCALL de KD3CCO copy"))
# Typing while receiving does not touch the transcript: it goes into the
# compose buffer and is shown at the bottom of the screen. It only becomes a
# transcript entry when the over starts.
s.type("x")
equals("typing while receiving stays out of the transcript", transcript(s)[-1][0], "RX")
equals("and lands in the compose buffer", s.compose, "x")
equals("then appears when the over starts", (s.start_over(), transcript(s)[-1]),
      ("x", ("KD3CCO", "x")))

print("\n-- backspace corrects while receiving, not mid-over --")
s2 = Session(callsign="KD3CCO")
for ch in "helo":
    s2.type(ch)
equals("backspace works while composing", (s2.backspace(), s2.compose), (True, "hel"))
s2.start_over()
equals("backspace refused mid-over", s2.backspace(), False)

print("\n-- abort stops immediately and says so --")
equals("abort while transmitting reports True", s2.abort(), True)
equals("state is receive", s2.state, RX)
equals("a marker is in the transcript", s2.entries[-1].who, "--")
equals("abort while receiving reports False", s2.abort(), False)

print("\n-- transmit time-out --")
now = [0.0]
s3 = Session(callsign="KD3CCO", tx_timeout=180, clock=lambda: now[0])
s3.type("a"); s3.start_over()
now[0] = 179.0; equals("not yet timed out at 179 s", s3.tx_timed_out(), False)
now[0] = 181.0; equals("timed out at 181 s", s3.tx_timed_out(), True)
s4 = Session(callsign="KD3CCO", tx_timeout=0, clock=lambda: now[0])
s4.type("a"); s4.start_over()
equals("TX_TIMEOUT = 0 never times out", s4.tx_timed_out(), False)

# Ctrl-Y does not unkey the radio. It marks fldigi's buffer "receive when
# drained", and everything already composed still has to go out — minutes, at
# 31 baud. Disarming the time-out here left the transmitter running with
# nothing watching it, which is how an over gets stuck on the air.
print("\n-- the time-out survives handing back --")
now2 = [0.0]
s6 = Session(callsign="KD3CCO", tx_timeout=180, clock=lambda: now2[0])
s6.type("a"); s6.start_over()
now2[0] = 5.0
equals("hand_back reports the over ended", s6.hand_back(), True)
equals("and the session is receiving", s6.state, RX)
now2[0] = 181.0
equals("but the time-out still fires while the radio may be keyed",
       s6.tx_timed_out(), True)

# Only the radio may disarm it.
s7 = Session(callsign="KD3CCO", tx_timeout=180, clock=lambda: now2[0])
now2[0] = 0.0
s7.type("a"); s7.start_over(); s7.hand_back()
s7.confirm_receive()
now2[0] = 181.0
equals("fldigi confirming receive disarms it", s7.tx_timed_out(), False)

# And an abort during the drain still counts as having stopped something.
s8 = Session(callsign="KD3CCO", tx_timeout=180, clock=lambda: now2[0])
now2[0] = 0.0
s8.type("a"); s8.start_over(); s8.hand_back()
equals("aborting mid-drain reports it stopped something", s8.abort(), True)
equals("and disarms the time-out", s8.tx_timed_out(), False)

print("\n-- a refused over says why --")
s9 = Session(callsign="KD3CCO")
s9.type("one"); s9.start_over()
s9.type("two")
equals("a second start_over is refused", s9.start_over(), None)
check("and says so rather than doing nothing silently",
      "already transmitting" in (s9.last_note or ""), s9.last_note)

print("\n-- resync when fldigi was never transmitting --")
s10 = Session(callsign="KD3CCO")
s10.type("x"); s10.start_over()
equals("resync drops to receive", s10.resync_to_receive(), True)
equals("state is receive", s10.state, RX)
equals("a second resync is a no-op", s10.resync_to_receive(), False)
check("an over can be started again", s10.start_over() is not None)

print("\n-- newlines close entries so speakers do not merge --")
s5 = Session(callsign="KD3CCO")
s5.receive("one\ntwo\n")
equals("two separate received lines", transcript(s5), [("RX", "one"), ("RX", "two")])

print("\n-- the compose line edits like a terminal --")
e = Session(callsign="KD3CCO")
for c in "hello wrld":
    e.type(c)
equals("cursor sits at the end while typing", e.cursor, 10)
e.move(-3)
equals("left arrow moves the cursor", e.cursor, 7)
e.type("o")
equals("typing inserts at the cursor", e.compose, "hello world")
equals("and the cursor follows the insertion", e.cursor, 8)
e.backspace()
equals("backspace deletes before the cursor", e.compose, "hello wrld")
e.home()
equals("home goes to the start", e.cursor, 0)
e.end()
equals("end goes to the end", e.cursor, 10)
equals("the cursor cannot run past the end", (e.move(5), e.cursor), (False, 10))
e.home()
equals("nor before the start", (e.move(-5), e.cursor), (False, 0))

print("\n-- previous overs can be recalled --")
h = Session(callsign="KD3CCO")
for c in "first over":
    h.type(c)
h.start_over(); h.hand_back()
for c in "second over":
    h.type(c)
h.start_over(); h.hand_back()
equals("history keeps them newest first", h.history, ["second over", "first over"])
for c in "draft":
    h.type(c)
h.recall(-1)
equals("up recalls the most recent", h.compose, "second over")
h.recall(-1)
equals("again goes further back", h.compose, "first over")
h.recall(1)
equals("down comes forward again", h.compose, "second over")
h.recall(1)
equals("and past the newest restores the draft", h.compose, "draft")
equals("the cursor lands at the end of a recalled line",
      (h.recall(-1), h.cursor), (True, len("second over")))

print("\n-- history is not touched mid-over --")
m = Session(callsign="KD3CCO")
for c in "hi":
    m.type(c)
m.start_over()
equals("recall does nothing while transmitting", m.recall(-1), False)
equals("nor does the cursor move", m.move(-1), False)

print("\n-- message memories insert at the cursor and can be undone --")
m = Session(callsign="KD3CCO")
for c in "de  k":
    m.type(c)
m.move(-2)
equals("cursor is where we put it", m.cursor, 3)
m.insert("KD3CCO")
equals("inserted at the cursor, not appended", m.compose, "de KD3CCO k")
equals("cursor follows the insertion", m.cursor, 9)
equals("undo takes it back out", (m.undo(), m.compose), (True, "de  k"))
equals("and restores the cursor", m.cursor, 3)
equals("undo with nothing to undo says so", m.undo(), False)

print("\n-- inserts stack, and unwind newest first --")
u = Session(callsign="KD3CCO")
u.insert("one ")
u.insert("two ")
equals("both applied", u.compose, "one two ")
u.undo()
equals("newest undone first", u.compose, "one ")
u.undo()
equals("then the next", u.compose, "")

print("\n-- mid-over an insert is sent, not buffered --")
t = Session(callsign="KD3CCO")
t.type("x")
t.start_over()
out = t.insert("73")
equals("the text is returned for sending", out, "73")
equals("nothing is left in the compose buffer", t.compose, "")
equals("and it cannot be undone once sent", t.undo(), False)

print("\n-- scrollback is bounded --")
s6 = Session(callsign="KD3CCO", scrollback=100)
for i in range(500):
    s6.note(f"line {i}")
equals("held at the limit", len(s6.entries), 100)
equals("oldest dropped, newest kept", s6.entries[-1].text, "line 499")

print()

print("\n-- last_note, for screens that hide the transcript --")
n = Session(callsign="KD3CCO")
equals("nothing yet", n.last_note, "")
n.note("search up: nothing found")
equals("the most recent note", n.last_note, "search up: nothing found")
n.note("mode changed to RTTY")
equals("and it follows the newest", n.last_note, "mode changed to RTTY")
n.entries.clear()
equals("clearing the transcript does not erase it",
       n.last_note, "mode changed to RTTY")

sys.exit(report())
