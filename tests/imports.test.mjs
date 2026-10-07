// How the plugin's QML files are allowed to import each other.
//
// The shell loads a plugin through its own import interceptor, and that
// interceptor does not resolve a relative import of a sibling .qml file: the
// component silently fails to load and the whole plugin widget disappears from
// the bar with one line in the shell log. A standalone `quickshell -p <dir>` run
// accepts it, so the bug is invisible until the real shell picks the plugin up.
//
// Both symptoms this has already caused, so the rule is enforced here instead of
// left to memory:
//
//   ui/ProgressSection.qml importing ui/HistoryStrip.qml
//   ui/Celebration.qml    importing ui/Confetti.qml
//
// The fix in both cases was the same: drop the import and use the composite
// namespace that Panel.qml's `import "ui"` sets up. `.js` libraries are fine by
// path, in the same directory or a parent one.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, relative } from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));

function qmlFiles(dir) {
  const out = [];
  for (const entry of readdirSync(join(root, dir), { withFileTypes: true })) {
    if (entry.isDirectory()) out.push(...qmlFiles(join(dir, entry.name)));
    else if (entry.name.endsWith(".qml")) out.push(join(dir, entry.name));
  }
  return out;
}

const files = [".", "ui", "state", "audio", "ipc"].flatMap(qmlFiles);

test("the plugin has QML files to check", () => {
  assert.ok(files.length > 5, files.join(", "));
});

test("no plugin file imports a sibling .qml by relative path", () => {
  const offenders = [];
  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    for (const match of source.matchAll(/^import\s+"([^"]+\.qml)"/gm)) {
      offenders.push(`${relative(root, join(root, file))} imports ${match[1]}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("the entry point imports every directory it composes from", () => {
  // A directory that exists but is never imported means its components are
  // unreachable, which is the other way this breaks silently.
  const panel = readFileSync(join(root, "Panel.qml"), "utf8");
  for (const dir of ["ui", "state", "ipc", "audio"]) {
    assert.match(panel, new RegExp(`^import "${dir}"$`, "m"), dir);
  }
});

test("no plugin file opens a Qt file or message dialog", () => {
  // QtQuick.Dialogs hands the dialog to the platform, which on this desktop is
  // GTK, so the GTK file chooser and GIO run inside the shell process. The
  // first time that path ran here it enumerated volumes through the gvfs
  // D-Bus monitor and aborted: SIGABRT under libgtk-3, in
  // g_variant_builder_add, with the shell's whole bar on top of it.
  //
  // The plugin lives in the one long-lived process that draws the desktop, so a
  // crash in a file picker is a crash of the shell. Anything that wants a file
  // chosen runs /usr/bin/zenity as its own process instead (ui/ActivityMenu.qml).
  const offenders = [];
  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    for (const match of source.matchAll(/^import\s+QtQuick\.Dialogs/gm)) {
      offenders.push(`${relative(root, join(root, file))}: ${match[0]}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("a file is only ever chosen by an absolute path to a separate process", () => {
  // The chooser has to be a fixed absolute executable in an argv array: a bare
  // name resolves through a PATH another process can prepend, and a command
  // string would turn data back into code.
  const menu = readFileSync(join(root, "ui", "ActivityMenu.qml"), "utf8");
  const command = /command: menu\.choosing === "export"[\s\S]*?\n\n/.exec(menu);
  assert.ok(command, "ActivityMenu.qml has no chooser command");
  // The first element of each argv array is the executable, and that is the one
  // that has to be an absolute path rather than a name off the PATH.
  const arrays = [...command[0].matchAll(/\[[^\]]*\]/g)].map((m) => m[0]);
  assert.equal(arrays.length, 2, command[0]);
  for (const argv of arrays) {
    const program = /^\[?\s*"([^"]*)"/.exec(argv);
    assert.ok(program, argv);
    assert.match(program[1], /^\/usr\/bin\/[a-z0-9-]+$/, program[1]);
  }
  assert.doesNotMatch(menu, /"bash"|"sh"|run\(|\.execDetached\(/);
});
