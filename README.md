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
  **Skip**. Skip jumps straight to the next round, and on the third round it ends
  the session.
- Finishing the third rest records the session. The history grows by one entry,
  the training-day count goes up, and the stored reps become what you just did.

**Stop** throws a running session away, after asking. It records nothing. A right
click on the bar icon during a session opens the panel on the same question, so a
stray right click cannot discard three finished rounds.

The panel also shows the chain so far, seven sessions to a page (the arrows, or
the left and right arrow keys). Each disc carries the reps that session asked for
and the colour of the gap to the session before it. The dot in the top right
applies the same idea to today, with the days since the last session and a
tooltip for the colour.

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

One file, and nothing else:

```
~/.local/state/opushy/tracker.json    (mode 0600, in a 0700 directory)
```

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

The plugin makes no network requests and reads no file other than the one above.
The only processes it starts are the system `python3` on its own helper and, for
the end-of-rest cue, a system audio player on a system sound file.

## Removing

```sh
omarchy plugin remove h1st0ry3d.opushy
```

That removes the plugin folder and the `opushy.debug` IPC target with it. Your
training history is left in place, because it lives outside that folder:

- `~/.local/state/opushy/` and the `tracker.json` inside it. Delete the file (or
  the directory) if you want the history gone. Reinstalling afterwards starts a
  fresh chain.
- The pre-1.0 `tracker.json` next to `Panel.qml`, if your install still has one.
  The plugin never writes to it and never reads it again.

No keys, units, timers or configuration files are involved.

## Development

```sh
./run_tests.sh
```

`tests/*.test.mjs` cover the progression and the document schema under
`node --test`. The QML `.js` libraries are loaded into a plain JS context, so
those tests need no QML runtime.

`tests/test_state_helper.py` covers the helper, including a symlink, a FIFO, a
directory and an oversized file planted at the state path, a write that has to
replace a symlink instead of following it, and the one-off import. It runs
against a throwaway home, never yours.

### Layout

```
manifest.json  icon.svg  LICENSE
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
| `showProgress` / `showSession` | jump between the two screens |

All of them ignore the string the shell passes.

## Licence

MIT, see [LICENSE](LICENSE).
