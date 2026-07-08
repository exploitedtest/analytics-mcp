"""End-to-end walkthrough of the canonical transcript scenario:

    "Is CAVA gaining lunch share against Chipotle in urban markets?"

Run:  python3 demo.py
"""

from __future__ import annotations

from analytics_mcp import (
    ManifestCache,
    ManifestProjector,
    InMemoryEntitlementResolver,
    Stage1CommerceStub,
    Stage2Workspace,
    build_workspace_context,
    check_execution,
    check_execution_by_id,
)
from analytics_mcp.ids import plan_id
from analytics_mcp.sample_data import (
    ADDON_DAYPART,
    ENT_CAVA,
    ENT_CHIPOTLE,
    ENT_SWEETGREEN,
    CAP_STORE_OVERLAP,
    CAP_WEB_ATTENTION,
    ORG_DEMO,
    ORG_OTHER,
    USER_ANALYST,
    build_catalog,
    build_coverage_index,
    build_entity_index,
    build_grant_store,
    build_relevance_rules,
)

QUESTION = "Is CAVA gaining lunch share against Chipotle in urban markets?"


def section(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def main() -> None:
    catalog = build_catalog()
    entity_index = build_entity_index()
    coverage_index = build_coverage_index()
    grants = build_grant_store()

    resolver = InMemoryEntitlementResolver(grants)
    projector = ManifestProjector(catalog)
    cache = ManifestCache()
    stage2 = Stage2Workspace(catalog, entity_index, coverage_index)
    stage1 = Stage1CommerceStub(catalog, build_relevance_rules())

    section("1. Middleware: entitlements -> manifest (shared cache)")
    ctx = build_workspace_context(USER_ANALYST, ORG_DEMO, resolver, projector, cache)
    ctx_other = build_workspace_context(USER_ANALYST, ORG_OTHER, resolver, projector, cache)
    print(f"org.demo manifest:  {ctx.manifest.manifest_id}")
    print(f"org.other manifest: {ctx_other.manifest.manifest_id}")
    print(
        f"cache entries={len(cache)} hits={cache.hits} misses={cache.misses}"
        "  <- identical grants share one projection"
    )

    section("2. Stage 2 inventory (what this workspace can do)")
    for cap in stage2.list_capabilities(ctx):
        dims = ", ".join(sorted(cap.usable_dimension_ids)) or "none"
        print(f"capability: {cap.definition.name}")
        print(f"  usable dimensions: {dims}")
    print("views: " + ", ".join(v.label for v in stage2.list_views(ctx)))

    section("3. Resolve entities, draft from the question")
    for r in stage2.resolve_entities(["CAVA", "CMG"]):
        best = r.resolved.canonical_name if r.resolved else "??"
        print(f"  {r.query!r} -> {best}")
    draft = stage2.draft_plan(ctx, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,))
    print("draft filters (intent, not permission):")
    for f in draft.filters:
        print(f"  {f.dimension_id} = {f.value}")

    section("4. Validate: the workspace boundary answers")
    validation = stage2.validate_plan(ctx, draft)
    print(f"status: {validation.status.value}")
    for d in validation.diagnostics:
        print(f"  [{d.severity.value:7}] {d.code.value}: {d.message}")
    print(f"blocking subjects: {validation.blocking_subject_ids}")

    section("5. The bridge: Stage 1 interprets the same diagnostics")
    for s in stage1.explain_blockers(
        resolver.resolve(USER_ANALYST, ORG_DEMO), validation.diagnostics
    ):
        print(f"  [blocker] {s.name} ({s.impact.value}): {s.reason}")
    for s in stage1.recommend_addons(
        resolver.resolve(USER_ANALYST, ORG_DEMO),
        next(iter(catalog.packages)),
        QUESTION,
    ):
        print(f"  [keyword] {s.name} ({s.impact.value}): {s.reason}")

    section("6. Grant Daypart Analysis -> new fingerprint, new manifest")
    grants.grant_addon(ORG_DEMO, ADDON_DAYPART)
    ctx2 = build_workspace_context(USER_ANALYST, ORG_DEMO, resolver, projector, cache)
    print(f"manifest: {ctx.manifest.manifest_id} -> {ctx2.manifest.manifest_id}")
    print("views now: " + ", ".join(v.label for v in stage2.list_views(ctx2)))
    validation2 = stage2.validate_plan(ctx2, draft)
    print(f"revalidated status: {validation2.status.value}")
    for d in validation2.diagnostics:
        print(f"  [{d.severity.value:7}] {d.code.value}: {d.message}")

    section("7. Compile: deterministic id, trace, caveats")
    plan = stage2.compile_plan(ctx2, draft)
    again = stage2.compile_plan(ctx2, draft)
    print(f"plan id: {plan.id} (recompile -> {again.id}, equal={plan.id == again.id})")
    print(f"executable: {plan.executable}")
    for step in plan.trace:
        print(f"  {step.step}. {step.action}: {step.detail}")

    section("8. Vault door: execution re-checks CURRENT grants")
    decision = check_execution(plan, ctx2.manifest, catalog.version)
    print(f"execute with daypart owned: allowed={decision.allowed}")
    grants.revoke_addon(ORG_DEMO, ADDON_DAYPART)
    ctx3 = build_workspace_context(USER_ANALYST, ORG_DEMO, resolver, projector, cache)
    decision = check_execution(plan, ctx3.manifest, catalog.version)
    print(
        f"after revocation: allowed={decision.allowed} "
        f"reason={decision.reason.value if decision.reason else None} "
        f"({decision.detail})"
    )
    decision = check_execution_by_id(
        plan_id("plan.forged00000000"),
        stage2.plan_store,
        ctx3.manifest,
        catalog.version,
    )
    print(
        f"forged plan id:   allowed={decision.allowed} "
        f"reason={decision.reason.value if decision.reason else None} "
        "<- plans cross boundaries as names, never descriptions"
    )

    section("9. Compatibility previews (data vs. workspace, kept distinct)")
    preview = stage2.preview_compatibility(
        ctx3, CAP_WEB_ATTENTION, (ENT_CAVA, ENT_CHIPOTLE)
    )
    print(f"web attention, CAVA+Chipotle: {preview.status.value}")
    preview = stage2.preview_compatibility(
        ctx3, CAP_WEB_ATTENTION, (ENT_CAVA, ENT_SWEETGREEN)
    )
    print(f"web attention, +Sweetgreen:   {preview.status.value} (data gap)")
    preview = stage2.preview_compatibility(
        ctx3, CAP_STORE_OVERLAP, (ENT_CAVA, ENT_CHIPOTLE)
    )
    print(f"store overlap:                {preview.status.value} (workspace gap)")
    for s in stage1.explain_blockers(
        resolver.resolve(USER_ANALYST, ORG_DEMO), preview.diagnostics
    ):
        print(f"  bridge suggests: {s.name} -- {s.reason}")


if __name__ == "__main__":
    main()
