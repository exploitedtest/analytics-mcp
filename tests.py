"""Model verification: the transcript's 'compatibility audit', as code.

Run:  python3 tests.py -v
"""

from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path

from analytics_mcp import (
    CatalogIntegrityError,
    CompatibilityStatus,
    CoverageIndex,
    DenialReason,
    Diagnostic,
    DiagnosticCode,
    EntitlementShape,
    GlobalCatalog,
    Impact,
    ManifestCache,
    ManifestProjector,
    InMemoryEntitlementResolver,
    PlanStatus,
    Severity,
    Stage1CommerceStub,
    Stage2Workspace,
    WorkspaceContext,
    build_workspace_context,
    check_execution,
    check_execution_by_id,
)
from analytics_mcp.ids import plan_id as make_plan_id
from analytics_mcp.catalog import (
    CapabilityDefinition,
    DimensionDefinition,
    MetricDefinition,
    ViewDefinition,
)
from analytics_mcp.ids import (
    EntityKind,
    capability_id,
    dimension_id,
    metric_id,
    package_id,
    view_id,
)
from analytics_mcp.sample_data import (
    ADDON_DAYPART,
    ADDON_STORE_OVERLAP,
    ADDON_WEB_ATTENTION,
    CAP_MARKET_SHARE,
    CAP_STORE_OVERLAP,
    CAP_WEB_ATTENTION,
    DIM_DAYPART,
    DIM_GEOGRAPHY,
    DIM_TIME_WINDOW,
    ENT_CAVA,
    ENT_CHIPOTLE,
    ENT_SWEETGREEN,
    MET_AVG_TICKET,
    MET_SPEND_SHARE,
    MET_WEB_ATTENTION,
    MET_YOY_GROWTH,
    ORG_DEMO,
    ORG_OTHER,
    PKG_RESTAURANT_CI,
    USER_ANALYST,
    VIEW_DAYPART_SPLIT,
    VIEW_WEB_ATTENTION,
    build_catalog,
    build_coverage_index,
    build_entity_index,
    build_grant_store,
    build_relevance_rules,
)

QUESTION = "Is CAVA gaining lunch share against Chipotle in urban markets?"
PACKAGE_DIR = Path(__file__).parent / "analytics_mcp"


def build_world():
    catalog = build_catalog()
    grants = build_grant_store()
    resolver = InMemoryEntitlementResolver(grants)
    projector = ManifestProjector(catalog)
    cache = ManifestCache()
    stage2 = Stage2Workspace(
        catalog, build_entity_index(), build_coverage_index()
    )
    stage1 = Stage1CommerceStub(catalog, build_relevance_rules())
    return catalog, grants, resolver, projector, cache, stage2, stage1


class TestIds(unittest.TestCase):
    def test_wrong_prefix_rejected(self):
        with self.assertRaises(ValueError):
            package_id("addon.daypart_analysis")

    def test_empty_suffix_rejected(self):
        with self.assertRaises(ValueError):
            dimension_id("dimension.")


class TestCatalogIntegrity(unittest.TestCase):
    def test_sample_catalog_validates(self):
        build_catalog().validate()  # should not raise

    def test_view_demanding_unsupported_dimension_fails(self):
        m = metric_id("metric.m1")
        d = dimension_id("dimension.d1")
        c = capability_id("capability.x.c1")
        v = view_id("view.v1")
        broken = GlobalCatalog(
            version="catalog.test",
            metrics={m: MetricDefinition(m, "M1", "")},
            dimensions={
                d: DimensionDefinition(d, "D1", "", frozenset({"a"}))
            },
            capabilities={
                c: CapabilityDefinition(
                    c, "C1", "", frozenset({EntityKind.BRAND}),
                    frozenset({m}), frozenset(),  # supports no dimensions
                )
            },
            views={
                v: ViewDefinition(
                    v, "V1", "", c, required_dimension_ids=frozenset({d})
                )
            },
        )
        with self.assertRaises(CatalogIntegrityError):
            broken.validate()


