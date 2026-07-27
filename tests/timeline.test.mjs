import test from "node:test";
import assert from "node:assert/strict";

import {
  pointerXToTimelineTime,
  timeToTimelinePercent,
} from "../static/js/utils/timeline.js";

test("timeline pointer mapping uses the full visible track", () => {
  assert.equal(pointerXToTimelineTime(120, 120, 800, 2_820), 0);
  assert.equal(pointerXToTimelineTime(920, 120, 800, 2_820), 2_820);
  assert.equal(pointerXToTimelineTime(520, 120, 800, 2_820), 1_410);
});

test("timeline pointer mapping clamps positions outside the track", () => {
  assert.equal(pointerXToTimelineTime(20, 120, 800, 2_820), 0);
  assert.equal(pointerXToTimelineTime(1_020, 120, 800, 2_820), 2_820);
});

test("playhead percentages share the same zero-to-duration scale", () => {
  assert.equal(timeToTimelinePercent(0, 2_820), 0);
  assert.equal(timeToTimelinePercent(1_410, 2_820), 50);
  assert.equal(timeToTimelinePercent(2_820, 2_820), 100);
  assert.equal(timeToTimelinePercent(3_000, 2_820), 100);
});
