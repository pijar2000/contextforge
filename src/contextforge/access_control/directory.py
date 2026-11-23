"""Local development authentication: API keys mapped to users from a YAML file.

Only SHA-256 digests of keys are stored. This is deliberately simple; see docs/access-control.md
for what it does not protect against.
"""

import hashlib
import hmac
from pathlib import Path

import yaml

from contextforge.access_control.models import ROLES, User


class UserDirectory:
    def __init__(self, entries: list[dict]):
        self._by_digest: dict[str, User] = {}
        self._by_id: dict[str, User] = {}
        for entry in entries:
            roles = tuple(entry["roles"])
            unknown = set(roles) - set(ROLES)
            if unknown:
                raise ValueError(f"user {entry['user_id']} has unknown roles: {sorted(unknown)}")
            user = User(
                user_id=entry["user_id"],
                tenant_id=entry["tenant_id"],
                roles=roles,
                display_name=entry.get("display_name", entry["user_id"]),
            )
            self._by_digest[entry["api_key_sha256"]] = user
            self._by_id[user.user_id] = user

    @classmethod
    def from_file(cls, path: Path) -> "UserDirectory":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(raw.get("users", []))

    @staticmethod
    def digest(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def authenticate(self, api_key: str | None) -> User | None:
        if not api_key:
            return None
        candidate = self.digest(api_key)
        found: User | None = None
        for stored, user in self._by_digest.items():
            # constant-time compare on every entry so timing does not reveal valid digests
            if hmac.compare_digest(stored, candidate):
                found = user
        return found

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def all_users(self) -> list[User]:
        return list(self._by_id.values())
