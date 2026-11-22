"""Source-level workflow guards and shell parsing; not a substitute for YAML parsing."""

from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile
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

    def watch_job(self):
        source = self.source()
        self.assertEqual(source.count("\n  watch_probe:\n"), 1)
        return source.split("\n  watch_probe:\n", 1)[1].split("\n  watch_smoke:\n", 1)[0]

    def test_watch_smoke_runs_independently_and_preserves_evidence(self):
        source = self.source()
        self.assertEqual(source.count("\n  watch_smoke:\n"), 1)
        job = source.split("\n  watch_smoke:\n", 1)[1]
        self.assertNotRegex(job, r"(?m)^\s*(needs|continue-on-error):")
        self.assertIn("runs-on: xcode-27", job)
        self.assertIn("DEVELOPER_DIR: /Applications/Xcode_27.1.app/Contents/Developer", job)
        self.assertIn("python3 -B scripts/ci/run_watch_smoke.py --output build/watch-smoke", job)
        artifact = job.split("- name: Preserve Watch UI smoke evidence", 1)[1]
        self.assertIn("if: ${{ always() }}", artifact)
        for path in ("*.log", "outcome.json", "capability/", "WatchSmoke.xcresult/"):
            self.assertIn("build/watch-smoke/" + path, artifact)

    def test_existing_validation_job_is_unchanged(self):
        # Fingerprint of the complete approved workflow before adding the
        # independent diagnostic job, including every existing build/test command.
        original = self.source().split("\n  watch_probe:\n", 1)[0].rstrip()
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "0e1931cdd3d0d7a89e0af2e1db3e035f7e209c9897be2c0f5091e625e147e278")

    def test_watch_probe_is_independent_and_uses_established_toolchain(self):
        job = self.watch_job()
        header = job.split("    steps:", 1)[0]
        self.assertIn("name: Watch Simulator capability gate (configuration only)", header)
        self.assertIn("runs-on: xcode-27", header)
        self.assertIn("DEVELOPER_DIR: /Applications/Xcode_27.1.app/Contents/Developer", header)
        self.assertRegex(header, r"timeout-minutes: [1-9][0-9]*")
        self.assertNotRegex(header, r"(?m)^\s*(needs|if):")
        self.assertNotIn("steps.ui_tests", job)
        self.assertNotIn("needs.", job)
        self.assertIn("uses: actions/checkout@v7", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("if ! command -v xcodegen > /dev/null 2>&1; then\n            brew install xcodegen", job)

    def test_watch_probe_generation_order_arguments_and_failure_propagation(self):
        job = self.watch_job()
        blocks = run_blocks(job)
        self.assertEqual(len(blocks), 4)
        self.assertIn("test ! -e build/watch-probe", blocks[0])
        self.assertIn("test -f DaylightWatchUITests/DaylightWatchUITests.swift", blocks[0])
        self.assertIn("xcodegen generate --spec project.yml", blocks[2])
        self.assertEqual(blocks[3].strip(),
            "set -euo pipefail\npython3 scripts/ci/probe_watch_simulator.py "
            "--project DaylightApp.xcodeproj --output build/watch-probe")
        self.assertNotIn("continue-on-error", job)
        for step in re.split(r"(?m)^      - name: ", job)[1:]:
            if not step.startswith("Preserve Watch probe diagnostics"):
                self.assertNotRegex(step, r"(?m)^\s*if:")
        for block in blocks:
            self.assertNotIn("|| true", block)
            self.assertTrue(block.startswith("set -euo pipefail"))
            self.assertNotRegex(block, r"simctl|xcodebuild|select_simulator|download|erase|delete")
            self.assertNotIn("mkdir -p build/watch-probe\n", block)

    def test_watch_probe_artifacts_survive_failure_and_are_separate(self):
        job = self.watch_job()
        artifact = job.split("- name: Preserve Watch probe diagnostics\n", 1)[1]
        self.assertIn("if: ${{ always() }}", artifact)
        self.assertIn("uses: actions/upload-artifact@v7", artifact)
        self.assertIn("name: daylight-watch-probe-${{ github.run_id }}-${{ github.run_attempt }}", artifact)
        self.assertIn("build/watch-probe/", artifact)
        self.assertIn("build/watch-probe-setup/", artifact)
        self.assertNotIn("daylight-validation-", artifact)
        self.assertGreater(job.index("- name: Preserve Watch probe diagnostics"),
                           job.index("- name: Probe Watch Simulator capabilities"))

    def test_watch_xcodegen_install_captures_both_streams_and_preserves_failure(self):
        job = self.watch_job()
        step = job.split("- name: Install XcodeGen for Watch probe\n", 1)[1].split("      - name:", 1)[0]
        blocks = run_blocks(step)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertLess(block.index("mkdir -p build/watch-probe-setup"), block.index("brew install"))
        self.assertIn("brew install xcodegen 2>&1 | tee build/watch-probe-setup/xcodegen-install.log", block)
        self.assertIn("set -euo pipefail", block)
        artifact = job.split("- name: Preserve Watch probe diagnostics\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn("if: ${{ always() }}", artifact)
        self.assertIn("build/watch-probe-setup/", artifact)

        bash = shutil.which("bash")
        if not bash:
            git = shutil.which("git")
            candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
            if candidate and candidate.is_file():
                bash = str(candidate)
        if not bash:
            self.skipTest("No installed Bash is available for mocked installation execution")
        for exit_code in (0, 23):
            with self.subTest(installation_exit=exit_code), tempfile.TemporaryDirectory() as temporary:
                # Functions prevent execution of real installers. Force only the
                # presence check to report missing, then execute the actual step.
                prelude = '''command() {
  if [ "$*" = "-v xcodegen" ]; then return 1; fi
  builtin command "$@"
}
brew() {
  printf 'synthetic install stdout\\n'
  printf 'synthetic install stderr\\n' >&2
  return %d
}
xcodegen() { printf 'synthetic version reached\\n'; }
''' % exit_code
                result = subprocess.run([bash], input=prelude + block, text=True,
                    cwd=temporary, capture_output=True, timeout=10, check=False)
                self.assertEqual(result.returncode, exit_code, result.stderr)
                setup = Path(temporary) / "build/watch-probe-setup"
                self.assertEqual((setup / "xcodegen-install.log").read_text(encoding="utf-8"),
                                 "synthetic install stdout\nsynthetic install stderr\n")
                self.assertEqual((setup / "xcodegen-version.log").exists(), exit_code == 0)


if __name__ == "__main__":
    unittest.main()
