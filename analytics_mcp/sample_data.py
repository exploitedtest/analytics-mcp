"""Sample dataset: the transcript's Restaurant CI scenario, made runnable.

Well-known ids are defined once, through the validating constructors, and
referenced everywhere else -- this module is the documented registry of
sample identifiers (no loose strings elsewhere).

Encoded state, matching the transcript's canonical scenario:

* org.demo owns the Restaurant Competitive Intelligence package plus the
  Web/App Attention add-on.
* Daypart Analysis and Store-Overlap Normalization are NOT owned.
* Coverage: card spend is solid for all three brands; web attention is
  partial (and absent for Sweetgreen); store overlap has no Sweetgreen row.

So a lunch-share question drafts cleanly, validates as blocked on the
daypart dimension, and the blocker bridge points at exactly one add-on.
"""

from __future__ import annotations

from .catalog import (
    AddOnDefinition,
    CapabilityDefinition,
    DimensionDefinition,
    GlobalCatalog,
    MetricDefinition,
    PackageDefinition,
    ViewDefinition,
)
from .commerce import Impact, RelevanceRule
from .entitlements import GrantStore
from .ids import (
    EntityKind,
    addon_id,
    capability_id,
    dimension_id,
    entity_id,
    metric_id,
    org_id,
    package_id,
    user_id,
    view_id,
)
from .ontology import (
    CapabilityAvailability,
    CoverageIndex,
    CoverageSummary,
    EntityCapabilityCoverage,
    EntityIndex,
    EntityRecord,
    GeographyCoverage,
    SampleQuality,
)

# --------------------------------------------------------------- identifiers

PKG_RESTAURANT_CI = package_id("package.restaurant_ci")

ADDON_DAYPART = addon_id("addon.daypart_analysis")
ADDON_STORE_OVERLAP = addon_id("addon.store_overlap")
ADDON_WEB_ATTENTION = addon_id("addon.web_attention")

CAP_MARKET_SHARE = capability_id("capability.card_spend.brand_market_share")
CAP_STORE_OVERLAP = capability_id("capability.location.store_overlap")
CAP_WEB_ATTENTION = capability_id("capability.web_attention.entity_trend")

MET_SPEND_SHARE = metric_id("metric.spend_share")
MET_YOY_GROWTH = metric_id("metric.yoy_growth")
MET_AVG_TICKET = metric_id("metric.avg_ticket")
MET_WEB_ATTENTION = metric_id("metric.web_attention")

DIM_TIME_WINDOW = dimension_id("dimension.time_window")
DIM_GEOGRAPHY = dimension_id("dimension.geography")
DIM_DAYPART = dimension_id("dimension.daypart")

VIEW_TREND_CHART = view_id("view.trend_chart")
VIEW_COMPARISON_TABLE = view_id("view.comparison_table")
VIEW_DAYPART_SPLIT = view_id("view.daypart_split")
VIEW_OVERLAP_MAP = view_id("view.store_overlap_map")
VIEW_WEB_ATTENTION = view_id("view.web_attention")

ENT_CAVA = entity_id("entity.brand.cava")
ENT_CHIPOTLE = entity_id("entity.brand.chipotle")
ENT_SWEETGREEN = entity_id("entity.brand.sweetgreen")

ORG_DEMO = org_id("org.demo")
ORG_OTHER = org_id("org.other")
USER_ANALYST = user_id("user.analyst")

CATALOG_VERSION = "catalog.v1"
ENTITY_SNAPSHOT = "entities.2026-07-01"
COVERAGE_SNAPSHOT = "coverage.2026-06-30"


# ------------------------------------------------------------------- catalog


