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

# A document the helper must accept unchanged. This is the shape 1.1 writes:
# `time` for the timestamp, one file called opushy_activity.json.
GOOD = {
    "maxPushups": 40,
    "reps": 33,
    "lastTrainingDate": "2026-09-27T12:00:00.000Z",
    "trainingDays": 5,
    "history": [
        {"time": "2026-09-26T12:00:00.000Z", "reps": 33},
        {"time": "2026-09-27T12:00:00.000Z", "reps": 34},
    ],
}

# The same document under the name 1.0 used, for the migration and for a
# read-before-the-rename. Same values on purpose: the point of every test that
# uses it is that a 1.0 history ends up as this one, byte for byte.
LEGACY = GOOD


class HelperTest(unittest.TestCase):
    """The file operations, against a throwaway home."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="opushy-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.state_dir = os.path.join(self.home, ".local", "state", "opushy")
        self.state_file = os.path.join(self.state_dir, "opushy_activity.json")
        # What 1.0 wrote, in the state directory. Only the migration tests touch
        # it; everything else must not know it exists.
        self.previous_file = os.path.join(self.state_dir, "tracker.json")
        self.backup_dir = os.path.join(self.state_dir, "backups")

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
            "history": [{"time": "nope", "reps": 1},
                        {"time": "2026-09-27T12:00:00.000Z", "reps": 34}],
            "unknown": {"nested": True},
        })
        self.assertEqual(self.stored(), {
            "maxPushups": 0,
            "reps": 0,
            "lastTrainingDate": "",
            "trainingDays": 0,
            "history": [{"time": "2026-09-27T12:00:00.000Z", "reps": 34}],
        })

    def test_a_history_longer_than_the_cap_is_trimmed(self):
        history = [{"time": "2026-09-27T12:00:00.000Z", "reps": 1} for _ in range(500)]
        self.write({"history": history})
        self.assertEqual(len(self.stored()["history"]), 400)

    # ---- the one-off import ----

    # ---- the 1.1 rename: tracker.json -> opushy_activity.json, ts -> time ----
    #
    # This is the one migration where getting it wrong loses a real history
    # silently, so each step is pinned: the old file is read, rewritten under
    # the new name and key, and only then removed.

    def write_previous(self, document=None, raw=None, mode=0o600):
        """Put 1.0's file in the state directory, as an upgrade would find it."""
        os.makedirs(self.state_dir, exist_ok=True)
        payload = raw if raw is not None else json.dumps(LEGACY)
        with open(self.previous_file, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(self.previous_file, mode)

    def legacy(self):
        """LEGACY with its `ts` keys put back, byte for byte as 1.0 wrote it."""
        return {
            "maxPushups": LEGACY["maxPushups"],
            "reps": LEGACY["reps"],
            "lastTrainingDate": LEGACY["lastTrainingDate"],
            "trainingDays": LEGACY["trainingDays"],
            "history": [{"ts": e["time"], "reps": e["reps"]} for e in LEGACY["history"]],
        }

    def test_a_1_0_file_is_renamed_and_its_history_kept(self):
        self.write_previous()
        self.assertEqual(state.migrate(self.target("nothing.json"), self.home), 0)
        # The same history, under the new name and the new key.
        self.assertEqual(self.stored(), LEGACY)
        self.assertFalse(os.path.exists(self.previous_file))
        with open(self.state_file, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn('"ts"', raw)
        self.assertIn('"time"', raw)
        self.assertEqual(self.mode(self.state_file), 0o600)

    def test_the_rename_runs_before_the_first_read(self):
        # Otherwise the panel reads a file that is not there yet and shows a
        # first run over the top of a history that still exists on disk.
        self.write_previous()
        state.migrate(self.target("nothing.json"), self.home)
        self.assertEqual(json.loads(self.read()), LEGACY)

    def test_a_legacy_file_from_the_plugin_folder_is_converted_too(self):
        # pre-1.0 wrote tracker.json next to Panel.qml, with ts.
        plugin = self.target("plugin")
        os.makedirs(plugin, exist_ok=True)
        legacy = os.path.join(plugin, "tracker.json")
        with open(legacy, "w", encoding="utf-8") as handle:
            json.dump(self.legacy(), handle)
        os.chmod(legacy, 0o644)

        self.assertEqual(state.migrate(legacy, self.home), 0)
        self.assertEqual(self.stored(), LEGACY)
        self.assertFalse(os.path.exists(self.previous_file))

    def test_a_1_0_file_wins_over_the_plugin_folder_copy(self):
        # The one in the state directory is the newer of the two.
        self.write_previous()
        plugin = self.target("plugin")
        os.makedirs(plugin, exist_ok=True)
        legacy = os.path.join(plugin, "tracker.json")
        with open(legacy, "w", encoding="utf-8") as handle:
            json.dump({"maxPushups": 1, "reps": 1}, handle)

        state.migrate(legacy, self.home)
        self.assertEqual(self.stored(), LEGACY)

    def test_the_rename_leaves_an_existing_new_file_alone(self):
        # A fresh state file is not a reason to delete a history that is sitting
        # beside it under the old name.
        self.write(GOOD)
        self.write_previous()

        self.assertEqual(state.migrate(self.target("nothing.json"), self.home), 0)
        self.assertEqual(self.stored(), GOOD)
        self.assertTrue(os.path.exists(self.previous_file))

    def test_the_rename_happens_only_once(self):
        self.write_previous()
        state.migrate(self.target("nothing.json"), self.home)
        self.write({"maxPushups": 77})
        state.migrate(self.target("nothing.json"), self.home)
        self.assertEqual(self.stored()["maxPushups"], 77)

    def test_a_1_0_file_that_is_broken_is_refused_and_kept(self):
        # Nothing is removed until a readable file has been written, so a bad
        # one is left for the user to look at instead of being deleted.
        self.write_previous(raw="not json")
        with self.assertRaises(ValueError):
            state.migrate(self.target("nothing.json"), self.home)
        self.assertFalse(os.path.exists(self.state_file))
        self.assertTrue(os.path.exists(self.previous_file))

    def test_an_oversized_1_0_file_is_refused_and_kept(self):
        self.write_previous(raw="{" + " " * (65536 + 1) + "}")
        with self.assertRaises(PermissionError):
            state.migrate(self.target("nothing.json"), self.home)
        self.assertTrue(os.path.exists(self.previous_file))

    def test_a_symlinked_1_0_file_is_not_followed(self):
        # The directory repair drops anything that is not a regular file, so a
        # link planted at the old name is removed rather than opened: the read
        # reports a first run and the file it pointed at is never touched.
        target = self.target("elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.legacy(), handle)
        os.makedirs(self.state_dir, exist_ok=True)
        os.symlink(target, self.previous_file)

        self.assertEqual(state.migrate(self.target("nothing.json"), self.home), 0)
        self.assertFalse(os.path.lexists(self.previous_file))
        self.assertFalse(os.path.exists(self.state_file))
        with open(target, "r", encoding="utf-8") as handle:
            # Never read through, and still in the old shape it was left in.
            self.assertEqual(json.load(handle), self.legacy())

    # ---- reading a document written before the rename ----

    def test_a_ts_history_is_still_read_and_written_back_as_time(self):
        # The panel's own read goes through Document.js, but the helper is what
        # has to survive a hand edit or an old backup.
        self.write(self.legacy())
        self.assertEqual(json.loads(self.read()), LEGACY)
        # And a rewrite drops the old key.
        self.write(self.legacy())
        with open(self.state_file, "r", encoding="utf-8") as handle:
            self.assertNotIn('"ts"', handle.read())

    def test_a_time_key_wins_over_a_ts_key_beside_it(self):
        mixed = {"history": [
            {"time": "2026-09-26T12:00:00.000Z", "ts": "1999-01-01T00:00:00.000Z",
             "reps": 7},
        ]}
        self.write(mixed)
        self.assertEqual(self.stored()["history"],
                         [{"time": "2026-09-26T12:00:00.000Z", "reps": 7}])

    def test_a_backup_written_before_the_rename_still_restores(self):
        # A file exported by 1.0, or by a 1.0 backup copy, is the whole point of
        # the feature, so it has to load rather than be refused as malformed.
        self.write(GOOD)
        old_backup = self.target("opushy_activity_2026-01-01.json")
        with open(old_backup, "w", encoding="utf-8") as handle:
            json.dump(self.legacy(), handle)
        self.restore(old_backup)
        self.assertEqual(self.stored(), LEGACY)

    def test_an_entry_with_only_ts_keeps_its_place_in_the_history(self):
        self.write({"history": [{"ts": "nope", "reps": 1},
                                {"ts": "2026-09-27T12:00:00.000Z", "reps": 34}]})
        self.assertEqual(self.stored()["history"],
                         [{"time": "2026-09-27T12:00:00.000Z", "reps": 34}])

    # ---- backup and restore ----

    def target(self, *parts):
        return os.path.join(self.home, *parts)

    def run_op(self, call, path, anchor=None):
        """Run a backup or a restore with its stdout captured, and hand back
        what it printed. The helper prints one result line for the panel, which
        would otherwise run over the test output."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = call(anchor or self.home, json.dumps({"path": path}))
        return code, buffer.getvalue()

    def export(self, path, anchor=None):
        return self.run_op(state.backup_export, path, anchor)

    def restore(self, path, anchor=None):
        return self.run_op(state.backup_restore, path, anchor)

    def exported(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_export_writes_the_state_document_where_asked(self):
        self.write(GOOD)
        out = os.path.join(self.home, "Documents")
        os.makedirs(out)
        target = os.path.join(out, "opushy_activity_2026-10-05.json")

        self.export(target)
        self.assertEqual(self.exported(target), GOOD)
        # The copy is as private as the state file it came from.
        self.assertEqual(self.mode(target), 0o600)

    def test_an_export_is_the_file_a_restore_reads_back(self):
        self.write(GOOD)
        target = self.target("backup.json")
        self.export(target)
        self.write({"maxPushups": 1, "reps": 1})
        self.restore(target)
        self.assertEqual(self.stored(), GOOD)

    def test_an_export_replaces_a_file_that_is_already_there(self):
        self.write(GOOD)
        target = self.target("backup.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({"maxPushups": 999}, handle)
        self.export(target)
        self.assertEqual(self.exported(target), GOOD)

    def test_a_restore_replaces_the_state_and_reports_it(self):
        self.write(GOOD)
        backup = self.target("backup.json")
        with open(backup, "w", encoding="utf-8") as handle:
            json.dump({"maxPushups": 12, "reps": 9, "trainingDays": 1,
                       "lastTrainingDate": "2026-09-01T12:00:00.000Z",
                       "history": [{"time": "2026-09-01T12:00:00.000Z", "reps": 9}]}, handle)

        _, printed = self.restore(backup)
        self.assertEqual(json.loads(printed)["sessions"], 1)
        self.assertEqual(self.stored()["maxPushups"], 12)

    def test_the_state_a_restore_replaces_is_kept_first(self):
        # So a restore is reversible: the copy is what the panel can put back
        # when the file that was picked turns out to be the wrong one.
        self.write(GOOD)
        backup = self.target("backup.json")
        with open(backup, "w", encoding="utf-8") as handle:
            json.dump({"maxPushups": 12, "reps": 9}, handle)

        self.restore(backup)
        kept = os.listdir(self.backup_dir)
        self.assertEqual(len(kept), 1)
        self.assertRegex(kept[0], r"^pre-restore_\d{8}_\d{6}-[0-9a-f]{8}\.json$")
        with open(os.path.join(self.backup_dir, kept[0]), "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), GOOD)
        # And the copy is private, like everything the plugin writes.
        self.assertEqual(self.mode(os.path.join(self.backup_dir, kept[0])), 0o600)

    def test_restore_keeps_only_the_newest_copies(self):
        # There has to be state to replace, since that is what triggers a copy.
        self.write(GOOD)
        backup = self.target("backup.json")
        os.makedirs(self.backup_dir, exist_ok=True)
        for i in range(state.SNAPSHOT_KEEP + 4):
            name = "pre-restore_2026010%d_120000-%08x.json" % (i % 10, i)
            with open(os.path.join(self.backup_dir, name), "w", encoding="utf-8") as handle:
                handle.write("{}")
            # mtime is what orders them, so it is set rather than slept for.
            os.utime(os.path.join(self.backup_dir, name), (1600000000 + i, 1600000000 + i))

        with open(backup, "w", encoding="utf-8") as handle:
            json.dump(GOOD, handle)
        self.restore(backup)
        self.assertEqual(len(os.listdir(self.backup_dir)), state.SNAPSHOT_KEEP)

    def test_restore_leaves_a_name_it_did_not_write_alone(self):
        # The prune is a deletion. It only considers the plugin's own pattern,
        # so anything else in that directory survives.
        os.makedirs(self.backup_dir, exist_ok=True)
        other = os.path.join(self.backup_dir, "notes.txt")
        with open(other, "w", encoding="utf-8") as handle:
            handle.write("mine")
        backup = self.target("backup.json")
        with open(backup, "w", encoding="utf-8") as handle:
            json.dump(GOOD, handle)

        self.restore(backup)
        with open(other, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "mine")

    def test_an_empty_document_is_not_restored_over_a_real_history(self):
        # `{}` is what a first run looks like. Restoring one would erase the
        # history on the strength of a file that simply was not a backup.
        self.write(GOOD)
        empty = self.target("empty.json")
        with open(empty, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(ValueError):
            self.restore(empty)
        self.assertEqual(self.stored(), GOOD)

    def test_a_broken_backup_is_refused_and_changes_nothing(self):
        self.write(GOOD)
        for payload in ("", "not json", "[1,2,3]", '{"history": "nope"}'):
            bad = self.target("bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                handle.write(payload)
            with self.assertRaises(ValueError, msg=repr(payload)):
                self.restore(bad)
            self.assertEqual(self.stored(), GOOD)

    def test_an_oversized_backup_is_refused(self):
        self.write(GOOD)
        big = self.target("big.json")
        with open(big, "w", encoding="utf-8") as handle:
            handle.write("{" + " " * (65536 + 1) + "}")
        with self.assertRaises(PermissionError):
            self.restore(big)
        self.assertEqual(self.stored(), GOOD)

    def test_a_missing_backup_is_reported_not_an_empty_history(self):
        self.write(GOOD)
        with self.assertRaises(ValueError):
            self.restore(self.target("nope.json"))
        self.assertEqual(self.stored(), GOOD)

    def test_an_export_before_the_first_session_is_refused(self):
        with self.assertRaises(ValueError):
            self.export(self.target("backup.json"))
        self.assertFalse(os.path.exists(self.target("backup.json")))

    def test_a_hostile_document_is_reduced_on_the_way_in(self):
        # The same closed schema as a write, so a backup written by something
        # else cannot inject a shape the panel does not expect.
        self.write(GOOD)
        hostile = self.target("hostile.json")
        with open(hostile, "w", encoding="utf-8") as handle:
            json.dump({"maxPushups": 1e999, "reps": -5,
                       "lastTrainingDate": "<img src=x>", "trainingDays": True,
                       "history": [{"time": "nope", "reps": 1},
                                   {"time": "2026-09-27T12:00:00.000Z", "reps": 34}],
                       "unknown": {"nested": True}}, handle)

        self.restore(hostile)
        self.assertEqual(self.stored(), {
            "maxPushups": 0,
            "reps": 0,
            "lastTrainingDate": "",
            "trainingDays": 0,
            "history": [{"time": "2026-09-27T12:00:00.000Z", "reps": 34}],
        })

    # ---- refused chosen paths ----

    def test_a_relative_or_traversing_path_is_refused(self):
        for path in ("backup.json", "~/backup.json", "/tmp/../etc/x",
                     "/tmp/./x.json", "/", "//x.json", "/tmp/\0x"):
            with self.assertRaises(PermissionError, msg=repr(path)):
                self.export(path)
        self.assertFalse(os.path.exists(self.target("backup.json")))

    def test_an_empty_path_is_refused_as_a_request_not_a_path(self):
        # No path at all is a malformed request rather than a refused path, so
        # it comes back as the same ValueError any other bad body would.
        with self.assertRaises(ValueError):
            self.export("")

    def test_a_foreign_writable_folder_is_refused(self):
        # A directory another account can write to is a place the write could
        # be redirected out of, so it is not somewhere to put a backup.
        shared = self.target("shared")
        os.makedirs(shared)
        os.chmod(shared, 0o777)
        with self.assertRaises(PermissionError):
            self.export(os.path.join(shared, "backup.json"))
        self.assertFalse(os.path.exists(os.path.join(shared, "backup.json")))

    def test_a_sticky_folder_is_allowed(self):
        # The sticky bit is what makes /tmp the one shared directory that is
        # safe to write into, so the rule has to let it through.
        if not hasattr(os, "mkdtemp"):
            self.skipTest("no mkdtemp")
        shared = tempfile.mkdtemp(prefix="opushy-sticky-", dir="/tmp")
        self.addCleanup(shutil.rmtree, shared, True)
        os.chmod(shared, 0o777 | 0o1000)
        self.write(GOOD)
        target = os.path.join(shared, "backup.json")
        self.export(target)
        self.assertEqual(self.exported(target), GOOD)

    def test_a_folder_that_is_not_a_directory_is_refused(self):
        plain = self.target("plain")
        with open(plain, "w", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(PermissionError):
            self.export(os.path.join(plain, "backup.json"))

    def test_a_linked_folder_on_the_way_to_the_backup_is_resolved(self):
        # A Documents symlink onto a mounted disk is ordinary, so the walk
        # follows it, and then checks where it landed like any other component.
        real = self.target("real")
        os.makedirs(real)
        link = self.target("Documents")
        os.symlink(real, link)
        self.write(GOOD)
        target = os.path.join(link, "backup.json")

        self.export(target)
        self.assertEqual(self.exported(os.path.join(real, "backup.json")), GOOD)

    def test_a_link_that_lands_in_a_foreign_writable_folder_is_refused(self):
        # Following the link is allowed; landing somewhere another account can
        # write to is not. The check happens after the link, not before.
        shared = self.target("shared")
        os.makedirs(shared)
        os.chmod(shared, 0o777)
        link = self.target("Documents")
        os.symlink(shared, link)
        with self.assertRaises(PermissionError):
            self.export(os.path.join(link, "backup.json"))
        self.assertFalse(os.path.exists(os.path.join(shared, "backup.json")))

    def test_a_link_cycle_does_not_spin(self):
        a = self.target("a")
        os.symlink(self.target("b"), a)
        os.symlink(a, self.target("b"))
        with self.assertRaises(PermissionError):
            self.export(os.path.join(a, "backup.json"))

    def test_a_symlinked_backup_is_not_restored_from(self):
        # The leaf is opened O_NOFOLLOW, so a link planted at the chosen name
        # is refused rather than read through.
        self.write(GOOD)
        target = self.target("elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(GOOD, handle)
        link = self.target("backup.json")
        os.symlink(target, link)
        with self.assertRaises(OSError):
            self.restore(link)

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
        self.state_file = os.path.join(self.home, ".local", "state", "opushy",
                                       "opushy_activity.json")

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

    def test_a_backup_request_needs_a_path(self):
        # The path is the one value in here that comes from a dialog rather than
        # from the plugin, so a request without one is refused before anything
        # is opened. Nothing here can reach the real home either way.
        for stdin in ("", "{}", '{"path": ""}', '{"path": 7}', '{"path": null}',
                      "[1,2,3]", "not json"):
            result = self.run_helper("backup", "export", stdin=stdin + "\n")
            self.assertEqual(result.returncode, 1, repr(stdin))
            self.assertNotIn("Traceback", result.stderr)

    def test_an_oversized_request_is_refused(self):
        result = self.run_helper("backup", "export",
                                 stdin='{"path": "/tmp/' + "x" * 70000 + '"}')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

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
