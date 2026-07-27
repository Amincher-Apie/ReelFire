// ReelFire — editor save, rough cut, export, report dialog + P2 auto-save
import { editorState } from "../state/editor-state.js";
import api from "../api/client.js";
import { byId } from "../utils/dom.js";
import { showToast, setButtonLoading } from "../utils/ui.js";

// ── P2: auto-save draft ───────────────────────────────────────────────

let autoSaveTimer = null;

function draftKey() {
  return "reelfire:draft:" + (editorState.jobId || "unknown");
}

export function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    const draft = {
      reviews: editorState.reviews,
      segments: editorState.segments.map((s) => ({ ...s })),
      savedAt: Date.now(),
    };
    try {
      localStorage.setItem(draftKey(), JSON.stringify(draft));
    } catch {
      // localStorage full or unavailable — silently skip
    }
  }, 2000);
}

export function checkDraft() {
  try {
    const raw = localStorage.getItem(draftKey());
    if (!raw) return;
    const draft = JSON.parse(raw);
    if (!draft || !draft.savedAt || !draft.reviews) return;

    // Check if draft has any actual review data
    const hasReviews = Object.values(draft.reviews).some(
      (r) => r && (r.recommendation || r.note)
    );
    const hasSegmentChanges = draft.segments && draft.segments.some((s, i) => {
      const cur = editorState.segments[i];
      return cur && (s.start !== cur.start || s.end !== cur.end || s.order !== cur.order);
    });

    if (!hasReviews && !hasSegmentChanges) {
      localStorage.removeItem(draftKey());
      return;
    }

    // Show recovery dialog
    const recover = window.confirm(
      "检测到未保存的审核草稿（" +
      new Date(draft.savedAt).toLocaleString("zh-CN") +
      "），是否恢复？\n\n选择"确定"恢复草稿，"取消"放弃草稿并使用服务端数据。"
    );

    if (recover) {
      editorState.reviews = draft.reviews || {};
      if (draft.segments) {
        // Merge segment boundaries from draft
        draft.segments.forEach((ds) => {
          const seg = editorState.segments.find((s) => s.id === ds.id);
          if (seg) {
            seg.start = ds.start;
            seg.end = ds.end;
            seg.order = ds.order;
          }
        });
      }
      editorState.dirty = true;
      // Re-render will be called by applyEditorData caller
      showToast("已恢复审核草稿", "info");
    }

    localStorage.removeItem(draftKey());
  } catch {
    // corrupted draft — silently clear
    try { localStorage.removeItem(draftKey()); } catch { /* ignore */ }
  }
}

export function clearDraft() {
  try { localStorage.removeItem(draftKey()); } catch { /* ignore */ }
}

// ── export ────────────────────────────────────────────────────────────

export function exportReview() {
  const exportData = {
    job_id: editorState.jobId,
    exported_at: new Date().toISOString(),
    segments: editorState.segments.map((seg) => {
      const review = editorState.reviews[seg.id] || {};
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
        review: review.recommendation || null,
        review_note: review.note || null,
      };
    }),
  };
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "review_" + editorState.jobId + ".json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("审核数据已导出", "success");
}

export function showReportDialog() {
  byId("report-content").textContent = JSON.stringify(
    {
      job_id: editorState.jobId,
      video: editorState.video,
      segments: editorState.segments,
      agent_comments: editorState.agentComments,
      keyframes: editorState.keyframes,
    },
    null,
    2
  );
  byId("report-dialog").showModal();
}

// ── save review ───────────────────────────────────────────────────────

export function saveReview() {
  if (!editorState.jobId || !editorState.segments.length) return;
  const button = byId("save-review-button");
  setButtonLoading(button, true, "保存中…");
  const body = {
    status: "pending",
    segments: editorState.segments.map((seg) => {
      const rev = editorState.reviews[seg.id] || {};
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        order: seg.order,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
        review: rev.recommendation || "",
        review_note: rev.note || "",
      };
    }),
  };
  api.patch("/api/jobs/" + encodeURIComponent(editorState.jobId) + "/review", body).then(
    () => {
      editorState.dirty = false;
      // update dirty indicator
      const btn = byId("save-review-button");
      if (btn) {
        const original = btn.dataset.originalLabel || "保存审核";
        btn.textContent = original;
      }
      clearDraft();
      showToast("审核结果已保存", "success");
      setButtonLoading(button, false);

      // reload data to get fresh server state
      import("./editor-segments.js").then((m) => m.loadEditorData(editorState.jobId));
    },
    (error) => {
      showToast(error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// ── rough cut ─────────────────────────────────────────────────────────

export function createRoughCut() {
  if (!editorState.jobId) return;
  const button = byId("rough-cut-button");
  setButtonLoading(button, true, "生成中…");

  // save review first, then cut
  const reviewBody = {
    status: "approved",
    segments: editorState.segments.map((seg) => {
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        order: seg.order,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
      };
    }),
  };

  api.patch("/api/jobs/" + encodeURIComponent(editorState.jobId) + "/review", reviewBody).then(
    () => api.post("/api/jobs/" + encodeURIComponent(editorState.jobId) + "/rough-cut", {}),
    (error) => {
      showToast("审核保存失败：" + error.message + "，继续尝试生成粗剪…", "info");
      return api.post("/api/jobs/" + encodeURIComponent(editorState.jobId) + "/rough-cut", {});
    }
  ).then(
    (resp) => {
      // P0 async: if backend returns render task, poll
      if (resp && resp.render_task_id) {
        setButtonLoading(button, true, "排队中…");
        return pollEditorRenderTask(resp.render_task_id, button);
      }
    }
  ).then(
    () => {
      clearDraft();
      showToast("粗剪视频已生成", "success");
      setButtonLoading(button, false);
      import("./editor-segments.js").then((m) => m.loadEditorData(editorState.jobId));
    },
    (error) => {
      showToast(error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// Poll async render task (ready for backend async export)
async function pollEditorRenderTask(taskId, button) {
  for (let i = 0; i < 120; i++) {
    try {
      const resp = await api.get(`/api/render/${encodeURIComponent(taskId)}`);
      if (resp.status === "completed") return;
      if (resp.status === "failed") throw new Error(resp.error || "导出失败");
      const stages = { queued: "排队中…", transcoding: "转码中…", merging: "拼接中…", writing: "写入中…" };
      setButtonLoading(button, true, stages[resp.status] || "处理中…");
    } catch (e) {
      if (e.status === 404) break; // endpoint not yet available, assume sync
      throw e;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}
