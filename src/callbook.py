"""Callsign lookup, for when the deck has a network and feels like it.

Three rules shape everything here, and they come from the deck rather than
from the lookup:

  * **It must never block.** cyberdeck.py is a single-threaded curses loop. An
    HTTP request in it freezes the screen for as long as the network takes,
    which in the field is "until the timeout". So a lookup is handed to a
    worker thread and the answer is collected later, or never.
  * **It must never gate a commit.** A QSO is logged whether or not anything
    is known about the other station. The lookup fills blanks the operator did
    not type; it does not hold the record up and it does not overwrite what was
    typed. Absent network is an ordinary condition, exactly like absent
    rigctld.
  * **It must work offline afterwards.** Every answer is cached to disk, so a
    station worked once is known on the next activation with the WiFi off. The
    cache is the point, not an optimisation — the deck spends most of its life
    without a network.

The network itself is injectable (`fetch=`), so every test in here runs with no
network and no mocking library.

Provider: callook.info, which is free, needs no key or registration, and
covers US callsigns. Non-US calls come back "not found", which is a correct
answer rather than an error — see `lookup`.
"""

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from xml.etree import ElementTree

URL = "https://callook.info/{call}/json"

# HamQTH covers the world where callook covers only the US, which is the whole
# reason for a second provider. It needs an account and a session, so it is
# more machinery than callook, and the credentials go in cyberdeck.secrets.
HAMQTH_URL = "https://www.hamqth.com/xml.php"
HAMQTH_PRG = "cyberdeck"
# Their documented session lifetime is one hour. Re-logging in early costs one
# request; discovering the expiry costs a failed lookup during a QSO.
HAMQTH_SESSION_S = 50 * 60
TIMEOUT_S = 4.0

# A cached answer is good for a long time: license data changes on the order of
# years, and a stale name is better than no name. Re-looked-up only if the
# entry predates this.
CACHE_TTL_S = 90 * 24 * 3600

# What a lookup is trying to find. The chain stops once it has all of these,
# and keeps asking while any is missing — see `lookup`.
WANTED = ("name", "qth", "grid")

# Beside the log, under the same XDG-ish directory qsolog uses, so the whole of
# the logger's state is in one place to back up or delete.
DEFAULT_CACHE_PATH = "~/.local/share/cyberdeck/callbook.json"


def cache_path(path=""):
    return os.path.expanduser(path or os.environ.get("CYBERDECK_CALLBOOK_CACHE")
                              or DEFAULT_CACHE_PATH)


