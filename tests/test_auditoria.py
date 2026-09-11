"""Audit log tests.

The audit trail is the only record of what the agent did. What is tested
here is mostly that it cannot quietly stop existing: a denial is logged
as loudly as an execution, and a broken jarvis.yaml does not switch
auditing off.
"""

from __future__ import annotations

import json
from pathlib import Path

from seguridad.auditoria import MAX_ARG_CHARS, Auditor, sanitize_args


def test_entry_is_written_as_one_json_line(tmp_path: Path) -> None:
    auditor = Auditor(tmp_path)
    auditor.registrar(
        herramienta="fs.list",
        args={"ruta": "C:\\Downloads"},
        politica="auto",
        resultado="ok",
    )
    lines = auditor.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["herramienta"] == "fs.list"
    assert entry["args"] == {"ruta": "C:\\Downloads"}
    assert entry["resultado"] == "ok"


def test_entries_append_never_overwrite(tmp_path: Path) -> None:
    auditor = Auditor(tmp_path)
    for i in range(3):
        auditor.registrar(
            herramienta="fs.list", args={"i": i}, politica="auto", resultado="ok"
        )
    # A fresh Auditor over the same directory must not truncate.
    Auditor(tmp_path).registrar(
        herramienta="fs.read", args={}, politica="auto", resultado="ok"
    )
    assert len(Auditor(tmp_path).leer()) == 4


def test_blocked_action_is_recorded(tmp_path: Path) -> None:
    """A refusal is the most interesting line in the file."""
    auditor = Auditor(tmp_path)
    auditor.registrar_bloqueo(
        herramienta="fs.delete",
        args={"ruta": "C:\\Windows"},
        politica="confirmar",
        motivo="fuera de las rutas permitidas",
        paso=2,
    )
    entry = auditor.leer()[-1]
    assert entry["resultado"] == "bloqueado"
    assert "fuera de las rutas permitidas" in entry["detalle"]
    assert entry["paso"] == 2


def test_approval_outcome_is_recorded(tmp_path: Path) -> None:
    auditor = Auditor(tmp_path)
    auditor.registrar(
        herramienta="fs.delete",
        args={"ruta": "C:\\Downloads\\viejo.zip"},
        politica="confirmar",
        requirio_aprobacion=True,
        aprobado=False,
        resultado="cancelado",
    )
    entry = auditor.leer()[-1]
    assert entry["requirio_aprobacion"] is True
    assert entry["aprobado"] is False


def test_verifier_observation_has_a_field(tmp_path: Path) -> None:
    """Fase 3 writes here; the column exists from the start."""
    auditor = Auditor(tmp_path)
    auditor.registrar(
        herramienta="fs.move",
        args={},
        politica="confirmar",
        resultado="ok",
        observacion="el archivo existe en el destino",
    )
    assert auditor.leer()[-1]["observacion"] == "el archivo existe en el destino"


def test_long_argument_is_truncated(tmp_path: Path) -> None:
    """An `fs.write` payload must not bury the fields that matter."""
    auditor = Auditor(tmp_path)
    auditor.registrar(
        herramienta="fs.write",
        args={"contenido": "x" * (MAX_ARG_CHARS * 3)},
        politica="confirmar",
        resultado="ok",
    )
    logged = auditor.leer()[-1]["args"]["contenido"]
    assert len(logged) < MAX_ARG_CHARS * 2
    assert "caracteres]" in logged


def test_credential_like_arguments_are_masked() -> None:
    clean = sanitize_args({"ruta": "C:\\x", "password": "hunter2", "api_key": "k"})
    assert clean["ruta"] == "C:\\x"
    assert clean["password"] == "[oculto]"
    assert clean["api_key"] == "[oculto]"


def test_broken_general_config_does_not_disable_auditing(
    tmp_path: Path, monkeypatch
) -> None:
    """Auditing must survive a config it cannot read."""
    import seguridad.auditoria as auditoria

    def explode(*args, **kwargs):
        raise RuntimeError("jarvis.yaml roto")

    monkeypatch.setattr(auditoria, "load_general_config", explode)
    auditor = Auditor()
    assert auditor.log_dir == auditoria.DEFAULT_LOG_DIR


def test_reading_missing_log_returns_empty(tmp_path: Path) -> None:
    assert Auditor(tmp_path).leer() == []


def test_leer_limit_returns_most_recent(tmp_path: Path) -> None:
    auditor = Auditor(tmp_path)
    for i in range(5):
        auditor.registrar(
            herramienta=f"fs.t{i}", args={}, politica="auto", resultado="ok"
        )
    recent = auditor.leer(limit=2)
    assert [e["herramienta"] for e in recent] == ["fs.t3", "fs.t4"]
