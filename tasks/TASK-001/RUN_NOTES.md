# TASK-001 — RUN_NOTES

**Scope**: `tasks/TASK-001/engine_hardened.py` is a **defensive hardening layer**
on top of `tasks/TASK-001/engine_redacted.py`. The original production
engine's business logic is **not modified** (mail copy / SMTP creds /
`SOURCES` list). This PR only adds validation + observability + tests.

## Files in this PR
| File                                         | Role                                                   |
|----------------------------------------------|--------------------------------------------------------|
| `tasks/TASK-001/engine_hardened.py`          | Input validators + `SwallowedExceptionCounter` + safe wrappers + smoke-runner |
| `tasks/TASK-001/RUN_NOTES.md`                | This file                                              |
| `tests/TASK-001/test_engine_hardened.py`     | 11 stdlib-only regression tests                        |

## Run

From a clean checkout (Python 3.12 / stdlib only):

```bash
PYTHONPATH=tasks/TASK-001 python3.12 -m unittest tests.TASK-001.test_engine_hardened -v
```

Expected: 11 tests, all `ok`, `unittest` exit code = 0.

## Exit-code contract (machine-distinguishable from "really 0 leads")

| Exit | Meaning                                                                              |
|------|--------------------------------------------------------------------------------------|
| 0    | Truly empty run — no swallowed exceptions                                            |
| 2    | Guard layer **caught** a swallowed exception (counter >=1, stderr JSON log emitted)  |
| 1    | Unhandled runtime error after the guard's last `except Exception` fallback           |

On the **seeded-bug check** (verifier reintroduces a tuple-unpack-family bug),
the new guard returns `None` + counter += 1 + exit code = 2,
strictly distinguishable from the original "0 leads" exit code 0.

## Honeypot / legit fixtures used by the tests (matches your spec)

Honeypot reject (3): `%E6%80..@qq.com`, `bad@-bad-.com`, `aaaa…x41@x.com`
Legit pass (4): `alice@example.com`, `bob.smith@subdomain.example.org`,
`carol+tag@x-y.example.io`, `dave_42@123.domain24.co`

## Out of scope (explicit)

- No rewrite of the production engine's business logic beyond the named points.
- No dependencies beyond the Python stdlib.
- Tests issue **zero network requests** (validation is pure-string + regex).
- No production SECRET or real customer email is referenced or logged.

## Why this is structurally defensive (not a band-aid)

The original failure was an `except: pass` swallowing a tuple-unpack error
and reporting "0 new leads". The hardened engine replaces every `except: pass`
with a guarded path:

- `safe_fetch(url, *, counter, origin)` — replaces `try: h = fetch(u) except: pass`
- `safe_email_iter(html, *, counter)` — replaces the unguarded `re.findall`
- `validate_list_url` / `validate_detail_url` / `validate_email` — strict
  pre-flight on the three engine ingestion points.

Every guarded failure is single-line JSON to stderr (`ts/origin/exc_type/msg/ctx`)
so a CI consumer can grep/parse to detect "0 leads vs 0 leads because broken".
