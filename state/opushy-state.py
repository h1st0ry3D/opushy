#!/usr/bin/python3
"""Opushy tracker state I/O, bound to descriptors (stdlib only).

Every read and write here goes through a descriptor that is validated and then
used, rather than through a pathname that is resolved again on every step:

  * directories are walked one component at a time with held dirfds, each opened
    `O_NOFOLLOW|O_DIRECTORY` and `fstat`-checked for owner and type; the plugin's
    own leaf is forced to 0700 and its contents repaired (anything that is not a
    regular file is removed, files get 0600)
  * reads open `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`, `fstat` the descriptor (regular
    file, our uid, one link, size) and read at most MAX_BYTES + 1 bytes, so
    oversize is an error rather than a silent truncation
  * writes create a fresh random 0600 file with `O_CREAT|O_EXCL|O_NOFOLLOW` in
    the destination directory, write through that descriptor, `fsync`, then
    `rename` over the destination and `fsync` the directory

Modes:

    opushy-state.py state read            # -> the saved tracker document
    opushy-state.py state write           # <- the same document on stdin
    opushy-state.py migrate <legacy-path> # one-off import of the old
                                          #    <plugin-dir>/tracker.json, and
                                          #    the one-off rename of 1.0's
                                          #    tracker.json onto
                                          #    opushy_activity.json
    opushy-state.py backup export         # <- {"path": "..."} on stdin: a copy
                                          #    of the state file where the user
                                          #    said
    opushy-state.py backup restore        # <- {"path": "..."} on stdin: that
                                          #    file replaces the state, after
                                          #    the state it replaces is copied
                                          #    into backups/

The write mode validates stdin against the same closed schema as the QML reader
(core/Document.js). A refused document exits non-zero; it never falls back to
"absent, so start fresh".

The two backup modes take a path the user's own file dialog produced, which is
the one pathname in here that is not under the plugin's state directory. It gets
its own walk: from the root, one component at a time, with held descriptors,
refusing anything another account can write to. Everything else here is opened
through a directory the plugin owns.
"""
import errno
import json
import os
import pwd
import re
import secrets
import stat
import sys
import time

MAX_BYTES = 65536          # document ceiling (400 history entries, indented)
MAX_REPS = 10000
MAX_TRAINING_DAYS = 1000000
HISTORY_MAX = 400
MAX_TS_LEN = 32
MAX_PATH_LEN = 4096        # a path is a path, but it is still a byte budget
MAX_PATH_DEPTH = 40
MAX_LINK_HOPS = 8
SNAPSHOT_KEEP = 10         # safety copies kept in backups/

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

_COMPONENT = re.compile(r"[A-Za-z0-9._-]+")
# Same shape as core/Progression.js TS_PATTERN: what Date.toISOString() writes.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")
# What marks a file in backups/ as one this plugin wrote. The name is the only
# marker there is, so it is the whole rule for what may be pruned later.
_SNAPSHOT = re.compile(r"pre-restore_\d{8}_\d{6}-[0-9a-f]{8}\.json")
_STATE_NAME = "opushy_activity.json"
# The name and the timestamp key this plugin used before 1.1. Both are read
# once and rewritten in the new shape, so an install that is upgraded keeps its
# history instead of starting over on a file the reader no longer looks at.
_PREVIOUS_STATE_NAME = "tracker.json"
_PREVIOUS_TIME_KEY = "ts"
_BACKUP_DIR = "backups"

# Plugin state, created if missing and forced to 0700.
STATE_CHAIN = (".local", "state", "opushy")
# Where a restore puts what it is about to replace.
BACKUP_CHAIN = STATE_CHAIN + (_BACKUP_DIR,)


def _ok_component(name):
    return bool(_COMPONENT.fullmatch(name)) and name not in (".", "..")


def _repair_dir(dir_fd, keep_dirs=()):
    """Drop everything that is not a regular file, and 0600 what stays. Runs on
    every call: a directory that is 0700 today can still hold a 0644 file.

    `keep_dirs` names the subdirectories that are part of the plugin's own
    layout. They are ours, so they are repaired to 0700 instead of removed;
    anything else that is not a regular file is dropped, since a directory
    that was ever wider can hold an entry this plugin did not put there."""
    for entry in os.listdir(dir_fd):
        try:
            st = os.stat(entry, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode):
            if stat.S_ISDIR(st.st_mode) and entry in keep_dirs \
                    and st.st_uid == os.geteuid():
                if st.st_mode & 0o077:
                    try:
                        os.chmod(entry, 0o700, dir_fd=dir_fd, follow_symlinks=False)
                    except OSError:
                        pass
                continue
            try:
                if stat.S_ISDIR(st.st_mode):
                    os.rmdir(entry, dir_fd=dir_fd)
                else:
                    os.unlink(entry, dir_fd=dir_fd)
            except OSError:
                pass
            continue
        if st.st_mode & 0o077:
            try:
                os.chmod(entry, 0o600, dir_fd=dir_fd, follow_symlinks=False)
            except OSError:
                pass


