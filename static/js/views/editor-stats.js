// ReelFire — editor statistics dashboard + charts + trajectory
import { editorState } from "../state/editor-state.js";
import { byId } from "../utils/dom.js";
import { getCanvasColors, setupHiDPI } from "../utils/canvas.js";

// ── stats dashboard ───────────────────────────────────────────────────

export function renderStatsDashboard() {
  const dash = byId("stats-dashboard");
  if (!dash) return;
  dash.hidden = false;

  const counts = { pass: 0, needs_review: 0, reject: 0, unset: 0 };
  editorState.segments.forEach((seg) => {
    const r = editorState.reviews[seg.id];
    const rec = r ? r.recommendation : "";
    if (rec === "pass") counts.pass++;
    else if (rec === "needs_review") counts.needs_review++;
    else if (rec === "reject") counts.reject++;
    else counts.unset++;
  });

  ["pass", "needs-review", "reject", "unset"].forEach((key) => {
    const el = byId("stat-" + key);
    if (el) el.textContent = String(counts[key.replace("-", "_")] || counts[key] || 0);
  });
}

export function showStatsDialog() {
  const dialog = byId("stats-dialog");
  if (!dialog) return;

  const counts = { pass: 0, needs_review: 0, reject: 0, unset: 0 };
  editorState.segments.forEach((seg) => {
    const r = editorState.reviews[seg.id];
    const rec = r ? r.recommendation : "";
    if (rec === "pass") counts.pass++;
    else if (rec === "needs_review") counts.needs_review++;
    else if (rec === "reject") counts.reject++;
    else counts.unset++;
  });

  const dlgPass = byId("dlg-stat-pass");
  const dlgNeeds = byId("dlg-stat-needs-review");
  const dlgReject = byId("dlg-stat-reject");
  const dlgUnset = byId("dlg-stat-unset");
  if (dlgPass) dlgPass.textContent = String(counts.pass);
  if (dlgNeeds) dlgNeeds.textContent = String(counts.needs_review);
  if (dlgReject) dlgReject.textContent = String(counts.reject);
  if (dlgUnset) dlgUnset.textContent = String(counts.unset);

  drawScoreDistribution(byId("chart-score-dist"));
  drawDurationChart(byId("chart-duration"));
  drawReviewPieChart(byId("chart-review-pie"), counts);

  dialog.showModal();
}

// ── charts ────────────────────────────────────────────────────────────

export function drawScoreDistribution(canvas) {
  if (!canvas) return;
  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 380;
  const H = 200;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();
  const segs = editorState.segments;
  if (!segs.length) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("无片段数据", W / 2, H / 2);
    return;
  }

  const barMaxW = Math.min(40, (W - 80) / segs.length);
  const gap = Math.max(4, (W - 80 - barMaxW * segs.length) / (segs.length + 1));
  const chartBottom = H - 28;
  const chartTop = 20;

  segs.forEach((seg, i) => {
    const x = 40 + gap + i * (barMaxW + gap);
    const barH = ((chartBottom - chartTop) * (Number(seg.score) || 0));
    const y = chartBottom - barH;

    ctx.fillStyle = colors.accent;
    ctx.fillRect(x, y, barMaxW, barH);

    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barMaxW / 2, chartBottom + 14);

    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(Math.round((Number(seg.score) || 0) * 100), x + barMaxW / 2, y - 4);
  });

  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(35, chartBottom);
  ctx.lineTo(W - 10, chartBottom);
  ctx.stroke();
}

export function drawDurationChart(canvas) {
  if (!canvas) return;
  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 380;
  const H = 200;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();
  const segs = editorState.segments;
  if (!segs.length) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("无片段数据", W / 2, H / 2);
    return;
  }

  const durations = segs.map((s) => Math.max(0, s.end - s.start));
  const maxDur = Math.max.apply(null, durations);
  if (maxDur <= 0) maxDur = 1;

  const barMaxW = Math.min(40, (W - 80) / segs.length);
  const gap = Math.max(4, (W - 80 - barMaxW * segs.length) / (segs.length + 1));
  const chartBottom = H - 28;
  const chartTop = 20;

  segs.forEach((seg, i) => {
    const x = 40 + gap + i * (barMaxW + gap);
    const barH = ((chartBottom - chartTop) * (durations[i] / maxDur));
    const y = chartBottom - barH;

    ctx.fillStyle = colors.primary;
    ctx.fillRect(x, y, barMaxW, barH);

    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barMaxW / 2, chartBottom + 14);

    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(durations[i].toFixed(1) + "s", x + barMaxW / 2, y - 4);
  });

  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(35, chartBottom);
  ctx.lineTo(W - 10, chartBottom);
  ctx.stroke();
}

