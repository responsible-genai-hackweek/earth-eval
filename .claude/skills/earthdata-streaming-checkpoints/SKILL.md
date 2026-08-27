---
name: earthdata-streaming-checkpoints
description: Use when building or running a long multi-year Earth-science data campaign - NASA Earthdata or NSIDC access, thousands of daily granules, parallel worker processes, FTP connection limits, resumable runs, atomic monthly checkpoints - or when deciding whether a requested statistic can be rebuilt from saved sufficient statistics instead of re-downloading raw data.
---

# Streaming Earthdata Campaigns with Sufficient-Statistic Checkpoints

**Companion:** `resumable-fetch-run-integrity` covers how the run behaves -
scheduling so a partial run still answers the question, which failures are worth
retrying, and never letting a missing datum and a failed fetch look alike.

**REQUIRED BACKGROUND:** read the `snow-hydrology-fsca-evaluation` skill and its
scientific contract before changing anything that affects what is compared.
This skill is about getting 5,113 days of data through the machine without
losing reproducibility.

**Core principle: raw data is transient; sufficient statistics are the
artifact.** A day's granules exist inside one worker's temporary directory for
seconds. What survives is a validated monthly checkpoint of additive sums —
enough to rebuild every downstream number exactly, and small enough to commit.

## Fail fast, before the campaign

Authenticate and decode one tiny model subset *before* any bulk download.
Missing credentials, a changed schema, or a moved endpoint must cost seconds,
not hours. Preflight both ends of the record and any known filename-stream
transition inside it — a resolver that is right for 2011 and wrong for 2020 will
otherwise fail 90% of the way through.

## Credentials

Read them through the provider's own resolution (`~/.netrc` or an environment
token). Never accept a credential as a CLI argument, never log it, never write
it into a results file, a checkpoint header, or a test fixture.

Two things about Earthdata Login break otherwise-correct code:

- **The login redirect crosses hosts, and HTTP clients drop the Authorization
  header when they do.** The symptom is a bare 401 on a request that should have
  worked. Re-attach credentials deliberately for the archive and login hosts.
- **HEAD does not trigger the login flow.** A HEAD returns 401 with no redirect
  history, while the same URL fetched with GET completes the hop and returns
  206. Get a file's size from `Content-Range` on a one-byte ranged GET instead -
  it costs the same one request and works on a cold session.

## Concurrency: two independent limits

| Resource | Limit | Why |
|----------|-------|-----|
| Worker processes | 16 | Bounds memory; lets the OS schedule across performance cores |
| Shared FTP slots | 8 | The archive rejects ~10 concurrent connections from one IP |

These are not the same number and must not be unified. **Do not raise the FTP
slot count to match the worker count** — the limiting resource is the archive's
connection policy, not local CPU. Enforce the slot cap with a semaphore shared
by *all* processes, and back off staggered (5/10/20 s) on a 421 response,
requeuing a failed month behind the others before its second attempt.

Set `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, and
`VECLIB_MAXIMUM_THREADS=1` **before NumPy is imported**, or 16 processes each
spawn a nested thread team and thrash. On Apple silicon, 16 normal-priority
processes is the portable way to get the performance cores used; there is no
supported P-core affinity API.

## Task unit and checkpoint contract

Use the **calendar month** as both the task unit and the minimum recomputation
unit. A worker builds one authenticated session and one static regridding map,
then processes dates sequentially: subset the model, download the reference
tiles into a private temporary directory, reduce, unlink immediately, accumulate.

A checkpoint stores additive sufficient statistics — `sum_w`, `sum_w_error`,
`sum_w_abs_error`, `sum_w_reference`, valid/expected/observed pixel counts, and
day counts — per cell **and** a domain row. Never store a pre-averaged metric as
the primary record: derived metrics cannot be re-combined, sums can.

Nothing else is a checkpoint. Not daily tables, not collocated arrays, not
cached granules, not a partial month.

**Write atomically:** unique temporary file → flush → `fsync` → atomic replace.
A power loss must never turn a partial file into a valid month.

## Reuse validation

Load a checkpoint only if *all* pass; otherwise report it and recompute:

1. Exact column schema and stable row order.
2. Configuration fingerprint (hash of the scientific contract terms) matches.
3. Cell coordinates, indices, and stable ids match.
4. Calendar-day count is correct for that month.
5. Counts are nonnegative and internally consistent.
6. `abs(bias) <= MAE`, and stored metrics agree with the stored sums.
7. The domain row reconstructs from the per-cell rows.

## Reconstruct before you re-download

Before scheduling any reprocessing, ask whether the requested quantity is a
function of statistics already saved. Monthly, seasonal, annual, and
climatological groupings, and per-cell or domain pooling, all rebuild exactly
from the stored sums. Re-download only when a required sufficient statistic is
genuinely absent or the contract itself changed — and say which of the two.

## Interruptible runs

A runtime deadline should stop *scheduling* new months and let in-flight months
finish their atomic writes; the command therefore overruns by up to one month's
work, which is correct. Workers ignore `SIGINT` so the parent can stop
submission cleanly. Print an explicit "paused cleanly" line — that, not the
prompt returning, is the signal it is safe to shut down. Rerunning the same
command validates existing checkpoints and schedules only what is missing.

## Common mistakes

- Caching granules "to save time later" — it does not resume anything a
  checkpoint cannot, and it leaks raw data into the repo.
- Averaging monthly metrics instead of combining sums.
- A per-worker retry policy with no global connection cap.
- Treating a 421 as fatal, or as an infinite-retry no-op.
- Writing final aggregates before every checkpoint validates.
- Committing granules, temporary subsets, caches, or build metadata.
