import hashlib

import pytest

from contextforge.access_control.directory import UserDirectory
from contextforge.access_control.models import User, access_filter_for, can_access, payload_allows
from contextforge.access_control.policy import PolicyResolver

ENG = User("bob", "acme", ("engineering",))
ADMIN = User("root", "acme", ("administrator",))


def test_group_membership_grants_access():
    assert can_access(ENG, "acme", "x", ["engineering"])
    assert not can_access(ENG, "acme", "x", ["product"])


def test_empty_allowed_groups_denies_everyone_except_owner_and_admin():
    assert not can_access(ENG, "acme", "x", [])
    assert can_access(ENG, "acme", "bob", [])
    assert can_access(ADMIN, "acme", "x", [])


def test_tenant_boundary_applies_even_to_administrators():
    assert not can_access(ADMIN, "other", "x", ["administrator"])
    assert not payload_allows({"tenant_id": "other", "allowed_groups": ["administrator"]},
                              access_filter_for(ADMIN))


def test_payload_rule_matches_user_rule():
    payload = {"tenant_id": "acme", "owner_id": "x", "allowed_groups": ["engineering"]}
    assert payload_allows(payload, access_filter_for(ENG))
    assert not payload_allows({**payload, "allowed_groups": ["product"]}, access_filter_for(ENG))


def test_policy_first_match_wins_and_default_is_restrictive(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(
        "default: {owner_id: system, allowed_groups: [administrator]}\n"
        "rules:\n"
        "  - {match: 'hr/secret*', allowed_groups: [administrator]}\n"
        "  - {match: 'hr/*', owner_id: hr, allowed_groups: [general_employee, administrator]}\n"
    )
    policy = PolicyResolver.from_file(f)
    assert policy.resolve("hr/secret-plan.md").allowed_groups == ("administrator",)
    assert "general_employee" in policy.resolve("hr/handbook.md").allowed_groups
    assert policy.resolve("misc/unlisted.md").allowed_groups == ("administrator",)


def test_authentication_uses_key_digests(tmp_path):
    digest = hashlib.sha256(b"secret-key").hexdigest()
    directory = UserDirectory([{"user_id": "u", "tenant_id": "t", "roles": ["product"], "api_key_sha256": digest}])
    assert directory.authenticate("secret-key").user_id == "u"
    assert directory.authenticate("wrong") is None
    assert directory.authenticate(None) is None
    assert directory.authenticate("") is None


def test_unknown_role_in_user_file_is_rejected():
    with pytest.raises(ValueError):
        UserDirectory([{"user_id": "u", "tenant_id": "t", "roles": ["wizard"], "api_key_sha256": "x"}])


def test_repository_user_file_loads():
    from pathlib import Path

    users = UserDirectory.from_file(Path(__file__).resolve().parents[2] / "config" / "users.yaml")
    assert users.authenticate("cf-dev-alice").is_admin
    assert users.authenticate("cf-dev-erin").roles == ("general_employee",)
