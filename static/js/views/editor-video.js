// ReelFire — editor video player + timeline (with P2 timeline zoom)
import { editorState } from "../state/editor-state.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatDuration, formatNumber } from "../utils/format.js";
import { selectSegment } from "./editor-segments.js";

// ── view ──────────────────────────────────────────────────────────────

export function setEditorView(view) {
  ["loading", "error", "empty", "content"].forEach((name) => {
    byId("editor-" + name).hidden = name !== view;
  });
}

// ── zoom state ────────────────────────────────────────────────────────

let timelineZoom = 1;
const ZOOM_MIN = 1;
const ZOOM_MAX = 16;
const ZOOM_STEP = 0.5;

export function getTimelineZoom() {
  return timelineZoom;
}

function setTimelineZoom(factor) {
  timelineZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, factor));
  const track = byId("timeline-track");
  const segBar = byId("timeline-segments-bar");
  if (track) track.style.transform = `scaleX(${timelineZoom})`;
  if (segBar) segBar.style.transform = `scaleX(${timelineZoom})`;
  // update zoom display
  const zoomLabel = byId("timeline-zoom-label");
  if (zoomLabel) zoomLabel.textContent = `${timelineZoom.toFixed(1)}x`;
  const zoomOutBtn = document.querySelector(".timeline-zoom-out");
  const zoomInBtn = document.querySelector(".timeline-zoom-in");
  if (zoomOutBtn) zoomOutBtn.disabled = timelineZoom <= ZOOM_MIN;
  if (zoomInBtn) zoomInBtn.disabled = timelineZoom >= ZOOM_MAX;
}

export function zoomIn() {
  setTimelineZoom(timelineZoom + ZOOM_STEP);
}

export function zoomOut() {
  setTimelineZoom(timelineZoom - ZOOM_STEP);
}

export function resetZoom() {
  setTimelineZoom(1);
}

// ── video ─────────────────────────────────────────────────────────────

export function renderVideo() {
  const videoEl = byId("editor-video");
  const placeholder = byId("video-placeholder");
  const status = byId("video-status");
  const video = editorState.video;

  if (video && video.path) {
    videoEl.src = video.path;
    videoEl.hidden = false;
    placeholder.hidden = true;
    videoEl.onloadedmetadata = () => {
      const actualDuration = Number(videoEl.duration);
      if (Number.isFinite(actualDuration) && actualDuration > 0) {
        editorState.video.duration = actualDuration;
        byId("timeline-duration").textContent = formatTime(actualDuration);
        renderTimeline();
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

export function renderTimeline() {
  if (!editorState.video) return;
  const duration = Number(editorState.video.duration);
  if (!Number.isFinite(duration) || duration <= 0) duration = 0;
  const scrubber = byId("timeline-scrubber");
  const track = byId("timeline-track");
  scrubber.max = String(duration);
  scrubber.value = "0";
  track.setAttribute("aria-valuemax", String(duration));

  // segment markers
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

  updatePlayhead(0);
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
  target = Math.max(0, duration > 0 ? Math.min(target, duration) : target);
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

  if (found && found !== editorState.selectedSegmentId) {
    const idx = editorState.segments.findIndex((s) => s.id === found);
    if (idx >= 0) {
      const target = markers[idx];
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

  // play/pause
  playButton.addEventListener("click", () => {
    if (videoEl && videoEl.src) {
      if (videoEl.paused) {
        videoEl.play();
        playButton.setAttribute("aria-label", "暂停");
      } else {
        videoEl.pause();
        playButton.setAttribute("aria-label", "播放");
      }
    }
  });

  // track click
  track.addEventListener("click", (e) => {
    if (!editorState.video) return;
    const rect = track.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / (rect.width * timelineZoom);
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
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / (rect.width * timelineZoom)));
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

  // timeupdate sync
  if (videoEl) {
    videoEl.addEventListener("timeupdate", () => {
      if (!isDragging) {
        updatePlayhead(videoEl.currentTime);
      }
    });
  }

  // P2: zoom with mouse wheel (Ctrl+Wheel) on track
  track.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      if (e.deltaY < 0) zoomIn();
      else zoomOut();
    }
  });

  // P2: zoom with buttons
  const zoomInBtn = document.querySelector(".timeline-zoom-in");
  const zoomOutBtn = document.querySelector(".timeline-zoom-out");
  const zoomResetBtn = document.querySelector(".timeline-zoom-reset");
  if (zoomInBtn) zoomInBtn.addEventListener("click", zoomIn);
  if (zoomOutBtn) zoomOutBtn.addEventListener("click", zoomOut);
  if (zoomResetBtn) zoomResetBtn.addEventListener("click", resetZoom);
}
