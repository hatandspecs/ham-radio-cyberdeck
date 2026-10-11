"""Logbook of The World, which means producing ADIF and handing it to tqsl.

LoTW does not take an upload the way QRZ does. Every record has to be
cryptographically signed with a callsign certificate issued by the ARRL, and
the only thing that can do that signing is `tqsl`, their program. There is no
HTTP API to post a QSO to, so this module is not a client — it is an ADIF
exporter plus a careful wrapper around a subprocess.

**LoTW is free.** It needs a callsign certificate, which costs nothing and is
issued after the ARRL validates the operator's identity. That is a different
thing from the QRZ logbook, which needs a paid subscription for any API call
at all (`qrzlog.py`, and §7.7a of the design doc). Having one says nothing
about having the other.

What was measured, on tqsl 2.8.6, 2026-10-10:

  * `tqsl --batch --nodate --quiet <log>` **hangs indefinitely** when the
    keystore holds no callsign certificate. It does not print an error and it
    does not exit. Headless — with DISPLAY and WAYLAND_DISPLAY unset — makes
    no difference.
  * With a display present it opens a GUI window even given `--batch`.
  * A command-line syntax error is the one case that exits promptly, with
    status 10.
  * `tqsl -v` prints the version and exits **255**, not 0. Treating a nonzero
    status as failure there reports tqsl as missing on a machine that has it.

So every invocation here goes through `timeout` and treats "still running" as
a failure mode of its own. A logger that can hang the deck waiting for a
dialog nobody can see is worse than one that cannot upload.

**Signing belongs off the deck.** The recommended path, and what §11 of the
design doc describes, is: export ADIF on the deck, copy it to the laptop, sign
and upload there. The reason is not only the hang — a callsign certificate is
a private key, and the deck's SD card travels in a backpack. `upload()` exists
for a station that has deliberately installed a certificate on the deck, and
it is not the default.
"""

import os
import shutil
import subprocess

# Outcomes, deliberately the same three words qrzlog uses so the interface can
# treat an upload the same way whichever destination it went to.
OK = "ok"
RETRY = "retry"
PERMANENT = "fail"

TQSL = "tqsl"
TIMEOUT_S = 120.0

# tqsl's documented exit statuses. Only 0 and 10 are confirmed by measurement
# here; the rest are from its documentation and are mapped conservatively,
# which is why anything unrecognized falls through to RETRY.
_STATUS = {
    0: (OK, ""),
    1: (RETRY, "canceled"),
    2: (PERMANENT, "LoTW rejected the log"),
    3: (RETRY, "unexpected response from LoTW"),
    4: (PERMANENT, "tqsl error"),
    5: (PERMANENT, "tqsl library error"),
    6: (PERMANENT, "tqsl could not read the log file"),
    7: (PERMANENT, "tqsl could not write its output"),
    8: (PERMANENT, "no QSOs in the log were signed"),
    9: (OK, "some QSOs were duplicates and were skipped"),
    10: (PERMANENT, "tqsl command syntax error"),
    11: (RETRY, "could not reach LoTW"),
}


def available(which=shutil.which):
    """Whether tqsl is on PATH at all. The deck image does not install it."""
    return bool(which(TQSL))


def version(run=None, timeout=10.0):
    """tqsl's version string, or "" if it is not installed or does not answer.

    `tqsl -v` is the one invocation measured to return promptly in every
    state, which makes it the only safe way to ask whether tqsl is usable.
    """
    run = run or _run
    try:
        status, out = run([TQSL, "-v"], timeout=timeout)
    except Exception:
        return ""
    # Measured: `tqsl -v` prints the version and exits 255. The status is
    # therefore not usable as a success test here, and the output is.
    if status is None:
        return ""
    for line in (out or "").splitlines():
        if "TQSL Version" in line:
            return line.strip()
    return ""


def _run(argv, timeout=TIMEOUT_S):
    """(status, combined output). Status is None if it had to be killed.

    Headless by construction: tqsl opens a window when it can find a display
    even in batch mode, and the deck has a framebuffer console and no X.
    Removing the display variables is what keeps it on the terminal.
    """
    env = dict(os.environ)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        return None, (exc.output or "") if isinstance(exc.output, str) else ""
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def classify(status, output=""):
    """(outcome, detail) for a tqsl exit status.

    `None` means it was killed on the timeout, which on tqsl overwhelmingly
    means a missing certificate rather than a slow network — that is the
    measured behavior with an empty keystore. The detail says so, because
    "timed out" on its own sends the operator looking at their WiFi.
    """
    if status is None:
        return PERMANENT, ("tqsl did not exit; it has no callsign "
                           "certificate, or it is waiting on a dialog")
    outcome, detail = _STATUS.get(status, (RETRY, f"tqsl exited {status}"))
    if outcome != OK and not detail:
        detail = f"tqsl exited {status}"
    text = (output or "").strip().splitlines()
    if outcome != OK and text:
        # tqsl's last line is usually the useful one; the first is its banner.
        last = text[-1].strip()
        if last and "TQSL Version" not in last:
            detail = f"{detail}: {last}"
    return outcome, detail


def sign_command(adif_path, location="", output_path="", upload=False,
                 tqsl=TQSL):
    """The tqsl command line, as a list. Built here so it can be shown.

    This is the function the export note calls to print a command for the
    operator to run on their own machine, which is the documented path. It is
    also what `upload` executes, so the printed command and the executed one
    cannot drift apart.
    """
    argv = [tqsl, "--batch", "--nodate", "--quiet"]
    if location:
        argv += ["--location", location]
    if upload:
        argv.append("--upload")
    elif output_path:
        argv += ["--output", output_path]
    argv.append(adif_path)
    return argv


def quoted_command(*a, **kw):
    """`sign_command` as a copy-pasteable shell string."""
    import shlex
    return " ".join(shlex.quote(part) for part in sign_command(*a, **kw))


def upload(adif_path, location="", run=None, timeout=TIMEOUT_S, tqsl=TQSL,
           which=shutil.which):
    """Sign and upload one ADIF file. Returns (outcome, detail).

    Whole-file, not per-QSO: tqsl signs a log, and LoTW's duplicate handling
    means re-uploading a file that overlaps a previous one is safe. That is a
    different shape from `qrzlog.drain`, which has to go one QSO at a time
    because QRZ's API takes no batches, and it is why there is no outbox here.
    """
    if not which(tqsl):
        return PERMANENT, "tqsl is not installed"
    if not adif_path or not os.path.exists(adif_path):
        return PERMANENT, f"no such file: {adif_path}"

    run = run or _run
    status, out = run(sign_command(adif_path, location=location, upload=True,
                                   tqsl=tqsl), timeout=timeout)
    return classify(status, out)
