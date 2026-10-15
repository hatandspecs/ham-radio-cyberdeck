"""LoTW through tqsl, with the subprocess injected so nothing is signed.

tqsl is not an API, it is a GUI program with a batch flag, and the properties
worth pinning are the ones that keep it from hanging the deck:

  * **a timeout kill is PERMANENT, not RETRY, and says why.** Measured on
    tqsl 2.8.6: with no callsign certificate in the keystore it blocks
    forever given `--batch --nodate --quiet`, headless, with no error. A
    "retry later" there retries forever, and a bare "timed out" sends the
    operator to look at their WiFi instead of at their certificate.
  * **`tqsl -v` exits 255.** Gating on a zero status reports tqsl as missing
    on a machine that has it, which is how this was found.
  * **status 9 is success.** Some QSOs were duplicates and were skipped; the
    rest went. Treating it as failure makes a second upload of an overlapping
    file look broken when it did exactly the right thing.
  * **the printed command and the executed one come from one function.** The
    documented path is to copy a command and run it where the certificate
    lives, and a printed command that differs from what the code would run is
    worse than no command.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import lotw

print("the command line")
equals("the plain signing form",
       lotw.sign_command("/tmp/log.adi"),
       ["tqsl", "--batch", "--nodate", "--quiet", "/tmp/log.adi"])
equals("with a station location",
       lotw.sign_command("/tmp/log.adi", location="Home"),
       ["tqsl", "--batch", "--nodate", "--quiet", "--location", "Home",
        "/tmp/log.adi"])
equals("uploading",
       lotw.sign_command("/tmp/log.adi", location="Home", upload=True),
       ["tqsl", "--batch", "--nodate", "--quiet", "--location", "Home",
        "--upload", "/tmp/log.adi"])
equals("signing to a file instead",
       lotw.sign_command("/tmp/log.adi", output_path="/tmp/log.tq8"),
       ["tqsl", "--batch", "--nodate", "--quiet", "--output", "/tmp/log.tq8",
        "/tmp/log.adi"])
# --upload and --output are mutually exclusive in intent: one sends it, the
# other keeps it. Asking for both means upload, and no stray output file.
check("upload wins over an output path",
      "--output" not in lotw.sign_command("/tmp/l.adi", output_path="/tmp/o.tq8",
                                          upload=True),
      str(lotw.sign_command("/tmp/l.adi", output_path="/tmp/o.tq8", upload=True)))

q = lotw.quoted_command("/tmp/a b.adi", location="Field Day")
check("a path with a space is quoted for the shell",
      "'/tmp/a b.adi'" in q and "'Field Day'" in q, q)

print("\nclassifying exit statuses")
equals("0 is success", lotw.classify(0), (lotw.OK, ""))
equals("9 means duplicates were skipped, which is success",
       lotw.classify(9)[0], lotw.OK)
equals("2 is a rejection and will not fix itself",
       lotw.classify(2)[0], lotw.PERMANENT)
equals("10 is a syntax error in our own command",
       lotw.classify(10)[0], lotw.PERMANENT)
equals("11 is a network problem worth retrying",
       lotw.classify(11)[0], lotw.RETRY)
equals("an unknown status is retryable, not fatal",
       lotw.classify(42)[0], lotw.RETRY)
check("and names the number so it can be looked up",
      "42" in lotw.classify(42)[1], lotw.classify(42)[1])

outcome, detail = lotw.classify(None)
equals("a hang is permanent", outcome, lotw.PERMANENT)
check("and blames the certificate, not the network",
      "certificate" in detail, detail)

outcome, detail = lotw.classify(2, "TQSL Version 2.8.6\nBad callsign certificate")
check("the last line of output is quoted back",
      "Bad callsign certificate" in detail, detail)
check("but the version banner is not",
      "TQSL Version" not in detail, detail)

print("\nversion detection")
equals("tqsl -v exits 255 and that is still a success",
       lotw.version(run=lambda argv, timeout=None: (255, "TQSL Version 2.8.6 [pkg]")),
       "TQSL Version 2.8.6 [pkg]")
equals("a hang is no version",
       lotw.version(run=lambda argv, timeout=None: (None, "")), "")
equals("output that is not a version is no version",
       lotw.version(run=lambda argv, timeout=None: (0, "command not found")), "")
equals("an exception is no version, not a crash",
       lotw.version(run=lambda argv, timeout=None: (_ for _ in ()).throw(OSError())),
       "")

print("\nuploading")
equals("no tqsl at all is permanent",
       lotw.upload("/tmp/x.adi", which=lambda _n: None)[0], lotw.PERMANENT)
equals("a missing log file is permanent, and says which",
       lotw.upload("/tmp/definitely-not-here.adi", which=lambda _n: "/usr/bin/tqsl")[0],
       lotw.PERMANENT)

import tempfile
with tempfile.TemporaryDirectory() as tmp:
    adif = os.path.join(tmp, "log.adi")
    with open(adif, "w") as fh:
        fh.write("<EOH>\n")

    seen = []
    def ok_run(argv, timeout=None):
        seen.append((argv, timeout))
        return 0, "TQSL Version 2.8.6\nFinal Status: Success"

    equals("a good run is OK",
           lotw.upload(adif, location="Home", run=ok_run,
                       which=lambda _n: "/usr/bin/tqsl"),
           (lotw.OK, ""))
    check("it passed --upload", "--upload" in seen[0][0], str(seen[0][0]))
    check("and the station location", "Home" in seen[0][0], str(seen[0][0]))
    equals("and a timeout was set, not left open",
           seen[0][1], lotw.TIMEOUT_S)

    def hangs(argv, timeout=None):
        return None, ""
    outcome, detail = lotw.upload(adif, run=hangs,
                                  which=lambda _n: "/usr/bin/tqsl")
    equals("a hung tqsl is permanent", outcome, lotw.PERMANENT)
    check("and explains itself", "certificate" in detail, detail)

print("\nthe three outcome words match qrzlog's")
import qrzlog
equals("ok", lotw.OK, qrzlog.OK)
equals("retry", lotw.RETRY, qrzlog.RETRY)
equals("fail", lotw.PERMANENT, qrzlog.PERMANENT)

sys.exit(report())
