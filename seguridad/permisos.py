"""Permission policy.

Reads `config/permisos.yaml` and answers what may run, under which
approval policy, and — since Fase 2 — over which paths and commands.

The policy is authoritative over the model. The planner reports whether
it *believes* a plan is dangerous, but that self-assessment is advice: a
model that forgets to flag `fs.delete` must not thereby make a deletion
automatic. Approval is granted by policy, never by the LLM.

ADR-0008 raised the stakes of the second half of this module. The
executor runs under the user's own Windows account, so `rutas_permitidas`
and `allowlist` are not a convenience layer on top of OS isolation —
**they are the isolation.** Nothing catches a path that slips past
`check_path`. That is why containment here is decided on the *resolved*
path (symlinks and `..` already collapsed) and by parent-chain
containment rather than string prefixes, and why every unclear case
denies instead of allowing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nucleo.configuracion import CONFIG_DIR, ConfigError, load_yaml


class Policy(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirmar"
    FORBIDDEN = "prohibido"


@dataclass(frozen=True)
class ToolPolicy:
    tool: str
    enabled: bool
    policy: Policy
    allowed_paths: tuple[str, ...] = ()
    allowlist: tuple[str, ...] = ()
    # True when the tool is not named in the file and fell back to the
    # default policy. Surfaced so the UI can show what was inferred.
    is_default: bool = False

    @property
    def requires_approval(self) -> bool:
        return self.policy is Policy.CONFIRM

    @property
    def is_forbidden(self) -> bool:
        return self.policy is Policy.FORBIDDEN or not self.enabled


def load_permissions(config_dir: Path | None = None) -> dict[str, Any]:
    directory = config_dir or CONFIG_DIR
    return load_yaml(directory / "permisos.yaml")


def default_policy(config_dir: Path | None = None) -> Policy:
    """The fallback for unlisted tools.

    Defaults to `confirmar` even if the key is missing: the safe reading
    of an incomplete config is to ask, never to act.
    """
    data = load_permissions(config_dir)
    raw = data.get("politica_por_defecto", Policy.CONFIRM.value)
    try:
        return Policy(raw)
    except ValueError as exc:
        raise ConfigError(
            f"politica_por_defecto invalida: {raw!r}. "
            f"Valores validos: {[p.value for p in Policy]}."
        ) from exc


def policy_for(tool: str, config_dir: Path | None = None) -> ToolPolicy:
    """Resolve the policy for one tool."""
    data = load_permissions(config_dir)
    tools = data.get("herramientas", {}) or {}
    entry = tools.get(tool)

    if entry is None:
        return ToolPolicy(
            tool=tool,
            enabled=True,
            policy=default_policy(config_dir),
            is_default=True,
        )

    raw = entry.get("politica", Policy.CONFIRM.value)
    try:
        policy = Policy(raw)
    except ValueError as exc:
        raise ConfigError(
            f"politica invalida para '{tool}': {raw!r}. "
            f"Valores validos: {[p.value for p in Policy]}."
        ) from exc

    return ToolPolicy(
        tool=tool,
        enabled=bool(entry.get("habilitada", True)),
        policy=policy,
        allowed_paths=tuple(entry.get("rutas_permitidas", []) or []),
        allowlist=tuple(entry.get("allowlist", []) or []),
    )


def plan_requires_approval(
    tools: list[str], config_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Whether a set of tools needs approval, and which ones force it.

    Returns:
        (requires_approval, reasons) — reasons are user-facing Spanish
        strings naming the tools that triggered it.
    """
    reasons: list[str] = []
    for tool in tools:
        resolved = policy_for(tool, config_dir)
        if resolved.is_forbidden:
            reasons.append(f"'{tool}' esta prohibida o deshabilitada")
        elif resolved.requires_approval:
            suffix = " (por politica por defecto)" if resolved.is_default else ""
            reasons.append(f"'{tool}' requiere confirmacion{suffix}")
    return bool(reasons), reasons


def forbidden_tools(
    tools: list[str], config_dir: Path | None = None
) -> list[str]:
    """Tools in the list that may not run at all."""
    return [t for t in tools if policy_for(t, config_dir).is_forbidden]


