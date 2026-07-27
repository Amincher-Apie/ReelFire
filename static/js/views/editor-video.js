// ReelFire — editor video player + timeline (with P2 playback speed control)
import { editorState } from "../state/editor-state.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatDuration, formatNumber } from "../utils/format.js";
import {
  pointerXToTimelineTime,
  timeToTimelinePercent,
} from "../utils/timeline.js";
import {
  adjacentSegmentIndex,
  editorShortcutAction,
  shouldIgnoreEditorShortcutTarget,
  steppedPlaybackTime,
} from "../utils/editor-shortcuts.js";
import { outputUrl } from "../utils/url.js";
import { selectSegment } from "./editor-segments.js";

// ── view ──────────────────────────────────────────────────────────────

export function setEditorView(view) {
  ["loading", "error", "empty", "content"].forEach((name) => {
    byId("editor-" + name).hidden = name !== view;
  });
}

// ── playback speed state ──────────────────────────────────────────────

let playbackSpeed = 1;
const SPEED_MIN = 0.25;
const SPEED_MAX = 4;
const SPEED_STEP = 0.25;
const SPEED_PRESETS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4];

// Cached DOM refs for speed buttons (set in bindTimelineEvents)
let _speedDownBtn = null;
let _speedUpBtn = null;
let _speedLabel = null;

export function getPlaybackSpeed() {
  return playbackSpeed;
}

function setPlaybackSpeed(speed) {
  playbackSpeed = Math.max(SPEED_MIN, Math.min(SPEED_MAX, speed));
  // Round to nearest preset
  let nearest = SPEED_PRESETS[0];
  let minDiff = Math.abs(playbackSpeed - nearest);
  for (const p of SPEED_PRESETS) {
    const diff = Math.abs(playbackSpeed - p);
    if (diff < minDiff) { minDiff = diff; nearest = p; }
  }
  playbackSpeed = nearest;

  // Apply to video element
  const videoEl = editorState.videoElement;
  if (videoEl) videoEl.playbackRate = playbackSpeed;

  // update speed display (use cached refs)
  const label = _speedLabel || byId("timeline-speed-label");
  if (label) label.textContent = playbackSpeed.toFixed(2).replace(/0+$/, "").replace(/\.$/, "") + "x";
  if (_speedDownBtn) _speedDownBtn.disabled = playbackSpeed <= SPEED_MIN;
  if (_speedUpBtn) _speedUpBtn.disabled = playbackSpeed >= SPEED_MAX;
}

export function speedUp() {
  setPlaybackSpeed(playbackSpeed + SPEED_STEP);
}

export function speedDown() {
  setPlaybackSpeed(playbackSpeed - SPEED_STEP);
}

export function resetSpeed() {
  setPlaybackSpeed(1);
}

// ── video ─────────────────────────────────────────────────────────────

export function renderVideo() {
  const videoEl = byId("editor-video");
  const placeholder = byId("video-placeholder");
  const status = byId("video-status");
  const video = editorState.video;

  // 新后端返回 video.url（直接可用），旧后端返回 video.path（需拼接 /outputs/）
  const videoSrc = video && (video.url || (video.path && outputUrl(editorState.jobId, video.path)));
  if (videoSrc) {
    videoEl.src = videoSrc;
    videoEl.hidden = false;
    placeholder.hidden = true;
    videoEl.onloadedmetadata = () => {
      const actualDuration = Number(videoEl.duration);
      if (Number.isFinite(actualDuration) && actualDuration > 0) {
        editorState.video.duration = actualDuration;
        byId("timeline-duration").textContent = formatTime(actualDuration);
        renderTimeline();
      }
      // Re-apply playback speed to the newly loaded video element
      if (videoEl.playbackRate !== playbackSpeed) {
        videoEl.playbackRate = playbackSpeed;
      }
    };
    videoEl.onerror = () => {
      videoEl.hidden = true;
      placeholder.hidden = false;
      status.textContent = "当前视频加载失败，请检查源文件格式或任务输出是否完整。";
    };
    videoEl.load();
  } else {
    videoEl.hidden = true;
    placeholder.hidden = false;
    status.textContent = "当前任务没有可预览的视频源。";
  }

  if (video) {
    byId("timeline-duration").textContent = formatTime(video.duration);
  }

  editorState.videoElement = videoEl;
}

// ── timeline ──────────────────────────────────────────────────────────

/**
 * Assign segments to non-overlapping vertical lanes so overlapping
 * segments stack instead of hiding each other.
 *
 * Returns { lanes: number[], totalLanes: number } — always an object.
 */
