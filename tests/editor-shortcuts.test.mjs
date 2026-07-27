import assert from "node:assert/strict";
import test from "node:test";

import {
  adjacentSegmentIndex,
  editorShortcutAction,
  shouldIgnoreEditorShortcutTarget,
  steppedPlaybackTime,
} from "../static/js/utils/editor-shortcuts.js";

test("editor shortcuts recognize space, arrows, and numeric keypad arrows", () => {
  assert.equal(editorShortcutAction({ key: " ", code: "Space" }), "toggle-playback");
  assert.equal(editorShortcutAction({ key: "ArrowLeft", code: "ArrowLeft" }), "step-backward");
  assert.equal(editorShortcutAction({ key: "4", code: "Numpad4" }), "step-backward");
  assert.equal(editorShortcutAction({ key: "ArrowRight", code: "ArrowRight" }), "step-forward");
  assert.equal(editorShortcutAction({ key: "6", code: "Numpad6" }), "step-forward");
  assert.equal(editorShortcutAction({ key: "8", code: "Numpad8" }), "previous-segment");
  assert.equal(editorShortcutAction({ key: "2", code: "Numpad2" }), "next-segment");
  assert.equal(editorShortcutAction({ key: "ArrowUp", code: "ArrowUp" }), "previous-segment");
  assert.equal(editorShortcutAction({ key: "ArrowDown", code: "ArrowDown" }), "next-segment");
  assert.equal(editorShortcutAction({ key: " ", code: "Space", ctrlKey: true }), null);
});

test("segment navigation clamps at boundaries and handles missing selection", () => {
  const segments = [{ id: "seg_001" }, { id: "seg_002" }, { id: "seg_003" }];

  assert.equal(adjacentSegmentIndex(segments, "seg_002", -1), 0);
  assert.equal(adjacentSegmentIndex(segments, "seg_002", 1), 2);
  assert.equal(adjacentSegmentIndex(segments, "seg_001", -1), 0);
  assert.equal(adjacentSegmentIndex(segments, "seg_003", 1), 2);
  assert.equal(adjacentSegmentIndex(segments, null, -1), 2);
  assert.equal(adjacentSegmentIndex(segments, null, 1), 0);
  assert.equal(adjacentSegmentIndex([], null, 1), -1);
});

test("frame stepping uses video fps and clamps to video boundaries", () => {
  assert.equal(steppedPlaybackTime(1, 10, 1, 25), 1.04);
  assert.equal(steppedPlaybackTime(0, 10, -1, 25), 0);
  assert.equal(steppedPlaybackTime(10, 10, 1, 25), 10);
  assert.ok(Math.abs(steppedPlaybackTime(1, 10, 1, 0) - (1 + 1 / 30)) < 1e-9);
});

test("typing and interactive controls keep their native keyboard behavior", () => {
  assert.equal(shouldIgnoreEditorShortcutTarget({ tagName: "INPUT" }), true);
  assert.equal(shouldIgnoreEditorShortcutTarget({ tagName: "BUTTON" }), true);
  assert.equal(shouldIgnoreEditorShortcutTarget({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(shouldIgnoreEditorShortcutTarget({ tagName: "MAIN" }), false);
});
