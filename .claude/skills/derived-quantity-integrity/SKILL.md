---
name: derived-quantity-integrity
description: Use when a reported number is a function of two or more fields — a ratio, a product, a density, a rate — computed over gridded, binned, or otherwise aggregated data; when a derived value disagrees with an independent implementation of the same specification; or when a summary or reporting step recomputes a value that an earlier step already derived and stored.
---

# Derived Quantity Integrity

**Derive per element, then aggregate.** For a non-linear `f`, `mean(f(x, y))` is
not `f(mean x, mean y)`. The mean of a ratio is not the ratio of means; the mean
of a product is not the product of means.

## The increment over pooling a single field

"Combine sufficient statistics first, then derive the metric" covers a quantity
that is a function of ONE field: sums of that field rebuild any grouping of it.
It does not cover a quantity that is a function of two. No sum of either field
alone rebuilds their product or their ratio, because the term that is lost is
the covariance between the two fields across the elements that were collapsed.

So check *which layer* applies the rule. A metrics layer that derives carefully
from stored aggregates is one layer too late if aggregates are what the
checkpoint stores: the stored inputs are each correct and still cannot answer
the question, and the only way out is discarding the checkpoints and refetching
the record. (`earthdata-streaming-checkpoints` owns the checkpoint contract.)

## What the wrong version looks like

The aggregates are already computed and each one is correct, so
`depth = domain_mean_mass / domain_mean_density` reads as arithmetic on two
valid numbers. Nothing raises, the units work out, the answer is plausible.
This class of bug produces a wrong number, not an error.

The error is not a constant offset that can be corrected afterwards. The
discarded covariance is a property of each case, so the size of the error varies
between cases. Measured on a 1 April snow depth series, the wrong ordering was
1.96x too large in the dry year and 1.21x in the wet one: it did not shift
values, it compressed the contrast the analysis existed to measure, in the
direction that made the anomalous year look less anomalous. The mechanism is
direct — in a dry year, low water equivalent and low density coincide in space,
and that spatial covariance is exactly what the wrong ordering throws away.

## Fixing it so it stays fixed

Compute the derived field per element, take the weighted mean of *that*, and
store it as its own column. Downstream steps read the stored column verbatim and
refuse to guess when it is absent — a summary step that re-derives from whichever
columns sit beside it reintroduces the bug at the reporting layer.

Pin the ordering with three regression tests:

1. the stored derived column is used even when it disagrees with what
   recomputation from its siblings would give;
2. a missing column yields null rather than a reconstruction;
3. a guard asserts the two orderings genuinely produce different numbers, so the
   fix cannot later be undone as an apparent no-op.

The third is the one easiest to skip, and the only one that survives a future
reader who takes the ordering for an accident.

## What agreement does and does not prove

An independently built implementation of the same specification is what surfaced
one such bug: 0.190 m from the pipeline against 0.097 m from the other
implementation, same date, same domain. Use a second implementation whenever one
exists — but it is a circumstance, not a technique to rely on. Two
implementations stop being comparable the moment they are scoped to different
experiments.

Agreement with your OWN earlier output proves much less. A rebuilt value that is
bit-identical to the previous derivation confirms a refactor changed no value —
the right question for a refactor, the wrong question when the earlier value is
what is under suspicion. Verifying that nothing changed cannot detect that
everything was already wrong.

## Red flags

- *"Both stored inputs are correct, so the derived value is correct."*
- *"The non-linearity is small, basically a constant factor."* Measured: 1.96x
  against 1.21x across the two cases being contrasted.
- *"It matches what we computed before."* A refactor check, not a correctness
  check.
- *"The units work out and the number is plausible."* The wrong ordering produces
  both.
- *"I'll re-derive it in the summary step from the columns that are there."*
