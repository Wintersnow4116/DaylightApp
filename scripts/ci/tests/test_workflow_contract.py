"""Source-level workflow guards and shell parsing; not a substitute for YAML parsing."""

from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[3]


def run_blocks(source):
    lines = source.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("run: "):
            value = line.lstrip()[5:]
            if value == "|":
                indent = len(line) - len(line.lstrip())
                following = []
                index += 1
                while index < len(lines) and (not lines[index].strip()
                        or len(lines[index]) - len(lines[index].lstrip()) > indent):
                    following.append(lines[index])
                    index += 1
                blocks.append(textwrap.dedent("\n".join(following)))
                continue
            blocks.append(value)
        index += 1
    return blocks


class WorkflowContractTests(unittest.TestCase):
    def source(self):
        return (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")

    def test_required_builds_dispatch_and_evidence_are_retained(self):
        source = self.source()
        self.assertRegex(source, r"(?m)^  workflow_dispatch:")
        for name in ("Build iOS Simulator Debug", "Build iOS Simulator Release",
                     "Build watchOS Simulator Debug", "Build watchOS Simulator Release"):
            self.assertIn(f"- name: {name}", source)
        self.assertEqual(source.count("-configuration Debug"), 2)
        self.assertEqual(source.count("-configuration Release"), 2)
        self.assertIn("-only-testing:DaylightUITests", source)
        self.assertIn("build/TestResults/DaylightUITests.xcresult", source)
        self.assertIn("build/validation/", source)
        artifact = source.split("- name: Preserve validation results and diagnostics", 1)[1]
        self.assertIn("if: ${{ always() }}", artifact.split("- name:", 1)[0])
        for step in ("ios_debug", "ios_release", "watch_debug", "watch_release"):
            section = source.split(f"id: {step}", 1)[1].split("- name:", 1)[0]
            self.assertIn("!cancelled() && steps.generate.outcome == 'success'", section)
            self.assertIn("CODE_SIGNING_ALLOWED=NO", section)
            self.assertIn("set -euo pipefail", section)
        self.assertIn("**Not automated:** watchOS installation, launch, button interaction", source)

    def test_all_run_blocks_have_valid_bash_syntax_when_bash_is_installed(self):
        bash = shutil.which("bash")
        if not bash:
            git = shutil.which("git")
            candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
            if candidate and candidate.is_file():
                bash = str(candidate)
        if not bash:
            self.skipTest("No installed Bash is available for shell syntax checks")
        blocks = run_blocks(self.source())
        self.assertGreaterEqual(len(blocks), 10)
        for index, block in enumerate(blocks):
            with self.subTest(block=index):
                # -n parses only: no build, installation or simulator command executes.
                result = subprocess.run([bash, "-n"], input=block, text=True,
                                        capture_output=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