def _http_get(url, timeout=TIMEOUT_S):
    """The default fetcher. Replaced wholesale in tests."""
    req = urllib.request.Request(url, headers={"User-Agent": "cyberdeck"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _first_name(text):
    """The first name out of a callbook's name field, cased for a log.

    `.title()` alone is wrong for initials: a real lookup of G3VA returns the
    nick "JP", and title-casing turns it into "Jp", which is not what anyone
    is called. A token with no vowels is initials and is left alone; so is a
    two-character one. Everything else is a word and gets title case, so
    "ROBERT J SMITH" is "Robert" and "Petr" stays "Petr".
    """
    first = (text or "").strip().split()
    if not first:
        return ""
    word = first[0]
    if word.isupper() and (len(word) <= 2 or not set(word) & set("AEIOUY")):
        return word
    return word.title()


def parse_callook(text):
    """Pull the useful fields out of a callook.info reply.

    Returns a dict with whatever was found, or {} for a call that is not in
    the database. Never raises: a malformed reply is indistinguishable from a
    missing one as far as the operator is concerned, and neither is worth an
    exception during a QSO.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict) or data.get("status") != "VALID":
        return {}

    out = {}
    name = (data.get("name") or "").strip()
    if name:
        # callook gives "FIRST LAST" or a club name in full. The log wants
        # something to say on the air, which is the first name.
        out["name"] = _first_name(name)

    addr = data.get("address") or {}
    line2 = (addr.get("line2") or "").strip()
    if line2:
        # "PITTSBURGH, PA 15213" -> "Pittsburgh, PA". The ZIP is not something
        # anybody reads back, and the deck has 66 columns.
        out["qth"] = re.sub(r"\s+\d{5}(-\d{4})?$", "", line2).title()
        out["qth"] = re.sub(r",\s*([A-Za-z]{2})$",
                            lambda m: ", " + m.group(1).upper(), out["qth"])

    loc = data.get("location") or {}
    grid = (loc.get("gridsquare") or "").strip()
    if grid:
        # Maidenhead convention is upper, digits, lower. callook returns it
        # already mixed, but not reliably.
        out["grid"] = grid[:4].upper() + grid[4:].lower()

    return out


def parse_hamqth(text):
    """Pull the useful fields out of a HamQTH XML reply.

    Returns {} for a call that is not there, an error, or anything
    unparseable — the same contract as `parse_callook`, so `lookup` does not
    care which provider answered.

    **`nick`, not `name`.** HamQTH's `name` is a private field and is empty
    whenever the operator has hidden it, which is often; `nick` is the on-air
    name and is the one worth putting in a log. Reading `name` first gets
    blanks from exactly the stations most likely to care.
    """
    try:
        root = ElementTree.fromstring((text or "").strip())
    except ElementTree.ParseError:
        return {}

    def find(tag):
        # HamQTH namespaces its replies, and the prefix has changed before.
        # Matching on the local name is what keeps this working either way.
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1].lower() == tag:
                return (el.text or "").strip()
        return ""

    if find("error"):
        return {}

    out = {}
    nick = find("nick") or find("name")
    if nick:
        out["name"] = _first_name(nick)
    qth = find("qth")
    country = find("country")
    if qth:
        out["qth"] = f"{qth.title()}, {country.title()}" if country else qth.title()
    elif country:
        out["qth"] = country.title()
    grid = find("grid")
    if grid:
        out["grid"] = grid[:4].upper() + grid[4:].lower()
    return out


class HamQTH:
    """A HamQTH session, re-established when it expires.

    Held as an object rather than a function because the session id is state:
    one login serves an hour of lookups, and logging in per contact would be
    two round trips instead of one on a connection that may be a phone
    hotspot.

    Credentials come from `cyberdeck.secrets`. With none, `enabled` is False
    and this provider is simply not used — the same rule the rest of the deck
    follows for absent configuration.
    """

    parse = staticmethod(parse_hamqth)

    def __init__(self, user="", password="", fetch=_http_get,
                 url=HAMQTH_URL, now=time.time, prg=HAMQTH_PRG):
        self.user = str(user or "").strip()
        self.password = str(password or "")
        self._fetch = fetch
        self._url = url
        self._now = now
        self._prg = prg
        self._session = ""
        self._session_at = 0.0
        self.last_error = ""

    @property
    def enabled(self):
        return bool(self.user and self.password)

    def _login(self):
        query = urllib.parse.urlencode({"u": self.user, "p": self.password})
        try:
            text = self._fetch(f"{self._url}?{query}")
        except Exception as exc:
            self.last_error = f"HamQTH unreachable ({type(exc).__name__})"
            return ""
        try:
            root = ElementTree.fromstring((text or "").strip())
        except ElementTree.ParseError:
            self.last_error = "HamQTH gave an unparseable reply"
            return ""
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1].lower()
            if tag == "session_id" and (el.text or "").strip():
                self._session = el.text.strip()
                self._session_at = self._now()
                self.last_error = ""
                return self._session
            if tag == "error":
                # "Wrong user name or password" — worth saying once, because
                # the symptom otherwise is a lookup that silently never works.
                self.last_error = f"HamQTH: {(el.text or '').strip()}"
                return ""
        self.last_error = "HamQTH returned no session"
        return ""

    def session(self):
        if self._session and self._now() - self._session_at < HAMQTH_SESSION_S:
            return self._session
        return self._login()

    def fetch(self, call):
        """Raw XML for one call, or "". Signature suits `lookup`'s `fetch`."""
        sid = self.session()
        if not sid:
            return ""
        query = urllib.parse.urlencode(
            {"id": sid, "callsign": call, "prg": self._prg})
        text = self._fetch(f"{self._url}?{query}")
        # Retry ONLY on session expiry. Matching any <error> would re-login
        # and repeat the request for every callsign that is simply not in the
        # database — "Callsign not found" is an <error> too — which doubles
        # the traffic for exactly the lookups that were already a dead end.
        if "session does not exist" in (text or "").lower():
            # One retry, and only after a fresh login: a session that expired
            # early is the expected failure here, not a reason to give up.
            self._session = ""
            sid = self.session()
            if sid:
                query = urllib.parse.urlencode(
                    {"id": sid, "callsign": call, "prg": self._prg})
                text = self._fetch(f"{self._url}?{query}")
        return text or ""


# QRZ's XML callsign service. A DIFFERENT thing from the QRZ logbook upload in
# qrzlog.py: different endpoint, different credential, different subscription.
# Having one says nothing about having the other.
QRZ_URL = "https://xmldata.qrz.com/xml/current/"
QRZ_AGENT = "cyberdeck1.0"


def parse_qrz(text):
    """Pull the useful fields out of a QRZ XML reply. {} for nothing known.

    **A non-subscriber gets the name and the town but usually not the grid.**
    Measured 2026-10-11: `<grid>` came back for one call in three, with
    "A subscription is required to access the complete record" on the others.
    The grid is the field most worth having, which is why QRZ is last in the
    chain rather than first — callook and HamQTH both give it away.
    """
    try:
        root = ElementTree.fromstring((text or "").strip())
    except ElementTree.ParseError:
        return {}

    found = {}
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1].lower()
        if name not in found:
            found[name] = (el.text or "").strip()

    if found.get("error"):
        return {}

    out = {}
    if found.get("fname"):
        out["name"] = _first_name(found["fname"])
    town = found.get("addr2", "")
    where = found.get("state") or found.get("country") or ""
    if town:
        out["qth"] = f"{town.title()}, {where}" if where else town.title()
    elif where:
        out["qth"] = where
    grid = found.get("grid", "")
    if grid:
        out["grid"] = grid[:4].upper() + grid[4:].lower()
    return out


class QRZXml:
    """A QRZ XML session, re-established when it lapses.

    Their documented position is that session keys have "no guaranteed
    lifetime" and are invalidated when the client's IP changes — which, on a
    deck that moves between a home network and a phone hotspot, happens. So
    there is no expiry timer here: a lapsed key is detected from the reply and
    the login is repeated, which is the only thing that can work.
    """

    def __init__(self, user="", password="", fetch=_http_get, url=QRZ_URL,
                 agent=QRZ_AGENT):
        self.user = str(user or "").strip()
        self.password = str(password or "")
        self._fetch = fetch
        self._url = url
        self._agent = agent
        self._session = ""
        self.subscription = ""
        self.last_error = ""

    parse = staticmethod(parse_qrz)

    @property
    def enabled(self):
        return bool(self.user and self.password)

    def _query(self, params):
        # urlencode is not optional: a QRZ account password may contain '&' —
        # this station's does — and pasting it raw into a query string
        # truncates it there and sends a different, shorter password.
        return f"{self._url}?{urllib.parse.urlencode(params)}"

    def _login(self):
        try:
            text = self._fetch(self._query(
                {"username": self.user, "password": self.password,
                 "agent": self._agent}))
        except Exception as exc:
            self.last_error = f"QRZ unreachable ({type(exc).__name__})"
            return ""
        try:
            root = ElementTree.fromstring((text or "").strip())
        except ElementTree.ParseError:
            self.last_error = "QRZ gave an unparseable reply"
            return ""

        key, error = "", ""
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1].lower()
            value = (el.text or "").strip()
            if tag == "key" and value:
                key = value
            elif tag == "error" and value:
                error = value
            elif tag == "subexp" and value:
                self.subscription = value
        if key:
            self._session = key
            self.last_error = ""
            return key
        self.last_error = f"QRZ: {error}" if error else "QRZ returned no session"
        return ""

    def session(self):
        return self._session or self._login()

    def fetch(self, call):
        """Raw XML for one call, or "". Signature suits the provider chain."""
        key = self.session()
        if not key:
            return ""
        text = self._fetch(self._query({"s": key, "callsign": call}))
        # A lapsed or IP-invalidated session says so in the reply. Retry once
        # after a fresh login — and only on that, not on "Not found", which is
        # also an <Error> and would double the traffic for every dead end.
        if re.search(r"session (?:timeout|does not exist|invalid)|"
                     r"invalid session", text or "", re.I):
            self._session = ""
            if self.session():
                text = self._fetch(self._query({"s": self._session,
                                                "callsign": call}))
        return text or ""


