"""Access projection: entitlements in, clean workspace manifest out.

This is the layer that lets Stage 2 stay boring. It runs in middleware,
above both MCP servers, and produces the ``WorkspaceManifest`` -- the only
lens through which Stage 2 ever sees scarcity. No offers, no states, no
commercial branching survive past this point.

Projector corrections vs. the transcript:

* The v2 projector contained ``dimension_ids | (capability.dimension_ids &
  dimension_ids)`` -- a set-algebra no-op (X | (Y & X) == X) left over from
  an abandoned idea. Gone. The rule it was groping for is simply: grants
  are explicit; capability support is checked at validation time.
* Metrics are granted explicitly (see catalog module docstring), not
  derived from capabilities.
* View gating generalizes v2's addon-flag into requirements: a view lights
  up iff its capability, required dimensions, and required metrics are all
  present in the manifest. Same daypart behavior, no special case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import GlobalCatalog, ViewDefinition
from .entitlements import EntitlementResolver, EntitlementShape
from .ids import (
    AddOnId,
    CapabilityId,
    DimensionId,
    MetricId,
    OrgId,
    PackageId,
    UserId,
    ViewId,
)


@dataclass(frozen=True)
class WorkspaceManifest:
    """The effective workspace: everything a Stage 2 call may touch.

    Contains no notion of "locked". Resources absent from the manifest are,
    from Stage 2's point of view, simply not part of this workspace.
    """

    manifest_id: str
    catalog_version: str
    package_ids: frozenset[PackageId]
    addon_ids: frozenset[AddOnId]
    capability_ids: frozenset[CapabilityId]
    metric_ids: frozenset[MetricId]
    dimension_ids: frozenset[DimensionId]
    view_ids: frozenset[ViewId]

    def has_capability(self, capability: CapabilityId) -> bool:
        return capability in self.capability_ids

    def has_metric(self, metric: MetricId) -> bool:
        return metric in self.metric_ids

    def has_dimension(self, dimension: DimensionId) -> bool:
        return dimension in self.dimension_ids

    def has_view(self, view: ViewId) -> bool:
        return view in self.view_ids


class ManifestProjector:
    """Pure function object: (catalog, entitlement shape) -> manifest."""

    def __init__(self, catalog: GlobalCatalog) -> None:
        self.catalog = catalog

    def build(self, shape: EntitlementShape) -> WorkspaceManifest:
        capability_ids: set[CapabilityId] = set()
        metric_ids: set[MetricId] = set()
        dimension_ids: set[DimensionId] = set()
        candidate_view_ids: set[ViewId] = set()

        for package_id in shape.package_ids:
            package = self.catalog.packages[package_id]
            capability_ids |= package.included_capability_ids
            metric_ids |= package.included_metric_ids
            dimension_ids |= package.included_dimension_ids
            candidate_view_ids |= package.included_view_ids

        for addon_id in shape.addon_ids:
            addon = self.catalog.addons[addon_id]
            capability_ids |= addon.added_capability_ids
            metric_ids |= addon.added_metric_ids
            dimension_ids |= addon.added_dimension_ids
            candidate_view_ids |= addon.added_view_ids

        view_ids = {
            view_id
            for view_id in candidate_view_ids
            if self._view_lights_up(
                self.catalog.views[view_id],
                capability_ids,
                dimension_ids,
                metric_ids,
            )
        }

        fingerprint = shape.fingerprint(self.catalog.version)
        return WorkspaceManifest(
            manifest_id=f"manifest.{fingerprint[:16]}",
            catalog_version=self.catalog.version,
            package_ids=shape.package_ids,
            addon_ids=shape.addon_ids,
            capability_ids=frozenset(capability_ids),
            metric_ids=frozenset(metric_ids),
            dimension_ids=frozenset(dimension_ids),
            view_ids=frozenset(view_ids),
        )

    @staticmethod
    def _view_lights_up(
        view: ViewDefinition,
        capability_ids: set[CapabilityId],
        dimension_ids: set[DimensionId],
        metric_ids: set[MetricId],
    ) -> bool:
        return (
            view.required_capability_id in capability_ids
            and view.required_dimension_ids <= dimension_ids
            and view.required_metric_ids <= metric_ids
        )


@dataclass
class ManifestCache:
    """Keyed by entitlement fingerprint. In production: Redis, key
    ``manifest:{catalog_version}:{fingerprint}``, invalidated by version
    bump rather than by deletion. Orgs with identical grants share entries
    (the point of the fingerprint fix)."""

    _cache: dict[str, WorkspaceManifest] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get_or_build(
        self, shape: EntitlementShape, projector: ManifestProjector
    ) -> WorkspaceManifest:
        key = shape.fingerprint(projector.catalog.version)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        manifest = projector.build(shape)
        self._cache[key] = manifest
        return manifest

    def __len__(self) -> int:
        return len(self._cache)


@dataclass(frozen=True)
class WorkspaceContext:
    """What a Stage 2 handler receives. Nothing else rides along."""

    org_id: OrgId
    user_id: UserId
    manifest: WorkspaceManifest


def build_workspace_context(
    user: UserId,
    org: OrgId,
    resolver: EntitlementResolver,
    projector: ManifestProjector,
    cache: ManifestCache,
) -> WorkspaceContext:
    """The middleware, as one honest function: resolve grants, project (or
    fetch) the manifest, hand Stage 2 a context it cannot argue with."""
    shape = resolver.resolve(user, org)
    manifest = cache.get_or_build(shape, projector)
    return WorkspaceContext(org_id=org, user_id=user, manifest=manifest)
