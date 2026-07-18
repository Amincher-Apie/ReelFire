# API 文档

## 1. 公共接口

### 1.1 健康检查

```
GET /api/health
```

**响应示例：**
```json
{
  "status": "ok",
  "model_ready": true
}
```

### 1.2 创建任务

```
POST /api/jobs
Content-Type: multipart/form-data
```

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| file | File | 是 | 视频文件 |
| project_name | String | 否 | 项目名称 |

**响应示例：**
```json
{
  "ok": true,
  "job_id": "20260717_101530_a1b2c3d4"
}
```

### 1.3 获取任务列表

```
GET /api/jobs
```

**响应示例：**
```json
{
  "ok": true,
  "jobs": [
    {
      "job_id": "20260717_101530_a1b2c3d4",
      "project_name": "游戏录屏",
      "asset_name": "game.mp4",
      "status": "completed",
      "created_at": "2026-07-17T10:15:30"
    }
  ]
}
```

### 1.4 获取单个任务

```
GET /api/jobs/{job_id}
```

**响应示例：**
```json
{
  "ok": true,
  "job": {
    "job_id": "20260717_101530_a1b2c3d4",
    "project_name": "游戏录屏",
    "asset_name": "game.mp4",
    "status": "completed",
    "created_at": "2026-07-17T10:15:30",
    "started_at": "2026-07-17T10:15:31",
    "completed_at": "2026-07-17T10:16:08",
    "settings": {},
    "result_file": "result/analysis_report.json",
    "error": null
  }
}
```

### 1.5 删除任务

```
DELETE /api/jobs/{job_id}
```

**响应示例：**
```json
{
  "ok": true
}
```

**错误响应：**
```json
{
  "ok": false,
  "error": "Cannot delete running job"
}
```

## 2. 方向 B 接口

### 2.1 分析任务

```
POST /api/jobs/{job_id}/analyze
```

**响应示例：**
```json
{
  "ok": true,
  "status": "running"
}
```

### 2.2 查看报告

```
GET /api/jobs/{job_id}/report
```

**响应示例：**
```json
{
  "ok": true,
  "report": {
    "job_id": "20260717_101530_a1b2c3d4",
    "total_frames": 90,
    "sample_interval": 2,
    "keyframes": [...],
    "top_keyframes": [...],
    "recommended_segments": [...],
    "scoring_weights": {...}
  }
}
```

### 2.3 生成粗剪视频

```
POST /api/jobs/{job_id}/rough-cut
```

**响应示例：**
```json
{
  "ok": true,
  "output_file": "result/rough_cut_20260717_101530_a1b2c3d4.mp4"
}
```

## 3. 错误响应格式

```json
{
  "ok": false,
  "error": "错误描述信息"
}
```

## 4. HTTP 状态码

| 状态码 | 说明 |
|---|---|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源未找到 |
| 500 | 服务器内部错误 |

## 5. 接口约束

- 成功响应包含 `ok: true`
- 失败响应包含 `ok: false` 和可读的 `error`
- 上传接口先返回任务编号，不阻塞等待完整推理
- 正在 `queued` 或 `running` 的任务不能直接删除
- 接口参数错误不能导致服务进程退出