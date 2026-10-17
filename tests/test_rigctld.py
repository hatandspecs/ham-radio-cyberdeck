"""The rigctld client, against a stand-in rigctld. No radio, no serial port.

**PTT is why this file exists now.** WSPR keys the radio through this client
and nothing else — fldigi is stopped while WSPR runs, which takes fldigi's
rig control with it — so `set_ptt` is the only thing between the deck and a
transmitter. The failure that matters is a radio left keyed, and the three
properties below are what guard against it:

  * `ptt()` returns **None** when the radio cannot be read, not False. A
    radio that cannot be read is not a radio known to be receiving.
  * `set_ptt()` returning True means the command was SENT. A Yaesu set
    command answers with silence, so there is nothing to confirm from.
  * Nothing here raises. The deck has to keep running with the radio
    unplugged.
"""
import os
import socket
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import rigctld_client


class FakeRigctld:
    """A socket that answers rigctld commands from a script.

    One connection per command, which is how the real client works -- it
    opens, sends, reads and closes, so a radio unplugged between two calls
    fails the second and not the first.
    """

    def __init__(self, replies):
        self.replies = dict(replies)
        self.seen = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    line = conn.recv(4096).decode("ascii", "replace").strip()
                except OSError:
                    continue
                self.seen.append(line)
                # The command word decides the reply; `T 1` and `T 0` share
                # one entry keyed on `T`.
                key = line.split()[0] if line else ""
                reply = self.replies.get(line, self.replies.get(key))
                if reply is not None:
                    try:
                        conn.sendall((str(reply) + "\n").encode())
                    except OSError:
                        pass

    def waited(self, count, seconds=5.0):
        """The commands seen, once there are `count` of them.

        **Not `seen` directly.** `seen` is appended by the server thread, and
        the client returns as soon as its socket closes -- so reading it
        immediately is a race that passes on an idle machine and fails under
        load. It did exactly that: `fake.seen[-1]` raised IndexError in a full
        suite run and passed on every rerun, which is the worst way for a
        test to be wrong.
        """
        import time as _t
        end = _t.monotonic() + seconds
        while _t.monotonic() < end and len(self.seen) < count:
            _t.sleep(0.005)
        return list(self.seen)

    def close(self):
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass


def client(replies):
    fake = FakeRigctld(replies)
    return fake, rigctld_client.Rigctld(port=fake.port, timeout=1.0)


print("ptt reads the radio's transmit state")
fake, c = client({"t": "1"})
equals("1 means transmitting", c.ptt(), True)
fake.close()

fake, c = client({"t": "0"})
equals("0 means receiving", c.ptt(), False)
fake.close()

print("\nand it answers None, not False, when it cannot know")
# This is the distinction the whole file exists for. A caller that treated
# None as False would read "cannot reach the radio" as "the radio is not
# transmitting", which is the one wrong answer that matters.
c = rigctld_client.Rigctld(port=1, timeout=0.3)
equals("nothing listening", c.ptt(), None)
check("which is not False", c.ptt() is not False, "")

fake, c = client({"t": "RPRT -1"})
equals("hamlib's error form", c.ptt(), None)
fake.close()

fake, c = client({"t": "banana"})
equals("an answer that is not 0 or 1", c.ptt(), None)
fake.close()

fake, c = client({"t": ""})
equals("an empty answer", c.ptt(), None)
fake.close()

print("\nset_ptt sends T 1 and T 0")
fake, c = client({"T": ""})
equals("keying reports the command went", c.set_ptt(True), True)
equals("and sent T 1", fake.waited(1)[-1], "T 1")
equals("unkeying too", c.set_ptt(False), True)
equals("and sent T 0", fake.waited(2)[-1], "T 0")
fake.close()

print("\nand it reports failure rather than raising")
c = rigctld_client.Rigctld(port=1, timeout=0.3)
equals("with nothing listening", c.set_ptt(True), False)
equals("unkeying fails the same way", c.set_ptt(False), False)

print("\nTrue means SENT, not keyed — so a caller must read it back")
# A Yaesu set command answers with silence, so there is nothing to confirm
# from. The stand-in below takes the command and reports still receiving,
# which is exactly the shape of a PTT that did not take.
fake, c = client({"T": "", "t": "0"})
equals("the command went", c.set_ptt(True), True)
equals("but the radio says it is not transmitting", c.ptt(), False)
check("so `set_ptt` returning True proves nothing about the radio",
      True, "which is why anything keying a transmitter reads ptt() back")
fake.close()

print("\nthe other reads still work, since WSPR depends on all of them")
fake, c = client({"f": "7038600", "m": "PKTUSB\n3000"})
check("connected", c.connected, "")
equals("frequency", c.frequency(), 7038600.0)
equals("mode", c.mode()[0], "PKTUSB")
fake.close()

print("\nnothing raises with the radio unplugged")
c = rigctld_client.Rigctld(port=1, timeout=0.3)
for name, call in (("connected", lambda: c.connected),
                   ("frequency", lambda: c.frequency()),
                   ("mode", lambda: c.mode()),
                   ("ptt", lambda: c.ptt()),
                   ("set_ptt", lambda: c.set_ptt(False)),
                   ("set_frequency", lambda: c.set_frequency(7038600))):
    try:
        call()
        check(f"{name} returned rather than raising", True, "")
    except Exception as exc:
        check(f"{name} returned rather than raising", False,
              f"{type(exc).__name__}: {exc}")

report()
