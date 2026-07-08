"""Stage 2: the analytical workspace MCP domain.

This module restores the depth of the transcript's v1 design (entity
resolution, capability profiles, coverage, compatibility previews, plan
draft/validate/compile with an inspectable trace) on top of v2's clean
architecture (a projected manifest as the only visibility boundary).

Design rules, enforced structurally and by tests:

* Inputs are ``WorkspaceContext`` plus three shared user-agnostic indexes
  (catalog, entity index, coverage index). Nothing user-decorated is read
  here, so every operation is cacheable by (manifest_id, arguments).
* Scarcity appears only as membership facts ("not in this workspace"),
  carried on diagnostics via ``subject_id``. This module has no concept of
  how a gap might be closed and no vocabulary for it.
* Drafting captures *intent*, not permission -- symmetrically for
  dimensions and metrics: a lunch question yields a daypart filter and the
  capability's full metric set even when the workspace lacks some of them.
  Validation then reports each membership gap precisely. That is how
  analyst intent becomes a structured signal for whoever owns scarcity,
  without this module ever knowing such a consumer exists.
* Every plan compiles to a deterministic content-addressed id, with a
  human-readable trace and propagated methodology caveats (v1's analyst
  trust features).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .catalog import CapabilityDefinition, GlobalCatalog, ViewDefinition
from .diagnostics import (
    Diagnostic,
    DiagnosticCode,
    PlanStatus,
    Severity,
    status_from,
)
from .ids import (
    CapabilityId,
    DimensionId,
    EntityId,
    MetricId,
    PlanId,
    ViewId,
)
from .ontology import (
    CapabilityAvailability,
    CoverageIndex,
    CoverageSummary,
    EntityCapabilityCoverage,
    EntityIndex,
    EntityRecord,
    EntityResolution,
    WEAK_SAMPLE_QUALITIES,
)
from .projection import WorkspaceContext

# --------------------------------------------------------------------------
# Sample-grade intent tables for the demo drafter.
#
# A production drafter is an LLM/planner; these tables exist so the demo and
# tests are deterministic. Values are catalog-consistent by construction and
# the tables are the single documented place where question tokens map to
# dimension values. No other keyword logic hides in this module.
# --------------------------------------------------------------------------

DEFAULT_TIME_WINDOW_VALUE = "trailing_12_months"

DAYPART_TERMS: Mapping[str, str] = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "dinner": "dinner",
}

GEOGRAPHY_TERMS: Mapping[str, str] = {
    "urban": "top_25_urban_dmas",
    "cities": "top_25_urban_dmas",
    "national": "national",
}

TIME_WINDOW_DIMENSION = DimensionId("dimension.time_window")
GEOGRAPHY_DIMENSION = DimensionId("dimension.geography")
DAYPART_DIMENSION = DimensionId("dimension.daypart")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.casefold()))


# --------------------------------------------------------------------------
# Workspace-effective read models
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceCapability:
    """A capability as it exists *in this workspace*: catalog semantics
    intersected with manifest membership."""

    definition: CapabilityDefinition
    usable_metric_ids: frozenset[MetricId]
    usable_dimension_ids: frozenset[DimensionId]


@dataclass(frozen=True)
class EntityCapabilityView:
    """One entity under one workspace capability: manifest ∩ capability ∩
    entity coverage. The three-way intersection is the honest answer to
    'what can I actually slice for CAVA here?'."""

    entity_id: EntityId
    capability_id: CapabilityId
    availability: CapabilityAvailability
    usable_metric_ids: frozenset[MetricId]
    usable_dimension_ids: frozenset[DimensionId]
    coverage: CoverageSummary


@dataclass(frozen=True)
class EntityCapabilityProfile:
    entity: EntityRecord
    items: tuple[EntityCapabilityView, ...]


# --------------------------------------------------------------------------
# Compatibility preview
# --------------------------------------------------------------------------


class CompatibilityStatus(str, Enum):
    COMPATIBLE = "compatible"
    COMPATIBLE_WITH_WARNINGS = "compatible_with_warnings"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True)
class CompatibilityPreview:
    capability_id: CapabilityId
    entity_ids: tuple[EntityId, ...]
    status: CompatibilityStatus
    common_metric_ids: frozenset[MetricId]
    common_dimension_ids: frozenset[DimensionId]
    diagnostics: tuple[Diagnostic, ...]


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FilterSelection:
    dimension_id: DimensionId
    value: str


@dataclass(frozen=True)
class AnalysisPlanDraft:
    objective: str
    primary_entity_id: EntityId
    comparison_entity_ids: tuple[EntityId, ...]
    capability_id: CapabilityId
    metric_ids: tuple[MetricId, ...]
    filters: tuple[FilterSelection, ...]
    #: Output views the caller wants rendered. Missing views degrade the
    #: answer rather than block it, so they validate as warnings.
    requested_view_ids: tuple[ViewId, ...] = ()

    @property
    def all_entity_ids(self) -> tuple[EntityId, ...]:
        return (self.primary_entity_id, *self.comparison_entity_ids)


@dataclass(frozen=True)
class PlanValidationResult:
    status: PlanStatus
    diagnostics: tuple[Diagnostic, ...]
    draft: AnalysisPlanDraft

    @property
    def blocking_subject_ids(self) -> tuple[str, ...]:
        """Deduplicated subject ids from blocking diagnostics -- the machine
        handoff for whichever layer owns the meaning of absence."""
        seen: list[str] = []
        for diagnostic in self.diagnostics:
            if (
                diagnostic.severity is Severity.ERROR
                and diagnostic.subject_id
                and diagnostic.subject_id not in seen
            ):
                seen.append(diagnostic.subject_id)
        return tuple(seen)


@dataclass(frozen=True)
class TraceStep:
    step: int
    action: str
    detail: str


@dataclass(frozen=True)
class CompiledPlan:
    """Deterministic compilation artifact.

    ``id`` is content-addressed over (catalog version, manifest id,
    normalized draft): the same analytical intent in the same workspace
    compiles to the same id, which makes compilation results cacheable and
    execution idempotent-friendly.
    """

    id: PlanId
    draft: AnalysisPlanDraft
    catalog_version: str
    manifest_id: str
    executable: bool
    caveats: tuple[str, ...]
    trace: tuple[TraceStep, ...]
    diagnostics: tuple[Diagnostic, ...]


def _draft_payload(draft: AnalysisPlanDraft) -> dict[str, object]:
    """Normalized, order-insensitive representation used for hashing."""
    return {
        "objective": draft.objective,
        "primary": draft.primary_entity_id,
        "comparisons": sorted(draft.comparison_entity_ids),
        "capability": draft.capability_id,
        "metrics": sorted(draft.metric_ids),
        "filters": sorted(
            [f.dimension_id, f.value] for f in draft.filters
        ),
        "views": sorted(draft.requested_view_ids),
    }


class PlanStore:
    """Server-side registry of compiled plans.

    Provenance rule: compiled plans cross process boundaries as *ids* only.
    An executor must resolve the id through this store (or its production
    equivalent) rather than accept a plan object from a caller -- otherwise
    every field on the plan, including ``executable``, is caller-asserted
    fiction. The content-addressed id does not protect against this: the
    hash has no secret in it, so anyone can mint a self-consistent object.
    """

    def __init__(self) -> None:
        self._plans: dict[PlanId, CompiledPlan] = {}

    def register(self, plan: CompiledPlan) -> None:
        self._plans[plan.id] = plan

    def get(self, plan_id: PlanId) -> CompiledPlan | None:
        return self._plans.get(plan_id)

    def __len__(self) -> int:
        return len(self._plans)


# --------------------------------------------------------------------------
# The Stage 2 service
# --------------------------------------------------------------------------


class Stage2Workspace:
    """Analytical workspace operations over a projected manifest.

    Construction takes the shared, user-agnostic indexes plus the
    server-side plan store. Per-request state arrives exclusively through
    ``WorkspaceContext``.
    """

    def __init__(
        self,
        catalog: GlobalCatalog,
        entity_index: EntityIndex,
        coverage_index: CoverageIndex,
        plan_store: PlanStore | None = None,
    ) -> None:
        self.catalog = catalog
        self.entity_index = entity_index
        self.coverage_index = coverage_index
        self.plan_store = plan_store if plan_store is not None else PlanStore()

    # ------------------------------------------------------------- ontology

    def resolve_entities(
        self, names: Iterable[str]
    ) -> tuple[EntityResolution, ...]:
        """Resolution is data-plane and workspace-independent by design:
        knowing that CAVA exists is not a grant-gated fact."""
        return self.entity_index.resolve(names)

    # ------------------------------------------------------------ inventory

    def list_capabilities(
        self, ctx: WorkspaceContext
    ) -> tuple[WorkspaceCapability, ...]:
        result: list[WorkspaceCapability] = []
        for capability_id in sorted(ctx.manifest.capability_ids):
            definition = self.catalog.capabilities[capability_id]
            result.append(
                WorkspaceCapability(
                    definition=definition,
                    usable_metric_ids=definition.metric_ids
                    & ctx.manifest.metric_ids,
                    usable_dimension_ids=definition.dimension_ids
                    & ctx.manifest.dimension_ids,
                )
            )
        return tuple(result)

    def list_views(self, ctx: WorkspaceContext) -> tuple[ViewDefinition, ...]:
        return tuple(
            self.catalog.views[view_id]
            for view_id in sorted(ctx.manifest.view_ids)
        )

    def get_capability_profiles(
        self, ctx: WorkspaceContext, entity_ids: Sequence[EntityId]
    ) -> tuple[EntityCapabilityProfile, ...]:
        profiles: list[EntityCapabilityProfile] = []
        for eid in entity_ids:
            record = self.entity_index.get(eid)
            if record is None:
                raise KeyError(
                    f"unknown entity {eid!r}; resolve names first via "
                    "resolve_entities"
                )
            items: list[EntityCapabilityView] = []
            for capability_id in sorted(ctx.manifest.capability_ids):
                coverage = self.coverage_index.get(eid, capability_id)
                if coverage is None:
                    continue  # no data row: the capability has nothing here
                definition = self.catalog.capabilities[capability_id]
                items.append(
                    EntityCapabilityView(
                        entity_id=eid,
                        capability_id=capability_id,
                        availability=coverage.availability,
                        usable_metric_ids=(
                            definition.metric_ids
                            & ctx.manifest.metric_ids
                            & coverage.supported_metric_ids
                        ),
                        usable_dimension_ids=(
                            definition.dimension_ids
                            & ctx.manifest.dimension_ids
                            & coverage.supported_dimension_ids
                        ),
                        coverage=coverage.coverage,
                    )
                )
            profiles.append(
                EntityCapabilityProfile(entity=record, items=tuple(items))
            )
        return tuple(profiles)

    # -------------------------------------------------------- compatibility

    def preview_compatibility(
        self,
        ctx: WorkspaceContext,
        capability_id: CapabilityId,
        entity_ids: Sequence[EntityId],
        filters: Sequence[FilterSelection] = (),
    ) -> CompatibilityPreview:
        diagnostics: list[Diagnostic] = []
        entity_tuple = tuple(entity_ids)

        definition = self.catalog.capabilities.get(capability_id)
        if definition is None:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.UNKNOWN_CAPABILITY,
                    f"Unknown capability: {capability_id}",
                    subject_id=str(capability_id),
                )
            )
            return CompatibilityPreview(
                capability_id,
                entity_tuple,
                CompatibilityStatus.NOT_AVAILABLE,
                frozenset(),
                frozenset(),
                tuple(diagnostics),
            )

        if not ctx.manifest.has_capability(capability_id):
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.CAPABILITY_NOT_IN_WORKSPACE,
                    f"{definition.name} is not part of this workspace.",
                    subject_id=str(capability_id),
                )
            )

        coverages: list[EntityCapabilityCoverage] = []
        for eid in entity_tuple:
            record = self.entity_index.get(eid)
            if record is None:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.UNKNOWN_ENTITY,
                        f"Unknown entity: {eid}",
                        subject_id=str(eid),
                    )
                )
                continue
            coverage = self.coverage_index.get(eid, capability_id)
            if (
                coverage is None
                or coverage.availability is CapabilityAvailability.UNAVAILABLE
            ):
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.NO_COVERAGE_FOR_ENTITY,
                        f"{record.canonical_name} has no usable data under "
                        f"{definition.name}.",
                        subject_id=str(eid),
                    )
                )
                continue
            if coverage.availability is CapabilityAvailability.PARTIAL:
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.PARTIAL_COVERAGE,
                        f"{record.canonical_name} has partial coverage under "
                        f"{definition.name}.",
                        subject_id=str(eid),
                    )
                )
            if coverage.coverage.sample_quality in WEAK_SAMPLE_QUALITIES:
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.LOW_SAMPLE_QUALITY,
                        f"{record.canonical_name}: sample quality is "
                        f"{coverage.coverage.sample_quality.value}.",
                        subject_id=str(eid),
                    )
                )
            coverages.append(coverage)

        if any(d.severity is Severity.ERROR for d in diagnostics):
            return CompatibilityPreview(
                capability_id,
                entity_tuple,
                CompatibilityStatus.NOT_AVAILABLE,
                frozenset(),
                frozenset(),
                tuple(diagnostics),
            )

        common_metrics = definition.metric_ids & ctx.manifest.metric_ids
        common_dimensions = (
            definition.dimension_ids & ctx.manifest.dimension_ids
        )
        for coverage in coverages:
            common_metrics &= coverage.supported_metric_ids
            common_dimensions &= coverage.supported_dimension_ids

        for selected in filters:
            diagnostics.extend(
                self._diagnose_filter(
                    ctx, definition, coverages, selected
                )
            )

        if any(d.severity is Severity.ERROR for d in diagnostics):
            status = CompatibilityStatus.NOT_AVAILABLE
        elif any(d.severity is Severity.WARNING for d in diagnostics):
            status = CompatibilityStatus.COMPATIBLE_WITH_WARNINGS
        else:
            status = CompatibilityStatus.COMPATIBLE

        return CompatibilityPreview(
            capability_id,
            entity_tuple,
            status,
            common_metrics,
            common_dimensions,
            tuple(diagnostics),
        )

    # -------------------------------------------------------------- drafting

    def draft_plan(
        self,
        ctx: WorkspaceContext,
        question: str,
        primary_entity_id: EntityId,
        comparison_entity_ids: Sequence[EntityId] = (),
        capability_id: CapabilityId | None = None,
    ) -> AnalysisPlanDraft:
        """Deterministic sample drafter. Captures intent (see module doc):
        filters and metrics reflect the question and the capability's
        semantics even where the workspace lacks them; validation then
        names each gap precisely."""
        if capability_id is None:
            capability_id = self._default_capability(ctx, primary_entity_id)

        definition = self.catalog.capabilities.get(capability_id)
        intended_metrics: tuple[MetricId, ...] = ()
        if definition is not None:
            # Full capability metric set, deliberately NOT intersected with
            # the manifest: a membership gap must surface as a validation
            # diagnostic, or metric-level demand is structurally silenced
            # and metric-granting add-ons become undiscoverable.
            intended_metrics = tuple(sorted(definition.metric_ids))

        tokens = _tokens(question)
        filters: list[FilterSelection] = [
            FilterSelection(TIME_WINDOW_DIMENSION, DEFAULT_TIME_WINDOW_VALUE)
        ]
        for token, value in sorted(GEOGRAPHY_TERMS.items()):
            if token in tokens:
                filters.append(FilterSelection(GEOGRAPHY_DIMENSION, value))
                break
        for token, value in sorted(DAYPART_TERMS.items()):
            if token in tokens:
                filters.append(FilterSelection(DAYPART_DIMENSION, value))
                break

        return AnalysisPlanDraft(
            objective=question,
            primary_entity_id=primary_entity_id,
            comparison_entity_ids=tuple(comparison_entity_ids),
            capability_id=capability_id,
            metric_ids=intended_metrics,
            filters=tuple(filters),
        )

    def _default_capability(
        self, ctx: WorkspaceContext, primary_entity_id: EntityId
    ) -> CapabilityId:
        candidates = sorted(ctx.manifest.capability_ids)
        if not candidates:
            raise ValueError("this workspace has no capabilities")
        primary = self.entity_index.get(primary_entity_id)
        if primary is not None:
            for candidate in candidates:
                definition = self.catalog.capabilities.get(candidate)
                if (
                    definition is not None
                    and primary.kind in definition.supported_entity_kinds
                ):
                    return candidate
        return candidates[0]

    # ------------------------------------------------------------ validation

    def validate_plan(
        self, ctx: WorkspaceContext, draft: AnalysisPlanDraft
    ) -> PlanValidationResult:
        diagnostics: list[Diagnostic] = []

        definition = self.catalog.capabilities.get(draft.capability_id)
        if definition is None:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.UNKNOWN_CAPABILITY,
                    f"Unknown capability: {draft.capability_id}",
                    subject_id=str(draft.capability_id),
                )
            )
            return PlanValidationResult(
                PlanStatus.INVALID, tuple(diagnostics), draft
            )

        if not ctx.manifest.has_capability(draft.capability_id):
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.CAPABILITY_NOT_IN_WORKSPACE,
                    f"{definition.name} is not part of this workspace.",
                    subject_id=str(draft.capability_id),
                )
            )

        known_coverages = self._diagnose_entities(
            definition, draft.all_entity_ids, diagnostics
        )
        self._diagnose_metrics(ctx, definition, draft, known_coverages,
                               diagnostics)
        self._diagnose_filters(ctx, definition, draft.filters,
                               known_coverages, diagnostics)
        self._diagnose_views(ctx, draft.requested_view_ids, diagnostics)

        return PlanValidationResult(
            status_from(diagnostics), tuple(diagnostics), draft
        )

    def _diagnose_entities(
        self,
        definition: CapabilityDefinition,
        entity_ids: Sequence[EntityId],
        diagnostics: list[Diagnostic],
    ) -> list[EntityCapabilityCoverage]:
        coverages: list[EntityCapabilityCoverage] = []
        for eid in entity_ids:
            record = self.entity_index.get(eid)
            if record is None:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.UNKNOWN_ENTITY,
                        f"Unknown entity: {eid}",
                        subject_id=str(eid),
                    )
                )
                continue
            if record.kind not in definition.supported_entity_kinds:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.ENTITY_KIND_NOT_SUPPORTED,
                        f"{definition.name} does not analyze "
                        f"{record.kind.value} entities.",
                        subject_id=str(eid),
                    )
                )
                continue
            coverage = self.coverage_index.get(eid, definition.id)
            if (
                coverage is None
                or coverage.availability is CapabilityAvailability.UNAVAILABLE
            ):
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.NO_COVERAGE_FOR_ENTITY,
                        f"{record.canonical_name} has no usable data under "
                        f"{definition.name}.",
                        subject_id=str(eid),
                    )
                )
                continue
            if coverage.availability is CapabilityAvailability.PARTIAL:
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.PARTIAL_COVERAGE,
                        f"{record.canonical_name} has partial coverage under "
                        f"{definition.name}.",
                        subject_id=str(eid),
                    )
                )
            if coverage.coverage.sample_quality in WEAK_SAMPLE_QUALITIES:
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.LOW_SAMPLE_QUALITY,
                        f"{record.canonical_name}: sample quality is "
                        f"{coverage.coverage.sample_quality.value}.",
                        subject_id=str(eid),
                    )
                )
            for note in coverage.coverage.warnings:
                diagnostics.append(
                    Diagnostic(
                        Severity.INFO,
                        DiagnosticCode.COVERAGE_NOTE,
                        f"{record.canonical_name}: {note}",
                        subject_id=str(eid),
                    )
                )
            coverages.append(coverage)
        return coverages

    def _diagnose_metrics(
        self,
        ctx: WorkspaceContext,
        definition: CapabilityDefinition,
        draft: AnalysisPlanDraft,
        coverages: list[EntityCapabilityCoverage],
        diagnostics: list[Diagnostic],
    ) -> None:
        if not draft.metric_ids:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.NO_METRICS_SELECTED,
                    "A plan needs at least one metric.",
                )
            )
            return
        names = {c.entity_id: c for c in coverages}
        for metric in draft.metric_ids:
            if metric not in self.catalog.metrics:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.UNKNOWN_METRIC,
                        f"Unknown metric: {metric}",
                        subject_id=str(metric),
                    )
                )
                continue
            if metric not in definition.metric_ids:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.METRIC_NOT_SUPPORTED_BY_CAPABILITY,
                        f"{self.catalog.metrics[metric].name} is not produced "
                        f"by {definition.name}.",
                        subject_id=str(metric),
                    )
                )
                continue
            if not ctx.manifest.has_metric(metric):
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.METRIC_NOT_IN_WORKSPACE,
                        f"{self.catalog.metrics[metric].name} is not part of "
                        "this workspace.",
                        subject_id=str(metric),
                    )
                )
                continue
            for coverage in names.values():
                if metric not in coverage.supported_metric_ids:
                    entity = self.entity_index.get(coverage.entity_id)
                    label = entity.canonical_name if entity else str(
                        coverage.entity_id
                    )
                    diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            DiagnosticCode.METRIC_NOT_COVERED_FOR_ENTITY,
                            f"{self.catalog.metrics[metric].name} is not "
                            f"covered for {label}.",
                            subject_id=str(metric),
                        )
                    )

    def _diagnose_filters(
        self,
        ctx: WorkspaceContext,
        definition: CapabilityDefinition,
        filters: Sequence[FilterSelection],
        coverages: list[EntityCapabilityCoverage],
        diagnostics: list[Diagnostic],
    ) -> None:
        seen: set[DimensionId] = set()
        for selected in filters:
            if selected.dimension_id in seen:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.DUPLICATE_DIMENSION_FILTER,
                        f"Dimension filtered twice: {selected.dimension_id}",
                        subject_id=str(selected.dimension_id),
                    )
                )
                continue
            seen.add(selected.dimension_id)
            diagnostics.extend(
                self._diagnose_filter(ctx, definition, coverages, selected)
            )

    def _diagnose_filter(
        self,
        ctx: WorkspaceContext,
        definition: CapabilityDefinition,
        coverages: list[EntityCapabilityCoverage],
        selected: FilterSelection,
    ) -> list[Diagnostic]:
        """Cause-specific filter diagnosis, shared by validation and
        compatibility preview. Order matters: semantic problems first, then
        membership, then data coverage -- so the subject of each diagnostic
        is the *actual* nearest cause. Membership does not short-circuit
        coverage: downstream consumers need both facts to judge whether
        closing a membership gap would actually improve the answer."""
        out: list[Diagnostic] = []
        dimension = self.catalog.dimensions.get(selected.dimension_id)
        if dimension is None:
            out.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.UNKNOWN_DIMENSION,
                    f"Unknown dimension: {selected.dimension_id}",
                    subject_id=str(selected.dimension_id),
                )
            )
            return out
        if selected.dimension_id not in definition.dimension_ids:
            out.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.DIMENSION_NOT_SUPPORTED_BY_CAPABILITY,
                    f"{dimension.name} does not apply to {definition.name}.",
                    subject_id=str(selected.dimension_id),
                )
            )
            return out
        if selected.value not in dimension.allowed_values:
            out.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.INVALID_DIMENSION_VALUE,
                    f"{selected.value!r} is not a valid {dimension.name} "
                    "value.",
                    subject_id=str(selected.dimension_id),
                )
            )
        if not ctx.manifest.has_dimension(selected.dimension_id):
            out.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.DIMENSION_NOT_IN_WORKSPACE,
                    f"{dimension.name} is not part of this workspace.",
                    subject_id=str(selected.dimension_id),
                )
            )
            # No early return: the per-entity coverage facts below must
            # accompany the membership fact (see docstring).
        for coverage in coverages:
            if selected.dimension_id not in coverage.supported_dimension_ids:
                entity = self.entity_index.get(coverage.entity_id)
                label = entity.canonical_name if entity else str(
                    coverage.entity_id
                )
                out.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.DIMENSION_NOT_COVERED_FOR_ENTITY,
                        f"{dimension.name} is not covered for {label}.",
                        subject_id=str(selected.dimension_id),
                    )
                )
        return out

    def _diagnose_views(
        self,
        ctx: WorkspaceContext,
        view_ids: Sequence[ViewId],
        diagnostics: list[Diagnostic],
    ) -> None:
        for vid in view_ids:
            view = self.catalog.views.get(vid)
            if view is None:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        DiagnosticCode.UNKNOWN_VIEW,
                        f"Unknown view: {vid}",
                        subject_id=str(vid),
                    )
                )
            elif not ctx.manifest.has_view(vid):
                # A missing output view degrades the deliverable, it does not
                # block the analysis -- hence WARNING, and a subject_id so the
                # request is recorded precisely.
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        DiagnosticCode.VIEW_NOT_IN_WORKSPACE,
                        f"{view.label} is not part of this workspace.",
                        subject_id=str(vid),
                    )
                )

    # ----------------------------------------------------------- compilation

    def compile_plan(
        self, ctx: WorkspaceContext, draft: AnalysisPlanDraft
    ) -> CompiledPlan:
        validation = self.validate_plan(ctx, draft)
        definition = self.catalog.capabilities.get(draft.capability_id)
        caveats = definition.caveats if definition is not None else ()

        payload = {
            "catalog_version": self.catalog.version,
            "manifest_id": ctx.manifest.manifest_id,
            "draft": _draft_payload(draft),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        plan = CompiledPlan(
            id=PlanId(f"plan.{digest[:16]}"),
            draft=draft,
            catalog_version=self.catalog.version,
            manifest_id=ctx.manifest.manifest_id,
            executable=validation.status is not PlanStatus.INVALID,
            caveats=caveats,
            trace=self._build_trace(ctx, draft, definition, validation),
            diagnostics=validation.diagnostics,
        )
        self.plan_store.register(plan)
        return plan

    def _build_trace(
        self,
        ctx: WorkspaceContext,
        draft: AnalysisPlanDraft,
        definition: CapabilityDefinition | None,
        validation: PlanValidationResult,
    ) -> tuple[TraceStep, ...]:
        """The analyst-facing plan trace (v1 trust feature, restored)."""
        entity_labels = []
        for eid in draft.all_entity_ids:
            record = self.entity_index.get(eid)
            entity_labels.append(
                f"{record.canonical_name} ({eid})" if record else str(eid)
            )
        steps = [
            ("resolve_entities", "; ".join(entity_labels) or "none"),
            (
                "select_capability",
                definition.name if definition else str(draft.capability_id),
            ),
            (
                "apply_filters",
                ", ".join(
                    f"{f.dimension_id}={f.value}" for f in draft.filters
                )
                or "none",
            ),
            ("select_metrics", ", ".join(draft.metric_ids) or "none"),
            (
                "workspace_boundary",
                f"manifest {ctx.manifest.manifest_id}, catalog "
                f"{self.catalog.version}",
            ),
            (
                "assess",
                f"status={validation.status.value}, "
                f"diagnostics={len(validation.diagnostics)}",
            ),
        ]
        if definition is not None and definition.caveats:
            steps.append(("caveats", " | ".join(definition.caveats)))
        return tuple(
            TraceStep(step=i + 1, action=action, detail=detail)
            for i, (action, detail) in enumerate(steps)
        )
