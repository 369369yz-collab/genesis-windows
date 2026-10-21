"""GENESIS tempemail module — privacy-preserving disposable email.

Public API:
    create_inbox()           -> dict  {"status": "ok", "address": str}
    read_inbox(address)       -> dict  {"status": "ok", "messages": [dict]}
    delete_inbox(address)     -> dict  {"status": "ok", ...}
    request_temp_phone(...)   -> raises TempPhoneRefused (hard red line)

Provider: 1secmail free disposable-email API
(https://www.1secmail.com/api/v1/ — documented, no signup, no cost).

HARD RED LINE (enforced in code, see _check_rate_limit and request_temp_phone):
  * Rotating disposable identities to dodge a service's rate limits / free-tier
    quotas is FORBIDDEN. create_inbox is locally rate-limited and burst patterns
    are blocked.
  * Temp-phone functionality is FORBIDDEN. Any request for a temporary phone
    number raises TempPhoneRefused.

1secmail inboxes cannot be explicitly deleted on the provider side; addresses
expire automatically on the provider's own schedule. delete_inbox() therefore
removes the address from the LOCAL registry and documents this honestly.

READ THROTTLE (throttling, not just a cap):
  * read_inbox is locally rate-limited: minimum 10 seconds between two reads
    (ReadThrottleExceeded on violation) — a runaway polling loop cannot hammer
    the free provider.
  * At most 25 message bodies are fetched per read_inbox call (result carries
    "truncated": True and "total": N when the inbox holds more).
  * Consecutive per-message fetches are paced 1.0 s apart.

ERROR CONTRACT: every provider/network failure surfaces as TempEmailError.
Transient connection failures (TimeoutError, OSError, http.client.HTTPException
incl. RemoteDisconnected) are retried with exponential backoff (3 attempts);
a real HTTP error response (URLError/HTTPError) is wrapped immediately.

NETWORK-BOUNDARY VALIDATION (the shape class, closed 2026-10-13):
  * Every value that crosses the network boundary is type-validated BEFORE
    the module calls a method on it or indexes into it. A hostile provider
    response shaped ANY way (wrong JSON types, non-dict list items,
    non-string mailbox entries, pathologically nested JSON) produces
    TempEmailError — never a raw AttributeError / TypeError / KeyError /
    IndexError / RecursionError.
  * Enforcement: _require_dict() / _require_list() helpers, applied at
    every parse site: genRandomMailbox, getMessages, each getMessages item,
    each readMessage body, and the local registry's fields (created_at,
    last_read_at, and addresses — wrong-typed values degrade gracefully
    instead of crashing).
  * Exception coverage in _api_get is exhaustive: the listed network
    classes (TimeoutError incl. socket.timeout, OSError incl. connection
    resets and TLS verification errors, http.client.HTTPException incl.
    RemoteDisconnected, urllib.error.URLError incl. HTTPError) get their
    own retry/wrap semantics, and a final `except Exception` clause is the
    contract's last line of defense — any exotic, non-listed exception
    from the network layer is wrapped as TempEmailError immediately, no
    retry. BaseException (KeyboardInterrupt, SystemExit) still propagates.
  * The json.loads RecursionError arm IS the parse-depth bound: a body
    nested deeper than the interpreter limit is a malformed provider
    response, wrapped — no separate depth check is needed.
  * Strictness note: a getMessages body that is not a JSON array is a
    malformed provider response and raises TempEmailError (no silent
    empty-inbox fallback); a non-dict message item raises TempEmailError
    (no silent skip); a non-string mailbox entry raises TempEmailError.
"""

import json
import os
import time
import http.client
import urllib.parse
import urllib.request
import urllib.error