def build_catalog() -> GlobalCatalog:
    metrics = {
        MET_SPEND_SHARE: MetricDefinition(
            MET_SPEND_SHARE,
            "Spend Share",
            "Entity spend divided by competitive-set spend.",
        ),
        MET_YOY_GROWTH: MetricDefinition(
            MET_YOY_GROWTH, "YoY Growth", "Year-over-year spend growth."
        ),
        MET_AVG_TICKET: MetricDefinition(
            MET_AVG_TICKET, "Average Ticket", "Average transaction amount."
        ),
        MET_WEB_ATTENTION: MetricDefinition(
            MET_WEB_ATTENTION,
            "Web/App Attention",
            "Digital engagement proxy.",
        ),
    }

    dimensions = {
        DIM_TIME_WINDOW: DimensionDefinition(
            DIM_TIME_WINDOW,
            "Time Window",
            "Trailing analysis window.",
            frozenset({"trailing_12_months", "trailing_24_months"}),
        ),
        DIM_GEOGRAPHY: DimensionDefinition(
            DIM_GEOGRAPHY,
            "Geography",
            "Geographic slice.",
            frozenset({"national", "top_25_urban_dmas", "dma"}),
        ),
        DIM_DAYPART: DimensionDefinition(
            DIM_DAYPART,
            "Daypart",
            "Meal-period slice.",
            frozenset({"breakfast", "lunch", "dinner", "all_day"}),
        ),
    }

    capabilities = {
        CAP_MARKET_SHARE: CapabilityDefinition(
            CAP_MARKET_SHARE,
            "Brand Card Spend Market Share",
            "Compare spend share and growth across brands.",
            frozenset({EntityKind.BRAND, EntityKind.COMPANY}),
            frozenset({MET_SPEND_SHARE, MET_YOY_GROWTH, MET_AVG_TICKET}),
            frozenset({DIM_TIME_WINDOW, DIM_GEOGRAPHY, DIM_DAYPART}),
            caveats=(
                "Card spend is a directional proxy, not reported revenue.",
                "Store-count normalization is recommended when footprints "
                "differ.",
            ),
        ),
        CAP_STORE_OVERLAP: CapabilityDefinition(
            CAP_STORE_OVERLAP,
            "Store-Overlap Normalization",
            "Normalize comparisons by overlapping trade areas.",
            frozenset({EntityKind.BRAND, EntityKind.COMPANY}),
            frozenset({MET_YOY_GROWTH}),
            frozenset({DIM_GEOGRAPHY}),
        ),
        CAP_WEB_ATTENTION: CapabilityDefinition(
            CAP_WEB_ATTENTION,
            "Web/App Attention Trend",
            "Digital attention trends for brands.",
            frozenset({EntityKind.BRAND, EntityKind.COMPANY}),
            frozenset({MET_WEB_ATTENTION, MET_YOY_GROWTH}),
            frozenset({DIM_TIME_WINDOW, DIM_GEOGRAPHY}),
        ),
    }

    views = {
        VIEW_TREND_CHART: ViewDefinition(
            VIEW_TREND_CHART,
            "Trend Chart",
            "Monthly trend chart.",
            CAP_MARKET_SHARE,
        ),
        VIEW_COMPARISON_TABLE: ViewDefinition(
            VIEW_COMPARISON_TABLE,
            "Comparison Table",
            "Entity comparison table.",
            CAP_MARKET_SHARE,
        ),
        VIEW_DAYPART_SPLIT: ViewDefinition(
            VIEW_DAYPART_SPLIT,
            "Lunch/Dinner Share Split",
            "Daypart-specific share view.",
            CAP_MARKET_SHARE,
            required_dimension_ids=frozenset({DIM_DAYPART}),
        ),
        VIEW_OVERLAP_MAP: ViewDefinition(
            VIEW_OVERLAP_MAP,
            "Store-Overlap Map",
            "Footprint-normalized map.",
            CAP_STORE_OVERLAP,
        ),
        VIEW_WEB_ATTENTION: ViewDefinition(
            VIEW_WEB_ATTENTION,
            "Web/App Attention",
            "Digital attention trend.",
            CAP_WEB_ATTENTION,
            required_metric_ids=frozenset({MET_WEB_ATTENTION}),
        ),
    }

    addons = {
        ADDON_DAYPART: AddOnDefinition(
            ADDON_DAYPART,
            "Daypart Analysis",
            "Adds breakfast/lunch/dinner cuts and the daypart split view.",
            added_dimension_ids=frozenset({DIM_DAYPART}),
            added_view_ids=frozenset({VIEW_DAYPART_SPLIT}),
        ),
        ADDON_STORE_OVERLAP: AddOnDefinition(
            ADDON_STORE_OVERLAP,
            "Store-Overlap Normalization",
            "Footprint-aware normalization and overlap maps.",
            added_capability_ids=frozenset({CAP_STORE_OVERLAP}),
            added_view_ids=frozenset({VIEW_OVERLAP_MAP}),
        ),
        ADDON_WEB_ATTENTION: AddOnDefinition(
            ADDON_WEB_ATTENTION,
            "Web/App Attention",
            "Adds digital attention signals.",
            added_capability_ids=frozenset({CAP_WEB_ATTENTION}),
            added_metric_ids=frozenset({MET_WEB_ATTENTION}),
            added_view_ids=frozenset({VIEW_WEB_ATTENTION}),
        ),
    }

    packages = {
        PKG_RESTAURANT_CI: PackageDefinition(
            PKG_RESTAURANT_CI,
            "Restaurant Competitive Intelligence",
            "Restaurant brand performance, share, growth, and competitive "
            "positioning.",
            included_capability_ids=frozenset({CAP_MARKET_SHARE}),
            included_metric_ids=frozenset(
                {MET_SPEND_SHARE, MET_YOY_GROWTH, MET_AVG_TICKET}
            ),
            included_dimension_ids=frozenset(
                {DIM_TIME_WINDOW, DIM_GEOGRAPHY}
            ),
            included_view_ids=frozenset(
                {VIEW_TREND_CHART, VIEW_COMPARISON_TABLE}
            ),
            addon_ids=frozenset(
                {ADDON_DAYPART, ADDON_STORE_OVERLAP, ADDON_WEB_ATTENTION}
            ),
        ),
    }

    catalog = GlobalCatalog(
        version=CATALOG_VERSION,
        metrics=metrics,
        dimensions=dimensions,
        capabilities=capabilities,
        views=views,
        packages=packages,
        addons=addons,
    )
    catalog.validate()
    return catalog


