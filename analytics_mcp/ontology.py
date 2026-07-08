"""Entity ontology and the entity x capability coverage index.

Both were designed in v1 of the transcript and silently dropped in v2's
refactor, which left Stage 2 comparing raw strings like ``"brand.cava"``
against nothing. They are restored here as *data-plane* artifacts:

* user-agnostic (cacheable globally, like the catalog),
* separately versioned (coverage snapshots churn far faster than catalog
  definitions -- daily-ish vs. quarterly-ish), and
* consulted by Stage 2 to answer "is there data?", never "is it paid for?".

Coverage answers a different question than entitlement. The daypart
dimension can be fully covered in the data for CAVA while absent from a
workspace manifest, and vice versa. Conflating those two axes was the root
confusion the two-stage split exists to untangle.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .ids import CapabilityId, DimensionId, EntityId, EntityKind, MetricId


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityRecord:
    id: EntityId
    canonical_name: str
    kind: EntityKind
    aliases: frozenset[str] = frozenset()


@dataclass(frozen=True)
class EntityResolution:
    """Result of resolving one free-text name.

    ``matches`` carries zero (unresolved), one (resolved), or several
    (ambiguous) records. Ambiguity is representable on purpose: a resolver
    that silently picks a winner is a resolver that quietly lies.
    """

    query: str
    matches: tuple[EntityRecord, ...]

    @property
    def resolved(self) -> EntityRecord | None:
        return self.matches[0] if len(self.matches) == 1 else None


@dataclass(frozen=True)
class EntityIndex:
    """Exact-match resolver over canonical names and aliases.

    Sample-grade on purpose: production resolution is a search service with
    ranking and typo tolerance. The *shape* of the answer (EntityResolution)
    is the part that matters for the MCP contract.
    """

    snapshot_version: str
    entities: Mapping[EntityId, EntityRecord] = field(default_factory=dict)

    def resolve(self, names: Iterable[str]) -> tuple[EntityResolution, ...]:
        results: list[EntityResolution] = []
        for name in names:
            needle = name.casefold().strip()
            matches = tuple(
                sorted(
                    (
                        record
                        for record in self.entities.values()
                        if record.canonical_name.casefold() == needle
                        or needle
                        in {alias.casefold() for alias in record.aliases}
                    ),
                    key=lambda record: record.id,
                )
            )
            results.append(EntityResolution(query=name, matches=matches))
        return tuple(results)

    def get(self, entity: EntityId) -> EntityRecord | None:
        return self.entities.get(entity)


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


class CapabilityAvailability(str, enum.Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class SampleQuality(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    MEDIUM_HIGH = "medium_high"
    HIGH = "high"


class GeographyCoverage(str, enum.Enum):
    NONE = "none"
    LIMITED = "limited"
    BROAD = "broad"
    FULL = "full"


#: Qualities that should surface as analyst-facing warnings.
WEAK_SAMPLE_QUALITIES: frozenset[SampleQuality] = frozenset(
    {SampleQuality.LOW, SampleQuality.MEDIUM}
)


@dataclass(frozen=True)
class CoverageSummary:
    history_depth_months: int
    sample_quality: SampleQuality
    geography_coverage: GeographyCoverage
    #: Free-text methodology notes, surfaced as INFO diagnostics.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityCapabilityCoverage:
    """What the data actually supports for one entity under one capability.

    A capability may support the daypart dimension in general while a given
    entity's panel is too thin to slice it. This record is where that
    difference lives.
    """

    entity_id: EntityId
    capability_id: CapabilityId
    availability: CapabilityAvailability
    supported_metric_ids: frozenset[MetricId]
    supported_dimension_ids: frozenset[DimensionId]
    coverage: CoverageSummary


@dataclass(frozen=True)
class CoverageIndex:
    """Snapshot of coverage records, keyed by (entity, capability).

    Linear scan is fine at sample scale; production would materialize this
    as an indexed store keyed the same way, refreshed per data drop.
    """

    snapshot_version: str
    records: tuple[EntityCapabilityCoverage, ...] = ()

    def get(
        self, entity: EntityId, capability: CapabilityId
    ) -> EntityCapabilityCoverage | None:
        for record in self.records:
            if record.entity_id == entity and record.capability_id == capability:
                return record
        return None