API_BASE = "https://www.1secmail.com/api/v1/"
# Per-attempt socket timeout. Worst case per _api_get call against a
# black-hole provider: 10 + 1 + 10 + 2 + 10 = 33 s (3 attempts, 1 s/2 s
# backoff). Worst case per read_inbox: 26 provider calls x 33 s ~ 14.3 min
# + 24 s pacing ~ 14.7 min, then a clean TempEmailError — bounded, never
# infinite. Retry semantics (3 attempts, exponential backoff, URLError
# wrapped immediately without retry) are untouched; only the per-attempt
# timeout was tightened (20 -> 10 s), because a free JSON API whose normal
# responses are sub-second does not need a 20 s hang per attempt, and the
# 3-attempt retry already covers slow networks.
API_TIMEOUT_S = 10

# read_inbox safety cap: the provider needs one HTTP call per message body.
# Without a cap, a spam-flooded inbox turns into an unbounded request burst
# (provider IP-ban risk). Cap + document.
_MAX_MESSAGES_PER_READ = 25

# Read-throttle policy: the read path gets the same discipline as the create
# path. A runaway caller looping read_inbox() must not be able to hammer the
# free provider into an IP ban.
_READ_MIN_INTERVAL_S = 10   # minimum seconds between two read_inbox calls
_READ_PACE_S = 1.0          # delay between consecutive per-message fetches

# Retry/backoff policy for transient network failures in _api_get.
_RETRY_ATTEMPTS = 3         # total attempts per provider call (1 + 2 retries)
_RETRY_BACKOFF_BASE_S = 1.0  # exponential backoff: base * 2**retry_index

# Local registry of created inboxes (provider-expiration is provider-side).
_REGISTRY_ENV = "GENESIS_TEMPEMAIL_REGISTRY"
_DEFAULT_REGISTRY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tempemail_registry.json"
)

# Rate-limit policy — the hard red line against quota-evasion rotation.
_MAX_CREATES_PER_HOUR = 10      # absolute ceiling per rolling hour
_MIN_INTERVAL_S = 60            # minimum seconds between two creates
_BURST_WINDOW_S = 600           # 10-minute burst window
_BURST_MAX = 3                  # more than 3 creates in the burst window = blocked


class TempEmailError(Exception):
    """Base error for tempemail failures (network, API, address format)."""


class RateLimitExceeded(TempEmailError):
    """Raised when create_inbox is called faster than the local policy allows."""


class ReadThrottleExceeded(TempEmailError):
    """Raised when read_inbox is called faster than the read policy allows."""


class QuotaEvasionBlocked(TempEmailError):
    """Raised when a creation pattern matches identity-rotation abuse."""


class TempPhoneRefused(TempEmailError):
    """Raised for any temp-phone request. Temp phones are forbidden, always."""


def _require_dict(value, context):
    """Validate a value that crossed the network boundary is a dict.

    `context` names the boundary for the error message
    (e.g. "readMessage response"). A wrong-typed value is a malformed
    provider response -> TempEmailError, never a raw AttributeError.
    """
    if not isinstance(value, dict):
        raise TempEmailError(
            "Provider returned a malformed %s: expected a JSON object, got %s."
            % (context, type(value).__name__)
        )
    return value


def _require_list(value, context):
    """Validate a value that crossed the network boundary is a list.

    A wrong-typed value is a malformed provider response -> TempEmailError,
    never a raw TypeError.
    """
    if not isinstance(value, list):
        raise TempEmailError(
            "Provider returned a malformed %s: expected a JSON array, got %s."
            % (context, type(value).__name__)
        )
    return value


def _registry_path():
    return os.environ.get(_REGISTRY_ENV, _DEFAULT_REGISTRY)


def _load_registry():
    path = _registry_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("created_at", []), list):
            data = _harden_addresses(data)
            return data
    except (OSError, ValueError, RecursionError):
        # RecursionError: a pathologically nested local registry file is
        # corrupt the same way a malformed one is — degrade to the empty
        # default, never crash the caller with a raw RecursionError.
        pass
    return {"created_at": []}


