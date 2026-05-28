"""Typed reference resolution for harness static review artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SAFE_REF_KINDS = {"section", "path", "design", "obligation", "decision", "architecture"}
SENSITIVE_PATH_MARKERS = (".env", ".ssh", "secret", "password", "private key")


@dataclass(frozen=True)
class ResolvedReference:
    raw: str
    kind: str
    value: str
    canonical: str
    metadata: dict[str, Any] = field(default_factory=dict)
    legacy: bool = False


class ReferenceUniverse:
    def __init__(self) -> None:
        self._refs: dict[tuple[str, str], dict[str, Any]] = {}
        self._legacy_paths: set[str] = set()

    def add(self, kind: str, value: str, **metadata: Any) -> None:
        self._refs[(kind, value)] = dict(metadata)

    def add_path(self, value: str, **metadata: Any) -> None:
        self.add("path", value, **metadata)
        self._legacy_paths.add(value)

    def metadata_for(self, kind: str, value: str) -> dict[str, Any] | None:
        return self._refs.get((kind, value))

    def has_legacy_path(self, value: str) -> bool:
        return value in self._legacy_paths or ("path", value) in self._refs


def _redact_ref(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE_PATH_MARKERS):
        return "[redacted-ref]"
    return value


def _unsafe_path(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or value.startswith("/")
        or "://" in value
        or ".." in value.split("/")
        or any(marker in lowered for marker in SENSITIVE_PATH_MARKERS)
    )


def resolve_reference(
    raw_ref: str,
    universe: ReferenceUniverse | set[str],
) -> tuple[ResolvedReference | None, str | None]:
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        return None, "reference must be a non-empty string."
    raw_ref = raw_ref.strip()
    if ":" in raw_ref:
        kind, value = raw_ref.split(":", 1)
        kind = kind.strip()
        value = value.strip()
    else:
        kind = "path"
        value = raw_ref
    if kind not in SAFE_REF_KINDS:
        return None, f"unsupported reference kind: {kind!r}"
    if kind == "path" and _unsafe_path(value):
        return None, f"unsafe reference: {_redact_ref(raw_ref)}"
    if kind != "path" and (not value or value.startswith("/") or "://" in value or ".." in value.split("/")):
        return None, f"unsafe reference: {_redact_ref(raw_ref)}"

    canonical = f"{kind}:{value}"
    legacy = ":" not in raw_ref and kind == "path"
    if isinstance(universe, set):
        if raw_ref not in universe and canonical not in universe and value not in universe:
            return None, f"unknown reference: {_redact_ref(raw_ref)}"
        return ResolvedReference(raw_ref, kind, value, canonical, {}, legacy), None

    metadata = universe.metadata_for(kind, value)
    if metadata is None and legacy and universe.has_legacy_path(value):
        metadata = universe.metadata_for("path", value) or {}
    if metadata is None:
        return None, f"unknown reference: {_redact_ref(raw_ref)}"
    return ResolvedReference(raw_ref, kind, value, canonical, dict(metadata), legacy), None
