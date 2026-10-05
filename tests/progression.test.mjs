// The training rules: base reps, the day thresholds, the decay, and the status a
// recorded session gets from the gap to the one before it.
import test from "node:test";
import assert from "node:assert/strict";
import { loadLibrary } from "./qmllibrary.mjs";

const Progression = loadLibrary("../core/Progression.js");

const DAY = 86400000;
// A fixed "now" so the expectations do not move with the wall clock.
const NOW = Date.parse("2026-09-27T12:00:00.000Z");

function daysAgo(n) {
  return new Date(NOW - n * DAY).toISOString();
}

test("a recorded max starts at 75% of it", () => {
  assert.equal(Progression.baseReps(25), 18);
  assert.equal(Progression.baseReps(40), 30);
  assert.equal(Progression.baseReps(1), 1);      // never below one rep
  assert.equal(Progression.baseReps(0), 0);
  assert.equal(Progression.baseReps(-5), 0);
});

test("without a recorded session the preview is the base", () => {
  assert.equal(Progression.nextReps(40, 0, "", NOW), 30);
  assert.equal(Progression.nextReps(40, 33, "", NOW), 30);   // stored reps ignored
  assert.equal(Progression.nextReps(0, 33, daysAgo(1), NOW), 0);
});

test("within two days the preview adds a rep", () => {
  assert.equal(Progression.nextReps(40, 33, daysAgo(0), NOW), 34);
  assert.equal(Progression.nextReps(40, 33, daysAgo(1), NOW), 34);
  assert.equal(Progression.nextReps(40, 33, daysAgo(2), NOW), 34);
});

test("day three keeps the stored value", () => {
  assert.equal(Progression.nextReps(40, 33, daysAgo(3), NOW), 33);
});

test("day four and later decay one rep per extra day", () => {
  assert.equal(Progression.nextReps(40, 33, daysAgo(4), NOW), 32);
  assert.equal(Progression.nextReps(40, 33, daysAgo(6), NOW), 30);
  assert.equal(Progression.nextReps(40, 33, daysAgo(33), NOW), 3);
});

test("the decay never reaches zero", () => {
  assert.equal(Progression.nextReps(40, 2, daysAgo(90), NOW), 1);
  assert.equal(Progression.nextReps(40, 1, daysAgo(400), NOW), 1);
});

test("a stored value of zero falls back to the base", () => {
  assert.equal(Progression.nextReps(40, 0, daysAgo(1), NOW), 31);
});

test("the preview stays inside the stored limit", () => {
  const ceiling = Progression.MAX_REPS;
  assert.equal(Progression.nextReps(ceiling, ceiling, daysAgo(0), NOW), ceiling);
  assert.equal(Progression.nextReps(ceiling, ceiling + 5, daysAgo(0), NOW), ceiling);
});

test("only ISO-8601 UTC instants are timestamps", () => {
  assert.ok(Progression.isValidTimestamp("2026-09-27T12:00:00.000Z"));    // toISOString()
  assert.ok(Progression.isValidTimestamp("2026-08-31T16:17:46.366811Z")); // python, microseconds
  assert.ok(Progression.isValidTimestamp("2026-09-27T12:00:00Z"));
  assert.ok(!Progression.isValidTimestamp("2026-09-27"));                // a bare date
  assert.ok(!Progression.isValidTimestamp("2026-09-27T12:00:00"));        // no zone
  assert.ok(!Progression.isValidTimestamp("2026-09-27T12:00:00+02:00"));  // offset zone
  assert.ok(!Progression.isValidTimestamp("2026-09-27T12:00:00.000Z\n")); // trailing control
  assert.ok(!Progression.isValidTimestamp("not a date at all"));
  assert.ok(!Progression.isValidTimestamp("<img src=x>"));
  assert.ok(!Progression.isValidTimestamp("x".repeat(Progression.MAX_TS_LEN + 1)));
  assert.ok(!Progression.isValidTimestamp(undefined));
  assert.ok(!Progression.isValidTimestamp(20260927));
  assert.ok(Number.isNaN(Progression.parseTimestamp("nope")));
  assert.ok(Number.isNaN(Progression.parseTimestamp("2026-13-45T99:99:99Z")));  // shape, not a date
});

