"""Exception taxonomy.

The distinction that matters operationally is between an error that must abort
the whole campaign (the product changed under us, or the domain is not covered)
and one that should fail a single month and let the rest proceed.
"""

from __future__ import annotations

__all__ = [
    "CheckpointInvalid",
    "DomainCoverageError",
    "FscaError",
    "GranuleMissingError",
    "SchemaError",
    "TransientSourceError",
]


class FscaError(Exception):
    """Base class for every error this package raises deliberately."""


class SchemaError(FscaError):
    """A product's schema is not what the scientific contract expects.

    Fatal for the campaign: silently continuing would compare the wrong thing.
    """


class DomainCoverageError(FscaError):
    """The configured tiles do not fully cover every target cell.

    Fatal unless explicitly accepted, because an under-covered cell still passes
    the support threshold while its mean is computed from a biased subregion.
    """


class GranuleMissingError(FscaError):
    """A granule that should exist does not. Fails its month."""


class TransientSourceError(FscaError):
    """A retryable transport failure - refused connection, reset, timeout."""


class CheckpointInvalid(FscaError):
    """A checkpoint failed validation and must be recomputed."""
