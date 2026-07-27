// ReelFire — review saving & rough cut creation
import { appState } from "../state/app-state.js";
import api from "../api/client.js";
import { byId } from "../utils/dom.js";
import { showToast, setButtonLoading } from "../utils/ui.js";
import { renderReport, loadReport, logTool } from "./analysis.js";

export function collectReview() {
  return [...document.querySelectorAll(".keyframe-card")].map((card) => {
    const index = Number(card.dataset.frameIndex);
    const frame = { ...appState.keyframes[index] };
    frame.decision = card.querySelector(".review-decision").value;
    frame.keep = frame.decision === "keep";
    frame.note = card.querySelector(".review-note").value.trim();
    return frame;
  });
}

export async function saveReview() {
  if (!appState.currentJobId || !appState.report) return;
  const button = byId("save-review-button");
  setButtonLoading(button, true, "保存中…");
  try {
    const keyframes = collectReview();
    logTool("PATCH", `/api/jobs/${appState.currentJobId}/review`, "保存人工审核决策");
    const payload = await api.patch(
      `/api/jobs/${encodeURIComponent(appState.currentJobId)}/review`,
      { keyframes, segments: appState.segments },
    );
    renderReport(payload.report);
    showToast("审核结果已保存", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

export async function createRoughCut() {
  if (!appState.currentJobId || !appState.report) return;
  const button = byId("rough-cut-button");
  setButtonLoading(button, true, "生成中…");
  try {
    await saveReview();
    logTool("POST", `/api/jobs/${appState.currentJobId}/rough-cut`, "调用 FFmpeg 生成粗剪");
    const resp = await api.post(`/api/jobs/${encodeURIComponent(appState.currentJobId)}/rough-cut`, {});

    // If backend returns async render task, poll for completion
    if (resp.render_task_id) {
      setButtonLoading(button, true, "排队中…");
      await pollRenderTask(resp.render_task_id);
    }

    await loadReport(appState.currentJobId);
    showToast("粗剪视频已生成", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

// Poll for async render task (ready for backend async export)
async function pollRenderTask(taskId) {
  const button = byId("rough-cut-button");
  for (let i = 0; i < 120; i++) {
    try {
      const resp = await api.get(`/api/render/${encodeURIComponent(taskId)}`);
      if (resp.status === "completed") {
        return;
      }
      if (resp.status === "failed") {
        throw new Error(resp.error || "导出失败");
      }
      const stages = { queued: "排队中…", transcoding: "转码中…", merging: "拼接中…", writing: "写入中…" };
      setButtonLoading(button, true, stages[resp.status] || "处理中…");
    } catch (e) {
      // If render endpoint doesn't exist yet (404), break and assume sync
      if (e.status === 404) break;
      throw e;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}
