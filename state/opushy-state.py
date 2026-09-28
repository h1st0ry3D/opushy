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
                                          #    <plugin-dir>/tracker.json

The write mode validates stdin against the same closed schema as the QML reader
(core/Document.js). A refused document exits non-zero; it never falls back to
"absent, so start fresh".
"""
import json
import os
import pwd
import re
import secrets
import stat
import sys

MAX_BYTES = 65536          # document ceiling (400 history entries, indented)
MAX_REPS = 10000
MAX_TRAINING_DAYS = 1000000
HISTORY_MAX = 400
MAX_TS_LEN = 32

_COMPONENT = re.compile(r"[A-Za-z0-9._-]+")
# Same shape as core/Progression.js TS_PATTERN: what Date.toISOString() writes.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")
_STATE_NAME = "tracker.json"

# Plugin state, created if missing and forced to 0700.
STATE_CHAIN = (".local", "state", "opushy")


def _ok_component(name):
    return bool(_COMPONENT.fullmatch(name)) and name not in (".", "..")


def _repair_dir(dir_fd):
    """Drop everything that is not a regular file, and 0600 what stays. Runs on
    every call: a directory that is 0700 today can still hold a 0644 file."""
    for entry in os.listdir(dir_fd):
        try:
            st = os.stat(entry, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode):
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


def open_chain(parts, start_fd, create_missing=False, repair_leaf=False):
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
                _repair_dir(fd)
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
    """Keep the known keys with the expected shapes and drop everything else."""
    if not isinstance(payload, dict):
        raise ValueError("state must be a JSON object")
    history = []
    raw_history = payload.get("history")
    if isinstance(raw_history, list):
        for entry in raw_history[-HISTORY_MAX:]:
            if not isinstance(entry, dict):
                continue
            ts = _timestamp(entry.get("ts"))
            if ts:
                history.append({"ts": ts, "reps": _bounded_int(entry.get("reps"), 0, MAX_REPS, 0)})
    return {
        "maxPushups": _bounded_int(payload.get("maxPushups"), 0, MAX_REPS, 0),
        "reps": _bounded_int(payload.get("reps"), 0, MAX_REPS, 0),
        "lastTrainingDate": _timestamp(payload.get("lastTrainingDate")),
        "trainingDays": _bounded_int(payload.get("trainingDays"), 0, MAX_TRAINING_DAYS, 0),
        "history": history,
    }


def state_read(anchor=None):
    dir_fd = home_chain(STATE_CHAIN, anchor, create_missing=True, repair_leaf=True)
    try:
        raw = read_bounded(dir_fd, _STATE_NAME)
        if raw is None:
            return 0            # no history yet: the panel shows first-run setup
        sys.stdout.write(raw.decode("utf-8", "strict"))
        return 0
    finally:
        os.close(dir_fd)


def state_write(anchor=None, payload=None):
    dir_fd = home_chain(STATE_CHAIN, anchor, create_missing=True, repair_leaf=True)
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
        write_atomic(dir_fd, _STATE_NAME,
                     (json.dumps(document, indent=2) + "\n").encode("utf-8"))
        return 0
    finally:
        os.close(dir_fd)


def migrate(legacy_path, anchor=None):
    """One-off import of the pre-1.0 state file, which Quickshell wrote at mode
    644. A no-op once the real state file exists, so it is safe to run on every
    load.

    Its mode is not required to be 0600, only that it is a plain file of ours
    within MAX_BYTES. The copy is written 0600 like everything else."""
    # The argument is checked first, so a malformed path leaves nothing behind.
    try:
        legacy_dir, legacy_name = open_legacy_dir(legacy_path)
    except FileNotFoundError:
        legacy_dir, legacy_name = None, None       # nothing there, which is the norm
    dir_fd = home_chain(STATE_CHAIN, anchor, create_missing=True, repair_leaf=True)
    try:
        if read_bounded(dir_fd, _STATE_NAME) is not None:
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
        json.loads(raw.decode("utf-8", "strict"))
        write_atomic(dir_fd, _STATE_NAME, raw)
        return 0
    finally:
        os.close(dir_fd)


def main():
    argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "state" and argv[1] == "read":
        return state_read()
    if len(argv) == 2 and argv[0] == "state" and argv[1] == "write":
        return state_write()
    if len(argv) == 2 and argv[0] == "migrate":
        return migrate(argv[1])
    sys.stderr.write("usage: opushy-state.py state read|write | migrate <legacy-path>\n")
    return 2


if __name__ == "__main__":
    # One line a human can read instead of a traceback.
    try:
        sys.exit(main())
    except (PermissionError, OSError, ValueError) as e:
        sys.stderr.write("opushy-state: %s\n" % e)
        sys.exit(1)
