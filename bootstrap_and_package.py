#!/usr/bin/env python3
"""Unified bootstrap + package runner for DPDP Scanner.

This script performs end-to-end setup using a JSON config:
1) Resolve/validate target platform
2) Ensure compatible Python is available (optionally install it)
3) Create/refresh one virtual environment
4) Install runtime/build dependencies
5) Optionally download spaCy model
6) Optionally run MySQL sample setup
7) Build and package executable via build_executable.py
8) Optionally run a scanner smoke test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parent


class StepError(RuntimeError):
    """Raised when a setup/build step fails."""


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}")


def run_cmd(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    check: bool = True,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    if shell:
        printable = cmd[0]
    else:
        printable = " ".join(cmd)
    log("CMD", printable)

    proc = subprocess.run(
        cmd if not shell else cmd[0],
        cwd=str(cwd) if cwd else None,
        env=env,
        shell=shell,
        text=True,
        capture_output=True,
    )

    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)

    if check and proc.returncode != 0:
        raise StepError(f"Command failed with exit code {proc.returncode}: {printable}")
    return proc


def has_network_access(hosts: Sequence[str] = ("pypi.org", "github.com"), timeout: float = 3.0) -> bool:
    for host in hosts:
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_platform(value: str) -> str:
    token = value.strip().lower()
    mapping = {
        "mac": "mac",
        "macos": "mac",
        "darwin": "mac",
        "osx": "mac",
        "linux": "linux",
        "windows": "windows",
        "win": "windows",
        "win32": "windows",
    }
    if token == "auto":
        current = sys.platform.lower()
        if current.startswith("darwin"):
            return "mac"
        if current.startswith("linux"):
            return "linux"
        if current.startswith("win"):
            return "windows"
        raise StepError(f"Unsupported runtime platform: {sys.platform}")

    resolved = mapping.get(token)
    if not resolved:
        raise StepError(f"Unsupported target_environment: {value}")
    return resolved


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def parse_python_version(output: str) -> Optional[Tuple[int, int, int]]:
    match = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def python_candidates(python_cfg: Dict[str, Any], target_env: str) -> List[List[str]]:
    version = str(python_cfg.get("version", "3.10")).strip()
    explicit_cmd = python_cfg.get("executable")
    candidates: List[List[str]] = []

    if explicit_cmd:
        if isinstance(explicit_cmd, str):
            tokens = shlex.split(explicit_cmd.strip())
            if tokens:
                candidates.append(tokens)
        elif isinstance(explicit_cmd, list):
            tokenized = [str(item) for item in explicit_cmd if str(item).strip()]
            if tokenized:
                candidates.append(tokenized)

    major_minor = version
    major = version.split(".")[0]
    if target_env == "windows":
        candidates.extend(
            [
                ["py", f"-{major_minor}"],
                ["py", f"-{major}"],
                [f"python{major_minor}"],
                ["python"],
            ]
        )
    else:
        candidates.extend(
            [
                [f"python{major_minor}"],
                ["python3"],
                ["python"],
            ]
        )

    deduped: List[List[str]] = []
    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def find_compatible_python(
    target_env: str,
    python_cfg: Dict[str, Any],
) -> Optional[List[str]]:
    required = str(python_cfg.get("version", "3.10")).strip()
    req_parts = required.split(".")
    req_major = int(req_parts[0])
    req_minor = int(req_parts[1]) if len(req_parts) > 1 else 0

    for candidate in python_candidates(python_cfg, target_env):
        try:
            proc = subprocess.run(
                [*candidate, "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue

        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        parsed = parse_python_version(output)
        if not parsed:
            continue

        major, minor, _ = parsed
        if (major, minor) == (req_major, req_minor):
            return candidate
    return None


def _with_optional_sudo(cmd: List[str]) -> List[str]:
    if os.name != "posix":
        return cmd
    get_euid = getattr(os, "geteuid", None)
    if callable(get_euid):
        try:
            if get_euid() == 0:
                return cmd
        except Exception:
            pass
    if command_exists("sudo"):
        return ["sudo", *cmd]
    return cmd


def linux_python_install_steps(version: str) -> List[List[str]]:
    major_minor = version

    if command_exists("apt-get"):
        return [
            _with_optional_sudo(["apt-get", "update"]),
            _with_optional_sudo(
                [
                    "apt-get",
                    "install",
                    "-y",
                    f"python{major_minor}",
                    f"python{major_minor}-venv",
                    f"python{major_minor}-distutils",
                    f"python{major_minor}-dev",
                ]
            ),
            _with_optional_sudo(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "python3",
                    "python3-venv",
                    "python3-dev",
                ]
            ),
        ]
    if command_exists("dnf"):
        return [
            _with_optional_sudo(
                [
                    "dnf",
                    "install",
                    "-y",
                    f"python{major_minor}",
                    f"python{major_minor}-devel",
                    "python3",
                    "python3-devel",
                ]
            )
        ]
    if command_exists("yum"):
        return [
            _with_optional_sudo(
                [
                    "yum",
                    "install",
                    "-y",
                    f"python{major_minor}",
                    f"python{major_minor}-devel",
                    "python3",
                    "python3-devel",
                ]
            )
        ]
    if command_exists("pacman"):
        return [
            _with_optional_sudo(["pacman", "-Sy", "--noconfirm", "python"])
        ]
    return []


def python_install_steps(target_env: str, version: str) -> List[List[str]]:
    if target_env == "mac":
        if command_exists("brew"):
            return [["brew", "install", f"python@{version}"]]
        return []

    if target_env == "linux":
        return linux_python_install_steps(version)

    if target_env == "windows":
        steps: List[List[str]] = []
        if command_exists("winget"):
            steps.append(["winget", "install", "-e", "--id", f"Python.Python.{version}"])
        if command_exists("choco"):
            steps.append(["choco", "install", "-y", "python", "--version", f"{version}.0"])
        return steps

    return []


def ensure_python(target_env: str, python_cfg: Dict[str, Any]) -> List[str]:
    python_cmd = find_compatible_python(target_env, python_cfg)
    if python_cmd:
        log("PYTHON", f"Using compatible interpreter: {' '.join(python_cmd)}")
        return python_cmd

    if not bool(python_cfg.get("install_if_missing", True)):
        raise StepError(
            "Compatible Python not found and install_if_missing=false. "
            f"Required: {python_cfg.get('version', '3.10')}"
        )

    version = str(python_cfg.get("version", "3.10")).strip()
    install_steps = python_install_steps(target_env, version)
    if not install_steps:
        raise StepError(
            "Compatible Python not found and no installer command is available for this platform. "
            f"Please install Python {version} manually."
        )

    for step in install_steps:
        try:
            run_cmd(step, cwd=ROOT)
        except StepError as exc:
            log("WARN", str(exc))

    python_cmd = find_compatible_python(target_env, python_cfg)
    if python_cmd:
        log("PYTHON", f"Compatible interpreter installed/found: {' '.join(python_cmd)}")
        return python_cmd

    raise StepError(
        f"Failed to locate Python {version} after installation attempts. "
        "Install it manually and rerun."
    )


def venv_python_path(venv_dir: Path, target_env: str) -> Path:
    if target_env == "windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_or_refresh_venv(
    python_cmd: List[str],
    target_env: str,
    env_cfg: Dict[str, Any],
    network_available: bool,
) -> Path:
    venv_dir = (ROOT / str(env_cfg.get("venv_dir", ".venv"))).resolve()
    clear = bool(env_cfg.get("clear", True))
    preserve_when_offline = bool(env_cfg.get("preserve_existing_venv_when_offline", True))

    if venv_dir.exists() and not clear:
        py_path = venv_python_path(venv_dir, target_env)
        if py_path.exists():
            log("VENV", f"Reusing existing virtual environment at {venv_dir}")
            return py_path

    if clear and not network_available and preserve_when_offline and venv_dir.exists():
        py_path = venv_python_path(venv_dir, target_env)
        if py_path.exists():
            log(
                "VENV",
                (
                    "Offline mode detected. Preserving existing virtual environment "
                    "and skipping clear/recreate."
                ),
            )
            return py_path

    if clear and venv_dir.exists():
        log("VENV", f"Removing existing venv: {venv_dir}")
        shutil.rmtree(venv_dir, ignore_errors=True)

    log("VENV", f"Creating virtual environment at {venv_dir}")
    cmd = [*python_cmd, "-m", "venv"]
    if clear:
        cmd.append("--clear")
    cmd.append(str(venv_dir))
    run_cmd(cmd, cwd=ROOT)

    py_path = venv_python_path(venv_dir, target_env)
    if not py_path.exists():
        raise StepError(f"Virtual environment python not found: {py_path}")
    return py_path


def install_dependencies(
    *,
    venv_python: Path,
    dep_cfg: Dict[str, Any],
    target_env: str,
    network_available: bool,
) -> None:
    if not bool(dep_cfg.get("enabled", True)):
        log("DEPS", "Dependency installation disabled by config.")
        return

    pip_env = _ensure_pg_config_env(target_env=target_env, dep_cfg=dep_cfg)
    # Enforce isolated virtualenv behavior for all pip/python child processes.
    pip_env["PYTHONNOUSERSITE"] = "1"
    pip_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    if not network_available:
        if not bool(dep_cfg.get("allow_offline_reuse_existing", True)):
            raise StepError(
                "Network is unavailable and allow_offline_reuse_existing=false. "
                "Enable network access or update config."
            )

        missing_modules = _missing_required_modules_for_offline(
            venv_python=venv_python,
            dep_cfg=dep_cfg,
            pip_env=pip_env,
        )
        if missing_modules:
            raise StepError(
                "Network is unavailable and this virtual environment is missing required "
                f"packages for offline reuse: {', '.join(missing_modules)}. "
                "Reconnect to the internet and rerun bootstrap once, or pre-provision .venv "
                "with dependencies and set environment.clear=false."
            )

        log(
            "DEPS",
            "Offline mode detected. Reusing installed dependencies from existing virtual environment.",
        )
        return

    pip_constraints = dep_cfg.get("pip_constraints", {}) or {}
    pip_version = str(pip_constraints.get("pip", "<26"))
    setuptools_version = str(pip_constraints.get("setuptools", "<81"))
    wheel_version = str(pip_constraints.get("wheel", ""))

    bootstrap_pkgs = [f"pip{pip_version}", f"setuptools{setuptools_version}"]
    if wheel_version:
        bootstrap_pkgs.append(f"wheel{wheel_version}")
    else:
        bootstrap_pkgs.append("wheel")

    run_cmd(
        [str(venv_python), "-m", "pip", "install", "--upgrade", *bootstrap_pkgs],
        cwd=ROOT,
        env=pip_env,
    )

    if bool(dep_cfg.get("install_poetry_core", True)):
        run_cmd(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "poetry-core>=1.7,<3"],
            cwd=ROOT,
            env=pip_env,
        )

    requirements_file = ROOT / str(dep_cfg.get("requirements_file", "requirements.txt"))
    if not requirements_file.exists():
        raise StepError(f"requirements file not found: {requirements_file}")

    use_no_build_isolation = bool(dep_cfg.get("use_no_build_isolation", True))
    install_cmd = [str(venv_python), "-m", "pip", "install"]
    if use_no_build_isolation:
        install_cmd.append("--no-build-isolation")
    install_cmd.extend(["-r", str(requirements_file)])
    install_proc = run_cmd(install_cmd, cwd=ROOT, check=False, env=pip_env)

    if install_proc.returncode != 0:
        stderr_text = (install_proc.stderr or "")
        fallback_enabled = bool(
            dep_cfg.get("piicatcher_ignore_requires_python_on_failure", True)
        )
        is_piicatcher_py_constraint_error = (
            "Package 'piicatcher' requires a different Python" in stderr_text
            or "piicatcher" in stderr_text and "requires a different Python" in stderr_text
        )

        if fallback_enabled and is_piicatcher_py_constraint_error:
            log(
                "WARN",
                "piicatcher Python metadata rejected this interpreter; "
                "retrying with a two-phase install and --ignore-requires-python for piicatcher.",
            )
            _install_requirements_without_piicatcher(
                venv_python=venv_python,
                requirements_file=requirements_file,
                use_no_build_isolation=use_no_build_isolation,
                pip_env=pip_env,
            )
            _install_piicatcher_with_ignore_python(
                venv_python=venv_python,
                dep_cfg=dep_cfg,
                use_no_build_isolation=use_no_build_isolation,
                pip_env=pip_env,
            )
        else:
            raise StepError(
                "Dependency installation failed. "
                "See pip output above for details."
            )

    if bool(dep_cfg.get("apply_compatibility_overrides", True)):
        _apply_compatibility_overrides(
            venv_python=venv_python,
            dep_cfg=dep_cfg,
            use_no_build_isolation=use_no_build_isolation,
            pip_env=pip_env,
        )

    if bool(dep_cfg.get("run_pip_check", True)):
        pip_check_proc = run_cmd(
            [str(venv_python), "-m", "pip", "check"],
            cwd=ROOT,
            env=pip_env,
            check=False,
        )
        final_returncode = pip_check_proc.returncode
        if pip_check_proc.returncode != 0:
            if bool(dep_cfg.get("apply_compatibility_overrides", True)):
                log(
                    "WARN",
                    "pip check reported conflicts; retrying compatibility overrides once.",
                )
                _apply_compatibility_overrides(
                    venv_python=venv_python,
                    dep_cfg=dep_cfg,
                    use_no_build_isolation=use_no_build_isolation,
                    pip_env=pip_env,
                )
                pip_check_retry = run_cmd(
                    [str(venv_python), "-m", "pip", "check"],
                    cwd=ROOT,
                    env=pip_env,
                    check=False,
                )
                final_returncode = pip_check_retry.returncode
            else:
                final_returncode = pip_check_proc.returncode

        if final_returncode != 0:
            if bool(dep_cfg.get("pip_check_strict", False)):
                raise StepError("pip check failed. See output above for details.")
            log(
                "WARN",
                "pip check still reports dependency conflicts. "
                "Continuing because pip_check_strict=false.",
            )

    if bool(dep_cfg.get("download_spacy_model", False)):
        _install_spacy_model(
            venv_python=venv_python,
            dep_cfg=dep_cfg,
            pip_env=pip_env,
        )


def _installed_spacy_version(
    *,
    venv_python: Path,
    pip_env: Dict[str, str],
) -> str:
    proc = run_cmd(
        [
            str(venv_python),
            "-c",
            "import spacy; print(spacy.__version__)",
        ],
        cwd=ROOT,
        env=pip_env,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _spacy_model_wheel_url(model_name: str, model_version: str) -> str:
    return (
        "https://github.com/explosion/spacy-models/releases/download/"
        f"{model_name}-{model_version}/"
        f"{model_name}-{model_version}-py3-none-any.whl"
    )


def _candidate_model_versions(
    *,
    dep_cfg: Dict[str, Any],
    spacy_version: str,
) -> List[str]:
    candidates: List[str] = []

    configured = str(dep_cfg.get("spacy_model_version", "")).strip()
    if configured:
        candidates.append(configured)

    if spacy_version:
        candidates.append(spacy_version)
        parts = spacy_version.split(".")
        if len(parts) >= 2:
            candidates.append(f"{parts[0]}.{parts[1]}.0")

    deduped: List[str] = []
    seen = set()
    for version in candidates:
        if not version or version in seen:
            continue
        seen.add(version)
        deduped.append(version)
    return deduped


def _install_spacy_model(
    *,
    venv_python: Path,
    dep_cfg: Dict[str, Any],
    pip_env: Dict[str, str],
) -> None:
    model_name = str(dep_cfg.get("spacy_model", "en_core_web_lg")).strip() or "en_core_web_lg"
    strict = bool(dep_cfg.get("spacy_model_strict", False))

    # First attempt the official spaCy installer command.
    direct = run_cmd(
        [str(venv_python), "-m", "spacy", "download", model_name],
        cwd=ROOT,
        env=pip_env,
        check=False,
    )
    if direct.returncode == 0:
        return

    log(
        "WARN",
        (
            f"spaCy model download failed for '{model_name}'. "
            "Attempting fallback wheel install from GitHub releases."
        ),
    )

    spacy_version = _installed_spacy_version(venv_python=venv_python, pip_env=pip_env)
    for model_version in _candidate_model_versions(dep_cfg=dep_cfg, spacy_version=spacy_version):
        wheel_url = _spacy_model_wheel_url(model_name=model_name, model_version=model_version)
        proc = run_cmd(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "--no-deps", wheel_url],
            cwd=ROOT,
            env=pip_env,
            check=False,
        )
        if proc.returncode == 0:
            log(
                "DEPS",
                f"Installed spaCy model '{model_name}' from fallback wheel: {model_version}",
            )
            return

    # Last attempt: let pip resolve from configured index if available.
    fallback_pkg = run_cmd(
        [str(venv_python), "-m", "pip", "install", "--upgrade", model_name],
        cwd=ROOT,
        env=pip_env,
        check=False,
    )
    if fallback_pkg.returncode == 0:
        return

    if strict:
        raise StepError(
            f"Failed to install spaCy model '{model_name}'. "
            "Set dependencies.spacy_model_strict=false to continue without failing bootstrap."
        )

    log(
        "WARN",
        (
            f"Could not install spaCy model '{model_name}'. "
            "Continuing because dependencies.spacy_model_strict=false."
        ),
    )


def _is_module_importable(
    *,
    venv_python: Path,
    module_name: str,
    pip_env: Dict[str, str],
) -> bool:
    proc = run_cmd(
        [
            str(venv_python),
            "-c",
            (
                "import importlib.util, sys; "
                f"sys.exit(0 if importlib.util.find_spec('{module_name}') else 1)"
            ),
        ],
        cwd=ROOT,
        env=pip_env,
        check=False,
    )
    return proc.returncode == 0


def _missing_required_modules_for_offline(
    *,
    venv_python: Path,
    dep_cfg: Dict[str, Any],
    pip_env: Dict[str, str],
) -> List[str]:
    default_modules = [
        "presidio_analyzer",
        "presidio_anonymizer",
        "spacy",
        "PyPDF2",
        "docx",
        "pymysql",
        "piicatcher",
        "dbcat",
    ]
    configured_modules = dep_cfg.get("offline_required_modules", default_modules) or default_modules

    modules_to_check: List[str] = []
    for module in configured_modules:
        text = str(module).strip()
        if text:
            modules_to_check.append(text)

    missing: List[str] = []
    for module in modules_to_check:
        if not _is_module_importable(
            venv_python=venv_python,
            module_name=module,
            pip_env=pip_env,
        ):
            missing.append(module)
    return missing


def _path_with_prefix(original_path: str, prefix: Path) -> str:
    prefix_str = str(prefix.resolve())
    if not original_path:
        return prefix_str
    parts = original_path.split(os.pathsep)
    if prefix_str in parts:
        return original_path
    return f"{prefix_str}{os.pathsep}{original_path}"


def _prepend_flag(env: Dict[str, str], key: str, flag: str) -> None:
    current = env.get(key, "").strip()
    if current:
        if flag in current.split():
            return
        env[key] = f"{flag} {current}"
    else:
        env[key] = flag


def _prepend_path_entry(env: Dict[str, str], key: str, entry: Path) -> None:
    entry_str = str(entry.resolve())
    current = env.get(key, "")
    if not current:
        env[key] = entry_str
        return
    parts = current.split(os.pathsep)
    if entry_str in parts:
        return
    env[key] = f"{entry_str}{os.pathsep}{current}"


def _brew_prefix(formula: str) -> Optional[Path]:
    proc = subprocess.run(
        ["brew", "--prefix", formula],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    candidate = Path((proc.stdout or "").strip())
    if candidate.exists():
        return candidate
    return None


def _configure_macos_build_env(env: Dict[str, str], dep_cfg: Dict[str, Any]) -> Dict[str, str]:
    if not bool(dep_cfg.get("ensure_macos_build_flags", True)):
        return env

    formula_candidates = dep_cfg.get(
        "macos_formula_candidates",
        ["libpq", "openssl@3", "openssl@1.1", "icu4c@78", "icu4c"],
    )
    prefixes: List[Path] = []
    for formula in formula_candidates:
        prefix = _brew_prefix(str(formula))
        if prefix:
            prefixes.append(prefix)

    for prefix in prefixes:
        bin_dir = prefix / "bin"
        include_dir = prefix / "include"
        lib_dir = prefix / "lib"
        pkgconfig_dir = lib_dir / "pkgconfig"

        if bin_dir.exists():
            _prepend_path_entry(env, "PATH", bin_dir)
        if include_dir.exists():
            _prepend_flag(env, "CPPFLAGS", f"-I{include_dir}")
            _prepend_flag(env, "CFLAGS", f"-I{include_dir}")
        if lib_dir.exists():
            _prepend_flag(env, "LDFLAGS", f"-L{lib_dir}")
            _prepend_flag(env, "LDFLAGS", f"-Wl,-rpath,{lib_dir}")
            _prepend_path_entry(env, "LIBRARY_PATH", lib_dir)
        if pkgconfig_dir.exists():
            _prepend_path_entry(env, "PKG_CONFIG_PATH", pkgconfig_dir)

    return env


def _has_mysql_config(path_value: Optional[str]) -> bool:
    if shutil.which("mysql_config", path=path_value):
        return True
    if shutil.which("mariadb_config", path=path_value):
        return True
    return False


def _linux_native_build_tools_install_steps() -> List[List[str]]:
    if command_exists("apt-get"):
        return [
            _with_optional_sudo(["apt-get", "update"]),
            _with_optional_sudo(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "build-essential",
                    "pkg-config",
                    "libpq-dev",
                    "default-libmysqlclient-dev",
                    "libssl-dev",
                    "libffi-dev",
                    "libxml2-dev",
                    "libxslt1-dev",
                    "zlib1g-dev",
                    "libjpeg-dev",
                    "patchelf",
                    "binutils",
                ]
            ),
            _with_optional_sudo(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "libmariadb-dev",
                    "libmariadb-dev-compat",
                ]
            ),
        ]
    if command_exists("dnf"):
        return [
            _with_optional_sudo(
                [
                    "dnf",
                    "install",
                    "-y",
                    "gcc",
                    "gcc-c++",
                    "make",
                    "pkgconf-pkg-config",
                    "postgresql-devel",
                    "mariadb-connector-c-devel",
                    "openssl-devel",
                    "libffi-devel",
                    "libxml2-devel",
                    "libxslt-devel",
                    "zlib-devel",
                    "patchelf",
                    "binutils",
                ]
            )
        ]
    if command_exists("yum"):
        return [
            _with_optional_sudo(
                [
                    "yum",
                    "install",
                    "-y",
                    "gcc",
                    "gcc-c++",
                    "make",
                    "pkgconfig",
                    "postgresql-devel",
                    "mariadb-connector-c-devel",
                    "openssl-devel",
                    "libffi-devel",
                    "libxml2-devel",
                    "libxslt-devel",
                    "zlib-devel",
                    "patchelf",
                    "binutils",
                ]
            )
        ]
    if command_exists("pacman"):
        return [
            _with_optional_sudo(
                [
                    "pacman",
                    "-Sy",
                    "--noconfirm",
                    "base-devel",
                    "pkgconf",
                    "postgresql-libs",
                    "mariadb-libs",
                    "openssl",
                    "libffi",
                    "libxml2",
                    "libxslt",
                    "zlib",
                    "patchelf",
                    "binutils",
                ]
            )
        ]
    return []


def _linux_pg_config_install_steps() -> List[List[str]]:
    if command_exists("apt-get"):
        return [
            _with_optional_sudo(["apt-get", "update"]),
            _with_optional_sudo(["apt-get", "install", "-y", "libpq-dev"]),
        ]
    if command_exists("dnf"):
        return [_with_optional_sudo(["dnf", "install", "-y", "postgresql-devel"])]
    if command_exists("yum"):
        return [_with_optional_sudo(["yum", "install", "-y", "postgresql-devel"])]
    if command_exists("pacman"):
        return [_with_optional_sudo(["pacman", "-Sy", "--noconfirm", "postgresql-libs"])]
    return []


def _ensure_pg_config_env(target_env: str, dep_cfg: Dict[str, Any]) -> Dict[str, str]:
    env = os.environ.copy()

    if target_env == "mac":
        env = _configure_macos_build_env(env, dep_cfg)

    if target_env == "linux" and bool(dep_cfg.get("ensure_linux_native_build_tools", True)):
        path_value = env.get("PATH")
        need_pg = bool(dep_cfg.get("ensure_pg_config", True)) and not shutil.which(
            "pg_config",
            path=path_value,
        )
        need_mysql = bool(dep_cfg.get("ensure_mysql_config", True)) and not _has_mysql_config(
            path_value
        )
        need_patchelf = bool(dep_cfg.get("ensure_patchelf", True)) and not shutil.which(
            "patchelf",
            path=path_value,
        )
        if need_pg or need_mysql or need_patchelf:
            log(
                "DEPS",
                (
                    "Installing Linux native build prerequisites "
                    "(compiler, pg/mysql client headers, patchelf)."
                ),
            )
            for step in _linux_native_build_tools_install_steps():
                run_cmd(step, cwd=ROOT, check=False)

    if not bool(dep_cfg.get("ensure_pg_config", True)):
        return env

    custom_pg_bin = str(dep_cfg.get("pg_config_bin_path", "")).strip()
    if custom_pg_bin:
        custom_path = Path(custom_pg_bin).expanduser()
        if custom_path.exists():
            env["PATH"] = _path_with_prefix(env.get("PATH", ""), custom_path)
            if shutil.which("pg_config", path=env["PATH"]):
                log("DEPS", f"pg_config enabled via configured path: {custom_path}")
                return env
        log("WARN", f"Configured pg_config_bin_path is invalid or pg_config not found there: {custom_pg_bin}")

    if shutil.which("pg_config", path=env.get("PATH")):
        return env

    log("DEPS", "pg_config not found. Attempting to install PostgreSQL client build tools.")

    if target_env == "mac":
        if not command_exists("brew"):
            log("WARN", "Homebrew not found. Cannot auto-install libpq for pg_config.")
            return env

        run_cmd(["brew", "install", "libpq"], cwd=ROOT, check=False)
        prefix = _brew_prefix("libpq")
        if prefix is None:
            log("WARN", "Unable to resolve Homebrew prefix for libpq after install attempt.")
            return env

        pg_bin = prefix / "bin"
        env["PATH"] = _path_with_prefix(env.get("PATH", ""), pg_bin)
        env = _configure_macos_build_env(env, dep_cfg)
        if shutil.which("pg_config", path=env["PATH"]):
            log("DEPS", f"pg_config enabled via PATH: {pg_bin}")
            return env

        log("WARN", f"pg_config still not found after libpq install. Checked: {pg_bin}")
        return env

    if target_env == "linux":
        for step in _linux_pg_config_install_steps():
            run_cmd(step, cwd=ROOT, check=False)
        if shutil.which("pg_config", path=env.get("PATH")):
            return env
        log("WARN", "pg_config still missing after linux install attempts.")
        if bool(dep_cfg.get("ensure_mysql_config", True)) and not _has_mysql_config(env.get("PATH")):
            log(
                "WARN",
                "mysql_config/mariadb_config is missing; mysqlclient-based builds may fail.",
            )
        if bool(dep_cfg.get("ensure_patchelf", True)) and not shutil.which(
            "patchelf",
            path=env.get("PATH"),
        ):
            log(
                "WARN",
                "patchelf is missing; PyInstaller linux bundling may fail.",
            )
        return env

    if target_env == "windows":
        log(
            "WARN",
            "pg_config missing on Windows. Install PostgreSQL (client tools) and add it to PATH.",
        )
        return env

    return env


def _install_requirements_without_piicatcher(
    *,
    venv_python: Path,
    requirements_file: Path,
    use_no_build_isolation: bool,
    pip_env: Dict[str, str],
) -> None:
    original_lines = requirements_file.read_text(encoding="utf-8").splitlines()
    filtered_lines: List[str] = []
    for line in original_lines:
        stripped = line.strip().lower()
        if stripped.startswith("piicatcher") or "piicatcher @" in stripped:
            continue
        filtered_lines.append(line)

    if not filtered_lines:
        return

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write("\n".join(filtered_lines) + "\n")
        temp_requirements = Path(handle.name)

    try:
        cmd = [str(venv_python), "-m", "pip", "install"]
        if use_no_build_isolation:
            cmd.append("--no-build-isolation")
        cmd.extend(["-r", str(temp_requirements)])
        run_cmd(cmd, cwd=ROOT, env=pip_env)
    finally:
        temp_requirements.unlink(missing_ok=True)


def _install_piicatcher_with_ignore_python(
    *,
    venv_python: Path,
    dep_cfg: Dict[str, Any],
    use_no_build_isolation: bool,
    pip_env: Dict[str, str],
) -> None:
    install_spec = str(
        dep_cfg.get("piicatcher_install_spec", "git+https://github.com/tokern/piicatcher.git")
    ).strip()
    if not install_spec:
        raise StepError("piicatcher_install_spec is empty in config.")

    cmd = [str(venv_python), "-m", "pip", "install"]
    if use_no_build_isolation:
        cmd.append("--no-build-isolation")
    cmd.extend(
        [
            "--prefer-binary",
            "--ignore-requires-python",
            f"piicatcher @ {install_spec}",
        ]
    )
    proc = run_cmd(cmd, cwd=ROOT, env=pip_env, check=False)
    if proc.returncode == 0:
        return

    stderr_text = (proc.stderr or "").lower()
    if "pg_config executable not found" in stderr_text:
        raise StepError(
            "piicatcher installation failed because pg_config is missing. "
            "Install PostgreSQL client tools (libpq) and ensure pg_config is in PATH."
        )
    raise StepError("piicatcher installation failed. See pip output above for details.")


def _apply_compatibility_overrides(
    *,
    venv_python: Path,
    dep_cfg: Dict[str, Any],
    use_no_build_isolation: bool,
    pip_env: Dict[str, str],
) -> None:
    overrides = dep_cfg.get("compatibility_overrides", []) or []
    packages: List[str] = []
    for item in overrides:
        text = str(item).strip()
        if text:
            packages.append(text)

    if not packages:
        return

    log("DEPS", f"Applying compatibility overrides: {', '.join(packages)}")
    cmd = [str(venv_python), "-m", "pip", "install", "--upgrade"]
    if use_no_build_isolation:
        cmd.append("--no-build-isolation")
    cmd.extend(packages)
    run_cmd(cmd, cwd=ROOT, env=pip_env)


def maybe_prepare_mysql(mysql_cfg: Dict[str, Any]) -> None:
    if not bool(mysql_cfg.get("enabled", False)):
        return

    script_path = ROOT / str(mysql_cfg.get("script", "test_data/database/mysql/setup_mysql_sample.sh"))
    if not script_path.exists():
        raise StepError(f"MySQL setup script not found: {script_path}")

    if script_path.suffix.lower() == ".sh":
        run_cmd(["bash", str(script_path)], cwd=ROOT)
    else:
        run_cmd([str(script_path)], cwd=ROOT)


def _remove_packaging_incompatible_packages(venv_python: Path, pkg_cfg: Dict[str, Any]) -> None:
    if not bool(pkg_cfg.get("remove_incompatible_packages", True)):
        return

    raw_packages = pkg_cfg.get("incompatible_packages", ["pathlib"]) or ["pathlib"]
    packages: List[str] = []
    for item in raw_packages:
        text = str(item).strip()
        if text:
            packages.append(text)

    for package in packages:
        show_proc = run_cmd(
            [str(venv_python), "-m", "pip", "show", package],
            cwd=ROOT,
            check=False,
        )
        if show_proc.returncode != 0:
            continue
        log("PACKAGE", f"Removing incompatible package before build: {package}")
        run_cmd(
            [str(venv_python), "-m", "pip", "uninstall", "-y", package],
            cwd=ROOT,
        )


def maybe_package(venv_python: Path, pkg_cfg: Dict[str, Any]) -> None:
    if not bool(pkg_cfg.get("enabled", True)):
        log("PACKAGE", "Packaging disabled by config.")
        return

    _remove_packaging_incompatible_packages(venv_python, pkg_cfg)

    build_script = ROOT / str(pkg_cfg.get("build_script", "build_executable.py"))
    if not build_script.exists():
        raise StepError(f"Build script not found: {build_script}")

    cmd: List[str] = [str(venv_python), str(build_script)]

    name = str(pkg_cfg.get("name", "dpdp-pii-scanner"))
    command_name = str(pkg_cfg.get("command_name", "dpdp-scan"))
    cmd.extend(["--name", name, "--command-name", command_name])

    if bool(pkg_cfg.get("onefile", False)):
        cmd.append("--onefile")
    if bool(pkg_cfg.get("zip", True)):
        cmd.append("--zip")

    model_package = str(pkg_cfg.get("model_package", "en_core_web_lg"))
    if model_package:
        cmd.extend(["--model-package", model_package])
    if bool(pkg_cfg.get("allow_missing_model", False)):
        cmd.append("--allow-missing-model")

    for flag, key in [
        ("--distpath", "distpath"),
        ("--workpath", "workpath"),
        ("--specpath", "specpath"),
    ]:
        if key in pkg_cfg and str(pkg_cfg[key]).strip():
            cmd.extend([flag, str((ROOT / str(pkg_cfg[key])).resolve())])

    run_cmd(cmd, cwd=ROOT)


def maybe_smoke_test(venv_python: Path, smoke_cfg: Dict[str, Any]) -> None:
    if not bool(smoke_cfg.get("enabled", False)):
        return

    scan_config = ROOT / str(smoke_cfg.get("config_file", "scanner_config.json"))
    output_file = ROOT / str(smoke_cfg.get("output_file", "output/output.json"))

    run_cmd(
        [
            str(venv_python),
            str(ROOT / "main.py"),
            "--config",
            str(scan_config),
            "--output",
            str(output_file),
        ],
        cwd=ROOT,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified environment + package bootstrapper")
    parser.add_argument(
        "--config",
        default="automation_runner_config.json",
        help="Path to bootstrap JSON config.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = (ROOT / args.config).resolve()
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        cfg = read_json(config_path)

        target_env = canonical_platform(str(cfg.get("target_environment", "auto")))
        current_env = canonical_platform("auto")
        if target_env != current_env and not bool(cfg.get("allow_cross_target", False)):
            raise StepError(
                f"Config target_environment={target_env} but current host is {current_env}. "
                "Set allow_cross_target=true to continue at your own risk."
            )

        python_cfg = cfg.get("python", {}) or {}
        env_cfg = cfg.get("environment", {}) or {}
        dep_cfg = cfg.get("dependencies", {}) or {}
        mysql_cfg = cfg.get("database_test_data", {}) or {}
        pkg_cfg = cfg.get("packaging", {}) or {}
        smoke_cfg = cfg.get("runtime_smoke_test", {}) or {}
        network_available = has_network_access()

        log("START", f"Loaded config: {config_path}")
        log("START", f"Target environment: {target_env}")
        log("START", f"Network available: {network_available}")

        python_cmd = ensure_python(target_env, python_cfg)
        venv_python = create_or_refresh_venv(
            python_cmd=python_cmd,
            target_env=target_env,
            env_cfg=env_cfg,
            network_available=network_available,
        )
        install_dependencies(
            venv_python=venv_python,
            dep_cfg=dep_cfg,
            target_env=target_env,
            network_available=network_available,
        )
        maybe_prepare_mysql(mysql_cfg)
        maybe_package(venv_python, pkg_cfg)
        maybe_smoke_test(venv_python, smoke_cfg)

        log("DONE", "Bootstrap and packaging completed successfully.")
        log("DONE", f"Virtual environment python: {venv_python}")
        return 0
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