class TestFingerprintAndCache(unittest.TestCase):
    def test_fingerprint_ignores_org_and_roles(self):
        a = EntitlementShape(
            ORG_DEMO, frozenset({"analyst"}),
            frozenset({PKG_RESTAURANT_CI}), frozenset({ADDON_WEB_ATTENTION}),
        )
        b = EntitlementShape(
            ORG_OTHER, frozenset({"admin"}),
            frozenset({PKG_RESTAURANT_CI}), frozenset({ADDON_WEB_ATTENTION}),
        )
        self.assertEqual(a.fingerprint("catalog.v1"), b.fingerprint("catalog.v1"))

    def test_fingerprint_tracks_projection_inputs(self):
        base = EntitlementShape(
            ORG_DEMO, frozenset(), frozenset({PKG_RESTAURANT_CI}), frozenset()
        )
        more = EntitlementShape(
            ORG_DEMO, frozenset(), frozenset({PKG_RESTAURANT_CI}),
            frozenset({ADDON_DAYPART}),
        )
        self.assertNotEqual(
            base.fingerprint("catalog.v1"), more.fingerprint("catalog.v1")
        )
        self.assertNotEqual(
            base.fingerprint("catalog.v1"), base.fingerprint("catalog.v2")
        )

    def test_orgs_with_identical_grants_share_manifest_cache_entry(self):
        _, _, resolver, projector, cache, _, _ = build_world()
        ctx_a = build_workspace_context(
            USER_ANALYST, ORG_DEMO, resolver, projector, cache
        )
        ctx_b = build_workspace_context(
            USER_ANALYST, ORG_OTHER, resolver, projector, cache
        )
        self.assertEqual(ctx_a.manifest.manifest_id, ctx_b.manifest.manifest_id)
        self.assertEqual(len(cache), 1)
        self.assertEqual((cache.hits, cache.misses), (1, 1))


class TestProjection(unittest.TestCase):
    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()
        self.ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )

    def test_base_manifest_contents(self):
        m = self.ctx.manifest
        self.assertEqual(
            m.capability_ids, frozenset({CAP_MARKET_SHARE, CAP_WEB_ATTENTION})
        )
        self.assertEqual(
            m.metric_ids,
            frozenset(
                {MET_SPEND_SHARE, MET_YOY_GROWTH, MET_AVG_TICKET,
                 MET_WEB_ATTENTION}
            ),
        )
        self.assertEqual(
            m.dimension_ids, frozenset({DIM_TIME_WINDOW, DIM_GEOGRAPHY})
        )
        self.assertNotIn(DIM_DAYPART, m.dimension_ids)
        self.assertNotIn(VIEW_DAYPART_SPLIT, m.view_ids)
        self.assertIn(VIEW_WEB_ATTENTION, m.view_ids)

    def test_daypart_grant_lights_up_dimension_and_view(self):
        self.grants.grant_addon(ORG_DEMO, ADDON_DAYPART)
        ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        self.assertIn(DIM_DAYPART, ctx.manifest.dimension_ids)
        self.assertIn(VIEW_DAYPART_SPLIT, ctx.manifest.view_ids)

    def test_view_gating_requires_capability_not_just_dimension(self):
        # Daypart add-on alone (no package): the split view's capability is
        # absent, so the view must not light up.
        shape = EntitlementShape(
            ORG_DEMO, frozenset(), frozenset(), frozenset({ADDON_DAYPART})
        )
        manifest = self.projector.build(shape)
        self.assertIn(DIM_DAYPART, manifest.dimension_ids)
        self.assertEqual(manifest.view_ids, frozenset())


class TestDomainSeparation(unittest.TestCase):
    """Stage 2 and projection must be structurally commerce-free."""

    CLEAN_MODULES = ("workspace.py", "projection.py", "ontology.py")
    FORBIDDEN_IMPORTS = ("commerce", "execution")
    FORBIDDEN_TOKENS = ("unlock", "sku", "price", "Money", "AccessState",
                        "UnlockOffer")

    def test_no_commerce_imports(self):
        for module in self.CLEAN_MODULES:
            source = (PACKAGE_DIR / module).read_text()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for forbidden in self.FORBIDDEN_IMPORTS:
                        self.assertNotIn(
                            forbidden, node.module,
                            f"{module} imports {node.module}",
                        )
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in self.FORBIDDEN_IMPORTS:
                            self.assertNotIn(forbidden, alias.name)

    def test_no_commercial_vocabulary(self):
        for module in self.CLEAN_MODULES:
            source = (PACKAGE_DIR / module).read_text()
            lowered = source.casefold()
            for token in self.FORBIDDEN_TOKENS:
                needle = token.casefold()
                self.assertNotIn(
                    needle, lowered,
                    f"{module} contains commercial vocabulary {token!r}",
                )

    def test_plan_status_has_no_commercial_member(self):
        self.assertEqual(
            {s.value for s in PlanStatus},
            {"valid", "valid_with_warnings", "invalid"},
        )


