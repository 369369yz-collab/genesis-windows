# genesis-tempemail — Disposable Email for Privacy-Preserving Signups

## What it does

`tempemail.py` gives GENESIS a disposable-email capability: create a throwaway
inbox, read the messages that arrive in it (e.g. signup verification codes),
and delete the inbox from local tracking. The purpose is **privacy** — signing
up for legitimate services without exposing the user's real email address and
without getting spam.

## HARD RED LINE

**Rotating disposable identities to dodge a service's rate limits, free-tier
quotas, or signup restrictions is FORBIDDEN and is blocked in code.**

- `create_inbox()` is locally rate-limited:
  - minimum 60 seconds between two creations,
  - maximum 10 creations per rolling hour,
  - burst pattern of more than 3 creations in 10 minutes raises
    `QuotaEvasionBlocked` (this is the signature of identity-rotation abuse).
- `read_inbox()` is locally rate-limited too (the read path gets the same
  discipline as the create path):
  - minimum 10 seconds between two reads (`ReadThrottleExceeded`),
  - at most 25 message bodies fetched per call (result carries
    `"truncated": true` and `"total": N` when the inbox holds more),
  - 1.0 s pacing between consecutive per-message fetches,
  - transient network failures are retried with exponential backoff
    (3 attempts) — a real HTTP error from the provider is wrapped
    immediately, never retried.
- **Temp-phone functionality does not exist.** Any call to
  `request_temp_phone()` raises `TempPhoneRefused`, unconditionally. There is
  no provider, no flag, no workaround — this is a standing policy of the module.

The quota-evasion variant of "temp everything" was reviewed and **declined**:
it violates services' rules, gets accounts banned, and harms the user in the
end. Legitimate use only.

## Architecture

Single module, stdlib-only (`urllib`, `json`, `os`, `time`).

```
tempemail.py          — create_inbox / read_inbox / delete_inbox /
                        request_temp_phone (refusal) / rate limiter
tempemail_registry.json — local registry: creation timestamps (rate limiting)
                        + last-read timestamp (read throttle)
                        + tracked addresses. NOT synced anywhere.
```

Provider: **1secmail** free disposable-email API
(`https://www.1secmail.com/api/v1/`), documented, no signup, no cost:

| Our function   | Provider call                                    |
|----------------|--------------------------------------------------|
| create_inbox() | `?action=genRandomMailbox&count=1`               |
| read_inbox()   | `?action=getMessages&login=..&domain=..` then `?action=readMessage&...&id=..` per message |
| delete_inbox() | **none exists** — provider expires addresses automatically |

## Bridge call points

**None.** This module talks directly to the 1secmail HTTP API. No bridge call
is needed or faked. Future note: if GENESIS ever routes provider traffic
through the network bridge, the single seam is `_api_get()` in `tempemail.py`.

## What's real vs what's stub

- **Real:** `create_inbox()`, `read_inbox()`, `delete_inbox()` against the live
  1secmail API (verified pattern from the provider's public documentation;
  unit tests mock the HTTP layer — see below).
- **Privacy caveat (inherent to the provider, not a bug):** 1secmail inboxes
  are PUBLIC — anyone who guesses or learns the address can read it. Use for
  throwaway signups only, never for sensitive accounts.
- **Real:** the rate limiter, the read throttle, and the temp-phone refusal —
  all enforced in code and covered by tests.
- **Real:** the error contract — every provider/network failure surfaces as
  `TempEmailError`; transient connection failures get bounded retries with
  exponential backoff (tested at the urlopen level).
- **Honest limitation, not a stub:** `delete_inbox()` cannot delete the address
  on the provider side because the 1secmail API has **no delete endpoint**.
  It removes the address from the local registry and returns
  `"provider_expiry": "automatic (no provider-side delete endpoint)"`.
  Provider-side addresses expire on the provider's own schedule.
- **Not faked:** there is no fake network fallback. If the provider is
  unreachable, the function raises `TempEmailError` with the real error.

## Windows-only notes

Nothing in this module is Windows-only — pure HTTP + stdlib. On the Windows
runner it works with the bundled Python 3.12 venv with zero extra installs.
Run `python windows_smoke_test.py` for the smoke check (mocked by default;
set `GENESIS_TEMPEMAIL_LIVE=1` for one real provider call).

## API reference

All public functions return plain dicts with a `"status"` key.

- `create_inbox() -> {"status": "ok", "address": str, "provider": "1secmail"}`
  Raises `RateLimitExceeded` / `QuotaEvasionBlocked` on policy violation,
  `TempEmailError` on provider failure.
- `read_inbox(address) -> {"status": "ok", "address": str,
  "messages": [{"id", "from", "subject", "date", "body"}, ...]}`
  Raises `TempEmailError` on invalid address or provider failure,
  `ReadThrottleExceeded` when called sooner than 10 s after the previous read.
  Fetches at most 25 bodies per call (`"truncated": true`, `"total": N` when
  more exist); per-message fetches are paced 1 s apart; transient network
  failures are retried with exponential backoff (3 attempts).
- `delete_inbox(address) -> {"status": "ok", "address": str,
  "provider_expiry": "automatic (no provider-side delete endpoint)"}`
- `request_temp_phone(...)` — always raises `TempPhoneRefused`.

## Tests

`pytest tests/` — HTTP layer fully mocked; see `tests/test_tempemail.py`.
`test_logs/` holds the three independent green runs (TRIPLE-TEST LAW).
