# Bug 记录 | BUG_RECORD

## 基本信息

| 项目 | 内容 |
|------|------|
| 项目名称 | ReelFire - 智能视频精彩片段提取系统 |
| 记录人 | ybbzzz |
| 记录日期 | 2026-07-18 |

---

## Bug 清单

### BUG-001

| 项目 | 内容 |
|------|------|
| 问题现象 | 上传层未校验文件内容魔数（Magic Number），将 PNG 图片改名 .mp4 后被接受并创建任务 |
| 复现步骤 | 1. 准备 fake_video.mp4（PNG 文件头 41 字节，改名 .mp4） 2. POST /api/jobs 上传 3. 返回 201 Created |
| 原因分析 | file_service.py 的 validate_file 方法仅检查扩展名是否在 ALLOWED_VIDEO_EXTENSIONS 集合中，未读取文件头魔数校验实际格式 |
| 修复方案 | 在 FileService.validate_file 中增加魔数校验：读取文件前 N 字节，比对 MP4（ftyp）、AVI（RIFF）、MOV（ftyp/moov）、MKV（1A 45 DF A3）等格式的魔数。不合规返回 FileValidationError |
| 验证结果 | 待修复后回归 |

---

### BUG-002

| 项目 | 内容 |
|------|------|
| 问题现象 | |
| 复现步骤 | |
| 原因分析 | |
| 修复方案 | |
| 验证结果 | |

---

## 统计

| 统计项 | 数量 |
|------|------|
| 已发现 | 1 |
| 已修复 | 0 |
| 待修复 | 1 |
