"""Permission policy tests.

Section 8.3/8.4: nothing destructive runs without approval, and anything
unlisted asks. These are unit tests over the policy file itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nucleo.configuracion import ConfigError
from seguridad.permisos import (
    Policy,
    default_policy,
    forbidden_tools,
    plan_requires_approval,
    policy_for,
)


def _write_permissions(tmp_path: Path, data: dict) -> Path:
    (tmp_path / "permisos.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path


def test_shipped_default_policy_is_confirm() -> None:
    assert default_policy() is Policy.CONFIRM


def test_unlisted_tool_falls_back_to_default(tmp_path: Path) -> None:
    directory = _write_permissions(
        tmp_path, {"herramientas": {}, "politica_por_defecto": "confirmar"}
    )
    resolved = policy_for("herramienta.inventada", directory)
    assert resolved.policy is Policy.CONFIRM
    assert resolved.is_default
    assert resolved.requires_approval


def test_missing_default_key_still_confirms(tmp_path: Path) -> None:
    """An incomplete config must fail safe, not fail open."""
    directory = _write_permissions(tmp_path, {"herramientas": {}})
    assert default_policy(directory) is Policy.CONFIRM
    assert policy_for("cualquiera", directory).requires_approval


def test_disabled_tool_is_forbidden(tmp_path: Path) -> None:
    directory = _write_permissions(
        tmp_path,
        {"herramientas": {"vision.act": {"habilitada": False, "politica": "auto"}}},
    )
    resolved = policy_for("vision.act", directory)
    assert resolved.is_forbidden


def test_invalid_policy_value_raises(tmp_path: Path) -> None:
    directory = _write_permissions(
        tmp_path, {"herramientas": {"fs.read": {"politica": "quiza"}}}
    )
    with pytest.raises(ConfigError, match="politica invalida"):
        policy_for("fs.read", directory)


def test_invalid_default_policy_raises(tmp_path: Path) -> None:
    directory = _write_permissions(
        tmp_path, {"herramientas": {}, "politica_por_defecto": "a_veces"}
    )
    with pytest.raises(ConfigError, match="politica_por_defecto invalida"):
        default_policy(directory)


def test_read_only_tools_may_be_automatic() -> None:
    assert not policy_for("fs.list").requires_approval
    assert not policy_for("fs.read").requires_approval


def test_destructive_tools_require_approval() -> None:
    for tool in ("fs.delete", "fs.move", "fs.write", "shell.run", "app.close"):
        assert policy_for(tool).requires_approval, f"{tool} deberia confirmar"


def test_plan_requiring_approval_names_the_reason() -> None:
    needs, reasons = plan_requires_approval(["fs.list", "fs.delete"])
    assert needs
    assert any("fs.delete" in reason for reason in reasons)


def test_read_only_plan_needs_no_approval() -> None:
    needs, reasons = plan_requires_approval(["fs.list", "fs.read"])
    assert not needs
    assert reasons == []


def test_vision_ships_confirmable_and_contained() -> None:
    """The shipped policy for `vision.act`, pinned deliberately.

    It shipped `habilitada: false` until 2026-08-14, blocked on ADR-0012.
    Now it exists, and what this pins is the shape it ships in, because
    two of the three properties are load-bearing:

    - `confirmar`, never `auto`. A keystroke is held by the whitelist in
      `accion/vision.py`; a click is held by nothing but the question,
      since no list can know whether the pixel under it says 'Guardar' or
      'Eliminar'. On `auto` the click would be the one action in Jarvis
      with no containment at all.
    - a non-empty allowlist, or it can drive no window — which is the
      containment `check_window_process` applies.

    Not a policy decision made in code: `permisos.yaml` still decides.
    This asserts what the file currently says, so that relaxing it is a
    visible edit to a test and not a quiet edit to a comment.
    """
    assert "vision.act" not in forbidden_tools(["fs.list", "vision.act"])

    resolved = policy_for("vision.act")
    assert resolved.policy is Policy.CONFIRM
    assert resolved.requires_approval
    assert resolved.allowlist, "sin allowlist no podria actuar sobre ninguna ventana"


def test_allowlist_is_read_for_shell() -> None:
    resolved = policy_for("shell.run")
    assert resolved.allowlist, "shell.run debe tener allowlist"
    assert "git" in resolved.allowlist


def test_allowed_paths_are_read() -> None:
    assert policy_for("fs.delete").allowed_paths
