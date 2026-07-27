// ReelFire — workbench page state (mutable singleton)
export const appState = {
  currentJobId: null,
  currentJob: null,
  currentProjectId: null,
  currentProjectName: null,
  currentProject: null,
  currentProjectJobs: [],
  report: null,
  keyframes: [],
  segments: [],
  analysisChunks: [],
  activeKeyframeChunkId: null,
  keyframeReviewMode: "segment",
  selectedFile: null,
  previewUrl: null,
  pollTimer: null,
  agentPollTimer: null,
  agentCallId: null,
  toolCalls: [],
};

export const statusLabels = {
  created: "已创建",
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
};
