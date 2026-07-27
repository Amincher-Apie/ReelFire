// ReelFire — URL helpers
export function outputUrl(jobId, relativePath) {
  const path = String(relativePath || "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/outputs/${encodeURIComponent(jobId)}/${path}`;
}
