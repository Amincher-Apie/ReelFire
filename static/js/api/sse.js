// ReelFire — SSE client (ready for backend SSE endpoint)
// Usage: const es = connectSSE(jobId, { onSnapshot, onChunk, onCompleted, onError });
// When backend SSE endpoint is ready, call watchJobWithSSE() instead of pollJob().

export function connectSSE(jobId, handlers = {}) {
  const es = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);

  es.addEventListener("task.snapshot", (e) => {
    try { handlers.onSnapshot?.(JSON.parse(e.data)); } catch { /* ignore malformed */ }
  });

  es.addEventListener("chunk.completed", (e) => {
    try { handlers.onChunkCompleted?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });

  es.addEventListener("agent.progress", (e) => {
    try { handlers.onAgentProgress?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });

  es.addEventListener("render.progress", (e) => {
    try { handlers.onRenderProgress?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });

  es.addEventListener("task.completed", (e) => {
    try { handlers.onCompleted?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });

  es.addEventListener("task.failed", (e) => {
    try { handlers.onError?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });

  // Browser auto-reconnects on error; Last-Event-ID sent automatically
  es.onerror = () => {
    // EventSource will auto-reconnect after a delay
    // If connection stays dead, caller can close and fall back to polling
  };

  return es;
}

export function isSSESupported() {
  return typeof EventSource !== "undefined";
}
