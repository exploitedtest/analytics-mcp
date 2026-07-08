# Two-Stage Analytics MCP — Completed Data Model (Stage 2 deep-dive)

A runnable Python data model consolidating the transcript's design: Stage 1 sells the room,
Stage 2 operates it richly, and an access-projection layer in between keeps the two from ever
meeting in code. Scope per decision: **Stage 2 gets the full v1 depth restored on the v2
architecture; commerce and execution are deliberate stubs.** Stdlib frozen dataclasses, zero
dependencies.

```
python3 tests.py -v     # 30 checks — the "compatibility audit" as code
python3 demo.py         # the canonical CAVA-lunch-share scenario, end to end
```

## Bounded contexts

```
ids, diagnostics        shared kernel: typed ids, codes, the subject_id contract
catalog                 semantic definitions   (user-agnostic, versioned: catalog.v1)
ontology                entities + coverage    (data-plane, versioned separately)
entitlements            grants -> EntitlementShape -> fingerprint
projection              shape -> WorkspaceManifest   (the middleware boundary)
workspace               STAGE 2: the deep analytical domain
commerce                STAGE 1 STUB: relevance rules + the blocker bridge
execution               vault-door gate stub
sample_data             Restaurant CI scenario, ids defined once
```

Imports point strictly downward. `workspace.py`, `projection.py`, and `ontology.py` are
verified commerce-free by AST inspection and vocabulary scan in `tests.py` — the domain
separation is a test, not a convention.

## What Stage 2 restored (v1 depth on v2 architecture)

The transcript's v2 refactor was architecturally right and surgically overzealous: it threw
out roughly half the v1 surface while cleaning house. Restored here, all operating through
the manifest lens only:

