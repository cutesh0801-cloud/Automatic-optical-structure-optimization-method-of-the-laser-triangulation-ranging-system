"""Versioned project persistence for Scheimpflug OptiMeter.

Only authoritative user input is persisted.  Calculated/derived values are
deliberately discarded while loading and saving so a project is always
recomputed by the current optical model.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PROJECT_SUFFIX = ".scheimpflug.json"


def default_workbook_design_input() -> dict[str, Any]:
    """Return the workbook's 17.5 mm / 150 mm reference as editable input."""

    return {
        "mode": "workbook",
        "sensor_axis": "height",
        "v_mm": 150.0,
        "d_mm": 100.0,
        "sensor_length_mm": 5.4378,
        "sensor_length_linked": True,
        "focal_length_literal_mm": 17.5,
        "focal_length_linked": True,
        "alpha_manual": False,
        "alpha_deg": None,
        "user_lens_presets": {"schema_version": 1, "presets": []},
    }


def default_hardware() -> dict[str, Any]:
    """Return the workbook camera and the lens identified by DWG 58206."""

    return {
        "camera_id": "basler-aca1300-60gm",
        "lens_id": "edmund-58-206",
    }


class ProjectError(ValueError):
    """Raised when a project document is invalid or unsupported."""


def _json_object(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Make a detached, JSON-compatible object and reject exotic values."""

    candidate = dict(value or {})
    try:
        encoded = json.dumps(candidate, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProjectError(f"JSON으로 저장할 수 없는 프로젝트 값입니다: {exc}") from exc
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):  # Defensive; ``candidate`` is already a dict.
        raise ProjectError("프로젝트 항목은 JSON 객체여야 합니다.")
    return decoded


@dataclass(frozen=True, slots=True)
class ProjectDocument:
    """Schema-v1 authoritative project data."""

    project_name: str = "새 프로젝트"
    design_input: dict[str, Any] = field(default_factory=default_workbook_design_input)
    hardware: dict[str, Any] = field(default_factory=default_hardware)
    selected_optimization: dict[str, Any] | None = None
    ui_state: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ProjectError(
                f"지원하지 않는 프로젝트 스키마입니다: {self.schema_version} "
                f"(지원: {SCHEMA_VERSION})"
            )
        if not isinstance(self.project_name, str) or not self.project_name.strip():
            raise ProjectError("프로젝트 이름은 비어 있을 수 없습니다.")

        # Frozen dataclasses can still contain a caller-owned mutable dict.  Copy
        # and validate each one so saved documents cannot change behind our back.
        object.__setattr__(self, "project_name", self.project_name.strip())
        object.__setattr__(self, "design_input", _json_object(self.design_input))
        object.__setattr__(self, "hardware", _json_object(self.hardware))
        object.__setattr__(self, "ui_state", _json_object(self.ui_state))
        if self.selected_optimization is not None:
            object.__setattr__(
                self,
                "selected_optimization",
                _json_object(self.selected_optimization),
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the stable wire representation."""

        document = asdict(self)
        # Keep schema at the top for readable files and simple diagnostics.
        return {
            "schema_version": document["schema_version"],
            "project_name": document["project_name"],
            "design_input": document["design_input"],
            "hardware": document["hardware"],
            "selected_optimization": document["selected_optimization"],
            "ui_state": document["ui_state"],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProjectDocument:
        """Parse a project and ignore non-authoritative legacy derived fields."""

        if not isinstance(raw, Mapping):
            raise ProjectError("프로젝트 최상위 값은 JSON 객체여야 합니다.")
        version = raw.get("schema_version")
        if type(version) is not int:  # bool must not be accepted as schema 1.
            raise ProjectError("schema_version 정수 값이 필요합니다.")
        if version != SCHEMA_VERSION:
            raise ProjectError(
                f"지원하지 않는 프로젝트 스키마입니다: {version} (지원: {SCHEMA_VERSION})"
            )

        def mapping_or_empty(key: str) -> dict[str, Any]:
            value = raw.get(key, {})
            if value is None:
                return {}
            if not isinstance(value, Mapping):
                raise ProjectError(f"{key} 항목은 JSON 객체여야 합니다.")
            return dict(value)

        def optional_mapping(key: str) -> dict[str, Any] | None:
            value = raw.get(key)
            if value is None:
                return None
            if not isinstance(value, Mapping):
                raise ProjectError(f"{key} 항목은 JSON 객체 또는 null이어야 합니다.")
            return dict(value)

        return cls(
            schema_version=version,
            project_name=raw.get("project_name", "새 프로젝트"),
            design_input=mapping_or_empty("design_input"),
            hardware=mapping_or_empty("hardware"),
            selected_optimization=optional_mapping("selected_optimization"),
            ui_state=mapping_or_empty("ui_state"),
        )


def normalize_project_path(path: str | Path) -> Path:
    """Append the compound project suffix when the caller omitted it."""

    result = Path(path).expanduser()
    if not str(result).lower().endswith(PROJECT_SUFFIX):
        if result.suffix.lower() == ".json":
            result = result.with_name(result.stem + PROJECT_SUFFIX)
        else:
            result = result.with_name(result.name + PROJECT_SUFFIX)
    return result


def save_project(path: str | Path, document: ProjectDocument) -> Path:
    """Atomically save *document* and return its normalized path."""

    target = normalize_project_path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        document.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        allow_nan=False,
    )

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    except OSError as exc:
        if temporary_name is not None:
            with suppress(OSError):
                Path(temporary_name).unlink(missing_ok=True)
        raise ProjectError(f"프로젝트를 저장하지 못했습니다: {exc}") from exc
    return target


def load_project(path: str | Path) -> ProjectDocument:
    """Load and validate a schema-v1 project."""

    source = Path(path).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectError(f"프로젝트를 열지 못했습니다: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(
            f"프로젝트 JSON 형식이 잘못되었습니다 ({exc.lineno}:{exc.colno})."
        ) from exc
    return ProjectDocument.from_dict(raw)
