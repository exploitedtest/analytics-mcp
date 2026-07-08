"""Stage 1 commerce -- deliberately a stub.

Per the scoping decision, Stage 2 is the deep model; this module carries
only the two commercial behaviors the architecture cannot demonstrate
without: contextual add-on recommendation, and the blocker bridge that
turns Stage 2 diagnostics into offers. Pricing, SKUs, access states,
package cards, and unlock offers are out of scope here and documented as
next steps in the README.

Two recommendation channels, deliberately distinct in strength:

* ``explain_blockers`` -- deterministic. Stage 2 said "dimension.daypart is
  not in this workspace"; the catalog's reverse index says which add-ons
  grant it; anything not already owned becomes a high-impact suggestion.
  This is the strongest demand signal the product has.
* ``recommend_addons`` -- heuristic. Declarative keyword rules over the
  question text, for the browsing moment before any plan exists. Weaker,
  and honest about it (capped below HIGH impact by construction: rules are
  data, and the sample rules use MEDIUM/HIGH as authored).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Sequence

from .catalog import GlobalCatalog
from .diagnostics import (
    COVERAGE_GAP_CODES,
    Diagnostic,
    WORKSPACE_MEMBERSHIP_CODES,
)
from .entitlements import EntitlementShape
from .ids import AddOnId, PackageId


class Impact(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_IMPACT_RANK = {Impact.HIGH: 0, Impact.MEDIUM: 1, Impact.LOW: 2}


@dataclass(frozen=True)
class RelevanceRule:
    """Declarative trigger: data, not code. Single-word tokens only;
    matching is whole-token so 'vs' does not light up inside 'investors'."""

    addon_id: AddOnId
    trigger_terms: frozenset[str]
    impact: Impact
    reason: str


@dataclass(frozen=True)
class AddOnSuggestion:
    addon_id: AddOnId
    name: str
    impact: Impact
    reason: str


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.casefold()))


class Stage1CommerceStub:
    def __init__(
        self,
        catalog: GlobalCatalog,
        relevance_rules: Sequence[RelevanceRule] = (),
    ) -> None:
        self.catalog = catalog
        self.relevance_rules = tuple(relevance_rules)

    def recommend_addons(
        self,
        shape: EntitlementShape,
        package_id: PackageId,
        question: str,
    ) -> tuple[AddOnSuggestion, ...]:
        """Keyword-rule recommendations, scoped to the package's advertised
        add-ons and filtered to what the org does not already own."""
        package = self.catalog.packages[package_id]
        tokens = _tokens(question)
        suggestions: list[AddOnSuggestion] = []
        for rule in self.relevance_rules:
            if rule.addon_id not in package.addon_ids:
                continue
            if rule.addon_id in shape.addon_ids:
                continue
            if not (rule.trigger_terms & tokens):
                continue
            addon = self.catalog.addons[rule.addon_id]
            suggestions.append(
                AddOnSuggestion(
                    addon_id=rule.addon_id,
                    name=addon.name,
                    impact=rule.impact,
                    reason=rule.reason,
                )
            )
        return tuple(
            sorted(
                suggestions,
                key=lambda s: (_IMPACT_RANK[s.impact], s.addon_id),
            )
        )

    def explain_blockers(
        self,
        shape: EntitlementShape,
        diagnostics: Sequence[Diagnostic],
    ) -> tuple[AddOnSuggestion, ...]:
        """The Stage 2 -> Stage 1 bridge.

        Consumes membership diagnostics (only those; semantic and coverage
        problems are not for sale), reverse-indexes each subject_id to the
        add-ons that would grant it, and suggests the ones not owned.
        Deterministic: no keywords, no scoring, no vibes.

        Coverage counterweight: when the same subject also carries a
        coverage-gap diagnostic, the suggestion is downgraded and says so.
        Selling access to a slice the data cannot deliver for these
        entities would be a refund waiting to happen.
        """
        weak_subjects = {
            d.subject_id
            for d in diagnostics
            if d.code in COVERAGE_GAP_CODES and d.subject_id
        }
        suggestions: dict[AddOnId, AddOnSuggestion] = {}
        for diagnostic in diagnostics:
            if diagnostic.code not in WORKSPACE_MEMBERSHIP_CODES:
                continue
            if not diagnostic.subject_id:
                continue
            weak = diagnostic.subject_id in weak_subjects
            for addon in self.catalog.addons_granting(diagnostic.subject_id):
                if addon.id in shape.addon_ids:
                    continue
                existing = suggestions.get(addon.id)
                if existing is not None and existing.impact is Impact.HIGH:
                    continue  # keep the strongest justification seen
                subject_name = self.catalog.display_name(
                    diagnostic.subject_id
                )
                reason = (
                    f"Grants {subject_name}, required by the current plan."
                )
                impact = Impact.HIGH
                if weak:
                    impact = Impact.MEDIUM
                    reason += (
                        " Note: data coverage for it is partial for the"
                        " entities in this plan."
                    )
                suggestions[addon.id] = AddOnSuggestion(
                    addon_id=addon.id,
                    name=addon.name,
                    impact=impact,
                    reason=reason,
                )
        return tuple(
            sorted(suggestions.values(), key=lambda s: s.addon_id)
        )
