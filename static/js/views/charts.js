// ReelFire — workbench chart rendering
import { appState } from "../state/app-state.js";
import { byId } from "../utils/dom.js";
import { getCanvasColors, setupHiDPI } from "../utils/canvas.js";

export function renderWorkbenchCharts(
  report,
  visibleSegments = appState.segments,
  segmentStartIndex = 0,
) {
  const card = byId("workbench-charts-card");
  if (!card) return;
  card.hidden = false;

  drawDetectionClassChart(report);
  drawSegmentScoreChart(visibleSegments, segmentStartIndex);
  drawWorkbenchTrajectory(report);
}

function detectionClassSummary(report) {
  const tagStats = report?.segment_tags?.tags;
  if (tagStats && typeof tagStats === "object" && !Array.isArray(tagStats)) {
    const entries = Object.entries(tagStats)
      .map(([label, stats]) => ({
        label,
        count: Number(stats?.count) || 0,
      }))
      .filter((item) => item.label && item.count > 0)
      .sort((left, right) => right.count - left.count);
    if (entries.length) return entries;
  }

  const summary = report?.segment_tags?.summary;
  if (!Array.isArray(summary)) return [];
  return summary
    .map((item) => {
      if (item && typeof item === "object") {
        return {
          label: String(item.label || ""),
          count: Number(item.count) || 0,
        };
      }
      const value = String(item || "").trim();
      const countStart = value.lastIndexOf("(");
      const countEnd = value.endsWith(")") ? value.length - 1 : -1;
      if (countStart <= 0 || countEnd <= countStart) {
        return { label: value, count: 0 };
      }
      return {
        label: value.slice(0, countStart),
        count: Number(value.slice(countStart + 1, countEnd)) || 0,
      };
    })
    .filter((item) => item.label && item.count > 0);
}

export function drawDetectionClassChart(report) {
  const canvas = byId("detection-bar-chart");
  const empty = byId("detection-chart-empty");
  if (!canvas) return;

  const summary = detectionClassSummary(report);
  if (!summary.length) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;

  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 24 : 370;
  const H = 200;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();
  const topN = summary.slice(0, 8);

  const maxCount = Math.max.apply(null, topN.map((d) => d.count || 0).concat([1]));
  const barMaxW = Math.min(36, (W - 80) / topN.length);
  const barGap = Math.max(3, (W - 80 - barMaxW * topN.length) / (topN.length + 1));
  const chartBottom = H - 24;
  const chartTop = 16;

  topN.forEach((item, i) => {
    const count = item.count || 0;
    const barH = ((chartBottom - chartTop) * count) / maxCount;
    const x = 44 + barGap + i * (barMaxW + barGap);
    const y = chartBottom - barH;

    ctx.fillStyle = colors.primary;
    ctx.fillRect(x, y, barMaxW, barH);

    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.save();
    ctx.translate(x + barMaxW / 2, chartBottom + 8);
    const label = (item.label || "").length > 6 ? (item.label || "").slice(0, 5) + "…" : (item.label || "");
    ctx.fillText(label, 0, 0);
    ctx.restore();

    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(String(count), x + barMaxW / 2, y - 4);
  });

  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(38, chartBottom);
  ctx.lineTo(W - 8, chartBottom);
  ctx.stroke();
}

