"""Two-stage analytics MCP data model.

Bounded contexts (one module each; import direction is strictly downward):

    ids, diagnostics          shared kernel
    catalog                   semantic definitions (user-agnostic, versioned)
    ontology                  entities + coverage (data-plane, versioned)
    entitlements              grants -> EntitlementShape (+ fingerprint)
    projection                shape -> WorkspaceManifest (middleware)
    workspace                 Stage 2 analytical operations (deep)
    commerce                  Stage 1 stub: relevance rules + blocker bridge
    execution                 vault-door gate stub
    sample_data               runnable Restaurant CI scenario
"""

from .catalog import (
    AddOnDefinition,
    CapabilityDefinition,
    CatalogIntegrityError,
    DimensionDefinition,
    GlobalCatalog,
    MetricDefinition,
    PackageDefinition,
    ViewDefinition,
)
from .commerce import AddOnSuggestion, Impact, RelevanceRule, Stage1CommerceStub
from .diagnostics import (
    COVERAGE_GAP_CODES,
    Diagnostic,
    DiagnosticCode,
    PlanStatus,
    Severity,
    WORKSPACE_MEMBERSHIP_CODES,
    status_from,
)
from .entitlements import (
    AddOnGrant,
    EntitlementResolver,
    EntitlementShape,
    GrantStore,
    InMemoryEntitlementResolver,
    PackageGrant,
)
from .execution import (
    DenialReason,
    ExecutionGateDecision,
    check_execution,
    check_execution_by_id,
)
from .ids import EntityKind
from .ontology import (
    CapabilityAvailability,
    CoverageIndex,
    CoverageSummary,
    EntityCapabilityCoverage,
    EntityIndex,
    EntityRecord,
    EntityResolution,
    GeographyCoverage,
    SampleQuality,
)
from .projection import (
    ManifestCache,
    ManifestProjector,
    WorkspaceContext,
    WorkspaceManifest,
    build_workspace_context,
)
from .workspace import (
    AnalysisPlanDraft,
    CompatibilityPreview,
    CompatibilityStatus,
    CompiledPlan,
    EntityCapabilityProfile,
    EntityCapabilityView,
    FilterSelection,
    PlanStore,
    PlanValidationResult,
    Stage2Workspace,
    TraceStep,
    WorkspaceCapability,
)

__all__ = [name for name in dir() if not name.startswith("_")]