def open_chain(parts, start_fd, create_missing=False, repair_leaf=False, keep_dirs=()):
    """Walk `parts` from the already-open `start_fd` with held descriptors and
    return the final dirfd. The caller still owns `start_fd`."""
    if not parts or not all(_ok_component(p) for p in parts):
        raise PermissionError("refusing directory chain")
    fd = os.dup(start_fd)
    try:
        for i, name in enumerate(parts):
            leaf = i == len(parts) - 1
            try:
                nfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=fd)
            except FileNotFoundError:
                # Created on demand, a component at a time, 0700. The legacy
                # import chain is never created, only read.
                if not create_missing:
                    raise
                os.mkdir(name, 0o700, dir_fd=fd)
                nfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=fd)
            os.close(fd)
            fd = nfd
            st = os.fstat(fd)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
                raise PermissionError("untrusted directory component: %s" % name)
            if leaf and repair_leaf:
                if st.st_mode & 0o077:
                    os.fchmod(fd, 0o700)
                _repair_dir(fd, keep_dirs)
        return fd
    except BaseException:
        os.close(fd)
        raise


def home_chain(parts, anchor=None, **kwargs):
    """Walk `parts` under the passwd home, which is the anchor because $HOME can
    be pointed anywhere. The home itself may be a symlink, so it is not opened
    O_NOFOLLOW.

    `anchor` overrides the home for the test suite. The command line never takes
    one: main() always calls these with the passwd home."""
    if anchor is None:
        anchor = pwd.getpwuid(os.geteuid()).pw_dir
    fd = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        return open_chain(parts, fd, **kwargs)
    finally:
        os.close(fd)


def open_legacy_dir(path):
    """Directory descriptor and file name for the pre-1.0 file, which the panel
    names as an absolute path (its own folder, wherever that is installed).

    The directory is opened with symlinks followed, because a plugin folder is
    legitimately a symlink on a checkout. The file inside it is opened
    O_NOFOLLOW|O_NONBLOCK and fstat-validated, and the document is validated
    again by the reader.
    """
    if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
        raise PermissionError("refusing legacy path")
    parts = [p for p in path.split("/") if p]
    if not parts:
        raise PermissionError("refusing legacy path")
    if any(p in (".", "..") for p in parts):
        raise PermissionError("refusing legacy path")
    name = parts.pop()
    if not _ok_component(name):
        raise PermissionError("refusing legacy file name")
    return os.open("/".join([""] + parts) or "/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC), name


def state_dir(anchor=None):
    """The plugin's own state directory: created on demand, forced to 0700,
    contents repaired. backups/ is part of that layout, so every call through
    here keeps it."""
    return home_chain(STATE_CHAIN, anchor, create_missing=True, repair_leaf=True,
                      keep_dirs=(_BACKUP_DIR,))


def snapshot_dir(anchor=None):
    """Where a restore keeps what it is about to replace. Same rules as the
    state directory above it, which is created first by the caller."""
    return home_chain(BACKUP_CHAIN, anchor, create_missing=True, repair_leaf=True)


def read_bounded(dir_fd, name, limit=MAX_BYTES):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1
                or st.st_size > limit):
            raise PermissionError("refusing %s: not a plain owner-only file within %d bytes"
                                  % (name, limit))
        os.set_blocking(fd, True)
        data = b""
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        if len(data) > limit:
            raise PermissionError("%s grew past the limit" % name)
        return data
    finally:
        os.close(fd)


