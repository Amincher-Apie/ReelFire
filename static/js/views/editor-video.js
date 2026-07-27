// ReelFire — editor video player + timeline (with P2 playback speed control)
import { editorState } from "../state/editor-state.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatDuration, formatNumber } from "../utils/format.js";
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
  const scrubber = byId("timeline-scrubber");
  const track = byId("timeline-track");
  scrubber.max = String(duration);
  // Only reset position to 0 on initial load (scrubber is at 0 from HTML)
  // but don't reset scrubber value — preserve user's position on re-render
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
  const pct = duration > 0 ? Math.min((currentTime / duration) * 100, 100) : 0;
  const playhead = byId("timeline-playhead");
  playhead.style.left = pct + "%";

  const track = byId("timeline-track");
  track.setAttribute("aria-valuenow", String(Math.round(currentTime)));

  byId("timeline-current").textContent = formatTime(currentTime);
  byId("timeline-scrubber").value = String(currentTime);

  highlightSegmentAtTime(currentTime);
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

export function highlightSegmentAtTime(time) {
  let found = null;
  editorState.segments.forEach((seg) => {
    if (time >= seg.start && time <= seg.end) {
      found = seg.id;
    }
  });

  const markers = document.querySelectorAll(".timeline-segment-marker");
  markers.forEach((marker) => {
    marker.classList.remove("active");
  });

  // FIXED: Always highlight the segment the playhead is on,
  // even if it's the currently selected segment.
  if (found) {
    const idx = editorState.segments.findIndex((s) => s.id === found);
    if (idx >= 0) {
      const target = markers[idx];
      if (target) target.classList.add("active");
    }
  }

  // If the playhead isn't on any segment, restore selected segment highlight
  if (!found && editorState.selectedSegmentId) {
    const selIdx = editorState.segments.findIndex((s) => s.id === editorState.selectedSegmentId);
    if (selIdx >= 0) {
      const target = markers[selIdx];
      if (target) target.classList.add("active");
    }
  }
}

export function bindTimelineEvents() {
  if (editorState.timelineBound) return;
  editorState.timelineBound = true;
  const track = byId("timeline-track");
  const scrubber = byId("timeline-scrubber");
  const playButton = byId("timeline-play");
  const videoEl = editorState.videoElement;
  let isDragging = false;

  // Cache speed button refs
  _speedDownBtn = document.querySelector(".timeline-speed-down");
  _speedUpBtn = document.querySelector(".timeline-speed-up");
  _speedLabel = byId("timeline-speed-label");

  // play/pause
  playButton.addEventListener("click", () => {
    if (videoEl && videoEl.src) {
      if (videoEl.paused) {
        videoEl.play().catch(() => {});
      } else {
        videoEl.pause();
      }
    }
  });

  // track click
  track.addEventListener("click", (e) => {
    if (!editorState.video) return;
    const rect = track.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    seekTo(pct * editorState.video.duration);
  });

  // track drag
  track.addEventListener("mousedown", () => {
    isDragging = true;
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging || !editorState.video) return;
    const rect = track.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    seekTo(pct * editorState.video.duration);
  });

  document.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      document.body.style.userSelect = "";
    }
  });

  // keyboard
  track.addEventListener("keydown", (e) => {
    if (!editorState.video) return;
    const step = editorState.video.duration / 100;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      seekTo(Math.min((videoEl ? videoEl.currentTime : 0) + step, editorState.video.duration));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      seekTo(Math.max((videoEl ? videoEl.currentTime : 0) - step, 0));
    }
  });

  scrubber.addEventListener("input", () => {
    if (videoEl && !videoEl.paused) videoEl.pause();
    seekTo(Number(scrubber.value));
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
}