class TestCanonicalScenario(unittest.TestCase):
    """The lunch-share question, end to end."""

    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()
        self.ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        self.draft = self.stage2.draft_plan(
            self.ctx, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,)
        )

    def test_resolution_handles_aliases_and_misses(self):
        cava, cmg, nope = self.stage2.resolve_entities(
            ["CAVA", "CMG", "Definitely Not A Brand"]
        )
        self.assertEqual(cava.resolved.id, ENT_CAVA)
        self.assertEqual(cmg.resolved.id, ENT_CHIPOTLE)
        self.assertIsNone(nope.resolved)
        self.assertEqual(nope.matches, ())

    def test_draft_captures_intent_beyond_workspace(self):
        self.assertEqual(self.draft.capability_id, CAP_MARKET_SHARE)
        dims = [f.dimension_id for f in self.draft.filters]
        self.assertIn(DIM_DAYPART, dims)  # intent, though not in manifest
        self.assertIn(DIM_GEOGRAPHY, dims)
        values = {f.dimension_id: f.value for f in self.draft.filters}
        self.assertEqual(values[DIM_DAYPART], "lunch")
        self.assertEqual(values[DIM_GEOGRAPHY], "top_25_urban_dmas")
        self.assertEqual(
            self.draft.metric_ids,
            (MET_AVG_TICKET, MET_SPEND_SHARE, MET_YOY_GROWTH),
        )

    def test_validation_blocks_on_daypart_membership_only(self):
        result = self.stage2.validate_plan(self.ctx, self.draft)
        self.assertEqual(result.status, PlanStatus.INVALID)
        errors = [
            d for d in result.diagnostics if d.severity is Severity.ERROR
        ]
        self.assertEqual(len(errors), 1)
        self.assertEqual(
            errors[0].code, DiagnosticCode.DIMENSION_NOT_IN_WORKSPACE
        )
        self.assertEqual(result.blocking_subject_ids, (str(DIM_DAYPART),))
        infos = [d for d in result.diagnostics if d.severity is Severity.INFO]
        self.assertEqual(len(infos), 2)  # coverage note per entity

    def test_bridge_maps_blocker_to_exactly_daypart_addon(self):
        result = self.stage2.validate_plan(self.ctx, self.draft)
        shape = self.resolver.resolve(USER_ANALYST, ORG_DEMO)
        suggestions = self.stage1.explain_blockers(shape, result.diagnostics)
        self.assertEqual([s.addon_id for s in suggestions], [ADDON_DAYPART])

    def test_keyword_rules_skip_owned_addons(self):
        shape = self.resolver.resolve(USER_ANALYST, ORG_DEMO)
        suggestions = self.stage1.recommend_addons(
            shape, PKG_RESTAURANT_CI, QUESTION
        )
        self.assertEqual(
            [s.addon_id for s in suggestions],
            [ADDON_DAYPART, ADDON_STORE_OVERLAP],
        )

    def test_unlocked_workspace_validates_clean(self):
        self.grants.grant_addon(ORG_DEMO, ADDON_DAYPART)
        ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        result = self.stage2.validate_plan(ctx, self.draft)
        self.assertEqual(result.status, PlanStatus.VALID)
        self.assertFalse(
            [d for d in result.diagnostics if d.severity is Severity.ERROR]
        )


class TestCompilation(unittest.TestCase):
    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()
        self.ctx_base = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        self.grants.grant_addon(ORG_DEMO, ADDON_DAYPART)
        self.ctx_full = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        self.draft = self.stage2.draft_plan(
            self.ctx_full, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,)
        )

    def test_plan_id_deterministic_and_manifest_scoped(self):
        one = self.stage2.compile_plan(self.ctx_full, self.draft)
        two = self.stage2.compile_plan(self.ctx_full, self.draft)
        other = self.stage2.compile_plan(self.ctx_base, self.draft)
        self.assertEqual(one.id, two.id)
        self.assertNotEqual(one.id, other.id)  # different manifest, different id

    def test_executable_tracks_validation(self):
        self.assertTrue(self.stage2.compile_plan(self.ctx_full, self.draft).executable)
        self.assertFalse(self.stage2.compile_plan(self.ctx_base, self.draft).executable)

    def test_trace_and_caveats_present(self):
        plan = self.stage2.compile_plan(self.ctx_full, self.draft)
        self.assertEqual(plan.caveats, self.catalog.capabilities[CAP_MARKET_SHARE].caveats)
        actions = [step.action for step in plan.trace]
        self.assertEqual(
            actions,
            ["resolve_entities", "select_capability", "apply_filters",
             "select_metrics", "workspace_boundary", "assess", "caveats"],
        )