def _harden_addresses(data):
    """Guard the registry `addresses` field the same way the other registry
    fields are guarded: a hand-edited/corrupt registry degrades gracefully,
    never crashes the caller.

    Convention, matching created_at (dropped non-numeric stamps) and
    last_read_at (degraded non-numeric to "no previous read"):
      * `addresses` present but not a list -> reset to [] ("no tracked
        addresses"), so create_inbox's tracked.append never raises a raw
        AttributeError and delete_inbox's `address in tracked` never raises
        a raw TypeError.
      * a list containing non-string/empty entries -> junk entries are
        dropped (the module only ever writes non-empty str addresses).
    The rest of the registry (e.g. created_at stamps) is untouched, so a
    corrupt addresses field never wipes rate-limit state.
    """
    addrs = data.get("addresses", [])
    if not isinstance(addrs, list):
        data["addresses"] = []
    else:
        data["addresses"] = [
            a for a in addrs if isinstance(a, str) and a
        ]
    return data


def _save_registry(reg):
    path = _registry_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _prune_old(reg, now):
    cutoff = now - 3600
    # Drop non-numeric stamps: a hand-edited/corrupt registry must degrade
    # to "no stamps", never crash _prune_old with a raw TypeError.
    # (bool is excluded explicitly: isinstance(True, int) is True.)
    reg["created_at"] = [
        t
        for t in reg.get("created_at", [])
        if isinstance(t, (int, float)) and not isinstance(t, bool) and t >= cutoff
    ]
    return reg


def _check_rate_limit(now=None):
    """Enforce the local creation policy. Raises RateLimitExceeded /
    QuotaEvasionBlocked on violation."""
    now = time.time() if now is None else now
    reg = _prune_old(_load_registry(), now)
    stamps = reg["created_at"]

    if stamps and now - stamps[-1] < _MIN_INTERVAL_S:
        raise RateLimitExceeded(
            "create_inbox called too soon after the previous create; "
            "wait %d seconds between inbox creations." % _MIN_INTERVAL_S
        )

    recent_burst = [t for t in stamps if now - t < _BURST_WINDOW_S]
    if len(recent_burst) >= _BURST_MAX:
        raise QuotaEvasionBlocked(
            "Burst creation pattern blocked: more than %d inboxes in %d seconds "
            "matches quota-evasion identity rotation, which is forbidden."
            % (_BURST_MAX, _BURST_WINDOW_S)
        )

    if len(stamps) >= _MAX_CREATES_PER_HOUR:
        raise RateLimitExceeded(
            "Hourly inbox-creation limit reached (%d/hour)."
            % _MAX_CREATES_PER_HOUR
        )

    stamps.append(now)
    _save_registry(reg)


def _check_read_throttle(now=None):
    """Enforce the local read policy. Raises ReadThrottleExceeded on violation.

    Stored in the local registry (same local-only caveat as the creation
    policy): minimum _READ_MIN_INTERVAL_S seconds between two read_inbox
    calls that touch the provider.
    """
    now = time.time() if now is None else now
    reg = _load_registry()
    last = reg.get("last_read_at")
    # A corrupt (non-numeric) last_read_at degrades to "no previous read",
    # never a raw TypeError. bool excluded: isinstance(True, int) is True.
    if (
        isinstance(last, (int, float))
        and not isinstance(last, bool)
        and now - last < _READ_MIN_INTERVAL_S
    ):
        raise ReadThrottleExceeded(
            "read_inbox called too soon after the previous read; "
            "wait %d seconds between inbox reads." % _READ_MIN_INTERVAL_S
        )
    reg["last_read_at"] = now
    _save_registry(reg)