class Cache:
    """Answers on disk, so a station worked once is known offline afterwards.

    Written whole on every store. The file is small — a few hundred bytes per
    callsign — and rewriting it is simpler than appending with no way to
    compact, which matters because this runs on an SD card that is written as
    little as the rest of the deck allows.
    """

    def __init__(self, path, now=time.time):
        self.path = path
        self._now = now
        self._data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._data = data
        except (OSError, ValueError):
            # A missing or corrupt cache is not a failure. It is an empty one.
            self._data = {}

    def get(self, call, ttl=CACHE_TTL_S):
        entry = self._data.get(call.upper())
        if not isinstance(entry, dict):
            return None
        if ttl and self._now() - entry.get("at", 0) > ttl:
            return None
        return dict(entry.get("info") or {})

    def put(self, call, info):
        self._data[call.upper()] = {"at": self._now(), "info": dict(info or {})}
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError:
            # Losing the cache costs a lookup, not a contact. Never raise out
            # of here: this runs on the commit path.
            pass

    def __len__(self):
        return len(self._data)


_ROUTES = "/proc/net/route"


def online(routes_path=_ROUTES):
    """Whether this machine has a default route, i.e. a way off the subnet.

    Read from /proc rather than probed over the network, deliberately. The
    answer is wanted on every menu draw and every lookup decision, and a
    machine with no route must get that answer instantly instead of waiting
    out a connection attempt -- which on the deck means the operator is in a
    field with the panel in front of them.

    A default route is not proof the internet is reachable. It is proof the
    attempt is worth making, which is the decision being taken. The lookup
    itself fails gracefully either way, and the distinction the operator cares
    about is "the WiFi is not associated" versus "I turned this off".

    The field in /proc/net/route is the destination as a little-endian hex
    word; 00000000 is the default route.
    """
    try:
        with open(routes_path, encoding="utf-8") as fh:
            next(fh, None)                               # the header row
            for line in fh:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return True
    except (OSError, StopIteration):
        return False
    return False