export function drawSegmentScoreChart(
  visibleSegments = appState.segments,
  segmentStartIndex = 0,
) {
  const canvas = byId("segment-score-chart");
  const empty = byId("segment-chart-empty");
  if (!canvas) return;

  const segs = Array.isArray(visibleSegments) ? visibleSegments : [];
  if (!segs.length) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;

  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 24 : 370;
  const H = 200;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();

  const barMaxW = Math.min(36, (W - 80) / segs.length);
  const barGap = Math.max(3, (W - 80 - barMaxW * segs.length) / (segs.length + 1));
  const chartBottom = H - 24;
  const chartTop = 16;

  segs.forEach((seg, i) => {
    const score = Number(seg.score) || 0;
    const barH = (chartBottom - chartTop) * score;
    const x = 44 + barGap + i * (barMaxW + barGap);
    const y = chartBottom - barH;

    ctx.fillStyle = colors.accent;
    ctx.fillRect(x, y, barMaxW, barH);

    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText(
      seg.id || ("#" + (segmentStartIndex + i + 1)),
      x + barMaxW / 2,
      chartBottom + 14,
    );

    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(Math.round(score * 100), x + barMaxW / 2, y - 4);
  });

  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(38, chartBottom);
  ctx.lineTo(W - 8, chartBottom);
  ctx.stroke();
}

function workbenchTrajectoryBoxes(report) {
  const boxes = [];
  const segments = Array.isArray(report?.segments)
    ? report.segments
    : appState.segments;
  segments.forEach((segment, segmentIndex) => {
    const tracks = segment?.tracking?.tracks;
    if (!Array.isArray(tracks)) return;
    tracks.forEach((track) => {
      if (!Array.isArray(track.points)) return;
      track.points.forEach((point) => {
        boxes.push({
          trackId: (
            track.track_key
            || `${segment.id || segmentIndex}:${track.track_id ?? 0}`
          ),
          x: Number(point.x) || 0,
          y: Number(point.y) || 0,
          w: Number(point.w) || 0,
          h: Number(point.h) || 0,
          timestamp: Number(point.timestamp) || 0,
        });
      });
    });
  });
  if (boxes.length) return boxes;

  appState.keyframes.forEach((kf) => {
    const trajectory = kf.trajectory;
    if (!Array.isArray(trajectory)) return;
    trajectory.forEach((box) => {
      boxes.push({
        trackId: `legacy:${box.track_id || 0}`,
        x: Number(box.x) || 0,
        y: Number(box.y) || 0,
        w: Number(box.w) || 0,
        h: Number(box.h) || 0,
        timestamp: Number(kf.timestamp) || 0,
      });
    });
  });
  return boxes;
}

export function drawWorkbenchTrajectory(report = appState.report) {
  const canvas = byId("workbench-trajectory-canvas");
  const empty = byId("trajectory-chart-empty");
  if (!canvas) return;

  const allBoxes = workbenchTrajectoryBoxes(report);

  if (!allBoxes.length) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  if (empty) empty.hidden = true;

  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 24 : 320;
  const H = 180;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();

  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  allBoxes.forEach((b) => {
    if (b.x < minX) minX = b.x;
    if (b.y < minY) minY = b.y;
    if (b.x + b.w > maxX) maxX = b.x + b.w;
    if (b.y + b.h > maxY) maxY = b.y + b.h;
  });

  const rangeX = maxX - minX || 1, rangeY = maxY - minY || 1;
  const margin = 16;
  const sc = Math.min((W - margin * 2) / rangeX, (H - margin * 2) / rangeY);

  const trackColors = [colors.accent, colors.primary, colors.success, colors.warning];
  const tracks = {};
  allBoxes.forEach((b) => {
    const key = String(b.trackId);
    if (!tracks[key]) tracks[key] = [];
    tracks[key].push(b);
  });

  let tIdx = 0;
  Object.keys(tracks).forEach((key) => {
    const boxes = tracks[key];
    const color = trackColors[tIdx % trackColors.length];
    tIdx++;

    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    boxes.forEach((b, i) => {
      const cx = margin + (b.x + b.w / 2 - minX) * sc;
      const cy = margin + (b.y + b.h / 2 - minY) * sc;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
    ctx.globalAlpha = 1;

    boxes.forEach((b) => {
      const rx = margin + (b.x - minX) * sc;
      const ry = margin + (b.y - minY) * sc;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(rx, ry, b.w * sc, b.h * sc);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(rx, ry, b.w * sc, b.h * sc);
      ctx.globalAlpha = 1;
    });
  });
}