export function drawReviewPieChart(canvas, counts) {
  if (!canvas) return;
  const size = 180;
  const ctx = setupHiDPI(canvas, size, size);
  const colors = getCanvasColors();
  const cx = size / 2, cy = size / 2, radius = Math.min(cx, cy) - 16;
  const total = counts.pass + counts.needs_review + counts.reject + counts.unset;

  if (total === 0) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("暂无审核数据", cx, cy);
    return;
  }

  const slices = [
    { value: counts.pass, color: colors.success },
    { value: counts.needs_review, color: colors.warning },
    { value: counts.reject, color: colors.danger },
    { value: counts.unset, color: colors.textFaint },
  ];

  let angle = -Math.PI / 2;
  slices.forEach((slice) => {
    if (slice.value <= 0) return;
    const sliceAngle = (slice.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angle, angle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = slice.color;
    ctx.fill();
    angle += sliceAngle;
  });

  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = colors.bg;
  ctx.fill();

  ctx.fillStyle = colors.textMuted;
  ctx.font = "bold 14px " + getComputedStyle(document.body).fontFamily;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(total), cx, cy);
}

// ── trajectory ────────────────────────────────────────────────────────

export function renderTrajectoryPanel() {
  const panel = byId("trajectory-panel");
  if (!panel) return;

  const hasTrajectory = editorState.keyframes.some((kf) =>
    Array.isArray(kf.trajectory) && kf.trajectory.length > 0
  );

  panel.hidden = false;
  const placeholder = byId("trajectory-placeholder");
  const canvas = byId("trajectory-canvas");

  if (!hasTrajectory) {
    if (placeholder) placeholder.hidden = false;
    if (canvas) canvas.hidden = true;
    return;
  }

  if (placeholder) placeholder.hidden = true;
  if (canvas) {
    canvas.hidden = false;
    drawTrajectory(canvas);
  }
}

export function drawTrajectory(canvas) {
  if (!canvas) return;
  const W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 500;
  const H = 280;
  const ctx = setupHiDPI(canvas, W, H);
  const colors = getCanvasColors();

  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, W, H);

  const allBoxes = [];
  editorState.keyframes.forEach((kf) => {
    const traj = kf.trajectory;
    if (!Array.isArray(traj)) return;
    traj.forEach((box) => {
      allBoxes.push({
        trackId: box.track_id || 0,
        x: Number(box.x) || 0,
        y: Number(box.y) || 0,
        w: Number(box.w) || 0,
        h: Number(box.h) || 0,
        timestamp: Number(kf.timestamp) || 0,
      });
    });
  });

  if (!allBoxes.length) return;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  allBoxes.forEach((b) => {
    if (b.x < minX) minX = b.x;
    if (b.y < minY) minY = b.y;
    if (b.x + b.w > maxX) maxX = b.x + b.w;
    if (b.y + b.h > maxY) maxY = b.y + b.h;
  });

  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const margin = 20;
  const scaleX = (W - margin * 2) / rangeX;
  const scaleY = (H - margin * 2) / rangeY;
  const sc = Math.min(scaleX, scaleY);

  const tracks = {};
  allBoxes.forEach((b) => {
    const key = String(b.trackId);
    if (!tracks[key]) tracks[key] = [];
    tracks[key].push(b);
  });

  const trackColors = [colors.accent, colors.primary, colors.success, colors.warning];
  let trackIdx = 0;
  Object.keys(tracks).forEach((key) => {
    const boxes = tracks[key];
    const color = trackColors[trackIdx % trackColors.length];
    trackIdx++;

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
      const rw = b.w * sc;
      const rh = b.h * sc;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(rx, ry, rw, rh);
      ctx.globalAlpha = 1;
    });
  });
}