# What the operator is told, which is three states from two settings. "off"
# is a decision they made; "no wifi" is a condition they can fix; "on" is
# working. Collapsing the last two into one word is what made a station with
# no association look like a station with the feature switched off.
CALLBOOK_OFF = "off"
CALLBOOK_ON = "on"
CALLBOOK_NO_NET = "no wifi"


def callbook_state(setting, is_online=None):
    """One of CALLBOOK_OFF / CALLBOOK_ON / CALLBOOK_NO_NET."""
    if str(setting or "").strip().lower() not in ("yes", "on", "true", "1"):
        return CALLBOOK_OFF
    if is_online is None:
        is_online = online()
    return CALLBOOK_ON if is_online else CALLBOOK_NO_NET


def providers_from(settings, fetch=_http_get):
    """The provider chain a configuration implies, in the order to try it.

    Ordered by what each one gives away free, not by which is best known:

      * **callook.info** — US only, no account, and it returns the grid.
      * **HamQTH** — worldwide, free account, and it returns the grid.
      * **QRZ XML** — worldwide, free account, but a non-subscriber usually
        does NOT get the grid (measured 2026-10-11). Last, because the grid
        is the field most worth having and this is the one that withholds it.

    A provider with no credentials is left out rather than added and skipped,
    so the chain contains only things that can actually answer.
    """
    out = []
    hq = HamQTH(settings.get("HAMQTH_USER", ""),
                settings.get("HAMQTH_PASSWORD", ""), fetch=fetch)
    if hq.enabled:
        out.append(hq)
    qrz = QRZXml(settings.get("QRZ_USER", ""),
                 settings.get("QRZ_PASSWORD", ""), fetch=fetch)
    if qrz.enabled:
        out.append(qrz)
    return out


