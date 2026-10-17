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

print("\nthe time-out disarms transmit by itself")
# **It used to stop the session.** The timer is for an unattended
# transmitter, and receiving carries no on-air risk, so ending the whole
# session gave up the part still doing something useful -- and handed the
# codec back and restarted fldigi because a clock ran out.
s6 = sched.Schedule(bands=["20 m"], tx_percent=0, timeout_minutes=60, seed=7)
s6.start(T0)
s6.set_transmit(True, T0)
equals("sixty minutes at the start",
       round(s6.timeout_remaining(T0) / 60), 60)
equals("fifty-nine a minute in",
       round(s6.timeout_remaining(T0 + 60) / 60), 59)
check("not timed out before it expires", not s6.timed_out(T0 + 3599), "")
check("timed out at the instant it does", s6.timed_out(T0 + 3600), "")
equals("and the tick disarms transmit, saying why", s6.tick(T0 + 3600),
       [("tx_off", "time-out")])
equals("transmit is off", s6.transmit, False)
# The session itself is untouched: still on, still decoding, still hopping.
equals("the session is still running", s6.wspr, True)
equals("and still decoding", s6.decode, True)
equals("so the next slot still tunes and captures",
       [a for a, _w in s6.tick(T0 + 3720)], ["tune", "capture"])

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

print("\ntwo transmissions never go out back to back")
# Observed on the air 2026-10-17: `tx next` fired, and the percentage
# independently chose the slot straight after it, so the deck beaconed twice
# running -- no listening between them, and a receiver hearing the same
# station twice for no gain.
s2 = sched.Schedule(bands=["40 m"], tx_percent=100, timeout_minutes=0)
s2.start(0.0)
s2.transmit = True

# Percent 100, so every slot would transmit if nothing stopped it.
first = [a for a, _w in s2.tick(0.0)]
equals("the first slot transmits", "transmit" in first, True)
second = [a for a, _w in s2.tick(sched.SLOT_SECONDS)]
equals("the one straight after it does NOT", "transmit" in second, False)
equals("it listens instead", "capture" in second, True)
third = [a for a, _w in s2.tick(2 * sched.SLOT_SECONDS)]
equals("and the one after that may transmit again",
       "transmit" in third, True)

print("\nthe one-shot still wins, because it was asked for")
# An operator who presses "transmit next slot" has asked for that slot.
s2 = sched.Schedule(bands=["40 m"], tx_percent=100, timeout_minutes=0)
s2.start(0.0)
s2.transmit = True
equals("the first slot transmits",
       "transmit" in [a for a, _w in s2.tick(0.0)], True)
s2.arm_tx_next(sched.SLOT_SECONDS * 0.5)   # arms the NEXT slot
after = [a for a, _w in s2.tick(sched.SLOT_SECONDS)]
equals("and the slot after it transmits when explicitly armed",
       "transmit" in after, True)

print("\nthe guard does not survive a stop")
# A new session is not the continuation of the old one.
s2 = sched.Schedule(bands=["40 m"], tx_percent=100, timeout_minutes=0)
s2.start(0.0)
s2.transmit = True
s2.tick(0.0)
s2.stop()
s2.start(sched.SLOT_SECONDS)
s2.transmit = True
equals("the first slot of a new session may transmit",
       "transmit" in [a for a, _w in s2.tick(sched.SLOT_SECONDS)], True)

print("\nwill_transmit has no side effects, because the screen calls it")
# It is asked every draw to show "next: TX". If it recorded anything, the
# display would change what the schedule does.
s2 = sched.Schedule(bands=["40 m"], tx_percent=100, timeout_minutes=0)
s2.start(0.0)
s2.transmit = True
before = s2.will_transmit(0.0)
for _ in range(20):
    s2.will_transmit(0.0)
equals("asking twenty times gives the same answer",
       s2.will_transmit(0.0), before)
equals("and the first slot still transmits",
       "transmit" in [a for a, _w in s2.tick(0.0)], True)

print("\nthe time-out disarms transmit and leaves the session receiving")
# It used to end the session: receiver stopped, band modes restored, capture
# gain put back, fldigi restarted. The timer is about an unattended
# TRANSMITTER, and receiving carries no on-air risk -- so a clock running
# out gave up the part still doing something useful.
s3 = sched.Schedule(bands=["40 m"], tx_percent=100, timeout_minutes=1)
s3.start(0.0)
s3.set_transmit(True, 0.0)
acts = [a for a, _w in s3.tick(0.0)]
equals("it transmits before the time-out", "transmit" in acts, True)

acts = s3.tick(61.0)
equals("the time-out reports transmit off",
       [a for a, _w in acts], ["tx_off"])
equals("transmit is disarmed", s3.transmit, False)
equals("and so is the one-shot", s3.tx_next, False)
equals("but the session is still running", s3.wspr, True)
equals("and still decoding", s3.decode, True)

# The next slot must still capture, which is the whole point.
acts = [a for a, _w in s3.tick(120.0)]
equals("the next slot captures", "capture" in acts, True)
equals("and does not transmit", "transmit" in acts, False)

print("\nand it cannot fire twice")
# `started_at` is cleared, so there is nothing left to time.
equals("no remaining time is reported", s3.timeout_remaining(200.0), None)
equals("it does not report timed out again", s3.timed_out(200.0), False)
equals("so a later tick is an ordinary one",
       [a for a, _w in s3.tick(240.0)], ["tune", "capture"])

print("\narming transmit again restarts the time-out")
# The guarantee is "no transmitting for longer than this without being told
# again", so re-arming is being told again.
# A longer limit for this part: with the one-minute ToT re-armed at 300,
# the next slot top is 360, which is EXACTLY the expiry -- so the tick timed
# out again instead of transmitting, and the first version of this check
# read that as "re-arming does not work".
s3.timeout_minutes = 10
s3.set_transmit(True, 300.0)
equals("the clock is running once more",
       round(s3.timeout_remaining(300.0)), 600)
equals("and it is not already expired", s3.timed_out(300.0), False)
equals("it transmits again", "transmit" in
       [a for a, _w in s3.tick(360.0)], True)

print("\ndisarming transmit spends the one-shot with it")
# Otherwise `tx next` fires on the slot after transmit was switched off.
s4 = sched.Schedule(bands=["40 m"], tx_percent=0, timeout_minutes=0)
s4.start(0.0)
s4.set_transmit(True, 0.0)
s4.arm_tx_next(0.0)
equals("the one-shot is armed", s4.tx_next, True)
s4.set_transmit(False, 10.0)
equals("and is gone with transmit", s4.tx_next, False)

sys.exit(report())
