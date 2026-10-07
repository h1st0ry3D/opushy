# Opushy

A pushup progression tracker for the [Omarchy](https://omarchy.org) bar. A
session is three rounds with a 45 second rest between them, and what the next
session asks for follows from how long it has been since the last one.

## Install

```sh
omarchy plugin add h1st0ry3D/opushy
```

There is nothing else to install, and nothing outside your home is touched. If
your system has no `pw-play`, `paplay` or `aplay`, or no
`/usr/share/sounds/freedesktop/stereo/complete.oga`, the panel is silent and the
countdown still runs.

## Using it

Click the bar icon to open the panel.

The first time, it asks for the most pushups you can do in one go. After that
everything happens through the panel:

- **Start** begins a session at round 1 with the target the progression picked.
- **Next** ends a round and starts the 45 second rest, which offers **Pause** and
  **Skip**. Skip jumps straight to the next round.
- On the third round the button says **Done** instead, because there is no rest
  after the last one. Pressing it records the session: the history grows by one
  entry, the training-day count goes up, and the stored reps become what you just
  did. Confetti then falls over the whole screen, and the panel shows what you
  just did: **New record** if the target beat your record, **Great progress** if
  it did not, with the reps in the middle and a **Finish** button at the bottom.
  The confetti is drawn on a fullscreen surface with an empty input region, so it
  never takes a click from the desktop underneath.

**Stop** throws a running session away, after asking. It records nothing. A right
click on the bar icon during a session opens the panel on the same question, so a
stray right click cannot discard three finished rounds. While nothing is running,
a right click opens **Back up** and **Restore** instead of the panel.

The panel also shows the chain so far, seven sessions to a page (the arrows, or
the left and right arrow keys). Each disc carries the reps that session asked for
and the colour of the gap to the session before it.

The bubble next to the panel's title applies the same idea to today: the days
since the last session, on the status colour, with a tooltip spelling out which
colour it is. It is the same component as the bar icon, and it is the only thing
the bar shows while idle. In the bar it drops the colour while the chain is on
track (0 to 2 days), because a green disc for an ordinary day is noise in a 27px
slot: one plain disc for an ordinary day, amber on day three, red from day four.
The running states still say what they say, the reps and the seconds left.

## Back up and restore

Right-click the bar icon while nothing is running.

- **Back up** writes the tracker file, as it is, to the place you pick. The
  suggested name is `opushy_activity_<today>.json`.
- **Restore** replaces your history with a file you pick, after asking. The
  tracker it replaces is copied into `~/.local/state/opushy/backups/` first, and
  only the newest ten of those copies are kept.

Both are unavailable during a session, and before the first record there is
nothing to keep, so a right click there opens the panel. The result of a backup
is shown on the menu. The result of a restore is shown on the panel, next to the
history it just replaced.

Picking the file needs `zenity`, which Omarchy already ships. Without it the menu
says so and the two rows stay greyed out, instead of appearing to do nothing.

The chooser runs as a separate process, and that is deliberate. Qt's own file
dialog runs the GTK file chooser and GIO inside the shell process, and the first
time it was tried here, enumerating volumes through the gvfs D-Bus monitor
aborted the entire shell out from under the bar. As a process of its own, the
same chooser is a window that can fail on its own.

To change the numbers on purpose, that is the route: **Back up**, edit the JSON,
then **Restore**. A backup is the tracker file exactly as it is, so editing it and
restoring it is the supported way to correct a chain.

## The progression

All of this is `core/Progression.js`, pure functions with the current time passed
in. Nothing that can be derived is stored.

```
base = max(1, floor(maxPushups * 0.75))     # the very first session
```

After that, from the last completed session:

| Days since the last session | Next session asks for |
|-----------------------------|-----------------------|
| 0, 1, 2                     | stored + 1            |
| 3                           | stored (unchanged)    |
| 4                           | stored - 1            |
| 5                           | stored - 2            |
| …                           | one less per extra day, never below 1 |

If a target exceeds the recorded max, the max moves up with it. The bar, the
panel header and the screens all read that one function, so they cannot disagree.
The day rolls over on its own: the panel re-reads the clock hourly.

The number a session asks for is fixed when you press **Start** and stored when
the session ends, so a panel left open overnight cannot change it halfway
through.

### Colours

| Colour | Meaning |
|--------|---------|
| green  | the gap to the previous session was 2 days or less |
| amber  | exactly 3 days |
| red    | 4 days or more |

A session's colour comes from its neighbours and is never stored, since a later
session can make an earlier one's gap longer.

## Where your data lives

The tracker is one file:

```
~/.local/state/opushy/tracker.json    (mode 0600, in a 0700 directory)
```

A restore also keeps the tracker it replaced:

```
~/.local/state/opushy/backups/pre-restore_<time>-<id>.json
```

Only the newest ten of those copies are kept. Anything else in that directory
is left alone.

```json
{
  "maxPushups": 40,
  "reps": 33,
  "lastTrainingDate": "2026-09-09T12:43:47.273Z",
  "trainingDays": 5,
  "history": [
    { "ts": "2026-09-02T12:25:35.733Z", "reps": 30 },
    { "ts": "2026-09-09T12:43:47.273Z", "reps": 33 }
  ]
}
```

- `maxPushups`, the record, raised when a session beats it
- `reps`, the last completed session's target, and the base for the next one
- `lastTrainingDate`, when the last session was completed rather than started
- `trainingDays`, how many sessions have been completed
- `history`, one entry per completed session, oldest first, most recent 400 kept

`state/opushy-state.py` writes the file. It reads and writes through validated
descriptors and replaces the file in one step, so an interrupted write leaves the
previous version in place. The panel never reads the file itself, and a file it
cannot make sense of is reported in the panel instead of being replaced. The
schema is checked on the way in and on the way out (`core/Document.js` and the
helper), so an entry with an unusable timestamp is dropped and the rest of the
history is kept.

A TUI or a script can read the same file. The format is the one above, and the
progression is in `core/Progression.js`.

### Coming from 1.0 and earlier

The state file used to live next to `Panel.qml`, inside the plugin folder. On the
first load, if there is no state file yet, the plugin imports
`<plugin folder>/tracker.json` from there, validates it like any other document
and writes it to the new location. The old file is left where it is, so delete it
yourself if you do not want it. Once the new file exists nothing is imported, so
editing the old one later changes nothing.

## Privacy

The plugin makes no network requests.

The only files it reads are the tracker above and, when you use **Back up** or
**Restore**, the one file you pick in the chooser. Nothing else on disk is
opened, and the chosen path is walked from the root and checked component by
component before it is read or written, so it cannot be talked into going
somewhere else.

The only processes it starts are:

- the system `python3` on its own helper, for every read and write
- `/usr/bin/zenity`, the file chooser, when you ask it to pick a file. It is a
  separate process on purpose; see **Back up and restore**
- a system audio player, for the end-of-rest cue, on a system sound file

## Removing

```sh
omarchy plugin remove h1st0ry3d.opushy
```

That removes the plugin folder and the `opushy.debug` IPC target with it. Your
training history is left in place, because it lives outside that folder:

- `~/.local/state/opushy/` and the `tracker.json` inside it, plus `backups/`,
  the copies taken before a restore. Delete the directory if you want the
  history gone. Reinstalling afterwards starts a fresh chain.
- The pre-1.0 `tracker.json` next to `Panel.qml`, if your install still has one.
  The plugin never writes to it and never reads it again.

No keys, units, timers or configuration files are involved.

## Development

```sh
./run_tests.sh
```

`tests/*.test.mjs` cover the progression, the document schema and the rules for
how the QML files may import each other, under `node --test`. The QML `.js`
libraries are loaded into a plain JS context, so those tests need no QML
runtime.

`tests/test_state_helper.py` covers the helper, including a symlink, a FIFO, a
directory and an oversized file planted at the state path, a write that has to
replace a symlink instead of following it, and the one-off import. It runs
against a throwaway home, never yours.

### Layout

```
manifest.json  preview.png  icon.svg  LICENSE
Panel.qml                     the entry point: state, session flow, layout
core/                         Progression.js (the rules), Document.js (the schema)
state/                        opushy-state.py (the only file I/O), Store.qml (its QML side)
ui/                           one component per screen, Plain.js, Status.js
audio/                        the end-of-rest cue
ipc/                          the opushy.debug surface
tests/  run_tests.sh
```

### Debugging

The panel answers `omarchy-shell shell opushy.debug <fn> x`:

| Function | Effect |
|----------|--------|
| `state`  | the derived state as JSON (default) |
| `start`  | start a session, as the Start button does |
| `next` / `skip` | end a round / skip the rest, as those buttons do |
| `showProgress` / `showSession` | jump between the two screens |

All of them ignore the string the shell passes. Driving `start` and three `next`
calls walks a whole session without touching the panel, which is the quickest
way to see the end-of-session screen.

## Licence

MIT, see [LICENSE](LICENSE).