`resolve_entities` (with representable ambiguity), `list_capabilities` / `list_views`
(workspace-effective: catalog ∩ manifest), `get_capability_profiles` (the three-way
intersection manifest ∩ capability ∩ per-entity coverage — the honest answer to "what can I
slice for CAVA *here*"), `preview_compatibility` (cause-specific diagnostics distinguishing
workspace gaps from data gaps), `draft_plan` / `validate_plan` / `compile_plan`
(deterministic content-addressed plan ids, methodology caveats, and the analyst-facing
trace — v1's trust features).

**The bridge.** Stage 2's drafter captures *intent*: a lunch question yields a daypart
filter even though the workspace lacks the dimension. Validation then emits
`dimension_not_in_workspace` with `subject_id=dimension.daypart` — a fact, not an offer.
Stage 1's `explain_blockers` reverse-indexes that subject through the catalog and produces
the Daypart Analysis suggestion deterministically. The two domains communicate through a
data contract (`Diagnostic.subject_id` + `WORKSPACE_MEMBERSHIP_CODES`), never an import.
This same channel is where "desired views become telemetry" plugs in later: the diagnostics
*are* the demand signals.

## Defects found in the transcript, and their resolutions

| Transcript said | Problem | Resolution here |
|---|---|---|
| `fingerprint()` hashes `org_id` + `roles` | Reduces the manifest cache to one entry per org — defeats its own goal | Hash only what projection reads: catalog version + grant sets. Verified: two orgs, one cache entry |
| `dims = dims \| (cap.dims & dims)` in projector | Set-algebra no-op; dead code masquerading as policy | Removed. Grants are explicit; capability support is a validation concern |
| Workspace metrics derived from capabilities | Makes metric-level add-ons (v1's "receipt basket metrics") inexpressible | Uniform explicit grants for capabilities, metrics, dimensions, views |
| Enum classes for catalog ids | Contradicts "catalog lives in DB, not code" — new package = code deploy | Typed `NewType` ids + validating constructors + one documented prefix registry |
| `PlanStatus.REQUIRES_UNLOCK` (v1) | Leaks commerce into Stage 2's vocabulary | Stage 2 statuses: valid / valid_with_warnings / invalid. Absence is a fact; meaning is Stage 1's job |
| `EntitlementResolver` referenced, never defined | Load-bearing vaporware | Protocol + in-memory implementation |
| "The executor still checks entitlements — the vault door" | Asserted three times, modeled zero times | `check_execution`: re-project from *current* grants, membership re-check (not manifest-id equality, so upgraded orgs still pass) |
| Entity ontology + coverage dropped in v2 | Stage 2 compared raw strings against nothing | Restored as separately-versioned data-plane indexes |
| View gating via `required_addon_id` | Special-cases the add-on mechanism into the catalog | Views declare required capability/dimensions/metrics; the projector lights them up from whatever grants supplied the parts |

## MCP tool surface (implementation prep)

| Tool | Server | Audience | Request → Response |
|---|---|---|---|
| `workspace.resolve_entities` | stage2 | client | names → `EntityResolution[]` |
| `workspace.list_capabilities` | stage2 | client | ctx → `WorkspaceCapability[]` |
| `workspace.list_views` | stage2 | client | ctx → `ViewDefinition[]` |
| `workspace.get_capability_profiles` | stage2 | client | ctx, entity_ids → `EntityCapabilityProfile[]` |
| `workspace.preview_compatibility` | stage2 | client | ctx, capability, entities, filters → `CompatibilityPreview` |
| `workspace.draft_plan` | stage2 | client | ctx, question, entities → `AnalysisPlanDraft` |
| `workspace.validate_plan` | stage2 | client | ctx, draft → `PlanValidationResult` |
| `workspace.compile_plan` | stage2 | client | ctx, draft → `CompiledPlan` |
| `commerce.recommend_addons` | stage1 | client | shape, package, question → `AddOnSuggestion[]` |
| `commerce.explain_blockers` | stage1 | client | shape, diagnostics → `AddOnSuggestion[]` |
| `entitlements.resolve` | internal | middleware | user, org → `EntitlementShape` |
| `manifests.get_or_build` | internal | middleware | shape → `WorkspaceManifest` |
| `execution.check_by_id` | internal | executor | plan_id (server-store lookup), current manifest → `ExecutionGateDecision` |

The `ctx` parameter is injected by middleware (`build_workspace_context`), never supplied by
the caller — an MCP client cannot name a manifest it wasn't given.

## Caching and versioning

| Artifact | Key | Invalidation |
|---|---|---|
| Global catalog | `catalog_version` | version bump; cache forever per version |
| Entity index | `snapshot_version` | per ontology refresh |
| Coverage index | `snapshot_version` | per data drop (churns fastest — kept out of the catalog on purpose) |
| Workspace manifest | `sha256(catalog_version, packages, addons)` | new fingerprint on any grant/catalog change; old keys simply miss |
| Compiled plan | `sha256(catalog_version, manifest_id, normalized draft)` | content-addressed; identical intent in identical workspace → identical id |

Nothing user-specific enters any key. Roles and org join the fingerprint only on the day
projection actually reads them (the `org_overrides_version` slot is reserved for that).

## Scrutiny round (post-review fixes)

Three risks were pulled out for adversarial review; all three turned out to warrant changes,
each regression-tested:

| Risk | Failure mode | Fix |
|---|---|---|
| Execution gate accepted a client-shaped `CompiledPlan` and trusted its `executable` flag | Forged plan objects cross the MCP boundary; `executable=True` is caller-asserted; the content hash has no secret so self-consistent forgeries are trivial | `PlanStore`: compile registers plans server-side; `check_execution_by_id` resolves by id and denies unknown ids (`plan_not_found`). Plans cross boundaries as names, never descriptions |
| Blocker bridge could sell a key to an empty room | Membership errors short-circuited per-entity coverage checks, so Stage 1 suggested add-ons at HIGH impact for slices the data can't deliver for these entities | Stage 2 emits membership and coverage facts together (still commerce-free); `explain_blockers` downgrades to MEDIUM with an explicit coverage note when the blocked subject also has a coverage gap — the transcript's `weak_coverage_penalty`, minimally |
| Drafter truncated metrics to the manifest while filters carried intent | Metric-level demand signals were structurally silenced — the exact add-on class the explicit-grant correction made expressible could never be asked for | Symmetric intent: drafts carry the capability's full metric set; validation names each gap; the shell can auto-prune to the included alternative while the signal survives |

Known residual risks, judged acceptable and left alone: manifest/plan ids truncate the hash
to 64 bits (collision-safe at any plausible scale, and ids are lookup keys, not security
boundaries); the domain-separation vocabulary test matches substrings and could false-positive
on innocent words someday; duplicate entity ids in a draft produce noisy-but-honest
diagnostics rather than a dedicated error; the bridge maps add-ons only, so package-granted
subjects yield no suggestion (a stub limitation, tested and documented).

## Deliberately out of scope (per the scoping decision)

Stage 1 pricing (Money, SKUs, offers, access states, package cards), execution billing
(credits, quotas, receipts, result envelopes, export rights), and the telemetry sink. The
seams are ready: offers key off package/add-on ids, the executor wraps `check_execution`,
and telemetry consumes the same diagnostics the bridge already reads. Infra note stands as
in the transcript: Terraform provisions routes/cache/IAM; the catalog is data in a store,
never resources in HCL.