def write_atomic(dir_fd, name, data):
    if len(data) > MAX_BYTES:
        raise ValueError("payload too large")
    tmp = ".%s.%s.tmp" % (name, secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def _bounded_int(value, low, high, fallback):
    # bool is an int subclass, and a JSON true would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value if low <= value <= high else fallback


def _timestamp(value):
    if not isinstance(value, str) or len(value) > MAX_TS_LEN:
        return ""
    return value if _TIMESTAMP.fullmatch(value) else ""


def clean_document(payload):
    """Keep the known keys with the expected shapes and drop everything else.

    A history entry's timestamp is read from `time`, or from `ts` for a document
    written before 1.1. Either way it comes out as `time`, so the shape on disk
    is the new one after the first write. A `ts` key alongside a `time` key does
    not win: the current name is the one that counts."""
    if not isinstance(payload, dict):
        raise ValueError("state must be a JSON object")
    history = []
    raw_history = payload.get("history")
    if isinstance(raw_history, list):
        for entry in raw_history[-HISTORY_MAX:]:
            if not isinstance(entry, dict):
                continue
            ts = _timestamp(entry.get("time"))
            if not ts:
                ts = _timestamp(entry.get(_PREVIOUS_TIME_KEY))
            if ts:
                history.append({"time": ts,
                                "reps": _bounded_int(entry.get("reps"), 0, MAX_REPS, 0)})
    return {
        "maxPushups": _bounded_int(payload.get("maxPushups"), 0, MAX_REPS, 0),
        "reps": _bounded_int(payload.get("reps"), 0, MAX_REPS, 0),
        "lastTrainingDate": _timestamp(payload.get("lastTrainingDate")),
        "trainingDays": _bounded_int(payload.get("trainingDays"), 0, MAX_TRAINING_DAYS, 0),
        "history": history,
    }


def dump_document(document):
    """The exact bytes the state file holds. One place builds them, so a write,
    a migrated file and a restored one are all the same document."""
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def state_read(anchor=None):
    dir_fd = state_dir(anchor)
    try:
        raw = read_bounded(dir_fd, _STATE_NAME)
        if raw is None:
            return 0            # no history yet: the panel shows first-run setup
        sys.stdout.write(raw.decode("utf-8", "strict"))
        return 0
    finally:
        os.close(dir_fd)


def state_write(anchor=None, payload=None):
    dir_fd = state_dir(anchor)
    try:
        if payload is None:
            # One bounded line, not read-to-EOF, so a caller that never closes
            # the pipe cannot leave this process waiting forever on a save.
            payload = sys.stdin.buffer.readline(MAX_BYTES + 1)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if len(payload) > MAX_BYTES:
            raise ValueError("payload too large")
        if not payload.strip():
            raise ValueError("empty document")
        document = clean_document(json.loads(payload.decode("utf-8", "strict")))
        write_atomic(dir_fd, _STATE_NAME, dump_document(document))
        return 0
    finally:
        os.close(dir_fd)


def migrate(legacy_path, anchor=None):
    """The one-off import, and the one-off rename onto 1.1's file name.

    Two older layouts are picked up, in this order:

      1. `tracker.json` in this directory, which 1.0 wrote
      2. `tracker.json` next to `Panel.qml`, which pre-1.0 wrote

    Both are converted to the current shape and written as
    `opushy_activity.json` with `time` for the timestamp, and the old file in
    this directory is removed once the new one is in place. It is a no-op as
    soon as that file exists, so it is safe on every load.

    Its mode is not required to be 0600, only that it is a plain file of ours
    within MAX_BYTES. The copy is written 0600 like everything else."""
    # The argument is checked first, so a malformed path leaves nothing behind.
    try:
        legacy_dir, legacy_name = open_legacy_dir(legacy_path)
    except FileNotFoundError:
        legacy_dir, legacy_name = None, None       # nothing there, which is the norm
    dir_fd = state_dir(anchor)
    try:
        if read_bounded(dir_fd, _STATE_NAME) is not None:
            # Already on the current file. An old one beside it is left alone
            # rather than removed: if one is there, something put it there, and a
            # fresh state file must not be the reason a history is destroyed.
            return 0

        # 1.0's file, in this directory. Renamed onto the current name with the
        # document rewritten, so an upgraded install keeps its history.
        previous = read_bounded(dir_fd, _PREVIOUS_STATE_NAME)
        if previous is not None:
            write_atomic(dir_fd, _STATE_NAME,
                         dump_document(clean_document(
                             json.loads(previous.decode("utf-8", "strict")))))
            try:
                os.unlink(_PREVIOUS_STATE_NAME, dir_fd=dir_fd)
                os.fsync(dir_fd)
            except OSError:
                pass        # the new file is in place, which is what matters
            return 0

        if legacy_dir is None:
            return 0
        try:
            raw = read_bounded(legacy_dir, legacy_name)
        except OSError as e:
            raise PermissionError("refusing the legacy file: %s" % e.strerror)
        finally:
            os.close(legacy_dir)
        if raw is None:
            return 0
        write_atomic(dir_fd, _STATE_NAME,
                     dump_document(clean_document(json.loads(raw.decode("utf-8", "strict")))))
        return 0
    finally:
        os.close(dir_fd)


# ---- backup and restore ---------------------------------------------------
#
# Both modes take one bounded line on stdin, {"path": "..."}, which is the file
# the user's own dialog returned. Read the same way `state write` reads its
# document, so a caller that never closes the pipe cannot leave this process
# waiting on a backup.


def _envelope(payload=None):
    if payload is None:
        payload = sys.stdin.buffer.readline(MAX_BYTES + 1)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("request too large")
    if not payload.strip():
        raise ValueError("empty request")
    request = json.loads(payload.decode("utf-8", "strict"))
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    path = request.get("path")
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_LEN:
        raise ValueError("request needs a path")
    return path


def _link_components(base, target):
    """The components a symlink target stands for, applied to what has been
    walked already. `..` pops the way the kernel pops it, and a target that
    climbs past the root is refused rather than clamped to it."""
    out = list(base)
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not out:
                raise PermissionError("link target climbs above the root")
            out.pop()
            continue
        out.append(part)
    return out


def _check_chosen_dir(dir_fd, name):
    """A directory on the way to a chosen path. It has to be a real directory,
    owned by us or by root for the system ones above the home, and not writable
    by another account: that is what would let something redirect the write
    sideways. The sticky bit is the exception, which is what makes /tmp the
    one shared directory that is safe to write into."""
    st = os.fstat(dir_fd)
    if not stat.S_ISDIR(st.st_mode):
        raise PermissionError("not a directory: %s" % name)
    if st.st_uid not in (0, os.geteuid()):
        raise PermissionError("not yours: %s" % name)
    if st.st_mode & 0o022 and not st.st_mode & 0o1000:
        raise PermissionError("%s is writable by other accounts" % name)


def open_chosen_dir(parts):
    """Directory descriptor for the folder a chosen path names, walked one
    component at a time from the root with held descriptors.

    A symlinked component is resolved here, unlike in the state chain, because
    this path came out of the user's own file dialog and a Documents symlink
    onto a mounted disk is ordinary. It is still bounded, and the target is
    checked like any other component, so the walk cannot be led off into a
    directory another account can write to. Every component is validated before
    the next one is opened, and the descriptor is the thing that is used
    afterwards, so the name is never resolved a second time.
    """
    if not parts or len(parts) > MAX_PATH_DEPTH or not all(_ok_component(p) for p in parts):
        raise PermissionError("refusing directory chain")
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    fd = os.dup(root_fd)
    try:
        pending = list(parts)
        hops = 0
        while pending:
            name = pending.pop(0)
            try:
                nfd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except OSError as e:
                # A symlinked component fails here as ENOTDIR (with
                # O_DIRECTORY) or ELOOP (without). Anything else, and anything
                # that turns out not to be a link once looked at, is a real
                # error: a plain file where a directory belongs, a name that is
                # not there at all.
                if e.errno not in (errno.ENOTDIR, errno.ELOOP):
                    raise
                try:
                    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    raise e
                if not stat.S_ISLNK(st.st_mode):
                    if e.errno == errno.ENOTDIR:
                        # ENOTDIR on a name that is not a link is a plain file
                        # where a directory has to be.
                        raise PermissionError("not a directory: %s" % name)
                    raise e
                # The link is resolved by hand and the walk restarts from the
                # root with the target spliced in, so a link that points
                # sideways cannot shorten the checks behind it.
                hops += 1
                if hops > MAX_LINK_HOPS:
                    raise PermissionError("too many links in the chosen path")
                target = os.readlink(name, dir_fd=fd)
                if not target or len(target) > MAX_PATH_LEN or "\0" in target:
                    raise PermissionError("refusing a link in the chosen path")
                # `pending` already dropped `name`, so the target replaces it
                # and whatever was queued behind it follows the link.
                pending = _link_components([], target) + pending
                if len(pending) > MAX_PATH_DEPTH:
                    raise PermissionError("chosen path too deep")
                os.close(fd)
                fd = os.dup(root_fd)
                continue
            os.close(fd)
            fd = nfd
            _check_chosen_dir(fd, name)
        return fd
    except BaseException:
        os.close(fd)
        raise
    finally:
        os.close(root_fd)


def _chosen_path(path):
    """The directory descriptor and file name for a path the panel hands over.
    The leaf is a plain component: no separator, no dot, nothing to traverse
    into. The panel builds the name, and this refuses anything else."""
    parts = [p for p in path.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise PermissionError("refusing chosen path")
    name = parts.pop()
    if not _ok_component(name):
        raise PermissionError("refusing chosen file name")
    return open_chosen_dir(parts), name


def snapshot_name():
    """A name for the copy a restore takes of what it is replacing: sortable by
    time, and with random bytes in it so two restores in the same second cannot
    land on one name."""
    return "pre-restore_%s-%s.json" % (time.strftime("%Y%m%d_%H%M%S", time.localtime()),
                                       secrets.token_hex(4))


def _prune_snapshots(dir_fd, keep=SNAPSHOT_KEEP):
    """Leave the newest `keep` copies. Only a name this plugin's own pattern
    matches and that is a regular file of ours is even considered, so a restore
    cannot delete something it did not write."""
    entries = []
    for name in os.listdir(dir_fd):
        if not _SNAPSHOT.fullmatch(name):
            continue
        try:
            st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid():
            entries.append((st.st_mtime, name))
    if len(entries) <= keep:
        return
    entries.sort()
    for _, name in entries[:len(entries) - keep]:
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError:
            pass


def backup_export(anchor=None, payload=None):
    """Copy the current state document to the chosen path, byte for byte, so a
    backup is the file the plugin would have written anyway. The state file is
    the source rather than the panel's copy, so what lands on disk is the same
    thing a restore reads back."""
    dir_fd, name = _chosen_path(_envelope(payload))
    try:
        state_fd = state_dir(anchor)
        try:
            raw = read_bounded(state_fd, _STATE_NAME)
        finally:
            os.close(state_fd)
        if raw is None:
            raise ValueError("nothing to back up yet")
        write_atomic(dir_fd, name, raw)
    finally:
        os.close(dir_fd)
    # One line for the panel to show, on stdout, with nothing a shell would
    # read as syntax. The name is the panel's own, echoed back so the two agree.
    sys.stdout.write(json.dumps({"ok": True, "name": name}) + "\n")
    return 0


def backup_restore(anchor=None, payload=None):
    """Replace the state document with the one in the chosen file.

    The state being replaced is copied into backups/ first, so a restore is
    itself reversible: the copy is what the panel offers to put back if the
    file that was picked turns out to be the wrong one. The incoming document
    goes through the same closed schema as a write, so a file that is not a
    backup is refused instead of half-applied.
    """
    dir_fd, name = _chosen_path(_envelope(payload))
    try:
        raw = read_bounded(dir_fd, name)
    finally:
        os.close(dir_fd)
    if raw is None:
        raise ValueError("that file is not there")
    document = clean_document(json.loads(raw.decode("utf-8", "strict")))
    if not any((document["maxPushups"], document["reps"], document["trainingDays"],
                document["history"])):
        # An empty document is what a first run looks like. Restoring one over
        # a real history would erase it on the strength of a wrong file.
        raise ValueError("that file holds no training data")

    state_fd = state_dir(anchor)
    try:
        previous = read_bounded(state_fd, _STATE_NAME)
        if previous is not None:
            backup_fd = snapshot_dir(anchor)
            try:
                kept = snapshot_name()
                write_atomic(backup_fd, kept, previous)
                _prune_snapshots(backup_fd)
            finally:
                os.close(backup_fd)
        write_atomic(state_fd, _STATE_NAME, dump_document(document))
    finally:
        os.close(state_fd)
    sys.stdout.write(json.dumps({"ok": True, "sessions": len(document["history"])}) + "\n")
    return 0


def main():
    argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "state" and argv[1] == "read":
        return state_read()
    if len(argv) == 2 and argv[0] == "state" and argv[1] == "write":
        return state_write()
    if len(argv) == 2 and argv[0] == "migrate":
        return migrate(argv[1])
    if len(argv) == 2 and argv[0] == "backup" and argv[1] == "export":
        return backup_export()
    if len(argv) == 2 and argv[0] == "backup" and argv[1] == "restore":
        return backup_restore()
    sys.stderr.write("usage: opushy-state.py state read|write | migrate <legacy-path>"
                     " | backup export|restore\n")
    return 2


if __name__ == "__main__":
    # One line a human can read instead of a traceback.
    try:
        sys.exit(main())
    except (PermissionError, OSError, ValueError) as e:
        sys.stderr.write("opushy-state: %s\n" % e)
        sys.exit(1)
