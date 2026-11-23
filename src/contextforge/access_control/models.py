"""Document-level authorization primitives.

Model: a document belongs to one tenant, has an owner and a list of allowed groups.
A user sees a document when they are in the same tenant AND (they are an administrator OR
they own it OR one of their roles is listed in the document's allowed groups).
A document without allowed groups is therefore visible only to its owner and administrators.
"""

from dataclasses import dataclass

ADMIN_ROLE = "administrator"
ROLES = ("administrator", "engineering", "product", "operations", "general_employee")


@dataclass(frozen=True)
class User:
    user_id: str
    tenant_id: str
    roles: tuple[str, ...]
    display_name: str = ""

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles


@dataclass(frozen=True)
class AccessFilter:
    """The subset of a user's identity that index backends need to filter on."""

    tenant_id: str
    user_id: str
    groups: tuple[str, ...]
    unrestricted_in_tenant: bool = False


def access_filter_for(user: User) -> AccessFilter:
    return AccessFilter(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        groups=tuple(user.roles),
        unrestricted_in_tenant=user.is_admin,
    )


def can_access(user: User, tenant_id: str, owner_id: str | None, allowed_groups) -> bool:
    if user.tenant_id != tenant_id:
        return False
    if user.is_admin:
        return True
    if owner_id and owner_id == user.user_id:
        return True
    return bool(set(user.roles) & set(allowed_groups or ()))


def payload_allows(payload: dict, flt: AccessFilter) -> bool:
    """Same rule as `can_access`, evaluated against an index payload (used by in-memory indexes)."""
    if payload.get("tenant_id") != flt.tenant_id:
        return False
    if flt.unrestricted_in_tenant:
        return True
    if payload.get("owner_id") == flt.user_id:
        return True
    return bool(set(flt.groups) & set(payload.get("allowed_groups") or ()))
