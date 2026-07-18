/**
 * ReelFire frontend logic
 */
let STATE = { currentJobId: null, currentJobData: null, currentSegments: [], currentKeyframes: [], pollTimer: null };
const API = {
  async get(url) { const r = await fetch(url); return r.json(); },
  async post(url, body) {
    const isForm = body instanceof FormData;
    const r = await fetch(url, {
      method: 'POST',
      headers: isForm ? {} : { 'Content-Type': 'application/json' },
      body: isForm ? body : JSON.stringify(body || {})
    });
    return r.json();
  },
  async patch(url, body) {
    const r = await fetch(url, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
  },
  async del(url) { const r = await fetch(url, { method: 'DELETE' }); return r.json(); }
};
function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>'"]/g, function(character) {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[character];
  });
}
function findByDataId(container, selector, key, value) {
  return Array.from(container.querySelectorAll(selector)).find(function(element) {
    return element.dataset[key] === String(value);
  }) || null;
}
function switchView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.header-nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  const nb = document.getElementById('nav-' + view);
  if (nb) nb.classList.add('active');
  if (view === 'task-list') loadTaskList();
  if (view === 'new-task') { stopPolling(); STATE.currentJobId = null; }
}
function showToast(msg, type) {
  type = type || 'info';
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(function() { t.style.opacity = '0'; setTimeout(function() { t.remove(); }, 300); }, 3500);
}
document.addEventListener('DOMContentLoaded', function() {
  var zone = document.getElementById('upload-zone');
  var inp = document.getElementById('video-file');
  if (!zone || !inp) return;
  zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', function() { zone.classList.remove('dragover'); });
  zone.addEventListener('drop', function(e) {
    e.preventDefault(); zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; showFileInfo(e.dataTransfer.files[0]); }
  });
  inp.addEventListener('change', function() { if (inp.files.length) showFileInfo(inp.files[0]); });
});
function showFileInfo(f) {
  var info = document.getElementById('file-info');
  var sz = f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : (f.size / 1024).toFixed(1) + ' KB';
  info.style.display = 'inline-flex';
  info.innerHTML = '<span class="file-name">' + escapeHtml(f.name) + '</span> ' + escapeHtml(sz);
}
function resetUpload() { document.getElementById('upload-form').reset(); document.getElementById('file-info').style.display = 'none'; }
async function createJob(e) {
  e.preventDefault();
  var btn = document.getElementById('btn-create');
  btn.disabled = true; btn.textContent = '上传中...';
  try {
    var fi = document.getElementById('video-file');
    if (!fi.files.length) { showToast('请选择一个视频文件', 'error'); btn.disabled = false; btn.textContent = '创建任务并上传'; return; }
    var fd = new FormData();
    fd.append('file', fi.files[0]);
    fd.append('project_name', document.getElementById('project-name').value || '击杀集锦提取');
    fd.append('game_type', document.getElementById('game-type').value);
    fd.append('sample_interval', document.getElementById('sample-interval').value);
    fd.append('target_duration', document.getElementById('target-duration').value);
    fd.append('output_ratio', document.getElementById('output-aspect').value);
    var data = await API.post('/api/jobs', fd);
    if (data.ok) {
      STATE.currentJobId = data.job_id;
      var queued = await API.post('/api/jobs/' + data.job_id + '/analyze', {});
      if (!queued.ok) throw new Error(queued.error || '任务已创建，但提交分析失败');
      showToast('任务创建成功，已进入分析队列！', 'success');
      switchView('task-list');
    }
    else { showToast(data.error || '创建任务失败', 'error'); }
  } catch (_) { showToast('网络错误，请重试', 'error'); }
  finally { btn.disabled = false; btn.textContent = '创建任务并上传'; }
}
async function loadTaskList() {
  document.getElementById('task-list-loading').style.display = 'flex';
  document.getElementById('task-list-empty').style.display = 'none';
  document.getElementById('task-list-error').style.display = 'none';
  document.getElementById('task-list-table').style.display = 'none';
  try {
    var data = await API.get('/api/jobs');
    if (!data.ok) throw new Error(data.error || '请求失败');
    var jobs = data.jobs || [];
    if (!jobs.length) { document.getElementById('task-list-loading').style.display = 'none'; document.getElementById('task-list-empty').style.display = 'flex'; return; }
    document.getElementById('task-list-loading').style.display = 'none';
    document.getElementById('task-list-table').style.display = 'block';
    var tb = document.getElementById('task-list-body');
    tb.innerHTML = '';
    jobs.sort(function(a, b) { return (b.created_at || '').localeCompare(a.created_at || ''); });
    var st = { created: '已创建', queued: '排队中', running: '分析中', completed: '已完成', failed: '失败' };
    var gn = { csgo: 'CS:GO/CS2', valorant: '无畏契约', other: '其他 FPS' };
    jobs.forEach(function(j) {
      var tr = document.createElement('tr');
      var jobId = String(j.job_id || '');
      var status = Object.prototype.hasOwnProperty.call(st, j.status) ? j.status : 'created';
      var gameName = gn[j.game_type] || j.game_type || '-';
      var isBusy = status === 'running' || status === 'queued';
      tr.innerHTML = '<td><span class="job-id">' + escapeHtml(jobId || '-') + '</span></td>' +
        '<td>' + escapeHtml(j.project_name || '-') + '</td>' +
        '<td class="truncate" style="max-width:150px">' + escapeHtml(j.asset_name || '-') + '</td>' +
        '<td>' + escapeHtml(gameName) + '</td>' +
        '<td><span class="status-badge ' + status + '"><span class="dot"></span>' + escapeHtml(st[status]) + '</span></td>' +
        '<td class="text-sm">' + escapeHtml(formatTime(j.created_at)) + '</td>' +
        '<td class="actions"><button class="btn btn-ghost btn-sm" data-action="open">查看</button>' +
        '<button class="btn btn-ghost btn-sm" data-action="delete"' + (isBusy ? ' disabled title="运行中不可删除"' : '') + '>删除</button></td>';
      tr.querySelector('[data-action="open"]').addEventListener('click', function() { openTask(jobId); });
      tr.querySelector('[data-action="delete"]').addEventListener('click', function() { deleteTask(jobId); });
      tb.appendChild(tr);
    });
  } catch (err) {
    document.getElementById('task-list-loading').style.display = 'none';
    document.getElementById('task-list-error').style.display = 'flex';
    document.getElementById('task-list-error-msg').textContent = err.message || '无法连接服务器';
  }
}
async function openTask(jobId) {
  STATE.currentJobId = jobId; STATE.currentJobData = null;
  switchView('task-detail');
  document.getElementById('detail-loading').style.display = 'flex';
  document.getElementById('detail-content').style.display = 'none';
  document.getElementById('detail-actions').style.display = 'none';
  document.getElementById('detail-title').textContent = '任务详情';
  stopPolling(); await refreshTaskDetail();
}
async function refreshTaskDetail() {
  if (!STATE.currentJobId) return;
  try {
    var data = await API.get('/api/jobs/' + STATE.currentJobId);
    if (!data.ok) throw new Error(data.error || '请求失败');
    var job = data.job || data;
    STATE.currentJobData = job;
    document.getElementById('detail-loading').style.display = 'none';
    document.getElementById('detail-content').style.display = 'block';
    document.getElementById('detail-actions').style.display = 'flex';
    document.getElementById('detail-title').textContent = job.project_name || '任务详情';
    renderVideoInfo(job);
    var st = job.status || 'created';
    ['detail-running','detail-queued','detail-failed','detail-completed'].forEach(function(id) { document.getElementById(id).style.display = 'none'; });
    if (st === 'queued') { document.getElementById('detail-queued').style.display = 'block'; startPolling(); }
    else if (st === 'running') { document.getElementById('detail-running').style.display = 'block'; startPolling(); }
    else if (st === 'failed') { document.getElementById('detail-failed').style.display = 'block'; document.getElementById('detail-error-msg').textContent = job.error || '未知错误'; }
    else if (st === 'completed') { document.getElementById('detail-completed').style.display = 'block'; await loadAnalysisReport(); }
  } catch (err) {
    document.getElementById('detail-loading').style.display = 'none';
    document.getElementById('detail-content').style.display = 'block';
    showToast('加载失败: ' + err.message, 'error');
  }
}
function startPolling() {
  stopPolling();
  STATE.pollTimer = setInterval(async function() {
    try {
      var data = await API.get('/api/jobs/' + STATE.currentJobId);
      if (data.ok) {
        var job = data.job || data;
        if (job.status === 'completed' || job.status === 'failed') { stopPolling(); await refreshTaskDetail(); }
        else {
          var pf = document.getElementById('detail-progress');
          if (pf) pf.style.width = '60%';
        }
      }
    } catch(e) {}
  }, 2000);
}
function stopPolling() { if (STATE.pollTimer) { clearInterval(STATE.pollTimer); STATE.pollTimer = null; } }
function renderVideoInfo(data) {
  var bar = document.getElementById('detail-video-info');
  var gn = { csgo: 'CS:GO/CS2', valorant: '无畏契约', other: '其他 FPS' };
  var st = { created: '已创建', queued: '排队中', running: '分析中', completed: '已完成', failed: '失败' };
  var status = Object.prototype.hasOwnProperty.call(st, data.status) ? data.status : 'created';
  bar.innerHTML = '<div class="info-item"><span class="info-label">素材</span><span class="info-value">' + escapeHtml(data.asset_name || '-') + '</span></div>' +
    '<div class="info-item"><span class="info-label">游戏</span><span class="info-value">' + escapeHtml(gn[data.game_type] || data.game_type || '-') + '</span></div>' +
    '<div class="info-item"><span class="info-label">状态</span><span class="status-badge ' + status + '"><span class="dot"></span>' + escapeHtml(st[status]) + '</span></div>' +
    '<div class="info-item"><span class="info-label">创建时间</span><span class="info-value">' + escapeHtml(formatTime(data.created_at)) + '</span></div>';
}
async function loadAnalysisReport() {
  try {
    var data = await API.get('/api/jobs/' + STATE.currentJobId + '/report');
    if (!data.ok) throw new Error(data.error || '无法加载报告');
    renderAnalysisResults(data.report || data);
  } catch (err) {
    document.getElementById('detail-keyframes').innerHTML = '<div class="state-container" style="padding:32px"><div class="state-title">' + escapeHtml(err.message) + '</div></div>';
  }
}
function renderAnalysisResults(r) {
  renderScoreBars(r);
  var w = r.score_weights || { object: 0.45, scene_change: 0.35, motion: 0.20 };
  document.getElementById('detail-weights-info').textContent = '权重：目标 ' + (w.object * 100).toFixed(0) + '% · 场景变化 ' + (w.scene_change * 100).toFixed(0) + '% · 运动 ' + (w.motion * 100).toFixed(0) + '%';
  renderSegments(r);
  STATE.currentKeyframes = r.keyframes || [];
  renderKeyframes(STATE.currentKeyframes);
  renderOutput(r);
}
function renderScoreBars(r) {
  var kfs = r.keyframes || [];
  var best = kfs.concat().sort(function(a, b) { return (b.highlight_score || 0) - (a.highlight_score || 0); })[0] || {};
  var c = document.getElementById('detail-score-bars');
  c.innerHTML = '<div class="score-bar-item object"><div class="sb-label">目标分数</div><div class="sb-value">' + fmtScore(best.object_score) + '</div><div class="sb-track"><div class="sb-fill" style="width:' + ((best.object_score || 0) * 100) + '%"></div></div></div>' +
    '<div class="score-bar-item scene"><div class="sb-label">场景变化</div><div class="sb-value">' + fmtScore(best.scene_change_score) + '</div><div class="sb-track"><div class="sb-fill" style="width:' + ((best.scene_change_score || 0) * 100) + '%"></div></div></div>' +
    '<div class="score-bar-item motion"><div class="sb-label">运动强度</div><div class="sb-value">' + fmtScore(best.motion_score) + '</div><div class="sb-track"><div class="sb-fill" style="width:' + ((best.motion_score || 0) * 100) + '%"></div></div></div>' +
    '<div class="score-bar-item composite"><div class="sb-label">综合分数</div><div class="sb-value">' + fmtScore(best.highlight_score) + '</div><div class="sb-track"><div class="sb-fill" style="width:' + ((best.highlight_score || 0) * 100) + '%"></div></div></div>';
}
function fmtScore(v) { return (v || 0).toFixed(3); }
function renderSegments(r) {
  var segs = r.segments || [];
  STATE.currentSegments = segs;
  var ed = document.getElementById('detail-segment-editor');
  document.getElementById('detail-seg-info').textContent = segs.length ? segs.length + ' 个片段' : '暂无候选片段';
  if (!segs.length) { ed.innerHTML = '<div class="text-sm text-muted">暂无候选片段</div>'; return; }
  ed.innerHTML = segs.map(function(seg, i) {
    var segmentId = escapeHtml(seg.id || ('seg_' + (i + 1)));
    return '<div class="segment-editor" data-seg-id="' + segmentId + '"><div class="seg-header"><h4>片段 #' + (i + 1) + '</h4><span class="text-sm text-muted">时长 ' + ((seg.end || 0) - (seg.start || 0)).toFixed(1) + 's</span></div>' +
      '<div class="seg-row"><div class="input-group"><label>开始 (秒)</label><input type="number" class="seg-start" value="' + escapeHtml(seg.start || 0) + '" min="0" step="0.5" data-seg-id="' + segmentId + '"></div>' +
      '<div class="input-group"><label>结束 (秒)</label><input type="number" class="seg-end" value="' + escapeHtml(seg.end || 0) + '" min="0" step="0.5" data-seg-id="' + segmentId + '"></div>' +
      '<div class="input-group" style="flex:0 0 auto"><label>排序</label><input type="number" class="seg-order" value="' + escapeHtml(seg.order || i + 1) + '" min="1" style="width:60px" data-seg-id="' + segmentId + '"></div></div></div>';
  }).join('');
  ed.querySelectorAll('.seg-start, .seg-end').forEach(function(inp) {
    inp.addEventListener('change', function() {
      var id = this.dataset.segId;
      var seg = STATE.currentSegments.find(function(s) { return s.id === id; });
      if (!seg) return;
      var startInput = findByDataId(ed, '.seg-start', 'segId', id);
      var endInput = findByDataId(ed, '.seg-end', 'segId', id);
      var st = parseFloat(startInput ? startInput.value : '0') || 0;
      var en = parseFloat(endInput ? endInput.value : '0') || 0;
      var p = this.closest('.segment-editor');
      if (st >= en) { p.style.borderColor = 'var(--danger)'; }
      else { p.style.borderColor = ''; p.querySelector('.seg-header .text-sm').textContent = '时长 ' + (en - st).toFixed(1) + 's'; }
    });
  });
}
function renderKeyframes(kfs) {
  var c = document.getElementById('detail-keyframes');
  if (!kfs.length) { c.innerHTML = '<div class="state-container" style="padding:24px"><div class="state-title">暂无关键帧</div></div>'; return; }
  var sorted = kfs.concat().sort(function(a, b) { return (a.order || 999) - (b.order || 999); });
  var labels = ['', 'multi_kill', 'clutch', 'entry', 'objective', 'other'];
  var ln = { '': '无标签', multi_kill: '多杀', clutch: '残局', entry: '突破', objective: '目标', other: '其他' };
  c.innerHTML = sorted.map(function(kf) {
    var sc = kf.highlight_score || 0;
    var scClass = sc >= 0.7 ? 'high' : sc >= 0.4 ? 'medium' : 'low';
    var dec = kf.decision || 'keep';
    var keyframeId = String(kf.id || '');
    var safeKeyframeId = escapeHtml(keyframeId);
    var imgSrc = kf.image ? '/outputs/' + STATE.currentJobId + '/' + kf.image : '';
    var imgTag = imgSrc ? '<img src="' + escapeHtml(imgSrc) + '" alt="关键帧">' : '<div style="width:100%;height:100%;background:var(--border-color);display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:12px">关键帧 ' + safeKeyframeId + '</div>';
    return '<div class="keyframe-card" data-kf-id="' + safeKeyframeId + '"><div class="kf-thumb">' + imgTag +
      '<span class="kf-timestamp">' + fmtTime(kf.timestamp) + '</span>' +
      '<span class="kf-score-badge ' + scClass + '">' + (sc * 100).toFixed(0) + '</span></div>' +
      '<div class="kf-body"><div class="kf-scores">' +
      '<span class="score-item"><span class="score-label">目标</span> <span class="score-val">' + fmtScore(kf.object_score) + '</span></span>' +
      '<span class="score-item"><span class="score-label">场景</span> <span class="score-val">' + fmtScore(kf.scene_change_score) + '</span></span>' +
      '<span class="score-item"><span class="score-label">运动</span> <span class="score-val">' + fmtScore(kf.motion_score) + '</span></span>' +
      '<span class="score-item"><span class="score-label">综合</span> <span class="score-val">' + fmtScore(sc) + '</span></span>' +
      (kf.object_count ? '<span class="score-item"><span class="score-label">目标数</span> <span class="score-val">' + kf.object_count + '</span></span>' : '') + '</div>' +
      '<div class="kf-controls"><div class="kf-decision">' +
      '<button class="' + (dec === 'keep' ? 'active-keep' : '') + '" data-decision="keep">保留</button>' +
      '<button class="' + (dec === 'skip' ? 'active-skip' : '') + '" data-decision="skip">忽略</button></div>' +
      '<select class="kf-label-select">' +
      labels.map(function(l) { return '<option value="' + l + '" ' + ((kf.label || '') === l ? 'selected' : '') + '>' + ln[l] + '</option>'; }).join('') + '</select>' +
      '<input type="number" class="kf-order" value="' + escapeHtml(kf.order || sorted.indexOf(kf) + 1) + '" min="1" style="width:52px">' +
      '<input type="text" class="kf-note" placeholder="备注..." value="' + escapeHtml(kf.note || '') + '"></div></div></div>';
  }).join('');
  c.querySelectorAll('.keyframe-card').forEach(function(card) {
    var keyframeId = card.dataset.kfId;
    card.querySelectorAll('[data-decision]').forEach(function(button) {
      button.addEventListener('click', function() { setDecision(keyframeId, button.dataset.decision); });
    });
    card.querySelector('.kf-label-select').addEventListener('change', function() { setLabel(keyframeId, this.value); });
    card.querySelector('.kf-order').addEventListener('change', function() { setOrder(keyframeId, this.value); });
    card.querySelector('.kf-note').addEventListener('change', function() { setNote(keyframeId, this.value); });
    var image = card.querySelector('img');
    if (image) image.addEventListener('error', function() { image.style.display = 'none'; });
  });
  updateKfCounts(kfs);
}
function updateKfCounts(kfs) {
  var total = kfs.length;
  var kept = kfs.filter(function(k) { return (k.decision || 'keep') === 'keep'; }).length;
  document.getElementById('kf-keep-count').textContent = '保留 ' + kept;
  document.getElementById('kf-skip-count').textContent = '忽略 ' + (total - kept);
}
function setDecision(id, d) {
  var kf = STATE.currentKeyframes.find(function(k) { return k.id === id; });
  if (!kf) return;
  kf.decision = d;
  var card = findByDataId(document, '.keyframe-card', 'kfId', id);
  if (card) {
    card.querySelectorAll('.kf-decision button').forEach(function(b) { b.className = ''; });
    var btns = card.querySelectorAll('.kf-decision button');
    btns[0].className = d === 'keep' ? 'active-keep' : '';
    btns[1].className = d === 'skip' ? 'active-skip' : '';
  }
  updateKfCounts(STATE.currentKeyframes);
}
function setLabel(id, l) { var kf = STATE.currentKeyframes.find(function(k) { return k.id === id; }); if (kf) kf.label = l; }
function setOrder(id, o) { var kf = STATE.currentKeyframes.find(function(k) { return k.id === id; }); if (kf) kf.order = parseInt(o) || 1; }
function setNote(id, n) { var kf = STATE.currentKeyframes.find(function(k) { return k.id === id; }); if (kf) kf.note = n; }
async function saveReview() {
  var btn = document.getElementById('btn-save-review');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    var keyframes = STATE.currentKeyframes.map(function(kf) {
      return Object.assign({}, kf, {
        decision: kf.decision || 'keep',
        label: kf.label || '',
        note: kf.note || '',
        order: kf.order || 1
      });
    });
    var segments = STATE.currentSegments.map(function(seg) {
      var editor = document.getElementById('detail-segment-editor');
      var si = findByDataId(editor, '.seg-start', 'segId', seg.id);
      var ei = findByDataId(editor, '.seg-end', 'segId', seg.id);
      var oi = findByDataId(editor, '.seg-order', 'segId', seg.id);
      return { id: seg.id, start: si ? parseFloat(si.value) : seg.start, end: ei ? parseFloat(ei.value) : seg.end, order: oi ? parseInt(oi.value) : (seg.order || 1) };
    });
    var data = await API.patch('/api/jobs/' + STATE.currentJobId + '/review', { keyframes: keyframes, segments: segments });
    if (data.ok) showToast('审核结果已保存', 'success');
    else showToast(data.error || '保存失败', 'error');
  } catch (err) { showToast('保存失败: ' + err.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '保存审核结果'; }
}
async function generateRoughCut() {
  var btn = document.getElementById('btn-rough-cut');
  btn.disabled = true; btn.textContent = '生成中...';
  try {
    var data = await API.post('/api/jobs/' + STATE.currentJobId + '/rough-cut', {});
    if (data.ok) { showToast('粗剪视频生成完成！', 'success'); await loadAnalysisReport(); }
    else showToast(data.error || '生成失败', 'error');
  } catch (err) { showToast('生成失败: ' + err.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '生成粗剪视频'; }
}
function renderOutput(r) {
  var c = document.getElementById('detail-output');
  var o = r.output || {};
  if (!o.video) { c.style.display = 'none'; return; }
  c.style.display = 'grid';
  c.innerHTML = '<div class="output-card"><div class="output-label">输出视频 ' + escapeHtml(o.ratio || '') + '</div><video controls preload="metadata"><source src="' + escapeHtml('/outputs/' + STATE.currentJobId + '/' + o.video) + '" type="video/mp4"></video></div>';
  if (o.contact_sheet) {
    c.innerHTML += '<div class="output-card"><div class="output-label">关键帧联系表</div><a href="' + escapeHtml('/outputs/' + STATE.currentJobId + '/' + o.contact_sheet) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-sm mt-8">查看联系表</a></div>';
  }
}
async function viewReport() {
  try {
    var data = await API.get('/api/jobs/' + STATE.currentJobId + '/report');
    document.getElementById('report-content').textContent = JSON.stringify(data.report || data, null, 2);
    document.getElementById('report-modal').style.display = 'flex';
  } catch (err) { showToast('无法加载报告: ' + err.message, 'error'); }
}
function closeReport() { document.getElementById('report-modal').style.display = 'none'; }
async function deleteTask(jobId) {
  if (!confirm('确定要删除这个任务吗？')) return;
  try {
    var data = await API.del('/api/jobs/' + jobId);
    if (data.ok) { showToast('任务已删除', 'info'); if (STATE.currentJobId === jobId) { STATE.currentJobId = null; switchView('task-list'); } else loadTaskList(); }
    else showToast(data.error || '删除失败', 'error');
  } catch (err) { showToast('删除失败: ' + err.message, 'error'); }
}
async function deleteCurrentJob() { if (STATE.currentJobId) await deleteTask(STATE.currentJobId); }
function formatTime(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch(e) { return iso; }
}
function fmtTime(s) {
  if (s == null) return '-';
  var m = Math.floor(s / 60); var sec = (s % 60).toFixed(1);
  return m + ':' + sec.toString().padStart(4, '0');
}
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeReport(); });
