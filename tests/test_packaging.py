from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import venv
import zipfile
from pathlib import Path

from ai_engineering_guardrails import __version__
from ai_engineering_guardrails.resources import RESOURCE_ROOT


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _package_build_available() -> bool:
    """Avoid treating an unrelated module named ``build`` as PyPA build."""
    if importlib.util.find_spec("build") is None or importlib.util.find_spec("wheel") is None:
        return False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class PackagingTests(unittest.TestCase):
    def test_declarative_metadata_and_resource_tree(self) -> None:
        data = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual("ai-engineering-guardrails", data["project"]["name"])
        self.assertEqual(
            "ai_engineering_guardrails.cli:main",
            data["project"]["scripts"]["ai-guardrails"],
        )
        self.assertEqual([], data["project"]["dependencies"])
        self.assertEqual(">=3.11", data["project"]["requires-python"])
        self.assertTrue((RESOURCE_ROOT / "policy/manifest.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "enforcement/command-policy.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "packs").is_dir())
        self.assertFalse((REPOSITORY_ROOT / "guardrails").exists())

    def test_packaged_readme_uses_absolute_documentation_links(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("](docs/", readme)
        self.assertIn("docs/README.md", readme)
        self.assertIn("assets/ai_comic_screen_only_corrected.png", (REPOSITORY_ROOT / "MANIFEST.in").read_text(encoding="utf-8"))

    def test_operator_documentation_and_release_governance_entrypoints_exist(self) -> None:
        for relative in (
            "docs/README.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "CHANGELOG.md",
            ".github/CODEOWNERS",
        ):
            self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)

    @unittest.skipUnless(_package_build_available(), "PyPA build and wheel are not installed")
    def test_wheel_and_sdist_work_outside_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            output = temporary_root / "release"
            outside = temporary_root / "outside"
            home = temporary_root / "home"
            outside.mkdir()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = ""
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            subprocess.run(
                [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            wheel = next(output.glob("*.whl"))
            sdist = next(output.glob("*.tar.gz"))
            expected_resources = _tree_hashes(RESOURCE_ROOT)
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                self.assertIn("ai_engineering_guardrails/__init__.py", names)
                self.assertIn("ai_engineering_guardrails/_resources/policy/manifest.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/enforcement/command-policy.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/packs/languages/python/pack.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/routing/model-maps/vscode.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/routing/model-maps/visualstudio.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/routing/model-maps/jetbrains.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/ux/statusline-profiles.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/ux/complexity-thresholds.json", names)
                self.assertFalse(any(name.startswith("guardrails/") for name in names))
                resource_prefix = "ai_engineering_guardrails/_resources/"
                wheel_resources = {
                    name.removeprefix(resource_prefix): hashlib.sha256(archive.read(name)).hexdigest()
                    for name in names
                    if name.startswith(resource_prefix) and not name.endswith("/")
                }
                self.assertEqual(expected_resources, wheel_resources)
                entry_point_path = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
                entry_points = archive.read(entry_point_path).decode("utf-8")
                self.assertIn("ai-guardrails = ai_engineering_guardrails.cli:main", entry_points)
                metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
                self.assertNotIn("Requires-Dist:", archive.read(metadata_path).decode("utf-8"))
            with tarfile.open(sdist) as archive:
                names = archive.getnames()
                self.assertTrue(any(name.endswith("ai_engineering_guardrails/_resources/policy/manifest.json") for name in names))
                self.assertTrue(any(name.endswith("docs/terminal-ux.md") for name in names))
                self.assertTrue(any(name.endswith("docs/README.md") for name in names))
                for filename in (
                    "SECURITY.md",
                    "CONTRIBUTING.md",
                    "CODE_OF_CONDUCT.md",
                    "CHANGELOG.md",
                ):
                    self.assertTrue(any(name.endswith(filename) for name in names), filename)
                self.assertFalse(any("/guardrails/" in name for name in names))
                self.assertFalse(any("/.idea/" in name or "/release/" in name for name in names))
                resource_marker = "/ai_engineering_guardrails/_resources/"
                sdist_resources = {
                    name.split(resource_marker, 1)[1]: hashlib.sha256(archive.extractfile(name).read()).hexdigest()
                    for name in names
                    if resource_marker in name and archive.getmember(name).isfile()
                }
                self.assertEqual(expected_resources, sdist_resources)
                self.assertTrue(any(name.endswith("assets/ai_comic_screen_only_corrected.png") for name in names))

            environment_root = temporary_root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment_root)
            scripts = environment_root / ("Scripts" if os.name == "nt" else "bin")
            interpreter = scripts / ("python.exe" if os.name == "nt" else "python")
            command = scripts / ("ai-guardrails.exe" if os.name == "nt" else "ai-guardrails")
            subprocess.run(
                [str(interpreter), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                cwd=outside,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            # Do not accidentally use optional validators or AI-product commands
            # from the developer's PATH while proving the isolated wheel.
            environment["PATH"] = str(scripts)

            def run_installed(arguments: list[str]) -> subprocess.CompletedProcess[str]:
                result = subprocess.run(
                    [str(command), *arguments],
                    cwd=outside,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    self.fail(
                        "installed command failed: "
                        + " ".join(arguments)
                        + f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                    )
                return result

            package_dir = Path(
                subprocess.run(
                    [str(interpreter), "-c", "import ai_engineering_guardrails as p; print(p.__path__[0])"],
                    cwd=outside,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            before = _tree_hashes(package_dir)
            module_path = subprocess.run(
                [str(interpreter), "-c", "import ai_engineering_guardrails as p; print(p.__file__)"],
                cwd=outside,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertNotIn(str(REPOSITORY_ROOT), module_path)
            old_import = subprocess.run(
                [str(interpreter), "-c", "import guardrails"], cwd=outside, env=environment, capture_output=True, text=True
            )
            self.assertNotEqual(0, old_import.returncode)
            module_version = subprocess.run(
                [str(interpreter), "-m", "ai_engineering_guardrails", "--version"],
                cwd=outside,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(f"ai-engineering-guardrails {__version__}", module_version)
            for arguments in (
                ["--help"],
                ["--version"],
                ["validate"],
                ["install", "--product", "codex", "--home", str(home), "--dry-run"],
                ["install", "--product", "vscode", "--home", str(home), "--dry-run"],
                ["install", "--product", "codex", "--home", str(home)],
                ["status", "--product", "codex", "--home", str(home)],
                ["update", "--product", "codex", "--home", str(home), "--dry-run"],
                ["update", "--product", "codex", "--home", str(home)],
                ["uninstall", "--product", "codex", "--home", str(home), "--dry-run"],
                ["uninstall", "--product", "codex", "--home", str(home)],
                ["packs", "list"],
                ["routing", "validate"],
                ["statusline", "capabilities"],
                ["statusline", "preview", "--product", "all", "--profile", "standard"],
                ["statusline", "install", "--product", "all", "--profile", "standard", "--home", str(home), "--dry-run"],
                ["statusline", "install", "--product", "all", "--profile", "standard", "--home", str(home)],
                ["statusline", "status", "--product", "all", "--home", str(home)],
                ["statusline", "uninstall", "--product", "all", "--home", str(home)],
                ["complexity", "--repo", str(outside)],
                ["activity", "--home", str(home)],
                ["demo", "--scenario", "all"],
                ["jetbrains", "print-chat-instructions"],
                ["explain", "--command", "git reset --hard"],
            ):
                run_installed(arguments)
            after = _tree_hashes(package_dir)
            self.assertEqual(before, after)
            version = run_installed(["--version"]).stdout.strip()
            self.assertEqual(f"ai-engineering-guardrails {__version__}", version)


if __name__ == "__main__":
    unittest.main()