# ------------------------------------------------------------------ ontology


def build_entity_index() -> EntityIndex:
    entities = {
        ENT_CAVA: EntityRecord(
            ENT_CAVA, "CAVA", EntityKind.BRAND, frozenset({"CAVA Group"})
        ),
        ENT_CHIPOTLE: EntityRecord(
            ENT_CHIPOTLE,
            "Chipotle",
            EntityKind.BRAND,
            frozenset({"Chipotle Mexican Grill", "CMG"}),
        ),
        ENT_SWEETGREEN: EntityRecord(
            ENT_SWEETGREEN, "Sweetgreen", EntityKind.BRAND, frozenset({"SG"})
        ),
    }
    return EntityIndex(snapshot_version=ENTITY_SNAPSHOT, entities=entities)


def build_coverage_index() -> CoverageIndex:
    card_spend_coverage = CoverageSummary(
        history_depth_months=36,
        sample_quality=SampleQuality.MEDIUM_HIGH,
        geography_coverage=GeographyCoverage.BROAD,
        warnings=("Smaller DMAs have weaker sample quality.",),
    )
    web_attention_coverage = CoverageSummary(
        history_depth_months=18,
        sample_quality=SampleQuality.MEDIUM,
        geography_coverage=GeographyCoverage.LIMITED,
        warnings=("App mapping may be incomplete.",),
    )
    overlap_coverage = CoverageSummary(
        history_depth_months=24,
        sample_quality=SampleQuality.HIGH,
        geography_coverage=GeographyCoverage.BROAD,
    )

    records: list[EntityCapabilityCoverage] = []

    for ent in (ENT_CAVA, ENT_CHIPOTLE, ENT_SWEETGREEN):
        records.append(
            EntityCapabilityCoverage(
                entity_id=ent,
                capability_id=CAP_MARKET_SHARE,
                availability=CapabilityAvailability.AVAILABLE,
                supported_metric_ids=frozenset(
                    {MET_SPEND_SHARE, MET_YOY_GROWTH, MET_AVG_TICKET}
                ),
                supported_dimension_ids=frozenset(
                    {DIM_TIME_WINDOW, DIM_GEOGRAPHY, DIM_DAYPART}
                ),
                coverage=card_spend_coverage,
            )
        )

    for ent in (ENT_CAVA, ENT_CHIPOTLE):
        records.append(
            EntityCapabilityCoverage(
                entity_id=ent,
                capability_id=CAP_WEB_ATTENTION,
                availability=CapabilityAvailability.PARTIAL,
                supported_metric_ids=frozenset(
                    {MET_WEB_ATTENTION, MET_YOY_GROWTH}
                ),
                supported_dimension_ids=frozenset(
                    {DIM_TIME_WINDOW, DIM_GEOGRAPHY}
                ),
                coverage=web_attention_coverage,
            )
        )
    # Sweetgreen: web attention explicitly unavailable (thin app signal).
    records.append(
        EntityCapabilityCoverage(
            entity_id=ENT_SWEETGREEN,
            capability_id=CAP_WEB_ATTENTION,
            availability=CapabilityAvailability.UNAVAILABLE,
            supported_metric_ids=frozenset(),
            supported_dimension_ids=frozenset(),
            coverage=CoverageSummary(
                history_depth_months=0,
                sample_quality=SampleQuality.LOW,
                geography_coverage=GeographyCoverage.NONE,
            ),
        )
    )

    for ent in (ENT_CAVA, ENT_CHIPOTLE):
        records.append(
            EntityCapabilityCoverage(
                entity_id=ent,
                capability_id=CAP_STORE_OVERLAP,
                availability=CapabilityAvailability.AVAILABLE,
                supported_metric_ids=frozenset({MET_YOY_GROWTH}),
                supported_dimension_ids=frozenset({DIM_GEOGRAPHY}),
                coverage=overlap_coverage,
            )
        )
    # Sweetgreen has no store-overlap row at all: absence is also a state.

    return CoverageIndex(
        snapshot_version=COVERAGE_SNAPSHOT, records=tuple(records)
    )