class TestVaultDoor(unittest.TestCase):
    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()
        self.grants.grant_addon(ORG_DEMO, ADDON_DAYPART)
        self.ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        draft = self.stage2.draft_plan(
            self.ctx, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,)
        )
        self.plan = self.stage2.compile_plan(self.ctx, draft)

    def current_manifest(self):
        return build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        ).manifest

    def test_allows_when_grants_hold(self):
        decision = check_execution(
            self.plan, self.current_manifest(), self.catalog.version
        )
        self.assertTrue(decision.allowed)

    def test_denies_after_revocation_with_precise_reason(self):
        self.grants.revoke_addon(ORG_DEMO, ADDON_DAYPART)
        decision = check_execution(
            self.plan, self.current_manifest(), self.catalog.version
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, DenialReason.ENTITLEMENT_REVOKED)
        self.assertIn(str(DIM_DAYPART), decision.detail)

    def test_denies_stale_catalog(self):
        decision = check_execution(
            self.plan, self.current_manifest(), "catalog.v2"
        )
        self.assertEqual(decision.reason, DenialReason.STALE_CATALOG)

    def test_denies_plans_that_failed_compile_validation(self):
        self.grants.revoke_addon(ORG_DEMO, ADDON_DAYPART)
        ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )
        draft = self.stage2.draft_plan(ctx, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,))
        bad_plan = self.stage2.compile_plan(ctx, draft)
        decision = check_execution(bad_plan, ctx.manifest, self.catalog.version)
        self.assertEqual(decision.reason, DenialReason.PLAN_NOT_EXECUTABLE)

    def test_boundary_form_rejects_unregistered_plan_ids(self):
        # A caller may NAME a plan, never DESCRIBE one: an id that compile
        # never produced resolves to nothing, whatever object the caller
        # holds locally.
        decision = check_execution_by_id(
            make_plan_id("plan.forged00000000"),
            self.stage2.plan_store,
            self.current_manifest(),
            self.catalog.version,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, DenialReason.PLAN_NOT_FOUND)

    def test_boundary_form_resolves_registered_plans(self):
        decision = check_execution_by_id(
            self.plan.id,
            self.stage2.plan_store,
            self.current_manifest(),
            self.catalog.version,
        )
        self.assertTrue(decision.allowed)


class TestCompatibilityAndProfiles(unittest.TestCase):
    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()
        self.ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, self.projector, self.cache
        )

    def test_partial_coverage_warns_but_remains_compatible(self):
        preview = self.stage2.preview_compatibility(
            self.ctx, CAP_WEB_ATTENTION, (ENT_CAVA, ENT_CHIPOTLE)
        )
        self.assertEqual(
            preview.status, CompatibilityStatus.COMPATIBLE_WITH_WARNINGS
        )
        self.assertEqual(
            preview.common_metric_ids,
            frozenset({MET_WEB_ATTENTION, MET_YOY_GROWTH}),
        )

    def test_data_gap_yields_not_available(self):
        preview = self.stage2.preview_compatibility(
            self.ctx, CAP_WEB_ATTENTION, (ENT_CAVA, ENT_SWEETGREEN)
        )
        self.assertEqual(preview.status, CompatibilityStatus.NOT_AVAILABLE)
        codes = {d.code for d in preview.diagnostics}
        self.assertIn(DiagnosticCode.NO_COVERAGE_FOR_ENTITY, codes)

    def test_workspace_gap_yields_not_available_with_subject(self):
        preview = self.stage2.preview_compatibility(
            self.ctx, CAP_STORE_OVERLAP, (ENT_CAVA, ENT_CHIPOTLE)
        )
        self.assertEqual(preview.status, CompatibilityStatus.NOT_AVAILABLE)
        shape = self.resolver.resolve(USER_ANALYST, ORG_DEMO)
        suggestions = self.stage1.explain_blockers(shape, preview.diagnostics)
        self.assertEqual(
            [s.addon_id for s in suggestions], [ADDON_STORE_OVERLAP]
        )

    def test_profiles_intersect_manifest_capability_and_coverage(self):
        (profile,) = self.stage2.get_capability_profiles(self.ctx, [ENT_CAVA])
        by_capability = {item.capability_id: item for item in profile.items}
        market_share = by_capability[CAP_MARKET_SHARE]
        # Coverage supports daypart; the manifest does not; intersection wins.
        self.assertEqual(
            market_share.usable_dimension_ids,
            frozenset({DIM_TIME_WINDOW, DIM_GEOGRAPHY}),
        )
        self.assertNotIn(CAP_STORE_OVERLAP, by_capability)  # not in manifest


