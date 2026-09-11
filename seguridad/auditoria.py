"""Local audit log.

Section 8.2 requires every executed action to be recorded: tool,
arguments, policy applied, whether approval was asked and granted, the
result, and the verifier's observation. This module is that record.

Three properties it must keep:

- **Append-only, one JSON object per line.** A crash mid-write costs the
  last line, never the file. It is also readable with a text editor,
  which matters for an audit log nobody has built a viewer for yet.
- **Local, always.** The log never leaves the machine. There is no
  remote sink to configure, deliberately: adding one would contradict
  the premise of the project.
- **It records attempts, not just successes.** A blocked step is the
  most interesting line in the file. `registrar_bloqueo` exists so that
  denials are as loud in the log as executions.

The verifier's observation arrives after the action, so entries are
written once the outcome is known. A step that never returns leaves no
line; that is what `registrar_inicio` is for in Fase 3, when the retry
loop can hang.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nucleo.configuracion import PROJECT_ROOT, load_general_config

DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILENAME = "auditoria.jsonl"

# Argument values longer than this are truncated in the log. A `fs.write`
# of a large file would otherwise put the whole payload in the audit
# trail, which buries the fields that matter.
MAX_ARG_CHARS = 500

# Substrings that mark an argument as worth hiding. The log is local, but
# 'local' is not 'safe to paste into a bug report'.
_SENSITIVE_HINTS = ("password", "contrasena", "token", "secret", "api_key")


@dataclass
class EntradaAuditoria:
    """One line of the audit trail."""

    momento: str
    herramienta: str
    args: dict[str, Any]
    politica: str
    requirio_aprobacion: bool
    aprobado: bool | None
    resultado: str
    detalle: str = ""
    observacion: str = ""
    duracion_s: float | None = None
    orden: str = ""
    paso: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _redact(value: Any) -> Any:
    text = value if isinstance(value, str) else repr(value)
    if len(text) > MAX_ARG_CHARS:
        omitted = len(text) - MAX_ARG_CHARS
        return f"{text[:MAX_ARG_CHARS]}... [+{omitted} caracteres]"
    return value


def sanitize_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Truncate long values and mask ones that look like credentials."""
    if not args:
        return {}
    clean: dict[str, Any] = {}
    for key, value in args.items():
        lowered = str(key).lower()
        if any(hint in lowered for hint in _SENSITIVE_HINTS):
            clean[key] = "[oculto]"
        else:
            clean[key] = _redact(value)
    return clean


class Auditor:
    """Writes audit entries to a local JSONL file.

    Instantiating it creates the log directory. Reads its location from
    `config/jarvis.yaml` (`logs.directorio`) so the user can move it
    without touching code.
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = Path(log_dir) if log_dir else self._configured_dir()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / LOG_FILENAME

    @staticmethod
    def _configured_dir() -> Path:
        try:
            configured = (load_general_config().get("logs") or {}).get(
                "directorio", "logs"
            )
        except Exception:
            # A broken jarvis.yaml must not be able to switch auditing
            # off. Falling back to the default directory keeps the record
            # even when configuration is unusable.
            return DEFAULT_LOG_DIR
        candidate = Path(os.path.expandvars(str(configured))).expanduser()
        return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

    def _write(self, entry: EntradaAuditoria) -> EntradaAuditoria:
        line = json.dumps(asdict(entry), ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return entry

    def registrar(
        self,
        *,
        herramienta: str,
        args: dict[str, Any] | None,
        politica: str,
        resultado: str,
        requirio_aprobacion: bool = False,
        aprobado: bool | None = None,
        detalle: str = "",
        observacion: str = "",
        duracion_s: float | None = None,
        orden: str = "",
        paso: int | None = None,
        **extra: Any,
    ) -> EntradaAuditoria:
        """Record one attempted action, whatever its outcome."""
        return self._write(
            EntradaAuditoria(
                momento=_now(),
                herramienta=herramienta,
                args=sanitize_args(args),
                politica=politica,
                requirio_aprobacion=requirio_aprobacion,
                aprobado=aprobado,
                resultado=resultado,
                detalle=detalle,
                observacion=observacion,
                duracion_s=duracion_s,
                orden=orden,
                paso=paso,
                extra=extra,
            )
        )

    def registrar_bloqueo(
        self,
        *,
        herramienta: str,
        args: dict[str, Any] | None,
        politica: str,
        motivo: str,
        orden: str = "",
        paso: int | None = None,
    ) -> EntradaAuditoria:
        """Record an action that was refused before running.

        Denials are first-class entries, not a footnote: a planner that
        keeps reaching for a forbidden path is a signal worth being able
        to grep for.

        `observacion` repeats `motivo` on purpose. A refused step never
        reaches the verifier, so `ResultadoPaso.observacion` falls back
        to its motive — and the log has to store what the system has,
        not a blank. Measured on 2026-08-13.
        """
        return self.registrar(
            herramienta=herramienta,
            args=args,
            politica=politica,
            resultado="bloqueado",
            detalle=motivo,
            observacion=motivo,
            orden=orden,
            paso=paso,
        )

    def leer(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read entries back, oldest first. For tests and for the UI."""
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            entries = [json.loads(line) for line in handle if line.strip()]
        return entries[-limit:] if limit else entries
