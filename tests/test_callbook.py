"""Callsign lookup, with no network and no mocking library.

The fetcher is injectable, which is the whole reason this can be tested at
all: every case below — a good reply, a station that does not exist, a
malformed reply, and no network whatsoever — is a function that returns a
string or raises, handed in at the call site.

The properties that matter are not about parsing. They are:

  * nothing raises out of a lookup. This code runs on the commit path, and an
    exception there loses a contact to a database that was never the point.
  * what the operator typed is never overwritten. They heard it on the air;
    callook is reading a license record that may be years stale.
  * a negative answer is cached. Otherwise every unlicensed-in-the-US call
    costs four seconds of timeout, every time it is worked.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import callbook


GOOD = """{"status":"VALID","type":"PERSON",
  "current":{"callsign":"W3ABC","operClass":"GENERAL"},
  "name":"ROBERT J SMITH",
  "address":{"line1":"123 MAIN ST","line2":"PITTSBURGH, PA 15213"},
  "location":{"latitude":"40.44","longitude":"-79.99","gridsquare":"EN90ak"}}"""

INVALID = '{"status":"INVALID"}'


print("parsing a good reply")
info = callbook.parse_callook(GOOD)
equals("first name only, title cased", info["name"], "Robert")
equals("city and state, no ZIP", info["qth"], "Pittsburgh, PA")
equals("grid in Maidenhead case", info["grid"], "EN90ak")

print("\nreplies that are not answers")
equals("a call that does not exist", callbook.parse_callook(INVALID), {})
equals("not JSON at all", callbook.parse_callook("<html>504</html>"), {})
equals("empty", callbook.parse_callook(""), {})
equals("None", callbook.parse_callook(None), {})
equals("JSON that is not an object", callbook.parse_callook("[1,2,3]"), {})

print("\npartial replies")
equals("no address", callbook.parse_callook(
    '{"status":"VALID","name":"JANE DOE"}'), {"name": "Jane"})
equals("no name", callbook.parse_callook(
    '{"status":"VALID","location":{"gridsquare":"FN10cs"}}'), {"grid": "FN10cs"})

print("\nlookup with no network")
def dead(url, timeout=None):
    raise OSError("Network is unreachable")

equals("no network is simply nothing known", callbook.lookup("W3ABC", fetch=dead), {})
check("and it does not raise", True)

print("\nlookup over a working fetcher")
calls = []
def ok(url, timeout=None):
    calls.append(url)
    return GOOD

equals("found", callbook.lookup("w3abc", fetch=ok)["name"], "Robert")
equals("the callsign is upper-cased into the URL", calls[0],
       "https://callook.info/W3ABC/json")
equals("an empty call never hits the network", callbook.lookup("", fetch=ok), {})
equals("and did not fetch", len(calls), 1)

print("\ncache")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "sub", "callbook.json")
    cache = callbook.Cache(path)
    equals("a missing cache file is an empty cache", len(cache), 0)

    hits = []
    def once(url, timeout=None):
        hits.append(url)
        return GOOD

    first = callbook.lookup("W3ABC", cache=cache, fetch=once)
    second = callbook.lookup("W3ABC", cache=cache, fetch=once)
    equals("same answer both times", first, second)
    equals("but only one fetch", len(hits), 1)

    reopened = callbook.Cache(path)
    equals("survives a restart", reopened.get("W3ABC")["name"], "Robert")
    equals("case does not matter on the way back out",
           reopened.get("w3abc")["name"], "Robert")

    misses = []
    def missing(url, timeout=None):
        misses.append(url)
        return INVALID

    callbook.lookup("ZZ9ZZZ", cache=cache, fetch=missing)
    callbook.lookup("ZZ9ZZZ", cache=cache, fetch=missing)
    equals("a negative answer is cached too", len(misses), 1)

    stale = callbook.Cache(path, now=lambda: 10 ** 12)
    equals("and expires", stale.get("W3ABC"), None)

print("\ncorrupt cache")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "callbook.json")
    with open(path, "w") as fh:
        fh.write("{not json at all")
    cache = callbook.Cache(path)
    equals("is an empty cache, not an error", len(cache), 0)
    cache.put("W3ABC", {"name": "Robert"})
    equals("and is usable afterwards", callbook.Cache(path).get("W3ABC")["name"], "Robert")

print("\nmerge never overwrites what was typed")
typed = {"call": "W3ABC", "name": "Bobby", "qth": "", "grid": ""}
merged = callbook.merge(typed, {"name": "Robert", "qth": "Pittsburgh, PA", "grid": "EN90ak"})
equals("the typed name wins", merged["name"], "Bobby")
equals("the blank qth is filled", merged["qth"], "Pittsburgh, PA")
equals("and the grid", merged["grid"], "EN90ak")
equals("the call is untouched", merged["call"], "W3ABC")

empty = callbook.merge({"call": "W3ABC"}, {})
equals("nothing known changes nothing", empty, {"call": "W3ABC"})

print("\nbackground lookups")
bg = callbook.Background(fetch=ok)
equals("nothing taken before anything is started", bg.take("W3ABC"), None)
bg.start("W3ABC")
for _ in range(200):                      # up to two seconds, in 10ms steps
    got = bg.take("W3ABC")
    if got is not None:
        break
    import time as _t; _t.sleep(0.01)
equals("the answer arrives", (got or {}).get("name"), "Robert")
equals("and is taken only once", bg.take("W3ABC"), None)

slow_bg = callbook.Background(fetch=dead)
slow_bg.start("W3XYZ")
check("a failing lookup still completes", True)

print("\nnames are cased for a log, not blindly title-cased")
# callook returns names in capitals ("ROBERT J SMITH"), so .title() alone
# turns an operator whose nick is "JP" into "Jp", which is not what anyone is
# called. A token with no vowels, or a two-character one, is initials.
equals("initials survive", callbook._first_name("JP"), "JP")
equals("two letters survive", callbook._first_name("NG"), "NG")
equals("a shouted name is title-cased", callbook._first_name("ROBERT J SMITH"),
       "Robert")
equals("a three-letter name with a vowel is a name",
       callbook._first_name("DON"), "Don")
equals("already-cased text is left alone", callbook._first_name("Petr"), "Petr")
equals("a hyphenated name keeps its shape",
       callbook._first_name("Jean-Luc"), "Jean-Luc")
equals("nothing in, nothing out", callbook._first_name(""), "")
equals("None in, nothing out", callbook._first_name(None), "")
equals("whitespace only", callbook._first_name("   "), "")


print("\nHamQTH, for the calls callook has never heard of")
# callook.info is US-only, which is the entire reason for a second provider.
# HamQTH needs an account and a session, so there is more to get wrong.
LOGIN = ('<HamQTH xmlns="https://www.hamqth.com"><session>'
         '<session_id>deadbeef</session_id></session></HamQTH>')
FOUND = ('<?xml version="1.0"?>\n'
         '<HamQTH version="2.7" xmlns="https://www.hamqth.com"><search>'
         '<callsign>ok2cqr</callsign><nick>Petr</nick><qth>Rican</qth>'
         '<country>Czech Republic</country><grid>jn79hw</grid>'
         '</search></HamQTH>')
NOTFOUND = ('<HamQTH xmlns="https://www.hamqth.com"><session>'
            '<error>Callsign not found</error></session></HamQTH>')
EXPIRED = ('<HamQTH xmlns="https://www.hamqth.com"><session>'
           '<error>Session does not exist or expired</error></session></HamQTH>')
BADCREDS = ('<HamQTH xmlns="https://www.hamqth.com"><session>'
            '<error>Wrong user name or password</error></session></HamQTH>')

got = callbook.parse_hamqth(FOUND)
# `nick` is the on-air name. HamQTH's `name` is a private field and is empty
# whenever the operator hid it, which is often — reading `name` first returns
# blanks from exactly the stations most likely to care.
equals("the on-air nick becomes the name", got["name"], "Petr")
equals("qth carries the country, since the point is non-US calls",
       got["qth"], "Rican, Czech Republic")
equals("the grid is cased the Maidenhead way", got["grid"], "JN79hw")
equals("a call that is not there is nothing known",
       callbook.parse_hamqth(NOTFOUND), {})
equals("an HTML error page is too", callbook.parse_hamqth("<html>502</html>"), {})
equals("and an empty body", callbook.parse_hamqth(""), {})
equals("and None", callbook.parse_hamqth(None), {})
# Their namespace prefix has changed before; matching the local name is what
# keeps this working when it changes again.
equals("a different namespace still parses",
       callbook.parse_hamqth(FOUND.replace("https://www.hamqth.com", "urn:x"))["name"],
       "Petr")
equals("and no namespace at all",
       callbook.parse_hamqth("<HamQTH><search><nick>Jo</nick></search></HamQTH>")["name"],
       "Jo")


def session_fetcher(reply):
    """A fake HamQTH: login requests get a session, lookups get `reply`."""
    seen = []
    def fetch(url, timeout=None):
        seen.append(url)
        return LOGIN if "callsign=" not in url else reply
    return seen, fetch


print("\n  sessions are reused, not re-established per contact")
seen, fetch = session_fetcher(FOUND)
hq = callbook.HamQTH("kd3cco", "pw", fetch=fetch)
check("credentials make it usable", hq.enabled)
equals("no credentials, not usable", callbook.HamQTH().enabled, False)
equals("a user with no password is not usable",
       callbook.HamQTH("kd3cco", "").enabled, False)

hq.fetch("OK2CQR")
equals("one login and one lookup", len(seen), 2)
check("the program name is sent", "prg=cyberdeck" in seen[1], seen[1])
hq.fetch("W3ABC")
equals("the second contact reuses the session", len(seen), 3)

print("\n  a not-found answer does not burn a second round trip")
# "Callsign not found" is an <error> too. Retrying on any error would double
# the traffic for exactly the lookups that were already a dead end.
seen, fetch = session_fetcher(NOTFOUND)
callbook.HamQTH("kd3cco", "pw", fetch=fetch).fetch("ZZ9ZZZ")
equals("login and lookup, and no retry", len(seen), 2)

print("\n  an expired session is retried once")
seen, fetch = session_fetcher(EXPIRED)
callbook.HamQTH("kd3cco", "pw", fetch=fetch).fetch("OK2CQR")
equals("login, lookup, login, lookup", len(seen), 4)

print("\n  a session that times out is re-established")
clock = [1000.0]
seen, fetch = session_fetcher(FOUND)
hq = callbook.HamQTH("kd3cco", "pw", fetch=fetch, now=lambda: clock[0])
hq.fetch("W3ABC")
equals("fresh session", len(seen), 2)
clock[0] += callbook.HAMQTH_SESSION_S + 1
hq.fetch("W3ABC")
equals("past the lifetime it logs in again", len(seen), 4)

print("\n  failures are survivable and said out loud once")
seen, fetch = session_fetcher(FOUND)
bad = callbook.HamQTH("kd3cco", "wrong",
                      fetch=lambda u, timeout=None: BADCREDS)
equals("bad credentials yield no session", bad.session(), "")
check("and the reason is kept, because the symptom is silence otherwise",
      "Wrong user name" in bad.last_error, bad.last_error)

dead = callbook.HamQTH("kd3cco", "pw",
                       fetch=lambda u, timeout=None: (_ for _ in ()).throw(
                           OSError("Network is unreachable")))
equals("no network yields no session, not an exception", dead.session(), "")
check("and says so", "unreachable" in dead.last_error, dead.last_error)
equals("a fetch with no session is an empty string", dead.fetch("W3ABC"), "")

print("\n  callook first, HamQTH only when it has nothing")
# Order matters: callook needs no account and its US license data is the more
# authoritative of the two. HamQTH is what makes a non-US call work at all.
seen, fetch = session_fetcher(FOUND)
hq = callbook.HamQTH("kd3cco", "pw", fetch=fetch)
us = callbook.lookup("W3ABC", fetch=lambda u, timeout=None: GOOD,
                     hamqth=hq)
equals("a US call is answered by callook", us["name"], "Robert")
equals("and HamQTH was never asked", len(seen), 0)

dx = callbook.lookup("OK2CQR",
                     fetch=lambda u, timeout=None: '{"status":"INVALID"}',
                     hamqth=hq)
equals("a call callook does not know falls through", dx["name"], "Petr")
check("HamQTH was asked", len(seen) >= 2, str(seen))

equals("no HamQTH configured is simply callook alone",
       callbook.lookup("OK2CQR",
                       fetch=lambda u, timeout=None: '{"status":"INVALID"}'),
       {})
equals("an unconfigured HamQTH is not consulted either",
       callbook.lookup("OK2CQR",
                       fetch=lambda u, timeout=None: '{"status":"INVALID"}',
                       hamqth=callbook.HamQTH()),
       {})

print("\n  a HamQTH that explodes does not take the lookup down")
class Explodes:
    enabled = True
    def fetch(self, call):
        raise RuntimeError("something unexpected")
equals("the contact still gets logged",
       callbook.lookup("OK2CQR",
                       fetch=lambda u, timeout=None: '{"status":"INVALID"}',
                       hamqth=Explodes()),
       {})

print("\nQRZ's XML lookup — a third provider, and a different QRZ service")
# Not the logbook upload in qrzlog.py: different endpoint, different
# credential, different subscription. Having one says nothing about the other.
QRZ_SESSION = ('<?xml version="1.0"?><QRZDatabase xmlns="http://xmldata.qrz.com">'
               '<Session><Key>abc123</Key><Count>43</Count>'
               '<SubExp>non-subscriber</SubExp></Session></QRZDatabase>')
QRZ_FOUND = ('<QRZDatabase xmlns="http://xmldata.qrz.com"><Callsign>'
             '<call>OK2CQR</call><fname>PETR</fname><name>HLOZEK</name>'
             '<addr2>Neratovice</addr2><country>Czech Republic</country>'
             '</Callsign><Session><Key>abc123</Key>'
             '<Message>A subscription is required to access the complete '
             'record.</Message></Session></QRZDatabase>')
QRZ_WITHGRID = QRZ_FOUND.replace("<addr2>", "<grid>jo70gg</grid><addr2>")
QRZ_NOTFOUND = ('<QRZDatabase xmlns="http://xmldata.qrz.com"><Session>'
                '<Key>abc123</Key><Error>Not found: ZZ9ZZZ</Error>'
                '</Session></QRZDatabase>')
QRZ_BADLOGIN = ('<QRZDatabase xmlns="http://xmldata.qrz.com"><Session>'
                '<Error>Username/password incorrect</Error>'
                '</Session></QRZDatabase>')

got = callbook.parse_qrz(QRZ_FOUND)
equals("the first name is taken from fname", got["name"], "Petr")
equals("town and country make the QTH", got["qth"], "Neratovice, Czech Republic")
# Measured against the live API 2026-10-11: a non-subscriber gets the name and
# the town but usually NOT the grid, which is the field most worth having.
# That is why QRZ is last in the chain rather than first.
check("a non-subscriber reply simply has no grid", "grid" not in got, str(got))
equals("and a reply that does have one is used",
       callbook.parse_qrz(QRZ_WITHGRID)["grid"], "JO70gg")
equals("a state is used where there is no country",
       callbook.parse_qrz(QRZ_FOUND.replace(
           "<country>Czech Republic</country>", "<state>PA</state>"))["qth"],
       "Neratovice, PA")
equals("not found is nothing known", callbook.parse_qrz(QRZ_NOTFOUND), {})
equals("garbage is too", callbook.parse_qrz("<html>502</html>"), {})
equals("and empty", callbook.parse_qrz(""), {})

print("\n  the password is URL-encoded, which is not optional")
# This station's QRZ password contains '&'. Pasted raw into a query string it
# terminates the query there and sends a different, shorter password — which
# fails as "incorrect password" and looks like the wrong password.
seen = []
def qrz_fetch(url, timeout=None):
    seen.append(url)
    return QRZ_SESSION if "username=" in url else QRZ_FOUND

q = callbook.QRZXml("KD3CCO", "pw&more$x", fetch=qrz_fetch)
q.session()
check("the ampersand is escaped", "pw%26more" in seen[0], seen[0])
check("and does not appear raw", "pw&more" not in seen[0], seen[0])
check("the agent is sent", "agent=" in seen[0], seen[0])
equals("the subscription status is kept", q.subscription, "non-subscriber")

print("\n  sessions, failures and retries")
equals("no credentials, not usable", callbook.QRZXml().enabled, False)
seen.clear()
q = callbook.QRZXml("KD3CCO", "pw", fetch=qrz_fetch)
q.fetch("OK2CQR")
equals("one login, one lookup", len(seen), 2)
q.fetch("W3ABC")
equals("the session is reused", len(seen), 3)

seen.clear()
def notfound_fetch(url, timeout=None):
    seen.append(url)
    return QRZ_SESSION if "username=" in url else QRZ_NOTFOUND
callbook.QRZXml("KD3CCO", "pw", fetch=notfound_fetch).fetch("ZZ9ZZZ")
# "Not found" is an <Error> too. Retrying on any error would double the
# traffic for exactly the lookups that were already a dead end.
equals("a not-found costs no retry", len(seen), 2)

seen.clear()
def expired_fetch(url, timeout=None):
    seen.append(url)
    if "username=" in url:
        return QRZ_SESSION
    return ('<QRZDatabase><Session><Error>Invalid session key</Error>'
            '</Session></QRZDatabase>')
callbook.QRZXml("KD3CCO", "pw", fetch=expired_fetch).fetch("W3ABC")
equals("a lapsed session is retried once", len(seen), 4)

bad = callbook.QRZXml("KD3CCO", "wrong",
                      fetch=lambda u, timeout=None: QRZ_BADLOGIN)
equals("bad credentials yield no session", bad.session(), "")
check("and the reason is kept", "incorrect" in bad.last_error, bad.last_error)
dead = callbook.QRZXml("KD3CCO", "pw",
                       fetch=lambda u, timeout=None: (_ for _ in ()).throw(
                           OSError("no route to host")))
equals("no network, no session, no exception", dead.session(), "")
check("and it says so", "unreachable" in dead.last_error, dead.last_error)

print("\nthe chain fills gaps rather than stopping at the first answer")
# The case that proves it, from this station's own callsign: callook has the
# name and the town but an EMPTY gridsquare, because the FCC record was never
# geocoded. HamQTH has the grid. Stopping at the first non-empty answer
# returned a contact with no grid when a grid was one request away.
CALLOOK_NO_GRID = ('{"status":"VALID","name":"DONALD J NATALE, III.",'
                   '"address":{"line2":"STATE COLLEGE, PA 16801"},'
                   '"location":{"latitude":"","longitude":"","gridsquare":""}}')
equals("callook alone has no grid for it",
       "grid" in callbook.parse_callook(CALLOOK_NO_GRID), False)

seen, fetch = session_fetcher(
    '<HamQTH xmlns="x"><search><nick>Don</nick><grid>FN10</grid>'
    '<qth>FN10cs</qth></search></HamQTH>')
hq = callbook.HamQTH("kd3cco", "pw", fetch=fetch)
filled = callbook.lookup("KD3CCO",
                         fetch=lambda u, timeout=None: CALLOOK_NO_GRID,
                         providers=[hq])
equals("callook's name wins, being the license record", filled["name"], "Donald")
equals("and its town", filled["qth"], "State College, PA")
equals("while the grid is filled from HamQTH", filled["grid"], "FN10")

print("\n  a complete first answer still costs one request")
seen, fetch = session_fetcher(QRZ_FOUND)
hq2 = callbook.HamQTH("kd3cco", "pw", fetch=fetch)
whole = callbook.lookup("W3ABC", fetch=lambda u, timeout=None: GOOD,
                        providers=[hq2])
equals("everything came from callook", whole["grid"], "EN90ak")
equals("and no provider was asked", len(seen), 0)

print("\n  the chain is ordered by what each gives away free")
chain = callbook.providers_from(
    {"HAMQTH_USER": "u", "HAMQTH_PASSWORD": "p",
     "QRZ_USER": "u", "QRZ_PASSWORD": "p"})
equals("HamQTH before QRZ, because QRZ withholds the grid",
       [type(p).__name__ for p in chain], ["HamQTH", "QRZXml"])
equals("a provider with no credentials is left out entirely",
       callbook.providers_from({"HAMQTH_USER": "u", "HAMQTH_PASSWORD": "p"}
                               )[0].__class__.__name__, "HamQTH")
equals("and nothing configured is an empty chain",
       callbook.providers_from({}), [])

print("\n  one broken provider does not stop the next")
class Explodes:
    enabled = True
    @staticmethod
    def parse(text):
        return {}
    def fetch(self, call):
        raise RuntimeError("boom")

seen, fetch = session_fetcher(
    '<HamQTH xmlns="x"><search><nick>Petr</nick><grid>jo70gg</grid>'
    '<qth>Rican</qth></search></HamQTH>')
survived = callbook.lookup(
    "OK2CQR", fetch=lambda u, timeout=None: INVALID,
    providers=[Explodes(), callbook.HamQTH("u", "p", fetch=fetch)])
equals("the second provider still answered", survived["name"], "Petr")

sys.exit(report())