class TestCoverageAwareBridge(unittest.TestCase):
    """A membership gap whose data is also thin must not be sold at full
    impact (the transcript's weak_coverage_penalty, in miniature)."""

    def setUp(self):
        self.catalog = build_catalog()
        grants = build_grant_store()
        self.resolver = InMemoryEntitlementResolver(grants)
        projector = ManifestProjector(self.catalog)
        cache = ManifestCache()
        # Same world, except Chipotle's card-spend panel cannot slice
        # daypart.
        base = build_coverage_index()
        records = tuple(
            dataclasses.replace(
                record,
                supported_dimension_ids=record.supported_dimension_ids
                - {DIM_DAYPART},
            )
            if record.entity_id == ENT_CHIPOTLE
            and record.capability_id == CAP_MARKET_SHARE
            else record
            for record in base.records
        )
        self.stage2 = Stage2Workspace(
            self.catalog,
            build_entity_index(),
            CoverageIndex(base.snapshot_version, records),
        )
        self.stage1 = Stage1CommerceStub(
            self.catalog, build_relevance_rules()
        )
        self.ctx = build_workspace_context(
            USER_ANALYST, ORG_DEMO, self.resolver, projector, cache
        )
        draft = self.stage2.draft_plan(
            self.ctx, QUESTION, ENT_CAVA, (ENT_CHIPOTLE,)
        )
        self.result = self.stage2.validate_plan(self.ctx, draft)

    def test_membership_and_coverage_facts_coexist(self):
        codes = {d.code for d in self.result.diagnostics}
        self.assertIn(DiagnosticCode.DIMENSION_NOT_IN_WORKSPACE, codes)
        self.assertIn(DiagnosticCode.DIMENSION_NOT_COVERED_FOR_ENTITY, codes)

    def test_bridge_downgrades_thin_coverage_suggestions(self):
        shape = self.resolver.resolve(USER_ANALYST, ORG_DEMO)
        (suggestion,) = [
            s
            for s in self.stage1.explain_blockers(
                shape, self.result.diagnostics
            )
            if s.addon_id == ADDON_DAYPART
        ]
        self.assertEqual(suggestion.impact, Impact.MEDIUM)
        self.assertIn("coverage", suggestion.reason)


class TestMetricIntentSymmetry(unittest.TestCase):
    """Drafts carry the capability's metric semantics; workspace gaps
    surface as diagnostics instead of silent truncation."""

    def setUp(self):
        (self.catalog, self.grants, self.resolver, self.projector,
         self.cache, self.stage2, self.stage1) = build_world()

    def test_metric_gap_surfaces_as_membership_diagnostic(self):
        # Add-on only, no package: the workspace has the web-attention
        # capability but not the package-granted yoy_growth metric.
        shape = EntitlementShape(
            ORG_DEMO, frozenset(), frozenset(),
            frozenset({ADDON_WEB_ATTENTION}),
        )
        ctx = WorkspaceContext(
            ORG_DEMO, USER_ANALYST, self.projector.build(shape)
        )
        draft = self.stage2.draft_plan(
            ctx, "Is CAVA getting digital attention?", ENT_CAVA
        )
        self.assertEqual(draft.capability_id, CAP_WEB_ATTENTION)
        self.assertIn(MET_YOY_GROWTH, draft.metric_ids)  # intent kept
        result = self.stage2.validate_plan(ctx, draft)
        self.assertIn(str(MET_YOY_GROWTH), result.blocking_subject_ids)
        # The stub bridge maps add-ons only; package-granted subjects yield
        # no suggestion. Documented Stage 1 stub limitation.
        suggestions = self.stage1.explain_blockers(
            shape, result.diagnostics
        )
        self.assertEqual(suggestions, ())


if __name__ == "__main__":
    unittest.main()