export function computeSegmentLanes() {
  const segs = editorState.segments;
  if (!segs.length) return { lanes: [], totalLanes: 0 };

  // Work on sorted copy (by start, then by end desc so longer segments go first)
  const indexed = segs.map((seg, i) => ({ seg, i, start: seg.start, end: seg.end }));
  indexed.sort((a, b) => a.start - b.start || b.end - a.end);

  const lanes = new Array(segs.length).fill(0);
  // For each lane, track the latest end time
  const laneEnds = [];

  indexed.forEach((item) => {
    let lane = 0;
    // Find the first lane where this segment doesn't overlap
    while (lane < laneEnds.length && laneEnds[lane] > item.start) {
      lane++;
    }
    lanes[item.i] = lane;
    laneEnds[lane] = item.end;
  });

  return { lanes, totalLanes: laneEnds.length };
}

export function renderTimeline() {
  if (!editorState.video) return;
  let duration = Number(editorState.video.duration);  // FIXED: let, not const
  if (!Number.isFinite(duration) || duration <= 0) duration = 0;
  const track = byId("timeline-track");
  track.setAttribute("aria-valuemax", String(duration));

  // Compute lane assignments for overlapping segments
  const { lanes, totalLanes } = computeSegmentLanes();
  const laneHeight = totalLanes > 0 ? 100 / totalLanes : 100;

  const segmentsBar = byId("timeline-segments-bar");
  clearChildren(segmentsBar);
  editorState.segments.forEach((seg, idx) => {
    const left = duration > 0 ? (seg.start / duration) * 100 : 0;
    const width =
      duration > 0
        ? Math.max(((seg.end - seg.start) / duration) * 100, 0.5)
        : 0;
    const marker = createElement("div", "timeline-segment-marker seg-" + idx);
    marker.style.left = left + "%";
    marker.style.width = width + "%";
    // Vertical lane stacking for overlapping segments
    if (totalLanes > 1) {
      const lane = lanes[idx] || 0;
      marker.style.top = (lane * laneHeight) + "%";
      marker.style.height = laneHeight + "%";
      marker.dataset.lane = String(lane);
    }
    marker.title =
      "片段 " +
      seg.id +
      ": " +
      formatTime(seg.start) +
      " – " +
      formatTime(seg.end) +
      " (评分 " +
      formatNumber(Number(seg.score) * 100, 0) +
      ")";
    marker.setAttribute("role", "button");
    marker.setAttribute("aria-label", marker.title);
    marker.setAttribute("tabindex", "0");
    marker.addEventListener("click", (e) => {
      e.stopPropagation();
      selectSegment(seg.id);
      seekTo(seg.start);
    });
    marker.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSegment(seg.id);
        seekTo(seg.start);
      }
    });
    segmentsBar.append(marker);
  });

  // Restore selected segment highlight after re-render
  if (editorState.selectedSegmentId) {
    const selIdx = editorState.segments.findIndex((s) => s.id === editorState.selectedSegmentId);
    if (selIdx >= 0) {
      const marker = segmentsBar.children[selIdx];
      if (marker) marker.classList.add("active");
    }
  }
}

export function updatePlayhead(currentTime) {
  if (!editorState.video) return;
  const duration = editorState.video.duration;
  const pct = timeToTimelinePercent(currentTime, duration);
  const playhead = byId("timeline-playhead");
  playhead.style.left = pct + "%";

  const track = byId("timeline-track");
  track.setAttribute("aria-valuenow", String(Math.round(currentTime)));
  track.setAttribute("aria-valuetext", formatTime(currentTime));

  byId("timeline-current").textContent = formatTime(currentTime);
}

export function seekTo(time) {
  const duration = editorState.video ? Number(editorState.video.duration) : 0;
  let target = Number(time);
  if (!Number.isFinite(target)) return;
  // Always clamp to [0, duration] even when duration is 0
  if (duration > 0) {
    target = Math.max(0, Math.min(target, duration));
  } else {
    target = 0;
  }
  if (editorState.videoElement && editorState.videoElement.src) {
    editorState.videoElement.currentTime = target;
  }
  updatePlayhead(target);
}

function segmentAtTime(time) {
  return editorState.segments.find((segment) => (
    time >= segment.start && time <= segment.end
  )) || null;
}

function syncSelectionAtTime(time) {
  const segment = segmentAtTime(time);
  if (segment) selectSegment(segment.id);
}

function toggleVideoPlayback(videoEl) {
  if (!videoEl || !videoEl.src) return;
  if (videoEl.paused) {
    videoEl.play().catch(() => {});
  } else {
    videoEl.pause();
  }
}

