"""Entitlements: who bought what, reduced to a cacheable shape.

The transcript referenced an ``EntitlementResolver`` without ever defining
it; the protocol and an in-memory implementation live here. Grants are the
admin-plane records (mutable store); ``EntitlementShape`` is the immutable
projection input derived from them per request.

The fingerprint fix
-------------------
The transcript's ``EntitlementShape.fingerprint`` hashed ``organization_id``
and ``roles`` into the cache key. That silently reduced the manifest cache
to one entry per org -- defeating the stated goal ("many users in the same
role, package, and add-on set should share the same manifest"). The rule
here: **hash exactly the inputs the projector reads, nothing else.** The
projector reads catalog version + grant sets, so that is the whole key.
org_id stays on the shape for auditing/context; it stays out of the hash.
If projection ever consumes roles or org-specific catalog overrides, those
inputs -- and only those -- join the hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from .ids import AddOnId, OrgId, PackageId, UserId


# --------------------------------------------------------------------------
# Grant records (admin plane)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageGrant:
    org_id: OrgId
    package_id: PackageId


@dataclass(frozen=True)
class AddOnGrant:
    org_id: OrgId
    addon_id: AddOnId


class GrantStore:
    """In-memory stand-in for the billing/entitlement database.

    Deliberately mutable: purchases and revocations happen at runtime.
    Everything downstream of this store is immutable and cacheable.
    """

    def __init__(self) -> None:
        self._package_grants: set[PackageGrant] = set()
        self._addon_grants: set[AddOnGrant] = set()

    def grant_package(self, org: OrgId, package: PackageId) -> None:
        self._package_grants.add(PackageGrant(org, package))

    def grant_addon(self, org: OrgId, addon: AddOnId) -> None:
        self._addon_grants.add(AddOnGrant(org, addon))

    def revoke_package(self, org: OrgId, package: PackageId) -> None:
        self._package_grants.discard(PackageGrant(org, package))

    def revoke_addon(self, org: OrgId, addon: AddOnId) -> None:
        self._addon_grants.discard(AddOnGrant(org, addon))

    def packages_for(self, org: OrgId) -> frozenset[PackageId]:
        return frozenset(
            g.package_id for g in self._package_grants if g.org_id == org
        )

    def addons_for(self, org: OrgId) -> frozenset[AddOnId]:
        return frozenset(
            g.addon_id for g in self._addon_grants if g.org_id == org
        )


# --------------------------------------------------------------------------
# Entitlement shape (projection input + cache identity)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntitlementShape:
    org_id: OrgId
    roles: frozenset[str]
    package_ids: frozenset[PackageId]
    addon_ids: frozenset[AddOnId]

    def fingerprint(
        self,
        catalog_version: str,
        org_overrides_version: str | None = None,
    ) -> str:
        """Cache identity for manifest projection.

        Excludes org_id and roles by design -- see module docstring. The
        optional ``org_overrides_version`` slot exists for the day an org
        gets bespoke catalog overrides; passing it re-scopes the key to
        exactly that org's override state without hashing the org itself.
        """
        payload: dict[str, object] = {
            "catalog_version": catalog_version,
            "package_ids": sorted(self.package_ids),
            "addon_ids": sorted(self.addon_ids),
        }
        if org_overrides_version is not None:
            payload["org_overrides_version"] = org_overrides_version
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class EntitlementResolver(Protocol):
    """Resolves a user/org to their current entitlement shape."""

    def resolve(self, user: UserId, org: OrgId) -> EntitlementShape: ...


@dataclass
class InMemoryEntitlementResolver:
    store: GrantStore
    roles_by_user: Mapping[UserId, frozenset[str]] = field(
        default_factory=dict
    )

    def resolve(self, user: UserId, org: OrgId) -> EntitlementShape:
        return EntitlementShape(
            org_id=org,
            roles=self.roles_by_user.get(user, frozenset()),
            package_ids=self.store.packages_for(org),
            addon_ids=self.store.addons_for(org),
        )