def lookup(call, cache=None, fetch=_http_get, url=URL, hamqth=None,
           providers=()):
    """Synchronous lookup. Cache first, network second, {} if neither answers.

    `{}` means "nothing known", which covers a call that is not in the
    database, a network that is not there, and a reply that made no sense. The
    caller treats all three identically, so distinguishing them would only
    create a decision nobody needs to make mid-QSO.

    callook is always tried first: it needs no account and no session, and for
    a US call its license data is the most authoritative of the three. Each
    provider in `providers` is then tried in order until one answers, which is
    what makes a non-US call work at all. `hamqth` is the older single-provider
    form and is simply prepended to the chain.

    **Partial answers are filled in from the next provider, not accepted as
    final.** This station's own call is the case that proves it: callook has
    the name and the town but an empty `gridsquare`, because the FCC record was
    never geocoded, while HamQTH has the grid. Stopping at the first non-empty
    answer returned a contact with no grid when a grid was one request away.

    Earlier providers win per field, so callook's license data is preferred for
    a US call. The chain stops as soon as name, QTH and grid are all present,
    so a complete first answer still costs exactly one request. Lookups run off
    the interface thread (`Background`), so the extra round trip when an answer
    is partial does not make anybody wait.
    """
    call = str(call).strip().upper()
    if not call:
        return {}

    if cache is not None:
        hit = cache.get(call)
        if hit is not None:
            return hit

    try:
        text = fetch(url.format(call=call))
    except Exception:
        # Deliberately broad. urllib raises half a dozen unrelated types for
        # "no network", and on the deck they are all the same event.
        return {}

    info = parse_callook(text)

    chain = ([hamqth] if hamqth is not None else []) + list(providers)
    for provider in chain:
        if all(info.get(field) for field in WANTED):
            break
        if not getattr(provider, "enabled", False):
            continue
        try:
            more = provider.parse(provider.fetch(call))
        except Exception:
            # Deliberately broad, per provider. One misbehaving callbook must
            # not stop the next one being asked, and none of them may stop the
            # contact being logged.
            continue
        for field, value in more.items():
            if value and not info.get(field):
                info[field] = value

    if cache is not None:
        # Negative answers are cached too. A call that is not in callook will
        # not be in it next time either, and the deck should not spend four
        # seconds finding that out again.
        cache.put(call, info)
    return info


def merge(parsed, info):
    """Fill blanks in a parsed entry from a lookup. Never overwrites.

    What the operator typed wins, always. They heard it on the air; the
    database is a guess from a license record that may be a decade old.
    """
    out = dict(parsed)
    for key in WANTED:
        if not out.get(key) and info.get(key):
            out[key] = info[key]
    return out


class Background:
    """Fire a lookup off and collect it later, or not at all.

    `start` returns immediately. `take` returns the answer if one has arrived
    and None otherwise, so the interface polls it on the frame it already
    draws rather than waiting on anything. A lookup still running when the
    operator commits is simply not used.
    """

    def __init__(self, cache=None, fetch=_http_get, providers=()):
        self._cache = cache
        self._fetch = fetch
        # The chain, or a background lookup silently skips every provider
        # that needs an account -- which is the two that cover the world.
        self._providers = list(providers)
        self._lock = threading.Lock()
        self._results = {}
        self._running = set()

    def start(self, call):
        call = str(call).strip().upper()
        if not call:
            return
        with self._lock:
            if call in self._running or call in self._results:
                return
            self._running.add(call)

        def work():
            info = lookup(call, cache=self._cache, fetch=self._fetch,
                          providers=self._providers)
            with self._lock:
                self._results[call] = info
                self._running.discard(call)

        threading.Thread(target=work, daemon=True).start()

    def take(self, call):
        """The answer for `call`, once, or None if it is not ready."""
        call = str(call).strip().upper()
        with self._lock:
            return self._results.pop(call, None)

    def pending(self):
        with self._lock:
            return len(self._running)
