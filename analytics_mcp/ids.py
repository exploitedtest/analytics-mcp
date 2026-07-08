"""Typed identifiers and shared closed vocabularies.

Identifier convention
---------------------
Every open-set identifier is a dot-prefixed string::

    <resource_type>.<name>              dimension.daypart
    <resource_type>.<domain>.<name>     capability.card_spend.brand_market_share

Open sets (catalog rows, entities, orgs, plans) are ``NewType`` strings built
through the validating constructors below. The catalog is *data*: adding a
package, add-on, or metric must never require a code deploy, which rules out
enums for these ids. (The transcript's v2 used enums for catalog ids while
simultaneously insisting the catalog live in the database -- those two
positions fight each other. This resolves the fight in favor of data.)

Closed vocabularies -- states, severities, kinds the code actually branches
on -- are enums, defined in the module that owns them. Only ``EntityKind``
lives here because both the catalog and the ontology need it.
"""

from __future__ import annotations

import enum
from typing import NewType

# --------------------------------------------------------------------------
# Open-set identifiers
# --------------------------------------------------------------------------

PackageId = NewType("PackageId", str)
AddOnId = NewType("AddOnId", str)
CapabilityId = NewType("CapabilityId", str)
MetricId = NewType("MetricId", str)
DimensionId = NewType("DimensionId", str)
ViewId = NewType("ViewId", str)
EntityId = NewType("EntityId", str)
OrgId = NewType("OrgId", str)
UserId = NewType("UserId", str)
PlanId = NewType("PlanId", str)

#: Single source of truth for id prefixes. Documented once, enforced below.
#: ``manifest.`` and ``plan.`` ids are derived (hash-based), not authored.
ID_PREFIXES: dict[str, str] = {
    "package": "package.",
    "addon": "addon.",
    "capability": "capability.",
    "metric": "metric.",
    "dimension": "dimension.",
    "view": "view.",
    "entity": "entity.",
    "org": "org.",
    "user": "user.",
    "plan": "plan.",
    "manifest": "manifest.",
}


def _checked(kind: str, value: str) -> str:
    prefix = ID_PREFIXES[kind]
    if not value.startswith(prefix) or len(value) <= len(prefix):
        raise ValueError(
            f"expected {kind} id with prefix {prefix!r}, got {value!r}"
        )
    return value


def package_id(value: str) -> PackageId:
    return PackageId(_checked("package", value))


def addon_id(value: str) -> AddOnId:
    return AddOnId(_checked("addon", value))


def capability_id(value: str) -> CapabilityId:
    return CapabilityId(_checked("capability", value))


def metric_id(value: str) -> MetricId:
    return MetricId(_checked("metric", value))


def dimension_id(value: str) -> DimensionId:
    return DimensionId(_checked("dimension", value))


def view_id(value: str) -> ViewId:
    return ViewId(_checked("view", value))


def entity_id(value: str) -> EntityId:
    return EntityId(_checked("entity", value))


def org_id(value: str) -> OrgId:
    return OrgId(_checked("org", value))


def user_id(value: str) -> UserId:
    return UserId(_checked("user", value))


def plan_id(value: str) -> PlanId:
    return PlanId(_checked("plan", value))


# --------------------------------------------------------------------------
# Shared closed vocabularies
# --------------------------------------------------------------------------


class EntityKind(str, enum.Enum):
    """What sort of thing an entity is. Shared by catalog and ontology."""

    BRAND = "brand"
    COMPANY = "company"
    CATEGORY = "category"
    LOCATION = "location"
