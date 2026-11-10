# Successive correction recovery — 10 November 2026

## Observed failure

The live model returned HTTP 200, but the local validator rejected its output:
`Correction after-value does not match the active instruction`. The user saw
this repeatedly while changing a quantity from 40 to 45 after an initial
self-correction from 50 to 40. The exact rejected live JSON was not provided;
the displayed validation error establishes an inconsistent correction record,
not which specific field value the live model chose.

## Changes

- Clarifies that the instructions are final active values and each correction's
  after-value must equal its referenced instruction's value.
- Gives the successive 50 → 40 → 45 example, represented by one net 50 → 45
  correction while retaining every original transcript turn.
- Validates provider output before returning it to the workflow.
- For an inconsistent after-value or duplicate net corrections only, requests
  one fresh extraction with the rejected candidate and validation feedback.
  The candidate is diagnostic data, never an approved instruction.
- Validates the recovery with the same strict schema and source checks. If it
  fails, the old version remains and the correction stays pending.
- Persists both validation candidates and their errors in the existing private
  local attempt reports. Nothing is auto-approved or emailed.

The first generation retains the existing limit of three HTTP attempts for
explicit 503 responses. The recovery allows exactly one HTTP attempt, with
no 503 retry: at most four HTTP requests total. A valid first candidate uses
one generation. Schema failures, invented source quotes and unrelated validation
errors do not trigger recovery. This adds a potential model call and can use
additional provider credits; no live calls were made while preparing the fix.

## Validation

236 offline Python tests pass. Eleven new tests cover single-pass success,
successful and unsuccessful recovery, fabricated quote rejection, duplicate
net corrections, request limits, complete trace retention and the HTTP endpoint
returning an unapproved version 2 after a failed correction is retried.
The existing 225 tests still pass. Services in these tests are simulated;
the actual model must still be checked on the user's laptop.

## Installation

Stop the server. Back up and extract `SunoJob_Correction_Fix.zip` into the
existing `$HOME/sunojob`, then run the tests and restart. The patch contains:

```text
sunojob/providers.py
sunojob/speech.py
tests/test_voice_adapters.py
tests/test_correction_recovery.py
CORRECTION_FIX_README.md
README.md and refreshed submission guides
```

It does not change the database schema, saved requests, receipts or credentials.
Also apply it to the clean submission folder before committing/pushing that
source. The refreshed submission kit already contains it.

In the UI, select the pending request. Keep the recognized correction text and
click Apply correction once. This makes a fresh model request and may make the
one recovery request described above. Check for version 2, quantity 45, no onion
and ask-before-menu-change. Then generate the new readback, listen fully,
confirm and complete separate owner acceptance. Do not reuse an old approval.
