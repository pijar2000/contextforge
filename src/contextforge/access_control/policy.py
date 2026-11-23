"""Assigns tenant, owner and allowed groups to documents at ingestion time.

Rules live in a YAML file and are matched against the path relative to the source root.
The first matching rule wins. Unmatched files get the default policy, which is restrictive
(administrators only) so that a forgotten rule never exposes a document.
"""

import fnmatch
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AccessPolicy:
    owner_id: str
    allowed_groups: tuple[str, ...]


class PolicyResolver:
    def __init__(self, default: AccessPolicy, rules: list[tuple[str, AccessPolicy]]):
        self._default = default
        self._rules = rules

    @classmethod
    def from_file(cls, path: Path) -> "PolicyResolver":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        default_raw = raw.get("default", {})
        default = AccessPolicy(
            owner_id=default_raw.get("owner_id", "system"),
            allowed_groups=tuple(default_raw.get("allowed_groups", ["administrator"])),
        )
        rules = [
            (
                rule["match"],
                AccessPolicy(
                    owner_id=rule.get("owner_id", default.owner_id),
                    allowed_groups=tuple(rule.get("allowed_groups", [])),
                ),
            )
            for rule in raw.get("rules", [])
        ]
        return cls(default, rules)

    def resolve(self, relative_path: str) -> AccessPolicy:
        posix = relative_path.replace("\\", "/")
        for pattern, policy in self._rules:
            if fnmatch.fnmatch(posix, pattern):
                return policy
        return self._default
