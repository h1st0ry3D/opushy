#!/usr/bin/python3
"""Tests for state/opushy-state.py.

The interesting cases are the ones the panel cannot defend against by itself: a
pathname that is a symlink, a FIFO, a directory or a monster, and a document that
is not what the writer produces.

The file-level cases call the helper's functions with a throwaway `anchor` (the
home to walk from), so nothing here can reach the real tracker. The command line
never takes an anchor, which is what `CommandLineTest` below pins down.

Run: python3 tests/test_state_helper.py   (or ./run_tests.sh)
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HELPER = os.path.join(ROOT, "state", "opushy-state.py")


def load_helper():
    spec = importlib.util.spec_from_file_location("opushy_state", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load_helper()

# A document the helper must accept unchanged.
GOOD = {
    "maxPushups": 40,
    "reps": 33,
    "lastTrainingDate": "2026-09-27T12:00:00.000Z",
    "trainingDays": 5,
    "history": [
        {"ts": "2026-09-26T12:00:00.000Z", "reps": 33},
        {"ts": "2026-09-27T12:00:00.000Z", "reps": 34},
    ],
}


class HelperTest(unittest.TestCase):
    """The file operations, against a throwaway home."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="opushy-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.state_dir = os.path.join(self.home, ".local", "state", "opushy")
        self.state_file = os.path.join(self.state_dir, "tracker.json")

    # ---- driving the helper ----

    def read(self):
        """The helper's stdout for a read, captured."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            state.state_read(self.home)
        return buffer.getvalue()

    def write(self, document):
        payload = document if isinstance(document, (str, bytes)) else json.dumps(document)
        return state.state_write(self.home, payload)

    def write_state_file(self, document, mode=0o600, raw=None):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as handle:
            handle.write(raw if raw is not None else json.dumps(document))
        os.chmod(self.state_file, mode)

    def stored(self):
        with open(self.state_file, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    # ---- the happy path ----

    def test_a_missing_file_is_a_first_run_not_an_error(self):
        self.assertEqual(self.read(), "")

    def test_write_then_read_round_trips(self):
        self.write(GOOD)
        self.assertEqual(self.stored(), GOOD)
        self.assertEqual(json.loads(self.read()), GOOD)

    def test_the_state_directory_and_file_are_private(self):
        self.write(GOOD)
        self.assertEqual(self.mode(self.state_dir), 0o700)
        self.assertEqual(self.mode(self.state_file), 0o600)

    def test_the_written_file_is_indented(self):
        self.write(GOOD)
        with open(self.state_file, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertIn("\n  ", raw)
        self.assertTrue(raw.endswith("\n"))

    def test_a_wide_directory_and_file_are_repaired(self):
        self.write_state_file(GOOD, mode=0o644)
        os.chmod(self.state_dir, 0o755)
        self.read()
        self.assertEqual(self.mode(self.state_dir), 0o700)
        self.assertEqual(self.mode(self.state_file), 0o600)

    def test_a_planted_symlink_in_the_state_directory_is_removed(self):
        os.makedirs(self.state_dir, exist_ok=True)
        victim = os.path.join(self.home, "victim")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write("must survive")
        os.symlink(victim, self.state_file)
        self.read()
        self.assertFalse(os.path.islink(self.state_file))
        with open(victim, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "must survive")

    def test_writing_replaces_a_symlink_instead_of_following_it(self):
        os.makedirs(self.state_dir, exist_ok=True)
        victim = os.path.join(self.home, "victim")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write("must survive")
        os.symlink(victim, self.state_file)

        self.write(GOOD)
        with open(victim, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "must survive")
        self.assertEqual(self.stored(), GOOD)
        self.assertEqual(self.mode(self.state_file), 0o600)

    # ---- refused reads ----

    def test_a_symlinked_state_file_is_removed_not_followed(self):
        # The directory repair drops anything that is not a regular file, so a
        # planted symlink is never opened: the read reports a first run and the
        # file it pointed at is untouched.
        os.makedirs(self.state_dir, exist_ok=True)
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(GOOD, handle)
        os.symlink(target, self.state_file)
        self.assertEqual(self.read(), "")
        self.assertFalse(os.path.lexists(self.state_file))
        with open(target, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), GOOD)      # never read through

    def test_a_fifo_state_file_does_not_hang(self):
        os.makedirs(self.state_dir, exist_ok=True)
        os.mkfifo(self.state_file)
        self.assertEqual(self.read(), "")
        self.assertFalse(os.path.lexists(self.state_file))

    def test_an_empty_directory_at_the_state_path_is_removed(self):
        os.makedirs(self.state_file, exist_ok=True)
        self.assertEqual(self.read(), "")
        self.assertFalse(os.path.lexists(self.state_file))

    def test_a_directory_holding_someone_elses_file_is_refused_not_emptied(self):
        # The repair never removes a tree it did not create, so a directory that
        # is not empty stays and the read is refused instead.
        os.makedirs(self.state_file, exist_ok=True)
        with open(os.path.join(self.state_file, "left-over"), "w", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(PermissionError):
            self.read()
        self.assertTrue(os.path.isdir(self.state_file))

    def test_an_oversized_state_file_is_refused(self):
        self.write_state_file(None, raw="{" + " " * (65536 + 1) + "}")
        with self.assertRaises(PermissionError):
            self.read()

    def test_a_symlinked_state_directory_is_refused(self):
        # The walk is O_NOFOLLOW on every component, so a symlinked state
        # directory is an error (ELOOP) rather than a redirect into a directory
        # somebody else owns.
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere, exist_ok=True)
        os.makedirs(os.path.join(self.home, ".local", "state"), exist_ok=True)
        os.symlink(elsewhere, self.state_dir)
        with self.assertRaises(OSError):
            self.read()

    def test_a_foreign_owned_file_is_refused(self):
        if os.geteuid() != 0:
            self.skipTest("needs root to hand a file to another uid")
        self.write_state_file(GOOD)
        os.chown(self.state_file, 1, 1)
        with self.assertRaises(PermissionError):
            self.read()

    # ---- refused writes ----

    def test_an_oversized_payload_is_refused(self):
        with self.assertRaises(ValueError):
            self.write({"maxPushups": 1, "pad": "x" * 70000})
        self.assertFalse(os.path.exists(self.state_file))

    def test_an_empty_or_broken_payload_is_refused(self):
        for payload in ("", "\n", "   \n", "not json\n", "[1,2,3]\n", '"a string"\n'):
            with self.assertRaises(ValueError, msg=repr(payload)):
                self.write(payload)
        self.assertFalse(os.path.exists(self.state_file))

    def test_a_hostile_document_is_reduced_to_the_schema(self):
        self.write({
            "maxPushups": 1e999,
            "reps": -5,
            "lastTrainingDate": "<img src=x>",
            "trainingDays": True,
            "history": [{"ts": "nope", "reps": 1},
                        {"ts": "2026-09-27T12:00:00.000Z", "reps": 34}],
            "unknown": {"nested": True},
        })
        self.assertEqual(self.stored(), {
            "maxPushups": 0,
            "reps": 0,
            "lastTrainingDate": "",
            "trainingDays": 0,
            "history": [{"ts": "2026-09-27T12:00:00.000Z", "reps": 34}],
        })

    def test_a_history_longer_than_the_cap_is_trimmed(self):
        history = [{"ts": "2026-09-27T12:00:00.000Z", "reps": 1} for _ in range(500)]
        self.write({"history": history})
        self.assertEqual(len(self.stored()["history"]), 400)

    # ---- the one-off import ----

    def test_the_legacy_file_is_imported_once(self):
        legacy_dir = os.path.join(self.home, "plugin")
        os.makedirs(legacy_dir, exist_ok=True)
        legacy = os.path.join(legacy_dir, "tracker.json")
        with open(legacy, "w", encoding="utf-8") as handle:     # mode 644, as Quickshell wrote it
            json.dump(GOOD, handle)
        os.chmod(legacy, 0o644)

        self.assertEqual(state.migrate(legacy, self.home), 0)
        self.assertEqual(self.stored(), GOOD)
        self.assertEqual(self.mode(self.state_file), 0o600)

        # A second import must not overwrite what the plugin has written since.
        self.write({"maxPushups": 99})
        state.migrate(legacy, self.home)
        self.assertEqual(self.stored()["maxPushups"], 99)

    def test_a_missing_legacy_file_is_not_an_error(self):
        self.assertEqual(state.migrate(os.path.join(self.home, "nope", "tracker.json"), self.home), 0)
        self.assertFalse(os.path.exists(self.state_file))

    def test_a_broken_legacy_path_is_refused(self):
        for path in ("", "relative/tracker.json", "/", "/tmp/\0x", "/tmp/../etc/x"):
            with self.assertRaises(PermissionError, msg=repr(path)):
                state.migrate(path, self.home)
        self.assertFalse(os.path.exists(self.state_file))

    def test_a_symlinked_legacy_file_is_not_imported(self):
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(GOOD, handle)
        link = os.path.join(self.home, "tracker.json")
        os.symlink(target, link)
        with self.assertRaises(PermissionError):
            state.migrate(link, self.home)
        self.assertFalse(os.path.exists(self.state_file))

    def test_an_oversized_legacy_file_is_not_imported(self):
        legacy = os.path.join(self.home, "tracker.json")
        with open(legacy, "w", encoding="utf-8") as handle:
            handle.write("{" + " " * (65536 + 1) + "}")
        with self.assertRaises(PermissionError):
            state.migrate(legacy, self.home)
        self.assertFalse(os.path.exists(self.state_file))


class CommandLineTest(unittest.TestCase):
    """The argument handling and exit codes, through the real binary."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="opushy-cli-")
        self.addCleanup(shutil.rmtree, self.home, True)
        # A HOME that is not the passwd home: the binary must ignore it, so
        # nothing in this class can reach the real tracker.
        self.state_file = os.path.join(self.home, ".local", "state", "opushy", "tracker.json")

    def run_helper(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-I", "-S", "-B", HELPER] + list(args),
                              input=stdin, capture_output=True, text=True, timeout=20,
                              env={"HOME": self.home, "PATH": "/usr/bin:/bin", "LC_ALL": "C"})

    def test_usage_is_an_error(self):
        for args in ([], ["state"], ["state", "sideways"], ["migrate"], ["other", "read"]):
            result = self.run_helper(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("usage:", result.stderr)

    def test_a_read_writes_nothing_under_HOME(self):
        result = self.run_helper("state", "read")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.state_file))

    def test_a_refused_argument_reports_one_line_not_a_traceback(self):
        # A malformed path is refused before the state directory is touched, so
        # this cannot depend on what the real home happens to contain.
        for path in ("", "relative/tracker.json", "/tmp/../etc/passwd"):
            result = self.run_helper("migrate", path)
            self.assertEqual(result.returncode, 1, repr(path))
            self.assertEqual(len(result.stderr.strip().splitlines()), 1, repr(path))
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
