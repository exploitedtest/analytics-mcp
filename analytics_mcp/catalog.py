"""Global semantic catalog: user-agnostic, versioned, cache-forever-ish.

This is the "room and furniture" registry: what capabilities, metrics,
dimensions, and views *exist*, and how packages and add-ons bundle them.
Nothing in here knows about users, orgs, grants, or prices. Pricing lives
with commerce (an offer book keyed by package/add-on id), so the catalog
stays a pure semantic artifact that every tenant can share from one cache.

Grant model (a deliberate correction to the transcript's v2):

* Packages and add-ons grant capabilities, metrics, dimensions, and views
  **explicitly and uniformly**. v2 derived workspace metrics from granted
  capabilities, which made metric-level add-ons (v1's "receipt basket
  metrics") inexpressible. Uniform explicit grants restore that degree of
  freedom at the cost of slightly more verbose package definitions.
* Whether a capability *supports* a dimension/metric is semantic (lives
  here); whether a workspace *has* it is entitlement (lives in projection).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .ids import (
    AddOnId,
    CapabilityId,
    DimensionId,
    EntityKind,
    MetricId,
    PackageId,
    ViewId,
)


@dataclass(frozen=True)
class MetricDefinition:
    id: MetricId
    name: str
    description: str


@dataclass(frozen=True)
class DimensionDefinition:
    id: DimensionId
    name: str
    description: str
    #: Global vocabulary. Per-entity value support is a coverage concern
    #: (see ontology.EntityCapabilityCoverage), not a catalog concern.
    allowed_values: frozenset[str]


@dataclass(frozen=True)
class CapabilityDefinition:
    id: CapabilityId
    name: str
    description: str
    supported_entity_kinds: frozenset[EntityKind]
    metric_ids: frozenset[MetricId]
    dimension_ids: frozenset[DimensionId]
    #: Methodology caveats, propagated into compiled plan traces (a v1
    #: trust feature that v2 silently dropped).
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class ViewDefinition:
    id: ViewId
    label: str
    description: str
    required_capability_id: CapabilityId
    required_dimension_ids: frozenset[DimensionId] = frozenset()
    required_metric_ids: frozenset[MetricId] = frozenset()


@dataclass(frozen=True)
class PackageDefinition:
    id: PackageId
    name: str
    description: str
    included_capability_ids: frozenset[CapabilityId]
    included_metric_ids: frozenset[MetricId]
    included_dimension_ids: frozenset[DimensionId]
    included_view_ids: frozenset[ViewId]
    #: Merchandising attachment: which add-ons this package advertises.
    addon_ids: frozenset[AddOnId] = frozenset()


@dataclass(frozen=True)
class AddOnDefinition:
    id: AddOnId
    name: str
    description: str
    added_capability_ids: frozenset[CapabilityId] = frozenset()
    added_metric_ids: frozenset[MetricId] = frozenset()
    added_dimension_ids: frozenset[DimensionId] = frozenset()
    added_view_ids: frozenset[ViewId] = frozenset()


class CatalogIntegrityError(ValueError):
    """Raised when a catalog references ids that do not exist in it."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "catalog failed integrity checks:\n  - " + "\n  - ".join(problems)
        )