def _api_get(params):
    """One provider HTTP call with bounded retry + exponential backoff.

    Transient connection failures (TimeoutError incl. socket.timeout,
    OSError incl. connection resets, http.client.HTTPException incl.
    RemoteDisconnected) are retried with exponential backoff, up to
    _RETRY_ATTEMPTS total attempts. A real HTTP error response from the
    provider (urllib.error.URLError / HTTPError) is wrapped immediately and
    is NOT retried — the provider answered, so hammering it again is wrong.

    CONTRACT: every failure that reaches the caller is a TempEmailError.
    Nothing from the network layer ever escapes raw.
    """
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(_RETRY_ATTEMPTS):
        req = urllib.request.Request(
            url, headers={"User-Agent": "GENESIS-tempemail/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
                body = resp.read()
        except urllib.error.URLError as exc:
            # Provider answered with an HTTP error (or DNS/TLS failed):
            # wrap immediately, do not retry.
            raise TempEmailError("Provider request failed: %s" % exc) from exc
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            # Flaky connection: back off and retry, then wrap.
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_BACKOFF_BASE_S * (2 ** attempt))
                continue
            raise TempEmailError(
                "Provider connection failed after %d attempts: %s: %s"
                % (_RETRY_ATTEMPTS, type(exc).__name__, exc)
            ) from exc
        except Exception as exc:
            # LAST LINE OF DEFENSE for the absolute contract ("nothing from
            # the network layer ever escapes raw"). The realistic network
            # failure classes are handled above with their own semantics
            # (retry transient, wrap URLError immediately); any exotic,
            # non-listed exception class raised by urlopen/resp.read()
            # (odd stdlib subclasses, vendor-specific errors) is wrapped
            # immediately WITHOUT retry — it is not a known-transient
            # failure, so hammering the provider is wrong. BaseException
            # (KeyboardInterrupt, SystemExit) still propagates: except
            # Exception never sees them.
            raise TempEmailError(
                "Provider request failed unexpectedly: %s: %s"
                % (type(exc).__name__, exc)
            ) from exc
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TempEmailError(
                "Provider returned a non-UTF-8 response body."
            ) from exc
        try:
            return json.loads(text)
        except (ValueError, RecursionError) as exc:
            # The RecursionError arm IS the parse-depth bound: a hostile
            # body nested deeper than the interpreter's recursion limit is
            # a malformed provider response, wrapped as TempEmailError —
            # never raw. No separate depth check is needed; the interpreter
            # enforces the bound, and this catch converts it. (RecursionError
            # is not a ValueError subclass, so the ValueError arm alone
            # would miss it.)
            raise TempEmailError(
                "Provider returned a malformed JSON response: %s: %s"
                % (type(exc).__name__, exc)
            ) from exc


def _split_address(address):
    if not isinstance(address, str) or "@" not in address:
        raise TempEmailError("Invalid email address: %r" % (address,))
    login, domain = address.rsplit("@", 1)
    if not login or not domain:
        raise TempEmailError("Invalid email address: %r" % (address,))
    return login, domain


def create_inbox():
    """Create one disposable inbox.

    Returns {"status": "ok", "address": address, "provider": "1secmail"}.
    The address is guaranteed to be a non-empty str: a non-string mailbox
    entry (or a malformed string) from the provider raises TempEmailError.
    Rate-limited locally (RateLimitExceeded) and burst-blocked
    (QuotaEvasionBlocked) — see module docstring for the red line.
    """
    _check_rate_limit()
    addrs = _require_list(
        _api_get({"action": "genRandomMailbox", "count": 1}),
        "genRandomMailbox response",
    )
    if not addrs:
        raise TempEmailError("Provider returned no mailbox.")
    address = addrs[0]
    # The documented return contract is address: str. A non-string mailbox
    # entry is a malformed provider response -> reject (never coerce a
    # garbage int into a fake address string). The address is also run
    # through _split_address so a malformed string fails here, not later.
    if not isinstance(address, str) or not address:
        raise TempEmailError(
            "Provider returned a malformed mailbox entry: expected a "
            "non-empty string, got %s." % type(address).__name__
        )
    _split_address(address)
    reg = _load_registry()
    tracked = reg.setdefault("addresses", [])
    if address not in tracked:
        tracked.append(address)
    _save_registry(reg)
    return {"status": "ok", "address": address, "provider": "1secmail"}


def read_inbox(address, max_messages=_MAX_MESSAGES_PER_READ):
    """Read messages in the inbox for `address`.

    Returns {"status": "ok", "address": address,
             "messages": [{"id", "from", "subject", "date", "body"}, ...]}.
    Bodies are fetched per-message from the provider (textBody preferred,
    htmlBody as fallback). At most `max_messages` bodies are fetched
    (default 25) — the list itself is never truncated silently: when the
    inbox holds more, the result carries "truncated": True and "total": N.

    Throttling (local, provider-protecting):
      * minimum 10 s between two read_inbox calls (ReadThrottleExceeded),
      * 1.0 s pacing between consecutive per-message fetches,
      * transient network failures inside _api_get get bounded retries
        with exponential backoff.
    All provider failures surface as TempEmailError — including malformed
    provider responses (non-list getMessages body, non-dict message items,
    non-dict readMessage bodies, bad message ids): the network boundary is
    type-validated before parsing (see module docstring).
    """
    login, domain = _split_address(address)
    _check_read_throttle()
    # NETWORK BOUNDARY: every shape the provider returns is validated before
    # use. A hostile/malformed response shaped ANY way raises TempEmailError
    # here — never a raw AttributeError/TypeError from the parse below.
    raw = _api_get({"action": "getMessages", "login": login, "domain": domain})
    items = _require_list(raw, "getMessages response")
    total = len(items)
    truncated = total > max_messages
    messages = []
    for i, m in enumerate(items[:max_messages]):
        if i:
            time.sleep(_READ_PACE_S)  # pace the per-message burst
        item = _require_dict(m, "getMessages item #%d" % i)
        mid = item.get("id")
        # The id is sent back to the provider as a query param; it must be a
        # real scalar id. Missing/bool/float ids are malformed responses.
        if isinstance(mid, bool) or not (
            isinstance(mid, int) or (isinstance(mid, str) and mid)
        ):
            raise TempEmailError(
                "Provider returned a malformed getMessages item #%d: "
                "expected an int/str message id, got %r." % (i, mid)
            )
        full = _require_dict(
            _api_get(
                {
                    "action": "readMessage",
                    "login": login,
                    "domain": domain,
                    "id": mid,
                }
            ),
            "readMessage response",
        )
        messages.append(
            {
                "id": mid,
                "from": full.get("from", ""),
                "subject": full.get("subject", ""),
                "date": full.get("date", ""),
                "body": full.get("textBody") or full.get("htmlBody") or "",
            }
        )
    result = {"status": "ok", "address": address, "messages": messages}
    if truncated:
        result["truncated"] = True
        result["total"] = total
    return result


def delete_inbox(address):
    """Delete an inbox from the LOCAL registry.

    The 1secmail API has no delete endpoint; provider-side addresses expire
    automatically on the provider's own schedule. This function removes the
    address from local tracking and states the provider reality honestly.

    Returns {"status": "ok", "address": address,
             "provider_expiry": "automatic (no provider-side delete endpoint)"}.
    """
    _split_address(address)  # validate format even though provider ignores us
    reg = _load_registry()
    tracked = reg.get("addresses", [])
    if address in tracked:
        tracked.remove(address)
        _save_registry(reg)
    return {
        "status": "ok",
        "address": address,
        "provider_expiry": "automatic (no provider-side delete endpoint)",
    }


def request_temp_phone(*args, **kwargs):
    """FORBIDDEN. Temp-phone functionality does not exist in this module.

    Always raises TempPhoneRefused. There is no phone-number provider, no
    flag, no workaround — the hard red line is unconditional.
    """
    raise TempPhoneRefused(
        "Temp-phone functionality is forbidden by module policy. "
        "This module provides disposable EMAIL only, for privacy-preserving "
        "signups. No temporary phone numbers will ever be issued."
    )