function runPlaybackShortcut(action, videoEl) {
  if (!videoEl || !videoEl.src || !editorState.video) return false;

  if (action === "toggle-playback") {
    toggleVideoPlayback(videoEl);
    return true;
  }

  if (action === "previous-segment" || action === "next-segment") {
    const direction = action === "previous-segment" ? -1 : 1;
    const targetIndex = adjacentSegmentIndex(
      editorState.segments,
      editorState.selectedSegmentId,
      direction,
    );
    const targetSegment = editorState.segments[targetIndex];
    if (!targetSegment) return false;

    selectSegment(targetSegment.id);
    seekTo(targetSegment.start);
    return true;
  }

  videoEl.pause();
  const direction = action === "step-backward" ? -1 : 1;
  seekTo(steppedPlaybackTime(
    videoEl.currentTime,
    editorState.video.duration,
    direction,
    editorState.video.fps,
  ));
  return true;
}

function handleEditorKeyboardShortcut(event) {
  if (
    event.defaultPrevented
    || shouldIgnoreEditorShortcutTarget(event.target)
    || document.querySelector("dialog[open]")
  ) {
    return;
  }

  const action = editorShortcutAction(event);
  if (!action) return;

  const videoEl = editorState.videoElement;
  if (runPlaybackShortcut(action, videoEl)) event.preventDefault();
}

export function bindTimelineEvents() {
  if (editorState.timelineBound) return;
  editorState.timelineBound = true;
  const track = byId("timeline-track");
  const playButton = byId("timeline-play");
  const videoEl = editorState.videoElement;
  let isDragging = false;

  // Cache speed button refs
  _speedDownBtn = document.querySelector(".timeline-speed-down");
  _speedUpBtn = document.querySelector(".timeline-speed-up");
  _speedLabel = byId("timeline-speed-label");

  // play/pause
  playButton.addEventListener("click", () => {
    toggleVideoPlayback(videoEl);
  });

  const seekFromPointer = (event) => {
    if (!editorState.video) return;
    const rect = track.getBoundingClientRect();
    const target = pointerXToTimelineTime(
      event.clientX,
      rect.left,
      rect.width,
      editorState.video.duration,
    );
    seekTo(target);
    return target;
  };

  track.addEventListener("pointerdown", (event) => {
    if (
      event.button !== 0
      || event.target.closest(".timeline-segment-marker")
    ) {
      return;
    }
    event.preventDefault();
    isDragging = true;
    track.classList.add("dragging");
    track.setPointerCapture(event.pointerId);
    track.focus({ preventScroll: true });
    document.body.style.userSelect = "none";
    const target = seekFromPointer(event);
    if (Number.isFinite(target)) syncSelectionAtTime(target);
  });

  track.addEventListener("pointermove", (event) => {
    if (!isDragging) return;
    seekFromPointer(event);
  });

  const finishDragging = (event) => {
    if (!isDragging) return;
    isDragging = false;
    track.classList.remove("dragging");
    if (track.hasPointerCapture(event.pointerId)) {
      track.releasePointerCapture(event.pointerId);
    }
    document.body.style.userSelect = "";
  };

  track.addEventListener("pointerup", finishDragging);
  track.addEventListener("pointercancel", finishDragging);

  // keyboard
  track.addEventListener("keydown", (e) => {
    if (!editorState.video) return;
    const action = editorShortcutAction(e);
    if (action && runPlaybackShortcut(action, videoEl)) {
      e.preventDefault();
    } else if (e.key === "Home") {
      e.preventDefault();
      seekTo(0);
    } else if (e.key === "End") {
      e.preventDefault();
      seekTo(editorState.video.duration);
    }
  });

  // timeupdate sync + play/pause/ended button state
  if (videoEl) {
    videoEl.addEventListener("timeupdate", () => {
      if (!isDragging) {
        updatePlayhead(videoEl.currentTime);
      }
    });
    videoEl.addEventListener("play", () => {
      playButton.setAttribute("aria-label", "暂停");
    });
    videoEl.addEventListener("pause", () => {
      playButton.setAttribute("aria-label", "播放");
    });
    videoEl.addEventListener("ended", () => {
      playButton.setAttribute("aria-label", "播放");
      updatePlayhead(editorState.video ? editorState.video.duration : 0);
    });
  }

  // P2: playback speed with mouse wheel (Ctrl+Wheel) on track
  track.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      if (e.deltaY < 0) speedUp();
      else speedDown();
    }
  });

  // P2: playback speed with buttons
  if (_speedUpBtn) _speedUpBtn.addEventListener("click", speedUp);
  if (_speedDownBtn) _speedDownBtn.addEventListener("click", speedDown);
  const speedResetBtn = document.querySelector(".timeline-speed-reset");
  if (speedResetBtn) speedResetBtn.addEventListener("click", resetSpeed);

  document.addEventListener("keydown", handleEditorKeyboardShortcut);
}