@dataclass(frozen=True)
class GlobalCatalog:
    """Versioned, immutable snapshot of the semantic catalog."""

    version: str
    metrics: Mapping[MetricId, MetricDefinition] = field(default_factory=dict)
    dimensions: Mapping[DimensionId, DimensionDefinition] = field(
        default_factory=dict
    )
    capabilities: Mapping[CapabilityId, CapabilityDefinition] = field(
        default_factory=dict
    )
    views: Mapping[ViewId, ViewDefinition] = field(default_factory=dict)
    packages: Mapping[PackageId, PackageDefinition] = field(
        default_factory=dict
    )
    addons: Mapping[AddOnId, AddOnDefinition] = field(default_factory=dict)

    # ------------------------------------------------------------- integrity

    def validate(self) -> None:
        """Referential integrity, run at load time. Executable paranoia:
        every cross-reference must resolve, and views may only require
        dimensions/metrics their capability actually supports."""
        problems: list[str] = []

        for capability in self.capabilities.values():
            for m in sorted(capability.metric_ids):
                if m not in self.metrics:
                    problems.append(f"{capability.id}: unknown metric {m}")
            for d in sorted(capability.dimension_ids):
                if d not in self.dimensions:
                    problems.append(f"{capability.id}: unknown dimension {d}")

        for view in self.views.values():
            cap = self.capabilities.get(view.required_capability_id)
            if cap is None:
                problems.append(
                    f"{view.id}: unknown capability "
                    f"{view.required_capability_id}"
                )
            else:
                for d in sorted(view.required_dimension_ids):
                    if d not in cap.dimension_ids:
                        problems.append(
                            f"{view.id}: requires dimension {d} that "
                            f"{cap.id} does not support"
                        )
                for m in sorted(view.required_metric_ids):
                    if m not in cap.metric_ids:
                        problems.append(
                            f"{view.id}: requires metric {m} that "
                            f"{cap.id} does not support"
                        )

        for package in self.packages.values():
            self._check_grants(
                str(package.id),
                problems,
                package.included_capability_ids,
                package.included_metric_ids,
                package.included_dimension_ids,
                package.included_view_ids,
            )
            for a in sorted(package.addon_ids):
                if a not in self.addons:
                    problems.append(f"{package.id}: unknown add-on {a}")

        for addon in self.addons.values():
            self._check_grants(
                str(addon.id),
                problems,
                addon.added_capability_ids,
                addon.added_metric_ids,
                addon.added_dimension_ids,
                addon.added_view_ids,
            )

        for dimension in self.dimensions.values():
            if not dimension.allowed_values:
                problems.append(f"{dimension.id}: empty allowed_values")

        if problems:
            raise CatalogIntegrityError(problems)

    def _check_grants(
        self,
        owner: str,
        problems: list[str],
        capability_ids: frozenset[CapabilityId],
        metric_ids: frozenset[MetricId],
        dimension_ids: frozenset[DimensionId],
        view_ids: frozenset[ViewId],
    ) -> None:
        for c in sorted(capability_ids):
            if c not in self.capabilities:
                problems.append(f"{owner}: unknown capability {c}")
        for m in sorted(metric_ids):
            if m not in self.metrics:
                problems.append(f"{owner}: unknown metric {m}")
        for d in sorted(dimension_ids):
            if d not in self.dimensions:
                problems.append(f"{owner}: unknown dimension {d}")
        for v in sorted(view_ids):
            if v not in self.views:
                problems.append(f"{owner}: unknown view {v}")

    # -------------------------------------------------------- reverse lookup

    def addons_granting(self, subject_id: str) -> tuple[AddOnDefinition, ...]:
        """Which add-ons would place ``subject_id`` into a workspace.

        This is the reverse index commerce uses to interpret Stage 2
        diagnostics. It lives on the catalog because it is pure structure;
        what to *do* with the answer (offer, hide, escalate) is commerce.
        """
        matches = [
            addon
            for addon in self.addons.values()
            if subject_id in addon.added_capability_ids
            or subject_id in addon.added_metric_ids
            or subject_id in addon.added_dimension_ids
            or subject_id in addon.added_view_ids
        ]
        return tuple(sorted(matches, key=lambda a: a.id))

    def display_name(self, subject_id: str) -> str:
        """Best-effort human label for any catalog id (falls back to the id)."""
        for mapping in (
            self.capabilities,
            self.metrics,
            self.dimensions,
            self.views,
            self.packages,
            self.addons,
        ):
            definition = mapping.get(subject_id)  # type: ignore[arg-type]
            if definition is not None:
                return getattr(
                    definition, "name", getattr(definition, "label", subject_id)
                )
        return subject_id
