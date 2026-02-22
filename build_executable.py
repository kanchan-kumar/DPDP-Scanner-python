#!/usr/bin/env python3
"""Build a standalone executable for the Presidio scanner using PyInstaller."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "main.py"
DEFAULT_CONFIG = ROOT / "scanner_config.json"
SRC_ROOT = ROOT / "src"
MIN_SUPPORTED_PYTHON = (3, 10)
MAX_SUPPORTED_PYTHON_EXCLUSIVE = (3, 14)
REQUIRED_BUILD_MODULES = ["PyInstaller", "altgraph"]
DARWIN_REQUIRED_BUILD_MODULES = ["macholib"]


def module_exists(name: str) -> bool:
    if importlib.util.find_spec(name) is not None:
        return True
    local_package = SRC_ROOT / name.replace(".", "/")
    return local_package.exists()


def is_supported_python() -> bool:
    current = (sys.version_info.major, sys.version_info.minor)
    return MIN_SUPPORTED_PYTHON <= current < MAX_SUPPORTED_PYTHON_EXCLUSIVE


def supported_python_series() -> str:
    return (
        f"{MIN_SUPPORTED_PYTHON[0]}.{MIN_SUPPORTED_PYTHON[1]}-"
        f"{MAX_SUPPORTED_PYTHON_EXCLUSIVE[0]}.{MAX_SUPPORTED_PYTHON_EXCLUSIVE[1] - 1}"
    )


def find_missing_build_modules() -> List[str]:
    modules = list(REQUIRED_BUILD_MODULES)
    if platform.system().lower() == "darwin":
        modules.extend(DARWIN_REQUIRED_BUILD_MODULES)
    return [name for name in modules if importlib.util.find_spec(name) is None]


def detect_mixed_virtualenv() -> List[str]:
    """
    Detect common venv corruption where multiple pythonX.Y site-packages folders
    exist under one .venv (for example python3.9 and python3.13).
    """
    lib_dir = Path(sys.prefix) / "lib"
    if not lib_dir.exists():
        return []
    candidates = []
    for child in sorted(lib_dir.glob("python*")):
        if (child / "site-packages").exists():
            candidates.append(child.name)
    return candidates if len(candidates) > 1 else []


def packaged_binary_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def packaged_config_name(args: argparse.Namespace) -> str:
    return f"{args.name}_config.json" if args.onefile else "scanner_config.json"


def build_command(args: argparse.Namespace) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--paths",
        str(SRC_ROOT),
        "--distpath",
        str(args.distpath),
        "--workpath",
        str(args.workpath),
        "--specpath",
        str(args.specpath),
    ]

    cmd.append("--onefile" if args.onefile else "--onedir")

    if DEFAULT_CONFIG.exists():
        cmd.extend(["--add-data", f"{DEFAULT_CONFIG}{os.pathsep}."])

    collect_candidates = [
        "pii_scanner",
        "presidio_analyzer",
        "presidio_anonymizer",
        "spacy",
        "thinc",
        "srsly",
        "catalogue",
        "tldextract",
        "PyPDF2",
        "docx",
        args.model_package,
    ]

    for package in collect_candidates:
        if package and module_exists(package):
            cmd.extend(["--collect-all", package])

    if args.model_package and not module_exists(args.model_package):
        if not args.allow_missing_model:
            raise RuntimeError(
                f"spaCy model package '{args.model_package}' is missing. "
                f"Install it before build (example: python -m spacy download {args.model_package}) "
                "or pass --allow-missing-model to continue."
            )
        print(
            f"Warning: model package '{args.model_package}' not found. "
            "Executable will rely on model availability at runtime."
        )

    cmd.append(str(ENTRYPOINT))
    return cmd


def output_root(args: argparse.Namespace) -> Path:
    return args.distpath if args.onefile else (args.distpath / args.name)


def packaged_binary_path(args: argparse.Namespace) -> Path:
    return output_root(args) / packaged_binary_name(args.name)


def post_build_config_copy(args: argparse.Namespace) -> Optional[Path]:
    if not DEFAULT_CONFIG.exists():
        return None

    target = output_root(args) / packaged_config_name(args)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEFAULT_CONFIG, target)
    print(f"Config file copied to: {target}")
    return target


def create_command_launchers(args: argparse.Namespace) -> None:
    """
    Create convenience command launchers which always pass local config first.
    If the user passes another --config later, argparse will use the last value.
    """
    target_dir = output_root(args)
    target_dir.mkdir(parents=True, exist_ok=True)

    binary_name = packaged_binary_name(args.name)
    config_name = packaged_config_name(args)
    command_name = args.command_name

    unix_launcher = target_dir / command_name
    unix_launcher.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                "set -eu",
                'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
                f'BIN="$SCRIPT_DIR/{binary_name}"',
                f'CONFIG="$SCRIPT_DIR/{config_name}"',
                'if [ ! -f "$BIN" ]; then',
                f'  echo "Executable not found: {binary_name}" >&2',
                "  exit 1",
                "fi",
                'if [ -f "$CONFIG" ]; then',
                '  exec "$BIN" --config "$CONFIG" "$@"',
                "fi",
                'exec "$BIN" "$@"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        unix_launcher.chmod(0o755)
    except Exception:
        pass

    windows_launcher = target_dir / f"{command_name}.cmd"
    windows_launcher.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                "set SCRIPT_DIR=%~dp0",
                f"set BIN=%SCRIPT_DIR%{binary_name}",
                f"set CONFIG=%SCRIPT_DIR%{config_name}",
                "if exist \"%CONFIG%\" (",
                "  \"%BIN%\" --config \"%CONFIG%\" %*",
                ") else (",
                "  \"%BIN%\" %*",
                ")",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )

    print(f"Command launchers created: {unix_launcher} and {windows_launcher}")


def create_zip_package(args: argparse.Namespace) -> Optional[Path]:
    """
    Create a distributable zip package.
    For onefile builds, create a temporary bundle folder with binary+config+launchers.
    """
    dist_root = output_root(args)
    platform_tag = f"{platform.system().lower()}-{platform.machine().lower()}"
    archive_base = args.distpath / f"{args.name}-{platform_tag}"
    archive_zip = archive_base.with_suffix(".zip")

    if archive_zip.exists():
        archive_zip.unlink()

    if args.onefile:
        bundle_dir = args.distpath / f"{args.name}-bundle"
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        bundle_dir.mkdir(parents=True, exist_ok=True)

        file_candidates = [
            packaged_binary_path(args),
            output_root(args) / packaged_config_name(args),
            output_root(args) / args.command_name,
            output_root(args) / f"{args.command_name}.cmd",
        ]
        for candidate in file_candidates:
            if candidate.exists():
                shutil.copy2(candidate, bundle_dir / candidate.name)

        shutil.make_archive(str(archive_base), "zip", root_dir=bundle_dir.parent, base_dir=bundle_dir.name)
    else:
        shutil.make_archive(str(archive_base), "zip", root_dir=args.distpath, base_dir=args.name)

    print(f"Zip package created: {archive_zip}")
    return archive_zip


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build standalone scanner executable")
    parser.add_argument("--name", default="dpdp-pii-scanner", help="Executable name")
    parser.add_argument(
        "--command-name",
        default="dpdp-scan",
        help="Launcher command name created in dist output.",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single-file executable (default is onedir for reliability).",
    )
    parser.add_argument(
        "--model-package",
        default="en_core_web_lg",
        help="spaCy model package to bundle.",
    )
    parser.add_argument(
        "--allow-missing-model",
        action="store_true",
        help="Allow build without installed spaCy model package.",
    )
    parser.add_argument("--distpath", type=Path, default=ROOT / "dist")
    parser.add_argument("--workpath", type=Path, default=ROOT / "build" / "pyinstaller")
    parser.add_argument("--specpath", type=Path, default=ROOT / "build" / "pyinstaller")
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Create a .zip package in dist after build.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not is_supported_python():
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(
            f"Unsupported Python runtime for build: {current}. "
            f"Use Python {supported_python_series()} and recreate .venv.",
            file=sys.stderr,
        )
        return 1

    if not ENTRYPOINT.exists():
        print(f"Entry point not found: {ENTRYPOINT}", file=sys.stderr)
        return 1

    mixed_venv_libs = detect_mixed_virtualenv()
    if mixed_venv_libs:
        print(
            "Build environment is inconsistent: multiple site-packages folders were found "
            f"under this venv ({', '.join(mixed_venv_libs)}).\n"
            "Recreate .venv using a single Python version and reinstall dependencies:\n"
            "  rm -rf .venv\n"
            "  python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  python -m pip install --upgrade pip\n"
            "  python -m pip install -r requirements.txt\n"
            "  python -m spacy download en_core_web_lg",
            file=sys.stderr,
        )
        return 1

    missing_modules = find_missing_build_modules()
    if missing_modules:
        missing = ", ".join(missing_modules)
        print(
            f"Build dependencies are missing for interpreter {sys.executable}: {missing}\n"
            "Install build dependencies with:\n"
            "  python -m pip install --upgrade pip\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    if not module_exists("PyInstaller"):
        print("PyInstaller is not installed. Install dependencies from requirements.txt", file=sys.stderr)
        return 1

    args.distpath.mkdir(parents=True, exist_ok=True)
    args.workpath.mkdir(parents=True, exist_ok=True)
    args.specpath.mkdir(parents=True, exist_ok=True)

    try:
        cmd = build_command(args)
        print("Running:", " ".join(cmd))
        pyi_config_dir = args.workpath / "pyinstaller-cache"
        pyi_config_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.setdefault("PYINSTALLER_CONFIG_DIR", str(pyi_config_dir))
        subprocess.run(cmd, check=True, env=env)
        post_build_config_copy(args)
        create_command_launchers(args)
        if args.zip:
            create_zip_package(args)
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    binary_path = packaged_binary_path(args)
    print(f"Build completed. Executable path: {binary_path}")
    print(f"Command launcher path: {output_root(args) / args.command_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