# ------------------------------------------------------------------- grants


def build_grant_store() -> GrantStore:
    """org.demo and org.other both own: Restaurant CI + Web/App Attention.
    Identical grants on purpose -- they must share a manifest cache entry."""
    store = GrantStore()
    for org in (ORG_DEMO, ORG_OTHER):
        store.grant_package(org, PKG_RESTAURANT_CI)
        store.grant_addon(org, ADDON_WEB_ATTENTION)
    return store


# ------------------------------------------------------------ commerce rules


def build_relevance_rules() -> tuple[RelevanceRule, ...]:
    return (
        RelevanceRule(
            addon_id=ADDON_DAYPART,
            trigger_terms=frozenset(
                {"lunch", "dinner", "breakfast", "daypart"}
            ),
            impact=Impact.HIGH,
            reason="Adds breakfast/lunch/dinner cuts for daypart questions.",
        ),
        RelevanceRule(
            addon_id=ADDON_STORE_OVERLAP,
            trigger_terms=frozenset(
                {"share", "against", "compare", "vs", "versus"}
            ),
            impact=Impact.HIGH,
            reason="Normalizes comparisons across different store "
            "footprints.",
        ),
        RelevanceRule(
            addon_id=ADDON_WEB_ATTENTION,
            trigger_terms=frozenset({"attention", "digital", "web", "app"}),
            impact=Impact.MEDIUM,
            reason="Adds a secondary demand signal.",
        ),
    )
