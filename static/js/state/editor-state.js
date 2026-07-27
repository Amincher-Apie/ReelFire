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

  // Export
  exports: [],
  activeExportId: null,
};
