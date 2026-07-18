const jobsElement = document.querySelector("#jobs");
const messageElement = document.querySelector("#message");
const form = document.querySelector("#upload-form");

function setMessage(message, isError = false) {
  messageElement.textContent = message;
  messageElement.className = isError ? "error" : "success";
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}

function actionButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = className;
  button.addEventListener("click", handler);
  return button;
}

function renderJobs(jobs) {
  jobsElement.replaceChildren();
  if (!jobs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "还没有任务。";
    jobsElement.append(empty);
    return;
  }
  jobs.forEach((job) => {
    const article = document.createElement("article");
    article.className = "job";
    const heading = document.createElement("div");
    heading.className = "job-heading";
    const title = document.createElement("h3");
    title.textContent = job.project_name;
    const status = document.createElement("span");
    status.className = `status ${job.status}`;
    status.textContent = job.status;
    heading.append(title, status);

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = `${job.job_id} · ${job.asset_name} · ${job.created_at}`;
    article.append(heading, meta);
    if (job.error) {
      const error = document.createElement("p");
      error.className = "error";
      error.textContent = job.error;
      article.append(error);
    }
    const actions = document.createElement("div");
    actions.className = "actions";
    if (!["queued", "running", "completed"].includes(job.status)) {
      actions.append(actionButton("启动分析", "", async () => {
        try {
          await api(`/api/jobs/${job.job_id}/analyze`, { method: "POST" });
          setMessage("分析任务已进入队列。当前阶段会明确失败，直到 CV 模块接入。")
          await loadJobs();
        } catch (error) { setMessage(error.message, true); }
      }));
    }
    if (!["queued", "running"].includes(job.status)) {
      actions.append(actionButton("删除", "delete", async () => {
        try {
          await api(`/api/jobs/${job.job_id}`, { method: "DELETE" });
          setMessage("任务已删除。")
          await loadJobs();
        } catch (error) { setMessage(error.message, true); }
      }));
    }
    article.append(actions);
    jobsElement.append(article);
  });
}

async function loadJobs() {
  try {
    const payload = await api("/api/jobs");
    renderJobs(payload.jobs);
  } catch (error) {
    jobsElement.textContent = error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const payload = await api("/api/jobs", { method: "POST", body: new FormData(form) });
    setMessage(`任务已创建：${payload.job_id}`);
    form.querySelector("input[type=file]").value = "";
    await loadJobs();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#refresh").addEventListener("click", loadJobs);
loadJobs();
