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
        self.assertEqual(["setuptools>=77.0.3", "wheel"], data["build-system"]["requires"])
        self.assertEqual("ai-engineering-guardrails", data["project"]["name"])
        self.assertEqual(
            "ai_engineering_guardrails.cli:main",
            data["project"]["scripts"]["ai-guardrails"],
        )
        self.assertEqual(["rich>=15.0.0,<16"], data["project"]["dependencies"])
        self.assertEqual(">=3.11", data["project"]["requires-python"])
        self.assertEqual("MIT", data["project"]["license"])
        self.assertEqual(["LICENSE"], data["project"]["license-files"])
        self.assertNotIn("License :: OSI Approved :: MIT License", data["project"]["classifiers"])
        self.assertTrue((RESOURCE_ROOT / "policy/manifest.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "enforcement/command-policy.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "evidence/registry.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "assurance/task-schema.json").is_file())
        self.assertTrue((RESOURCE_ROOT / "packs").is_dir())
        self.assertFalse((REPOSITORY_ROOT / "guardrails").exists())

    def test_packaged_readme_uses_absolute_documentation_links(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("](docs/", readme)
        self.assertIn("docs/README.md", readme)
        self.assertIn("assets/ai_comic_screen_only_corrected.png", (REPOSITORY_ROOT / "MANIFEST.in").read_text(encoding="utf-8"))

    def test_public_install_guides_use_the_published_package_without_stale_claims(self) -> None:
        stale_phrases = (
            "this repository does not publish a package",
            "package is not published",
            "publication is only prepared",
            "install the application from a reviewed clone",
        )
        required_sequence = (
            "pipx install ai-engineering-guardrails",
            "ai-guardrails install --dry-run",
            "ai-guardrails install",
            "ai-guardrails status",
        )
        for relative in ("README.md", "docs/user-guide.md"):
            with self.subTest(document=relative):
                text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
                lowered = text.lower()
                for phrase in stale_phrases:
                    self.assertNotIn(phrase, lowered)
                lines = [line.strip() for line in text.splitlines()]
                positions = [lines.index(value) for value in required_sequence]
                self.assertEqual(positions, sorted(positions))

    def test_operator_documentation_and_release_governance_entrypoints_exist(self) -> None:
        for relative in (
            "docs/README.md",
            "docs/releasing.md",
            "docs/evidence-and-assurance.md",
            "docs/technical-writing.md",
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
            (outside / "component").mkdir()
            (outside / "component/SKILL.md").write_text(
                "---\nname: component\ndescription: Inspect a bounded local fixture without executing its resources.\n---\n\n# Fixture\n",
                encoding="utf-8",
            )
            (outside / "reports").mkdir()
            (outside / "reports/before.sarif").write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")
            (outside / "reports/after.sarif").write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")
            (outside / "reports/before.xml").write_text('<coverage line-rate="1"/>', encoding="utf-8")
            (outside / "reports/after.xml").write_text('<coverage line-rate="1"/>', encoding="utf-8")
            (outside / "reports/tests.xml").write_text('<testsuite><testcase name="ok"/></testsuite>', encoding="utf-8")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = ""
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["HOME"] = str(home)
            environment["USERPROFILE"] = str(home)
            environment["XDG_CONFIG_HOME"] = str(home / ".config")
            environment["APPDATA"] = str(home / "AppData/Roaming")
            environment["LOCALAPPDATA"] = str(home / "AppData/Local")
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
            private_key_marker = b"-----BEGIN " + b"PRIVATE KEY-----"
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
                self.assertIn("ai_engineering_guardrails/_resources/evidence/registry.json", names)
                self.assertIn("ai_engineering_guardrails/_resources/assurance/task-schema.json", names)
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
                metadata = archive.read(metadata_path).decode("utf-8")
                self.assertEqual(
                    ["Requires-Dist: rich<16,>=15.0.0"],
                    [line for line in metadata.splitlines() if line.startswith("Requires-Dist:")],
                )
                self.assertIn("License-Expression: MIT", metadata)
                self.assertIn("License-File: LICENSE", metadata)
                self.assertNotIn("Classifier: License ::", metadata)
                self.assertTrue(any(name.endswith(".dist-info/licenses/LICENSE") for name in names))
                self.assertFalse(
                    any(
                        "/.idea/" in f"/{name}"
                        or "/.DS_Store" in f"/{name}"
                        or "__pycache__" in name
                        or name.endswith((".pyc", ".tmp"))
                        for name in names
                    )
                )
                for name in names:
                    if name.endswith("/"):
                        continue
                    content = archive.read(name)
                    self.assertNotIn(str(REPOSITORY_ROOT).encode(), content)
                    self.assertNotIn(str(Path.home()).encode(), content)
                    self.assertNotIn(private_key_marker, content)
            with tarfile.open(sdist) as archive:
                names = archive.getnames()
                self.assertTrue(any(name.endswith("ai_engineering_guardrails/_resources/policy/manifest.json") for name in names))
                self.assertTrue(any(name.endswith("/LICENSE") for name in names))
                self.assertTrue(any(name.endswith("docs/terminal-ux.md") for name in names))
                self.assertTrue(any(name.endswith("docs/README.md") for name in names))
                self.assertTrue(any(name.endswith("docs/releasing.md") for name in names))
                self.assertTrue(any(name.endswith("docs/evidence-and-assurance.md") for name in names))
                self.assertTrue(any(name.endswith("docs/technical-writing.md") for name in names))
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
                forbidden_parts = {
                    ".DS_Store",
                    ".idea",
                    ".pytest_cache",
                    ".mypy_cache",
                    "__pycache__",
                    ".ai-guardrails",
                    "release",
                }
                for member in archive.getmembers():
                    parts = set(Path(member.name).parts)
                    self.assertFalse(parts & forbidden_parts, member.name)
                    if not member.isfile():
                        continue
                    self.assertLessEqual(member.size, 2_000_000, member.name)
                    content_file = archive.extractfile(member)
                    self.assertIsNotNone(content_file)
                    content = content_file.read()
                    self.assertNotIn(str(REPOSITORY_ROOT).encode(), content)
                    self.assertNotIn(str(Path.home()).encode(), content)
                    self.assertNotIn(private_key_marker, content)

            environment_root = temporary_root / "venv"
            # CI installs the exact reviewed direct dependency set before this
            # offline smoke test. Expose that set without consulting an index;
            # the project wheel itself is still installed only into this venv.
            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment_root)
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
            dependency_script = """
import importlib.metadata as metadata
import markdown_it
import pygments
import rich
from pip._vendor.packaging.requirements import Requirement

pending = ["ai-engineering-guardrails"]
checked = set()
while pending:
    distribution = pending.pop()
    key = distribution.casefold()
    if key in checked:
        continue
    checked.add(key)
    for raw_requirement in metadata.requires(distribution) or ():
        requirement = Requirement(raw_requirement)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        installed = metadata.version(requirement.name)
        if requirement.specifier and installed not in requirement.specifier:
            raise RuntimeError(f"{requirement.name} {installed} does not satisfy {requirement.specifier}")
        pending.append(requirement.name)
print(metadata.version("rich"))
print("|".join(sorted(checked)))
"""
            dependency_check = subprocess.run(
                [
                    str(interpreter),
                    "-c",
                    dependency_script,
                ],
                cwd=outside,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            dependency_lines = dependency_check.stdout.strip().splitlines()
            self.assertEqual("15.0.0", dependency_lines[0])
            self.assertTrue(
                {"ai-engineering-guardrails", "rich", "markdown-it-py", "pygments", "mdurl"}
                .issubset(set(dependency_lines[1].split("|")))
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
            self.assertTrue(package_dir.resolve().is_relative_to(environment_root.resolve()), package_dir)
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
                ["task", "--help"],
                ["component", "--help"],
                ["complexity", "--help"],
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
                ["policy", "audit"],
                ["policy", "evidence", "maintainability"],
                ["task", "init", "--repo", str(outside)],
                ["task", "validate", "--repo", str(outside)],
                ["task", "status", "--repo", str(outside)],
                ["task", "receipt", "--repo", str(outside), "--format", "json"],
                ["component", "inspect", str(outside / "component")],
                ["component", "audit", "--home", str(home)],
                ["skills", "audit"],
                [
                    "complexity", "compare", "--repo", str(outside),
                    "--baseline-sarif", "reports/before.sarif", "--current-sarif", "reports/after.sarif",
                    "--baseline-coverage", "reports/before.xml", "--current-coverage", "reports/after.xml",
                    "--junit", "reports/tests.xml",
                ],
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
