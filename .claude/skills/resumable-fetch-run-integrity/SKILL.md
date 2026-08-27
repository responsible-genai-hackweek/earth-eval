---
name: resumable-fetch-run-integrity
description: Use when a long data-fetch run over many independent units - water years, months, tiles - is being written, scheduled, resumed, interrupted, or re-scoped; when a finished run may be missing units, or has produced empty values whose cause is unknown; when requests are failing with HTTP errors or dropped connections; or when a number is about to be derived from a record that may be partial.
---

# Run Integrity for Long Resumable Fetches

**Companion:** `earthdata-streaming-checkpoints` owns what to persist and how -
the checkpoint contract, sufficient statistics, reuse validation, and the
credential and concurrency specifics of NASA Earthdata and NSIDC archives. This
skill is about whether the run itself behaves: what it fetches first, what it
retries, and what it admits when it fails.

**Core principle: a partial run is the normal outcome, not the failure case.** An
hours-long fetch will be interrupted, re-scoped, or hit a bad minute at the
archive. What matters is that the state left on disk is usable as far as it goes
and honest about how far that is.

Throughout, the *unit* is whatever the run resumes at — a water year, a month, a
tile. Retries happen below it; absence is reported at it.

## Schedule so the first units are the ones that carry the claim

Order decides what an interrupted run is worth. **Fetch descending from the most
recent unit.** Ascending is a property of how ranges are written, not of the
question being asked.

A run walking a 46-year record ascending holds, after an hour of fetching, only
its six oldest years, while the two years the analysis is about arrive last. Such
a partial run answers nothing, which is the opposite of what resumability is for.
Descending, the recent years land within minutes and each further unit deepens
the climatology from the end where the comparison is most relevant.

An intermediate rule of "feature years first, then most recent to oldest" was
superseded by plain descending, which already puts those years first.

## Retry only what a retry can fix

| Response | Retry | Why |
|---|---|---|
| 429, 500, 502, 503, 504 | Yes, with backoff | Throttling or a server fault; the identical request succeeds later |
| Dropped connection, read timeout | Yes, with backoff | A dropped connection is not a missing granule; treating it as one silently shortens the record |
| 404 | **No** | The granule name or the production stream is wrong. Four attempts cannot fix a wrong URL — they only slow the failure down |

The two mistakes cost differently. Retrying the un-retryable burns attempts and
delays the real diagnosis. Failing to retry the retryable loses a whole unit: one
HTTP 500 on a single day destroyed an entire water year, and it was one of the
two near-miss extreme years the figures existed to show. **Retry the request that
failed**, so one bad second costs a retry rather than the unit enclosing it.

Apply the policy on **every** access path. A policy that covers the reference
reader and not the sibling model fetch loses a unit to the path it does not
cover.

**Name the fault you actually saw.** A fetch that reports every non-200 as "wrong
production stream" is right for a 404 and wrong for a 500, and sends the next
debugger into stream-resolution logic for an archive having a bad moment. Report
addressing faults and server faults separately.

## No failure may be silent

Absence produces no log line, so a run with per-unit logging and a zero exit
status can still be short a unit.

**Never swallow a per-day exception.** A day-level `except` absorbed an
`AttributeError` and turned an entire year into NaN with no error at all. Collect
failures and report them.

**End the run by reconciling intent against disk.** Compare the units the run
meant to produce against the units present, and state plainly which are absent.
Noticing a gap must not depend on someone reading a directory listing.

## Type the empty cells

A missing reference and a failed fetch write an identical empty value, and that
distinction decides whether a short record is a property of the data or a
property of the run. The established rule that a null must say which kind of null
it is (see `snow-bias-statistics-and-figures`) applies to the fetcher's own
output: carry a per-row status — `ok`, `no_reference`, `fetch_failed` — into the
**written record**, not only into the log.

In one validation run 32 days had no value: 18 were a documented all-fill
interval in the archive, 14 were transient disconnections. Undifferentiated they
read as a single 32-day data gap. After retries the count fell to exactly 18,
which matched an independently stated validation gate.

## Build the connection pool once per process

Authenticated sessions are per thread, so they die with the pool. A fresh
16-thread pool per water year made every thread repeat the Earthdata OAuth
redirect handshake for every year; measured throughput was about two minutes per
water year against an expected forty-five seconds. Let the pool live for the
process, and the handshake is paid once per thread for the whole run.

## Re-scoping: stash, verify, keep the record contiguous

When a scope change makes finished units surplus, **move them aside rather than
delete them**; scope changes back. Six stashed year-slabs, verified against the
current storage code and their expected array shape before being trusted, saved
about eight minutes of refetching when the range was restored. A stashed unit is
not a validated one — verify before reuse.

Move them out of the *active record*, not merely out of the plan. Leaving
1981-1986 beside 2000-2026 puts a thirteen-year hole in the middle of the record,
and a climatological mean over a gappy span is not a climatology. A record on
disk is contiguous, or it is explicitly labelled as not.

## Red flags

- "It finished without an exception, so the record is complete."
- "I'll start at the beginning of the record and let it run."
- "It's a network error — retry everything." *(Including the 404 that will never
  succeed.)*
- "The failures are all in the log." *(The log is not attached to the data.)*
- "Those days just have no data." *(Do you know that, or did the fetch fail?)*
- "Only one day out of 365 failed." *(If the unit is the year, the year failed.)*
