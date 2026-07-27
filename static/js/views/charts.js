// ReelFire — workbench chart rendering
import { appState } from "../state/app-state.js";
import { byId } from "../utils/dom.js";
import { getCanvasColors, setupHiDPI } from "../utils/canvas.js";

export function renderWorkbenchCharts(report) {
  const card = byId("workbench-charts-card");
  if (!card) return;
  card.hidden = false;

  drawDetectionClassChart(report);
  drawSegmentScoreChart();
  drawWorkbenchTrajectory();
}

export function drawDetectionClassChart(report) {
  const canvas = byId("detection-bar-chart");
  const empty = byId("detection-chart-empty");
  if (!canvas) return;

  const summary = (report.segment_tags && report.segment_tags.summary) ? report.segment_tags.summary : [];
  if (!Array.isArray(summary) || !summary.length) {
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

export function drawSegmentScoreChart() {
  const canvas = byId("segment-score-chart");
  const empty = byId("segment-chart-empty");
  if (!canvas) return;

  if (!appState.segments || !appState.segments.length) {
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
  const segs = appState.segments;

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
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barMaxW / 2, chartBottom + 14);

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

export function drawWorkbenchTrajectory() {
  const canvas = byId("workbench-trajectory-canvas");
  const empty = byId("trajectory-chart-empty");
  if (!canvas) return;

  const hasTrajectory = appState.keyframes.some((kf) =>
    Array.isArray(kf.trajectory) && kf.trajectory.length > 0
  );

  if (!hasTrajectory) {
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

  const allBoxes = [];
  appState.keyframes.forEach((kf) => {
    const traj = kf.trajectory;
    if (!Array.isArray(traj)) return;
    traj.forEach((box) => {
      allBoxes.push({
        trackId: box.track_id || 0,
        x: Number(box.x) || 0,
        y: Number(box.y) || 0,
        w: Number(box.w) || 0,
        h: Number(box.h) || 0,
      });
    });
  });

  if (!allBoxes.length) {
    canvas.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }

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
