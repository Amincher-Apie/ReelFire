// ReelFire — file upload handling
import { appState } from "../state/app-state.js";
import { byId, createElement } from "../utils/dom.js";
import { formatBytes } from "../utils/format.js";

export function clearSelectedFile() {
  appState.selectedFile = null;
  if (appState.previewUrl) URL.revokeObjectURL(appState.previewUrl);
  appState.previewUrl = null;
  byId("video-file").value = "";
  byId("preview-video").removeAttribute("src");
  byId("preview-video").load();
  byId("file-preview").hidden = true;
  byId("upload-zone").hidden = false;
  byId("file-error").textContent = "";
}

export function selectFile(file) {
  if (!file) {
    clearSelectedFile();
    return;
  }
  const allowedExtensions = /\.(mp4|mov|avi|mkv)$/i;
  if (!file.type.startsWith("video/") && !allowedExtensions.test(file.name)) {
    byId("file-error").textContent = "请选择 MP4、MOV、AVI 或 MKV 视频文件。";
    return;
  }
  if (file.size > 2 * 1024 * 1024 * 1024) {
    byId("file-error").textContent = "视频文件不能超过 2GB。";
    return;
  }
  if (appState.previewUrl) URL.revokeObjectURL(appState.previewUrl);
  appState.selectedFile = file;
  appState.previewUrl = URL.createObjectURL(file);
  byId("preview-video").src = appState.previewUrl;
  byId("video-filename").textContent = file.name;
  byId("video-filesize").textContent = formatBytes(file.size);
  byId("upload-zone").hidden = true;
  byId("file-preview").hidden = false;
  byId("file-error").textContent = "";
}

export function initUpload() {
  const input = byId("video-file");
  const zone = byId("upload-zone");
  input.addEventListener("change", () => selectFile(input.files[0]));
  byId("clear-file-button").addEventListener("click", clearSelectedFile);
  ["dragenter", "dragover"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
    });
  });
  zone.addEventListener("drop", (event) => {
    selectFile(event.dataTransfer.files[0]);
  });
}
