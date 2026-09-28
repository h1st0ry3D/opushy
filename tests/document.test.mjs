// The state document as input: what survives a parse, what is dropped, and what
// the writer is allowed to produce.
import test from "node:test";
import assert from "node:assert/strict";
import { loadLibrary, plain } from "./qmllibrary.mjs";

const Progression = loadLibrary("../core/Progression.js");
const Document = loadLibrary("../core/Document.js");

const TS = "2026-09-27T12:00:00.000Z";

function parse(value) {
  return Document.parse(typeof value === "string" ? value : JSON.stringify(value), Progression);
}

test("an absent, empty or broken document is a first run", () => {
  for (const raw of ["", "   ", "not json", "{", "[]", "null", "42", '"a string"']) {
    assert.deepEqual(parse(raw), Document.emptyDocument(), raw);
  }
  assert.deepEqual(Document.parse(undefined, Progression), Document.emptyDocument());
});

test("a well formed document is taken as it is", () => {
  const doc = parse({
    maxPushups: 40,
    reps: 33,
    lastTrainingDate: TS,
    trainingDays: 5,
    history: [{ ts: "2026-09-26T12:00:00.000Z", reps: 33 }]
  });
  assert.equal(doc.maxPushups, 40);
  assert.equal(doc.reps, 33);
  assert.equal(doc.lastTrainingDate, TS);
  assert.equal(doc.trainingDays, 5);
  assert.deepEqual(plain(doc.history), [{ ts: "2026-09-26T12:00:00.000Z", reps: 33 }]);
});

test("unknown keys are dropped", () => {
  const doc = parse({ maxPushups: 40, evil: "<img src=x>", nested: { a: 1 } });
  assert.deepEqual(Object.keys(doc).sort(), Object.keys(Document.emptyDocument()).sort());
});

test("numbers must be finite integers in range", () => {
  assert.equal(parse({ maxPushups: "40" }).maxPushups, 0);
  assert.equal(parse({ maxPushups: true }).maxPushups, 0);
  assert.equal(parse({ maxPushups: null }).maxPushups, 0);
  assert.equal(parse({ maxPushups: 40.7 }).maxPushups, 40);
  assert.equal(parse({ maxPushups: 0 }).maxPushups, 0);
  assert.equal(parse({ maxPushups: Document.MAX_REPS }).maxPushups, Document.MAX_REPS);
  assert.equal(parse({ maxPushups: Document.MAX_REPS + 1 }).maxPushups, 0);
  assert.equal(parse({ maxPushups: -1 }).maxPushups, 0);
  // 1e999 parses to Infinity in JSON.parse, and is not a number we store.
  assert.equal(parse('{"maxPushups": 1e999}').maxPushups, 0);
  assert.equal(parse('{"reps": 1e999}').reps, 0);
});

test("only the ISO-8601 UTC shape is a timestamp", () => {
  assert.equal(parse({ lastTrainingDate: TS }).lastTrainingDate, TS);
  assert.equal(parse({ lastTrainingDate: "2026-08-31T16:17:46.366811Z" }).lastTrainingDate,
               "2026-08-31T16:17:46.366811Z");
  assert.equal(parse({ lastTrainingDate: "" }).lastTrainingDate, "");
  assert.equal(parse({ lastTrainingDate: "2026-09-27" }).lastTrainingDate, "");
  assert.equal(parse({ lastTrainingDate: 12345 }).lastTrainingDate, "");
  assert.equal(parse({ lastTrainingDate: "x".repeat(Document.MAX_TS_LEN + 1) }).lastTrainingDate, "");
});

test("a broken history entry is dropped, the rest is kept", () => {
  const doc = parse({
    history: [
      { ts: "2026-09-20T12:00:00.000Z", reps: 30 },
      { ts: "not a date", reps: 31 },        // unusable date
      "2026-09-21T12:00:00.000Z",           // legacy bare timestamp
      42,                                    // legacy scalar
      null,
      [],                                     // an array, not an entry
      { reps: 32 },                          // no date
      { ts: "2026-09-22T12:00:00.000Z" },    // no reps: counted as 0, not dropped
      { ts: "2026-09-23T12:00:00.000Z", reps: 1e999 }
    ]
  });
  assert.deepEqual(plain(doc.history), [
    { ts: "2026-09-20T12:00:00.000Z", reps: 30 },
    { ts: "2026-09-22T12:00:00.000Z", reps: 0 },
    { ts: "2026-09-23T12:00:00.000Z", reps: 0 }
  ]);
});

test("a history that is not a list is empty", () => {
  for (const history of [{}, "nope", 42, null, true]) {
    assert.deepEqual(plain(parse({ history }).history), []);
  }
});

test("the history keeps the most recent entries", () => {
  const many = [];
  for (let i = 0; i < Document.HISTORY_MAX + 25; i++) {
    many.push({ ts: new Date(Date.UTC(2020, 0, 1) + i * 86400000).toISOString(), reps: i });
  }
  const doc = parse({ history: many });
  assert.equal(doc.history.length, Document.HISTORY_MAX);
  assert.equal(doc.history[0].reps, 25);
  assert.equal(doc.history[doc.history.length - 1].reps, many.length - 1);
});

test("serialize emits one line with only the known keys, in range", () => {
  const line = Document.serialize({
    maxPushups: 40,
    reps: 33,
    lastTrainingDate: TS,
    trainingDays: 5,
    history: [{ ts: TS, reps: 33 }],
    extra: "dropped"
  }, Progression);
  assert.ok(!line.includes("\n"));
  assert.deepEqual(Object.keys(JSON.parse(line)).sort(),
    ["history", "lastTrainingDate", "maxPushups", "reps", "trainingDays"]);

  // Whatever the caller passes, the writer emits the same shape it would read.
  const hostile = JSON.parse(Document.serialize({
    maxPushups: 1e999,
    reps: -3,
    lastTrainingDate: "<img src=x>",
    trainingDays: "many",
    history: "not a list"
  }, Progression));
  assert.deepEqual(hostile, {
    maxPushups: 0, reps: 0, lastTrainingDate: "", trainingDays: 0, history: []
  });
});

test("a document survives the round trip unchanged", () => {
  const doc = {
    maxPushups: 40,
    reps: 33,
    lastTrainingDate: TS,
    trainingDays: 5,
    history: [
      { ts: "2026-09-26T12:00:00.000Z", reps: 33 },
      { ts: TS, reps: 34 }
    ]
  };
  const once = Document.parse(Document.serialize(doc, Progression), Progression);
  const twice = Document.parse(Document.serialize(once, Progression), Progression);
  assert.deepEqual(plain(once), doc);
  assert.deepEqual(plain(twice), doc);
});
