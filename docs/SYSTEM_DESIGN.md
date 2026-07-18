# 系统设计（第一阶段）

## 分层

```text
浏览器 / API 调用方
        |
routes/api_routes.py       HTTP 校验与响应
        |
        +-- file_service.py       文件名、扩展名、空文件和保存
        +-- job_service.py        job.json、报告、目录、状态与删除
        +-- analysis_service.py   受控后台线程与 CV 接入口
        +-- ffmpeg_service.py     FFmpeg 就绪检查与粗剪接入口
        |
outputs/<job_id>/          本地文件系统持久化
```

`app.py` 只创建应用、初始化服务、注册蓝图与错误处理，并提供命令行启动参数。

## 任务持久化

任务编号严格匹配 `YYYYMMDD_HHMMSS_8位小写十六进制`。目录固定为：

```text
outputs/<job_id>/
├─ input/<安全文件名>
├─ keyframes/
├─ result/
└─ job.json
```

真实算法成功后增加 `analysis_report.json`；真实粗剪成功后在 `result/` 增加视频。写 JSON 时在同目录创建唯一临时文件，完成 `flush + fsync` 后使用 `os.replace` 原子替换。进程内还使用可重入锁，避免多个后台/请求线程交错写入。

## 状态与后台线程

```text
created -> queued -> running -> completed
                           \-> failed
failed  -> queued  （允许人工重试）
```

路由线程先原子地把任务更新为 `queued`，再提交给最大 1～2 个工作线程的 `ThreadPoolExecutor`。后台只接收 job_id、`Path` 和普通字典，不接收 Flask `request`。开始执行时写 `running/started_at`；算法返回真实报告后写 `completed/completed_at/result_file`；任何算法异常均写 `failed/completed_at/error`。

当前 `analyze_video(video_path, job_dir, settings)` 明确抛出 `NotImplementedError`，所以不会产生伪造结果。

## 重启恢复策略

本地线程不能跨进程恢复。应用启动时扫描合法任务目录，把遗留的 `queued` 或 `running` 任务标记为 `failed`，错误写为“服务重启导致后台分析任务中断，请重新发起分析”。绝不假装任务已完成。第一版不使用数据库、Redis、Celery 或跨进程队列。

## 安全边界

- job_id 同时通过正则和 `Path.resolve()` 的直接父目录检查；
- 上传扩展名在保存前校验，保存名来自 `secure_filename`；
- 删除只允许 `outputs` 的直接合法子目录，并拒绝忙碌任务；
- API 不返回系统绝对路径或 Python 堆栈；
- 损坏的任务 JSON 在列表中被跳过，详情/报告返回可读 JSON 错误；
- 模型就绪和 FFmpeg 就绪均实时检查，不写死为 `true`。

## 后续接入口

- CV：`services.analysis_service.analyze_video` 已返回可 JSON 序列化的真实报告字典，并输出带 YOLO 框关键帧；
- 算法增强：报告根据候选片段内的真实检测生成 `segment_tags`，并根据最高分关键帧生成不虚构事件的 `ai_cover_prompt`；
- FFmpeg：`services.ffmpeg_service.create_rough_cut` 已生成真实文件并返回 `Path`；
- 前端：轮询任务详情，完成后读取 `/report`，通过 `/review` 写回人工选择，再调用 `/rough-cut`。
