"""Containment tests: paths and commands.

ADR-0008 put the executor under the user's own Windows account, which
makes `rutas_permitidas` and `allowlist` the only thing standing between
a bad plan and the rest of the disk. So these are not tests of a helper
function — they are the tests of the sandbox itself, and they are written
adversarially: traversal, lookalike siblings, symlinks, UNC paths,
environment variables and command chaining.

Everything runs against the real filesystem in `tmp_path`. Rule 4
forbids mocking here: a path check that passes against a fake filesystem
proves nothing about `Path.resolve()` on Windows.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from nucleo.configuracion import ConfigError
from seguridad.permisos import allowed_roots, check_command, check_path


def _config(tmp_path: Path, herramientas: dict) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(exist_ok=True)
    (directory / "permisos.yaml").write_text(
        yaml.safe_dump(
            {"herramientas": herramientas, "politica_por_defecto": "confirmar"},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "archivo.txt").write_text("hola", encoding="utf-8")
    return root


@pytest.fixture
def fs_config(tmp_path: Path, sandbox: Path) -> Path:
    return _config(
        tmp_path,
        {
            "fs.list": {
                "habilitada": True,
                "politica": "auto",
                "rutas_permitidas": [str(sandbox)],
            },
            "fs.delete": {
                "habilitada": True,
                "politica": "confirmar",
                "rutas_permitidas": [str(sandbox)],
            },
            "fs.write": {"habilitada": True, "politica": "confirmar"},
            "vision.act": {"habilitada": False, "politica": "confirmar"},
        },
    )


# --- lo que si se permite -------------------------------------------


def test_path_inside_root_is_allowed(fs_config: Path, sandbox: Path) -> None:
    check = check_path("fs.list", sandbox / "sub" / "archivo.txt", fs_config)
    assert check.allowed
    assert check.resolved == (sandbox / "sub" / "archivo.txt").resolve()


def test_root_itself_is_allowed(fs_config: Path, sandbox: Path) -> None:
    assert check_path("fs.list", sandbox, fs_config).allowed


def test_nonexistent_path_under_root_is_allowed(
    fs_config: Path, sandbox: Path
) -> None:
    """`fs.write` creating a new file must not be blocked for not existing."""
    assert check_path("fs.list", sandbox / "todavia_no.txt", fs_config).allowed


def test_check_is_truthy(fs_config: Path, sandbox: Path) -> None:
    assert check_path("fs.list", sandbox, fs_config)
    assert not check_path("fs.list", "C:\\Windows", fs_config)


# --- travesia y parecidos -------------------------------------------


def test_traversal_out_of_root_is_denied(fs_config: Path, sandbox: Path) -> None:
    escape = sandbox / "sub" / ".." / ".." / ".." / "fuera.txt"
    check = check_path("fs.list", escape, fs_config)
    assert not check.allowed
    assert "fuera de las rutas permitidas" in check.reason


def test_sibling_with_same_prefix_is_denied(
    tmp_path: Path, sandbox: Path, fs_config: Path
) -> None:
    """The string-prefix bug: `sandbox_malo` must not pass as `sandbox`."""
    vecino = sandbox.parent / f"{sandbox.name}_malo"
    vecino.mkdir()
    assert not check_path("fs.list", vecino / "x.txt", fs_config).allowed


def test_absolute_path_elsewhere_is_denied(fs_config: Path) -> None:
    assert not check_path("fs.list", "C:\\Windows\\System32", fs_config).allowed


@pytest.mark.parametrize("ruta", ["", "   ", None])
def test_empty_path_is_denied(fs_config: Path, ruta: object) -> None:
    assert not check_path("fs.list", ruta, fs_config).allowed


def test_null_byte_is_denied(fs_config: Path, sandbox: Path) -> None:
    check = check_path("fs.list", f"{sandbox}\\x\0y.txt", fs_config)
    assert not check.allowed
    assert "nulo" in check.reason


@pytest.mark.parametrize("ruta", ["\\\\servidor\\compartido\\x", "//servidor/x"])
def test_unc_path_is_denied(fs_config: Path, ruta: str) -> None:
    check = check_path("fs.list", ruta, fs_config)
    assert not check.allowed
    assert "red" in check.reason


def test_symlink_escaping_root_is_denied(
    fs_config: Path, sandbox: Path, tmp_path: Path
) -> None:
    """Containment is decided after following links, not before."""
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "secreto.txt").write_text("x", encoding="utf-8")
    enlace = sandbox / "atajo"
    try:
        enlace.symlink_to(fuera, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("crear symlinks requiere privilegios en Windows")

    check = check_path("fs.list", enlace / "secreto.txt", fs_config)
    assert not check.allowed


def test_junction_escaping_root_is_denied(
    fs_config: Path, sandbox: Path, tmp_path: Path
) -> None:
    """Same property via a junction, which needs no privileges.

    The symlink test above skips on a machine without Developer Mode —
    exactly this machine. A junction is the escape route actually
    available to an unprivileged process here, so it is the one that has
    to be proven closed.
    """
    fuera = tmp_path / "fuera_junction"
    fuera.mkdir()
    (fuera / "secreto.txt").write_text("x", encoding="utf-8")
    enlace = sandbox / "atajo_j"

    creado = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(enlace), str(fuera)],
        capture_output=True,
        text=True,
    )
    if creado.returncode != 0 or not enlace.exists():
        pytest.skip(f"no se pudo crear el junction: {creado.stderr.strip()}")

    check = check_path("fs.list", enlace / "secreto.txt", fs_config)
    assert not check.allowed
    assert "fuera de las rutas permitidas" in check.reason


# --- configuracion que falla cerrada --------------------------------


def test_tool_without_allowed_paths_gets_nothing(
    fs_config: Path, sandbox: Path
) -> None:
    """An empty `rutas_permitidas` means nowhere, never everywhere."""
    check = check_path("fs.write", sandbox / "x.txt", fs_config)
    assert not check.allowed
    assert "no tiene rutas_permitidas" in check.reason


def test_forbidden_tool_is_denied_before_path_check(
    fs_config: Path, sandbox: Path
) -> None:
    check = check_path("vision.act", sandbox, fs_config)
    assert not check.allowed
    assert "prohibida o deshabilitada" in check.reason


def test_unlisted_tool_is_denied(fs_config: Path, sandbox: Path) -> None:
    """Falling back to `confirmar` still grants no paths."""
    assert not check_path("fs.inventada", sandbox, fs_config).allowed


def test_environment_variable_in_root_is_expanded(tmp_path: Path) -> None:
    directory = _config(
        tmp_path,
        {
            "fs.list": {
                "habilitada": True,
                "politica": "auto",
                "rutas_permitidas": ["%USERPROFILE%\\Downloads"],
            }
        },
    )
    roots = allowed_roots("fs.list", directory)
    assert roots and "%" not in str(roots[0])
    assert check_path("fs.list", roots[0] / "x.pdf", directory).allowed


def test_unexpandable_variable_in_root_raises(tmp_path: Path) -> None:
    """A root that never expands would silently deny everything."""
    directory = _config(
        tmp_path,
        {
            "fs.list": {
                "habilitada": True,
                "politica": "auto",
                "rutas_permitidas": ["%NO_EXISTE_ESTA_VARIABLE%\\x"],
            }
        },
    )
    with pytest.raises(ConfigError, match="no se pudo expandir"):
        check_path("fs.list", "C:\\x", directory)


def test_shipped_config_confines_fs_delete_to_downloads() -> None:
    """The real permisos.yaml, not a fixture: delete may not roam."""
    assert not check_path("fs.delete", "C:\\Windows\\System32\\drivers").allowed
    assert not check_path("fs.delete", "C:\\proyectos\\Jarvis\\main.py").allowed


# --- comandos --------------------------------------------------------


@pytest.fixture
def shell_config(tmp_path: Path) -> Path:
    return _config(
        tmp_path,
        {
            "shell.run": {
                "habilitada": True,
                "politica": "confirmar",
                "allowlist": ["git", "python", "robocopy"],
            },
            "shell.libre": {"habilitada": True, "politica": "confirmar"},
        },
    )


@pytest.mark.parametrize(
    "comando",
    ["git status", "GIT status", "git.exe status", "python -c pass"],
)
def test_allowlisted_command_is_allowed(shell_config: Path, comando: str) -> None:
    assert check_command("shell.run", comando, shell_config).allowed


@pytest.mark.parametrize(
    "comando",
    [
        "git status & del C:\\Windows",
        "git status && rmdir /s C:\\",
        "git status | more",
        "git status ; shutdown",
        "git status `whoami`",
        "git status $(whoami)",
        "git status\ndel x",
        "git log > C:\\salida.txt",
        "git apply < C:\\parche.diff",
    ],
)
def test_command_chaining_is_denied(shell_config: Path, comando: str) -> None:
    """The allowlist is worthless if a second command rides along."""
    check = check_command("shell.run", comando, shell_config)
    assert not check.allowed
    assert "encadenar o redirigir" in check.reason


def test_percent_expansion_is_denied(shell_config: Path) -> None:
    """cmd.exe would expand it after the check, so the vetted string
    would not be the executed one."""
    check = check_command("shell.run", "git add %USERPROFILE%", shell_config)
    assert not check.allowed
    assert "%" in check.reason


@pytest.mark.parametrize("comando", ["del C:\\x", "powershell -c x", "curl http://x"])
def test_command_outside_allowlist_is_denied(
    shell_config: Path, comando: str
) -> None:
    check = check_command("shell.run", comando, shell_config)
    assert not check.allowed
    assert "allowlist" in check.reason


def test_tool_without_allowlist_runs_nothing(shell_config: Path) -> None:
    check = check_command("shell.libre", "git status", shell_config)
    assert not check.allowed
    assert "no tiene allowlist" in check.reason


def test_quoted_program_path_fails_closed(shell_config: Path) -> None:
    """Not supported, and it denies rather than guessing.

    `"C:\\Program Files\\Git\\bin\\git.exe" status` splits on the space
    inside the path. Rather than parse quoting, the check refuses: a
    wrong guess here would run an unvetted program.
    """
    comando = '"C:\\Program Files\\Git\\bin\\git.exe" status'
    assert not check_command("shell.run", comando, shell_config).allowed


@pytest.mark.parametrize("comando", ["", "   ", None])
def test_empty_command_is_denied(shell_config: Path, comando: object) -> None:
    assert not check_command("shell.run", comando, shell_config).allowed
