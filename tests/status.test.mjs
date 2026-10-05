// ui/Status.js: the colours, and the wording the day bubble uses.
//
// The status values come from core/Progression.js rather than being written out
// here, because Status.js names its own constants after the colours: Status.ON_TRACK
// is "#2E7D32", not the 1 that Progression.ON_TRACK is.
import test from "node:test";
import assert from "node:assert/strict";
import { loadLibrary } from "./qmllibrary.mjs";

const Status = loadLibrary("../ui/Status.js");
const Progression = loadLibrary("../core/Progression.js");

test("a session that has never happened reads as an unknown count", () => {
  assert.equal(Status.dayLabel(false, 0), "∞");
  assert.equal(Status.dayLabel(false, 999), "∞");
});

test("the day label counts days, and says zero on the day itself", () => {
  assert.equal(Status.dayLabel(true, 0), "0d");
  assert.equal(Status.dayLabel(true, 1), "1d");
  assert.equal(Status.dayLabel(true, 12), "12d");
});

test("every status value maps to a colour and to wording", () => {
  for (const value of [Progression.ON_TRACK, Progression.KEEP, Progression.DROP]) {
    assert.match(Status.colorForValue(value), /^#[0-9A-F]{6}$/, `colour for ${value}`);
    assert.ok(Status.labelForValue(value).length > 0, `label for ${value}`);
  }
});

test("the three statuses are visually distinct", () => {
  const values = [Progression.ON_TRACK, Progression.KEEP, Progression.DROP];
  const colours = values.map((value) => Status.colorForValue(value));
  assert.equal(new Set(colours).size, colours.length);
});