"""Execution gate -- the vault door, reduced to its invariant.

The transcript repeatedly asserts "the executor still checks entitlements
before paid execution; that remains the vault door" and then never models
it. This stub models exactly the invariant and nothing else (billing,
credits, quotas, and result envelopes are out of the chosen scope):

    Never trust a compiled plan's manifest. Re-project from CURRENT grants
    at execution time and re-check membership. Compiled plans are cacheable
    promises about *shape*, not about *permission*.

Note the check is membership-based, not ``manifest_id`` equality: an org
that has gained grants since compile time still passes (their new manifest
is a superset), while a revoked org fails with a precise reason.

Provenance: ``check_execution`` assumes the plan object was resolved from
the server-side ``PlanStore``. Anything arriving over a process boundary
must go through ``check_execution_by_id`` -- a caller may *name* a plan,
never *describe* one; otherwise every field on it, including
``executable``, is caller-asserted.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .ids import PlanId
from .projection import WorkspaceManifest
from .workspace import CompiledPlan, PlanStore


class DenialReason(str, enum.Enum):
    PLAN_NOT_FOUND = "plan_not_found"
    PLAN_NOT_EXECUTABLE = "plan_not_executable"
    STALE_CATALOG = "stale_catalog"
    ENTITLEMENT_REVOKED = "entitlement_revoked"


@dataclass(frozen=True)
class ExecutionGateDecision:
    allowed: bool
    reason: DenialReason | None = None
    detail: str = ""


def check_execution(
    plan: CompiledPlan,
    current_manifest: WorkspaceManifest,
    current_catalog_version: str,
) -> ExecutionGateDecision:
    """Pure gate function; the executor calls this after middleware has
    re-projected the manifest from current grants."""
    if not plan.executable:
        return ExecutionGateDecision(
            allowed=False,
            reason=DenialReason.PLAN_NOT_EXECUTABLE,
            detail="plan failed validation at compile time",
        )

    if plan.catalog_version != current_catalog_version:
        return ExecutionGateDecision(
            allowed=False,
            reason=DenialReason.STALE_CATALOG,
            detail=(
                f"plan compiled against {plan.catalog_version}, current is "
                f"{current_catalog_version}; recompile"
            ),
        )

    missing: list[str] = []
    if not current_manifest.has_capability(plan.draft.capability_id):
        missing.append(str(plan.draft.capability_id))
    for metric in plan.draft.metric_ids:
        if not current_manifest.has_metric(metric):
            missing.append(str(metric))
    for selected in plan.draft.filters:
        if not current_manifest.has_dimension(selected.dimension_id):
            missing.append(str(selected.dimension_id))

    if missing:
        return ExecutionGateDecision(
            allowed=False,
            reason=DenialReason.ENTITLEMENT_REVOKED,
            detail="no longer in workspace: " + ", ".join(sorted(set(missing))),
        )

    return ExecutionGateDecision(allowed=True)


def check_execution_by_id(
    plan_id: PlanId,
    store: PlanStore,
    current_manifest: WorkspaceManifest,
    current_catalog_version: str,
) -> ExecutionGateDecision:
    """Boundary-facing form: resolve provenance through the server-side
    store, then apply the invariant."""
    plan = store.get(plan_id)
    if plan is None:
        return ExecutionGateDecision(
            allowed=False,
            reason=DenialReason.PLAN_NOT_FOUND,
            detail=f"no compiled plan registered under {plan_id}",
        )
    return check_execution(plan, current_manifest, current_catalog_version)
