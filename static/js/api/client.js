// ReelFire — API client
const api = {
  async request(url, options = {}) {
    const response = await fetch(url, options);
    let payload;
    try {
      payload = await response.json();
    } catch {
      const error = new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
      error.status = response.status;
      throw error;
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || `请求失败（HTTP ${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return payload;
  },

  get(url) {
    return this.request(url);
  },

  post(url, body) {
    const isForm = body instanceof FormData;
    return this.request(url, {
      method: "POST",
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      body: isForm ? body : JSON.stringify(body || {}),
    });
  },

  patch(url, body) {
    return this.request(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  delete(url) {
    return this.request(url, { method: "DELETE" });
  },

  postForm(url, formData) {
    return this.request(url, {
      method: "POST",
      body: formData,
    });
  },
};

export default api;
