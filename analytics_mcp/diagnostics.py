"""Diagnostics: the shared kernel between Stage 2 and everything else.

The subject_id contract
-----------------------
A ``Diagnostic`` is a *fact* about a plan or a preview, carrying an optional
machine-readable ``subject_id`` (the offending or absent resource id).

This is the entire cross-domain bridge:

* Stage 2 reports ``dimension.daypart is not in this workspace`` -- a fact
  about the manifest, nothing more. Stage 2 does not know whether the gap is
  commercial, contractual, or permanent.
* Stage 1 (commerce) consumes the same diagnostic, reverse-indexes the
  subject_id through the catalog, and decides what -- if anything -- to offer.

Because the bridge is a data contract rather than an import, the two domains
never touch. The codes in ``WORKSPACE_MEMBERSHIP_CODES`` are the only ones a
commercial layer should ever interpret as demand signals; the rest are
semantic or data-plane problems money cannot fix.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Iterable


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(str, enum.Enum):
    """Every diagnostic the model can emit. No ad-hoc string codes."""

    # -- catalog referential problems (caller sent an id we've never heard of)
    UNKNOWN_CAPABILITY = "unknown_capability"
    UNKNOWN_METRIC = "unknown_metric"
    UNKNOWN_DIMENSION = "unknown_dimension"
    UNKNOWN_VIEW = "unknown_view"
    UNKNOWN_ENTITY = "unknown_entity"

    # -- workspace membership (the only scarcity Stage 2 can see)
    CAPABILITY_NOT_IN_WORKSPACE = "capability_not_in_workspace"
    METRIC_NOT_IN_WORKSPACE = "metric_not_in_workspace"
    DIMENSION_NOT_IN_WORKSPACE = "dimension_not_in_workspace"
    VIEW_NOT_IN_WORKSPACE = "view_not_in_workspace"

    # -- semantic compatibility (the ask is malformed regardless of grants)
    ENTITY_KIND_NOT_SUPPORTED = "entity_kind_not_supported"
    METRIC_NOT_SUPPORTED_BY_CAPABILITY = "metric_not_supported_by_capability"
    DIMENSION_NOT_SUPPORTED_BY_CAPABILITY = (
        "dimension_not_supported_by_capability"
    )
    INVALID_DIMENSION_VALUE = "invalid_dimension_value"
    DUPLICATE_DIMENSION_FILTER = "duplicate_dimension_filter"
    NO_METRICS_SELECTED = "no_metrics_selected"

    # -- data-plane coverage (the data itself is thin or absent)
    NO_COVERAGE_FOR_ENTITY = "no_coverage_for_entity"
    PARTIAL_COVERAGE = "partial_coverage"
    LOW_SAMPLE_QUALITY = "low_sample_quality"
    METRIC_NOT_COVERED_FOR_ENTITY = "metric_not_covered_for_entity"
    DIMENSION_NOT_COVERED_FOR_ENTITY = "dimension_not_covered_for_entity"
    COVERAGE_NOTE = "coverage_note"


#: Codes a commercial layer may interpret as demand signals. Everything else
#: is a semantic or data problem and should never become an upsell prompt.
WORKSPACE_MEMBERSHIP_CODES: frozenset[DiagnosticCode] = frozenset(
    {
        DiagnosticCode.CAPABILITY_NOT_IN_WORKSPACE,
        DiagnosticCode.METRIC_NOT_IN_WORKSPACE,
        DiagnosticCode.DIMENSION_NOT_IN_WORKSPACE,
        DiagnosticCode.VIEW_NOT_IN_WORKSPACE,
    }
)


#: Codes indicating the underlying data is thin or absent for a specific
#: metric or dimension (subject_id names that resource). A commercial
#: consumer should treat these as a counterweight to membership gaps with
#: the same subject: a door is only worth its key if the room behind it is
#: furnished.
COVERAGE_GAP_CODES: frozenset[DiagnosticCode] = frozenset(
    {
        DiagnosticCode.METRIC_NOT_COVERED_FOR_ENTITY,
        DiagnosticCode.DIMENSION_NOT_COVERED_FOR_ENTITY,
    }
)


class PlanStatus(str, enum.Enum):
    """Stage 2 plan statuses.

    Deliberately has no ``REQUIRES_UNLOCK`` member: whether a gap can be
    closed commercially is not a fact Stage 2 is allowed to know. A plan
    blocked on workspace membership is simply INVALID here; the shell hands
    the diagnostics to Stage 1, which may turn them into offers.
    """

    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID = "invalid"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: DiagnosticCode
    message: str
    #: Machine-readable id of the offending/absent resource (see module doc).
    subject_id: str | None = None


def status_from(diagnostics: Iterable[Diagnostic]) -> PlanStatus:
    """Fold diagnostics into a plan status. INFO never demotes a plan."""
    status = PlanStatus.VALID
    for diagnostic in diagnostics:
        if diagnostic.severity is Severity.ERROR:
            return PlanStatus.INVALID
        if diagnostic.severity is Severity.WARNING:
            status = PlanStatus.VALID_WITH_WARNINGS
    return status