test("days since the last session", () => {
  assert.equal(Progression.daysSince(daysAgo(0), NOW), 0);
  assert.equal(Progression.daysSince(daysAgo(3), NOW), 3);
  assert.equal(Progression.daysSince(daysAgo(3.5), NOW), 3);   // partial days floor
  // A date in the future (clock change, hand-edited file) reads as recent.
  assert.equal(Progression.daysSince(daysAgo(-1), NOW), -1);
  // Anything unparseable is "no idea", far past the decay threshold.
  assert.equal(Progression.daysSince("", NOW), Progression.UNKNOWN_DAYS);
  assert.equal(Progression.daysSince("junk", NOW), Progression.UNKNOWN_DAYS);
});

test("the day count is re-evaluated when it changes, not on a 24h offset", () => {
  // daysSince counts whole 24h periods from a UTC instant, so the boundary is
  // UTC midnight. Anywhere in a UTC day the wait is the time left in that day.
  const mid = Date.UTC(2026, 9, 5, 12, 0, 0);
  assert.equal(Progression.msUntilNextDay(mid), 12 * 3600000 + 3000);
  // Just before the boundary the wait is small, and never zero or negative:
  // firing exactly on the boundary would flip a session saved moments earlier.
  const almost = Date.UTC(2026, 9, 5, 23, 59, 59, 900);
  assert.equal(Progression.msUntilNextDay(almost), 3100);
  // 22:30 UTC is half an hour short of the boundary, whatever the local zone is.
  const lateUtc = Date.UTC(2026, 9, 5, 22, 30, 0);
  assert.equal(Progression.msUntilNextDay(lateUtc), 90 * 60000 + 3000);
});

test("status thresholds", () => {
  assert.equal(Progression.statusForDays(0), Progression.ON_TRACK);
  assert.equal(Progression.statusForDays(2), Progression.ON_TRACK);
  assert.equal(Progression.statusForDays(3), Progression.KEEP);
  assert.equal(Progression.statusForDays(4), Progression.DROP);
  assert.equal(Progression.statusForDays(40), Progression.DROP);
});

test("a record is beaten, not matched", () => {
  assert.equal(Progression.isRecord(41, 40), true);
  assert.equal(Progression.isRecord(40, 40), false);
  assert.equal(Progression.isRecord(39, 40), false);
  assert.equal(Progression.isRecord(1, 0), true);
});

test("a session's status comes from the gap to the one before it", () => {
  const history = [
    { ts: daysAgo(6), reps: 30 },
    { ts: daysAgo(6), reps: 30 },   // same day
    { ts: daysAgo(4), reps: 31 },   // two days later
    { ts: daysAgo(1), reps: 32 },   // three days later
    { ts: daysAgo(0), reps: 33 },   // one day later
  ];
  assert.equal(Progression.historyValue(history, 0), Progression.ON_TRACK);
  assert.equal(Progression.historyValue(history, 1), Progression.ON_TRACK);
  assert.equal(Progression.historyValue(history, 2), Progression.ON_TRACK);
  assert.equal(Progression.historyValue(history, 3), Progression.KEEP);
  assert.equal(Progression.historyValue(history, 4), Progression.ON_TRACK);
});

test("history status survives a broken timestamp", () => {
  const history = [{ ts: "junk", reps: 30 }, { ts: daysAgo(1), reps: 31 }];
  assert.equal(Progression.historyValue(history, 0), Progression.ON_TRACK);
  assert.equal(Progression.historyValue(history, 1), Progression.ON_TRACK);
  assert.equal(Progression.historyValue([], 0), Progression.ON_TRACK);
  assert.equal(Progression.historyValue(history, 99), Progression.ON_TRACK);
  assert.equal(Progression.historyValue("not an array", 0), Progression.ON_TRACK);
});

test("entry accessors never hand back a non-number", () => {
  assert.equal(Progression.entryReps({ reps: 30 }), 30);
  assert.equal(Progression.entryReps({ reps: "30" }), 30);
  assert.equal(Progression.entryReps({ reps: 30.7 }), 30);
  assert.equal(Progression.entryReps({ reps: "thirty" }), 0);
  assert.equal(Progression.entryReps({}), 0);
  assert.equal(Progression.entryReps(null), 0);
  assert.equal(Progression.entryTs({ ts: "2026-09-27T12:00:00.000Z" }), "2026-09-27T12:00:00.000Z");
  assert.equal(Progression.entryTs({}), "");
  assert.equal(Progression.entryTs(null), "");
});
