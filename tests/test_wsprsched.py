"""The WSPR slot schedule — docs/wspr_design.md §6a, §7, §8.

Every case here is about a moment: the top of a slot, 40 seconds in, UTC
midnight, the instant a time-out expires. None of them can be waited for, so
the schedule holds no clock and is told the time — the same reason
`session.py` holds none.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wsprsched as sched

# An exact even minute, so the arithmetic below is readable.
T0 = 1781000000 - (1781000000 % 120)


print("slots are two minutes and start on the even minute")
equals("a slot starts on its own boundary", sched.slot_start(T0), T0)
equals("and 90 seconds in, still the same boundary",
       sched.slot_start(T0 + 90), T0)
equals("120 seconds on is the next one", sched.slot_start(T0 + 120), T0 + 120)
equals("the capture window is 114 s of the 120",
       (sched.CAPTURE_SECONDS, sched.SLOT_SECONDS), (114, 120))
check("inside the window at the top", sched.in_capture(T0), "")
check("still inside at 113 s", sched.in_capture(T0 + 113), "")
check("outside at 114 s", not sched.in_capture(T0 + 114), "")
equals("time to the next slot, from the top",
       sched.seconds_to_next_slot(T0), 120)
equals("and from halfway", sched.seconds_to_next_slot(T0 + 60), 60)

print("\nthe slot index is the UTC day's, not the process's")
# Two decks started minutes apart must agree about which slot is which, or
# their band rotations drift apart and neither is where the other expects.
midnight = T0 - (T0 % 86400)
equals("midnight is slot 0", sched.slot_index(midnight), 0)
equals("two minutes later, slot 1", sched.slot_index(midnight + 120), 1)
equals("the last slot of the day", sched.slot_index(midnight + 86400 - 120),
       719)
equals("and it wraps at midnight", sched.slot_index(midnight + 86400), 0)

print("\nband hopping cycles the chosen bands")
BANDS = ["20 m", "40 m", "80 m"]
got = [sched.band_for_slot(BANDS, midnight + 120 * i) for i in range(7)]
equals("in order, repeating", got,
       ["20 m", "40 m", "80 m", "20 m", "40 m", "80 m", "20 m"])
equals("one band is not a special case",
       [sched.band_for_slot(["20 m"], midnight + 120 * i) for i in range(3)],
       ["20 m", "20 m", "20 m"])
equals("no bands is no band", sched.band_for_slot([], midnight), "")
equals("and blanks are ignored", sched.band_for_slot(["", "40 m"], midnight),
       "40 m")
# Keyed on the slot index, so a restart lands where the schedule says rather
# than restarting the rotation.
equals("the rotation is a function of the clock, not of history",
       sched.band_for_slot(BANDS, midnight + 120 * 4),
       sched.band_for_slot(BANDS, midnight + 120 * 7))

print("\nthe transmit percentage is stable within a slot")
# Asked twice per slot -- once to decide, once to display "next: transmit" --
# so an answer that changed between the two would show one thing and do
# another.
for i in range(20):
    t = midnight + 120 * i
    first = sched.transmits_in_slot(t, 20, seed=7)
    check(f"slot {i} answers the same twice",
          first == sched.transmits_in_slot(t, 20, seed=7), "")
    check(f"slot {i} answers the same 30 s in",
          first == sched.transmits_in_slot(t + 30, 20, seed=7), "")

print("\nand it transmits about the fraction asked for")
for pct in (10, 20, 50):
    hits = sum(sched.transmits_in_slot(midnight + 120 * i, pct, seed=7)
               for i in range(720))
    share = 100 * hits / 720
    check(f"{pct}% gives roughly {pct}% of slots ({share:.0f}%)",
          abs(share - pct) < 8, f"{hits} of 720")
equals("0% never transmits",
       sum(sched.transmits_in_slot(midnight + 120 * i, 0, seed=7)
           for i in range(100)), 0)
equals("100% always does",
       sum(sched.transmits_in_slot(midnight + 120 * i, 100, seed=7)
           for i in range(100)), 100)
check("a nonsense percentage does not transmit",
      not sched.transmits_in_slot(midnight, "lots", seed=7), "")
# Two stations on the same percentage must not collide in the same slots
# forever, which is what a regular every-Nth pattern would do.
a = [sched.transmits_in_slot(midnight + 120 * i, 20, seed=1)
     for i in range(200)]
b = [sched.transmits_in_slot(midnight + 120 * i, 20, seed=2)
     for i in range(200)]
check("different seeds give different schedules", a != b, "")

print("\nthe four toggles compose into four named states")
s = sched.Schedule(bands=["20 m"], tx_percent=100, seed=7)
equals("nothing on is idle", s.state, sched.IDLE)
s.start(T0)
equals("WSPR on, decode on is receiving", s.state, sched.RECEIVING)
s.decode = False
equals("WSPR on, decode off is listening — the level check", s.state,
       sched.LISTENING)
s.decode = True
s.transmit = True
equals("and with transmit on, beaconing", s.state, sched.BEACONING)
s.stop()
equals("stopped is idle again", s.state, sched.IDLE)
check("and stopping disarms transmit", not s.transmit, "")

print("\none slot produces exactly one slot's worth of actions")
s = sched.Schedule(bands=["20 m", "40 m"], tx_percent=0, seed=7)
s.start(T0)
equals("at the top of the slot, tune and capture", s.tick(T0),
       [("tune", "20 m"), ("capture", "20 m")])
equals("30 seconds in, nothing more", s.tick(T0 + 30), [])
equals("and again, still nothing", s.tick(T0 + 31), [])
equals("the next slot acts once, on the next band", s.tick(T0 + 120),
       [("tune", "40 m"), ("capture", "40 m")])
# A tick that arrives twice, or late, or after the process was asleep, must
# not double up.
s2 = sched.Schedule(bands=["20 m"], tx_percent=0, seed=7)
s2.start(T0)
s2.tick(T0)
equals("a repeated tick at the same instant does nothing", s2.tick(T0), [])

print("\na tick that arrives mid-slot skips it rather than truncating")
# Starting a capture 40 s into a window hands wsprd a short file that
# decodes nothing, which looks like a dead band instead of a missed slot.
s3 = sched.Schedule(bands=["20 m"], tx_percent=0, seed=7)
s3.start(T0)
equals("40 seconds in, no capture is started", s3.tick(T0 + 40), [])
equals("but the next slot is taken normally", s3.tick(T0 + 120),
       [("tune", "20 m"), ("capture", "20 m")])

print("\ntransmit next is a one-shot and wins over the percentage")
s4 = sched.Schedule(bands=["20 m"], tx_percent=0, seed=7)
s4.start(T0)
s4.transmit = True
check("0% would not transmit", not s4.will_transmit(T0 + 120), "")
s4.arm_tx_next(T0)
check("armed, the NEXT slot transmits", s4.will_transmit(T0 + 120), "")
check("but not this one", not s4.will_transmit(T0), "")
acts = s4.tick(T0 + 120)
equals("and the slot transmits instead of capturing", acts,
       [("tune", "20 m"), ("transmit", "20 m")])
check("the one-shot is spent", not s4.tx_next, "")
equals("so the slot after it captures again", s4.tick(T0 + 240),
       [("tune", "20 m"), ("capture", "20 m")])

print("\ntransmit next does nothing while transmit is off")
# It arms a beacon; with transmit switched off there is no beacon to arm.
s5 = sched.Schedule(bands=["20 m"], tx_percent=100, seed=7)
s5.start(T0)
s5.arm_tx_next(T0)
check("still no transmission", not s5.will_transmit(T0 + 120), "")

print("\nthe time-out stops the session by itself")
s6 = sched.Schedule(bands=["20 m"], tx_percent=0, timeout_minutes=60, seed=7)
s6.start(T0)
equals("sixty minutes at the start",
       round(s6.timeout_remaining(T0) / 60), 60)
equals("fifty-nine a minute in",
       round(s6.timeout_remaining(T0 + 60) / 60), 59)
check("not timed out before it expires", not s6.timed_out(T0 + 3599), "")
check("timed out at the instant it does", s6.timed_out(T0 + 3600), "")
equals("and the tick stops it, saying why", s6.tick(T0 + 3600),
       [("stop", "time-out")])
equals("which leaves it idle", s6.state, sched.IDLE)
equals("a stopped session ticks to nothing", s6.tick(T0 + 3720), [])

print("\nthe default time-out is sixty minutes, and zero means no limit")
equals("the default", sched.Schedule().timeout_minutes, 60)
s7 = sched.Schedule(bands=["20 m"], timeout_minutes=0)
s7.start(T0)
equals("zero reports no remaining time rather than none left",
       s7.timeout_remaining(T0), None)
check("and never times out", not s7.timed_out(T0 + 86400), "")
equals("no session reports nothing",
       sched.Schedule().timeout_remaining(T0), None)

print("\na configurable time-out is honoured")
s8 = sched.Schedule(bands=["20 m"], timeout_minutes=5)
s8.start(T0)
check("five minutes is not up at four", not s8.timed_out(T0 + 240), "")
check("and is up at five", s8.timed_out(T0 + 300), "")

report()
