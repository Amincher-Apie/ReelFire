// ReelFire — editor page state (mutable singleton)
export const editorState = {
  jobId: null,
  editorData: null,
  segments: [],
  agentComments: [],
  keyframes: [],
  video: null,
  selectedSegmentId: null,
  videoElement: null,
  timelineBound: false,
  dirty: false,
  reviews: {},       // { segmentId: { recommendation: "pass"|"needs_review"|"reject", note: "" } }
  output: null,      // { video, contact_sheet, ... }

  // P2: undo/redo stacks
  undoStack: [],
  redoStack: [],

  // Auto-save
  saveStatus: "saved",    // "saved" | "saving" | "error" | "unsaved"
  saveVersion: null,
  segmentThumbnails: {},   // {segmentId: thumbnailUrl}

  // Agent report (loaded independently via /report-data)
  agentReport: null,       // { availability, status, summary, tags, suggestions, review, evidence_refs, knowledge_refs }

  // Export
  exports: [],
  activeExportId: null,
  analysisPollTimer: null,
  agentPollTimer: null,
  agentCallId: null,
  agentCallStatus: null,
  agentStreamPollAttempts: 0,
};