# --------------------------------------------------------------------
# Containment (Fase 2). See the ADR-0008 note in the module docstring.
# --------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """The verdict on one concrete argument.

    `reason` is user-facing Spanish: it is shown when a step is blocked
    and written to the audit log, so it has to name the actual cause, not
    just say no.
    """

    allowed: bool
    reason: str = ""
    resolved: Path | None = None

    def __bool__(self) -> bool:
        return self.allowed


def _expand(raw: str) -> Path:
    """Expand environment variables and `~`, without touching the disk."""
    return Path(os.path.expandvars(str(raw).strip())).expanduser()


def _is_unc(path: Path) -> bool:
    """True for `\\\\server\\share` style paths.

    A UNC path reaches another machine. Every root in permisos.yaml is
    local, so a UNC path can never be contained by one — but it is
    rejected explicitly rather than left to fail containment, because the
    reason the user needs to read is 'red', not 'fuera de las rutas'.
    """
    text = str(path)
    return text.startswith("\\\\") or text.startswith("//")


def allowed_roots(tool: str, config_dir: Path | None = None) -> list[Path]:
    """The resolved roots a tool may touch.

    Raises:
        ConfigError: if a root still contains an unexpanded `%VAR%`. A
            root that does not expand would silently contain nothing and
            turn into a deny-everything rule that looks like a bug in the
            tool. Failing loudly at config level is the honest outcome.
    """
    policy = policy_for(tool, config_dir)
    roots: list[Path] = []
    for raw in policy.allowed_paths:
        expanded = _expand(raw)
        if "%" in str(expanded):
            raise ConfigError(
                f"rutas_permitidas de '{tool}' contiene una variable que no "
                f"se pudo expandir: {raw!r}"
            )
        roots.append(expanded.resolve())
    return roots


def check_path(
    tool: str, raw_path: Any, config_dir: Path | None = None
) -> Check:
    """Whether `tool` may touch `raw_path`.

    Denies by default. In particular a tool with no `rutas_permitidas`
    gets nothing: an empty list is read as 'nowhere', never as
    'anywhere'. That reading is what makes an incomplete permisos.yaml
    safe instead of wide open.
    """
    policy = policy_for(tool, config_dir)
    if policy.is_forbidden:
        return Check(False, f"'{tool}' esta prohibida o deshabilitada")

    if raw_path is None or not str(raw_path).strip():
        return Check(False, f"'{tool}' recibio una ruta vacia")

    if "\0" in str(raw_path):
        return Check(False, "la ruta contiene un byte nulo")

    candidate = _expand(raw_path)
    if _is_unc(candidate):
        return Check(
            False, "las rutas de red (UNC) no estan permitidas: solo disco local"
        )

    roots = allowed_roots(tool, config_dir)
    if not roots:
        return Check(
            False,
            f"'{tool}' no tiene rutas_permitidas en permisos.yaml, "
            "asi que no puede tocar ninguna ruta",
        )

    # resolve() collapses `..` and follows symlinks, so containment is
    # decided on where the path really lands. Checking the raw string
    # instead would let `Downloads\..\..\Windows` through.
    resolved = candidate.resolve()

    for root in roots:
        if resolved == root or root in resolved.parents:
            return Check(True, resolved=resolved)

    listed = ", ".join(str(r) for r in roots)
    return Check(
        False,
        f"la ruta {resolved} esta fuera de las rutas permitidas para "
        f"'{tool}' ({listed})",
        resolved=resolved,
    )


# Anything that lets one command turn into two, or redirect output.
# `shell.run` is allowlisted by program name, and that allowlist means
# nothing if `git status & del C:\...` counts as running `git`.
_SHELL_OPERATORS = ("&", "|", ";", "`", "$(", "\n", "\r", ">", "<")


def check_command(
    tool: str, raw_command: Any, config_dir: Path | None = None
) -> Check:
    """Whether `tool` may run `raw_command`.

    Two independent gates: the command may chain nothing, and its program
    must be on the allowlist. Both must pass.
    """
    policy = policy_for(tool, config_dir)
    if policy.is_forbidden:
        return Check(False, f"'{tool}' esta prohibida o deshabilitada")

    command = str(raw_command or "").strip()
    if not command:
        return Check(False, f"'{tool}' recibio un comando vacio")

    for operator in _SHELL_OPERATORS:
        if operator in command:
            return Check(
                False,
                f"el comando contiene {operator!r}, que permite encadenar o "
                "redirigir; solo se admite un unico comando simple",
            )

    # `%VAR%` is expanded by cmd.exe *after* this check would have run, so
    # the string vetted here would not be the string executed. Rejected
    # rather than expanded: a check that inspects a different command than
    # the one that runs is not a check.
    if "%" in command:
        return Check(
            False,
            "el comando contiene '%', que cmd.exe expandiria despues de "
            "esta validacion; escribe la ruta completa",
        )

    if not policy.allowlist:
        return Check(
            False,
            f"'{tool}' no tiene allowlist en permisos.yaml, "
            "asi que no puede ejecutar ningun comando",
        )

    program = Path(command.split()[0]).name.lower()
    program = program[:-4] if program.endswith(".exe") else program

    allowed = {p.strip().lower() for p in policy.allowlist}
    if program not in allowed:
        listed = ", ".join(sorted(allowed))
        return Check(
            False,
            f"'{program}' no esta en la allowlist de '{tool}' ({listed})",
        )

    return Check(True)


# Only these reach the network. The rest are refused by scheme, before
# any allowlist is consulted, because they are not "a different site" —
# they are a different *capability*: `file://` reads the disk without
# going through fs.*, `javascript:` executes in the page, and `data:` and
# `view-source:` smuggle content past the origin the user approved.
_ESQUEMAS_WEB = ("http", "https")


def check_url(tool: str, raw_url: Any, config_dir: Path | None = None) -> Check:
    """Whether `tool` may navigate to `raw_url`.

    Two independent gates, in this order: the scheme must be one that
    actually means 'a web page', and the host must be allowlisted.
    Scheme first, because a `file:///C:/Windows/...` URL is not a domain
    question — it is `fs.read` wearing a disguise, and it would bypass
    `rutas_permitidas` entirely.
    """
    policy = policy_for(tool, config_dir)
    if policy.is_forbidden:
        return Check(False, f"'{tool}' esta prohibida o deshabilitada")

    texto = str(raw_url or "").strip()
    if not texto:
        return Check(False, f"'{tool}' recibio una URL vacia")

    try:
        parsed = urlparse(texto)
    except ValueError as exc:
        return Check(False, f"URL invalida: {exc}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ESQUEMAS_WEB:
        return Check(
            False,
            f"el esquema '{scheme or '(ninguno)'}' no esta permitido; "
            f"solo {' y '.join(_ESQUEMAS_WEB)}. Para leer archivos usa fs.read.",
        )

    if "@" in (parsed.netloc or ""):
        # user:pass@host makes the visible host differ from the real one,
        # which would let an approval prompt show something other than
        # where the browser actually goes.
        return Check(False, "la URL lleva credenciales incrustadas (@)")

    host = (parsed.hostname or "").lower()
    if not host:
        return Check(False, "la URL no tiene dominio")

    if not policy.allowlist:
        return Check(
            False,
            f"'{tool}' no tiene allowlist de dominios en permisos.yaml, "
            "asi que no puede abrir ninguna pagina",
        )

    permitidos = {d.strip().lower().lstrip(".") for d in policy.allowlist if d.strip()}
    for dominio in permitidos:
        # `endswith('.' + dominio)` and not a bare prefix check: otherwise
        # `example.com.atacante.net` and `noexample.com` would both pass.
        if host == dominio or host.endswith(f".{dominio}"):
            return Check(True)

    listados = ", ".join(sorted(permitidos))
    return Check(
        False,
        f"el dominio '{host}' no esta en la allowlist de '{tool}' ({listados})",
    )


def check_allowlist(
    tool: str, raw_name: Any, config_dir: Path | None = None
) -> Check:
    """Whether `tool` may act on the named program.

    This is `app.launch`'s gate, and it is a security control, not a
    convenience. Starting an arbitrary executable is arbitrary code
    execution — the exact thing `shell.run`'s allowlist exists to
    prevent. Without this check, `app.launch("cmd.exe")` would walk
    straight around it, and the careful command allowlist above would be
    decoration.

    Only bare program names are accepted. A path is refused rather than
    resolved: `C:\\algo\\notepad.exe` has an allowlisted *basename* while
    being an entirely different binary, so matching on basename alone
    would be a hole. Bare names go through the normal PATH lookup, which
    is the behaviour the user's allowlist entry describes.
    """
    policy = policy_for(tool, config_dir)
    if policy.is_forbidden:
        return Check(False, f"'{tool}' esta prohibida o deshabilitada")

    name = str(raw_name or "").strip().strip('"').strip("'")
    if not name:
        return Check(False, f"'{tool}' recibio un nombre vacio")

    if any(char in name for char in ("\\", "/", ":")):
        return Check(
            False,
            f"'{tool}' solo admite el nombre del programa, no una ruta "
            f"({name!r}); anade el programa a la allowlist por su nombre",
        )

    for operator in _SHELL_OPERATORS:
        if operator in name:
            return Check(False, f"el nombre contiene {operator!r}")

    if not policy.allowlist:
        return Check(
            False,
            f"'{tool}' no tiene allowlist en permisos.yaml, "
            "asi que no puede abrir ninguna aplicacion",
        )

    normalised = name.lower()
    normalised = normalised[:-4] if normalised.endswith(".exe") else normalised

    allowed = {p.strip().lower() for p in policy.allowlist}
    allowed = {a[:-4] if a.endswith(".exe") else a for a in allowed}
    if normalised not in allowed:
        listed = ", ".join(sorted(allowed))
        return Check(
            False,
            f"'{name}' no esta en la allowlist de '{tool}' ({listed})",
        )

    return Check(True, resolved=None)


def check_window_process(
    tool: str, raw_process: Any, config_dir: Path | None = None
) -> Check:
    """Whether `tool` may drive a window belonging to `raw_process`.

    This is the containment for `uia.*` (Fase 4.1), and it is the reason
    those tools can be `auto` without being unlimited. Driving the
    accessibility tree is the most powerful thing in the project after
    `shell.run`: a click has no undo, and the window under it might be a
    'are you sure you want to delete?' dialog or somebody's bank. Without
    a limit here, `uia.*` would be the only tool in Jarvis with none.

    **Why the process and not the title.** The title is a label the
    application writes for humans: it is localised, and it changes while
    you work — Notepad's becomes '*Sin titulo: Bloc de notas' the moment
    a character is typed. Containment keyed on it would come undone in
    the middle of the task it was containing, and worse, would be
    forgeable by any program that can name its own window. The owning
    process is a fact Windows reports, not a string anyone chose.

    Deliberately separate from `check_allowlist` rather than a wrapper
    around it, because the two vet different kinds of thing. That one
    inspects a name **the model wrote**, so it must refuse paths and
    shell operators. This one inspects a name **the OS reported** about a
    window that already exists, so those checks would be theatre; what it
    must never do instead is accept an empty or unknown process, which is
    what the two guards below are for.
    """
    policy = policy_for(tool, config_dir)
    if policy.is_forbidden:
        return Check(False, f"'{tool}' esta prohibida o deshabilitada")

    if not policy.allowlist:
        return Check(
            False,
            f"'{tool}' no tiene allowlist en permisos.yaml, asi que no puede "
            "actuar sobre ninguna ventana",
        )

    name = str(raw_process or "").strip()
    if not name:
        # Windows would not say who owns the window. Denied, not waved
        # through: an unidentifiable window is the one case where being
        # permissive costs the most.
        return Check(
            False,
            f"no se pudo determinar que programa es dueno de esa ventana, "
            f"asi que '{tool}' no actua sobre ella",
        )

    normalised = name.lower()
    normalised = normalised[:-4] if normalised.endswith(".exe") else normalised

    allowed = {p.strip().lower() for p in policy.allowlist}
    allowed = {a[:-4] if a.endswith(".exe") else a for a in allowed}
    if normalised not in allowed:
        listed = ", ".join(sorted(allowed))
        return Check(
            False,
            f"esa ventana pertenece a '{normalised}', que no esta en la "
            f"allowlist de '{tool}' ({listed})",
        )

    return Check(True)
