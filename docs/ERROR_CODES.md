\# ReelFire 错误码规范



\## 1. 文档状态



\* 阶段：Day 1 契约设计

\* 当前状态：错误码已设计，代码尚未全面接入

\* 计划实现：Day 2～Day 3

\* 兼容原则：保留现有 `error` 字符串，新增稳定的 `error\_code`



尚未接入代码或测试的错误码不得描述为当前已经可用。



\## 2. 设计目的



当前 ReelFire 失败响应主要依赖 HTTP 状态码和中文错误信息，例如：



```json

{

&#x20; "ok": false,

&#x20; "error": "任务不存在"

}

```



中文错误信息适合直接展示，但不适合作为前端判断依据，因为文字可能调整。



新增错误码后，统一使用：



```json

{

&#x20; "ok": false,

&#x20; "error": "任务不存在",

&#x20; "error\_code": "JOB\_NOT\_FOUND"

}

```



其中：



\* `ok`：是否成功；

\* `error`：面向用户的可读提示；

\* `error\_code`：稳定的程序判断标识；

\* `details`：可选的字段级错误或补充信息；

\* `request\_id`：后续可选，用于关联服务日志。



\## 3. 通用失败响应



\### 3.1 标准格式



```json

{

&#x20; "ok": false,

&#x20; "error": "请求参数不合法",

&#x20; "error\_code": "VALIDATION\_ERROR"

}

```



\### 3.2 带字段详情



```json

{

&#x20; "ok": false,

&#x20; "error": "请求参数不合法",

&#x20; "error\_code": "VALIDATION\_ERROR",

&#x20; "details": {

&#x20;   "username": "用户名长度必须为 3～32 个字符"

&#x20; }

}

```



\### 3.3 禁止返回的内容



API 错误响应不得包含：



```text

Python 堆栈

异常类完整路径

开发者本机绝对路径

数据库文件绝对路径

SQL 原文中的敏感值

密码或密码哈希

Session Secret

API Key

Agent 服务密钥

未经脱敏的 Prompt

```



详细异常只允许写入服务端日志。



\## 4. HTTP 状态码原则



| HTTP 状态 | 使用场景                    |

| ------: | ----------------------- |

|   `400` | 请求格式、字段、数值或业务参数不合法      |

|   `401` | 未登录、会话失效或登录凭据错误         |

|   `403` | 已登录，但无权访问目标资源           |

|   `404` | 资源或接口不存在                |

|   `405` | HTTP 方法不受支持             |

|   `409` | 当前资源状态与操作冲突             |

|   `413` | 上传内容超过服务器限制             |

|   `422` | 暂不使用，第一阶段字段校验统一使用 `400` |

|   `500` | 服务内部错误、持久化数据损坏          |

|   `501` | 本机缺少当前功能依赖，例如 FFmpeg    |

|   `503` | 外部 Agent、模型或依赖服务暂时不可用   |



同一个错误码应固定对应一个主要 HTTP 状态，不应在不同接口随意变化。



\## 5. 通用错误码



| 错误码                      | HTTP | 含义                |

| ------------------------ | ---: | ----------------- |

| `VALIDATION\_ERROR`       |  400 | 请求字段、类型、范围或格式不合法  |

| `INVALID\_JSON`           |  400 | 请求体不是合法 JSON 对象   |

| `RESOURCE\_NOT\_FOUND`     |  404 | 通用资源不存在           |

| `ROUTE\_NOT\_FOUND`        |  404 | 请求的 API 路由不存在     |

| `METHOD\_NOT\_ALLOWED`     |  405 | 当前接口不支持该 HTTP 方法  |

| `REQUEST\_TOO\_LARGE`      |  413 | 请求体或上传文件超过限制      |

| `DATA\_CORRUPTED`         |  500 | 持久化 JSON 或数据库数据损坏 |

| `INTERNAL\_ERROR`         |  500 | 未分类的服务内部异常        |

| `DEPENDENCY\_UNAVAILABLE` |  503 | 必需的外部服务或依赖暂时不可用   |



示例：



```json

{

&#x20; "ok": false,

&#x20; "error": "当前接口不支持该 HTTP 方法",

&#x20; "error\_code": "METHOD\_NOT\_ALLOWED"

}

```



\## 6. 认证错误码



| 错误码                   | HTTP | 含义          |

| --------------------- | ---: | ----------- |

| `AUTH\_REQUIRED`       |  401 | 当前接口要求登录    |

| `INVALID\_CREDENTIALS` |  401 | 用户名或密码错误    |

| `SESSION\_EXPIRED`     |  401 | 登录会话已失效     |

| `USER\_DISABLED`       |  403 | 用户已被禁用      |

| `USERNAME\_EXISTS`     |  409 | 用户名已被注册     |

| `USER\_NOT\_FOUND`      |  404 | 管理操作中的用户不存在 |



登录失败统一返回：



```json

{

&#x20; "ok": false,

&#x20; "error": "用户名或密码错误",

&#x20; "error\_code": "INVALID\_CREDENTIALS"

}

```



用户名不存在和密码错误不得返回不同提示，避免泄露账户是否存在。



\## 7. 项目错误码



| 错误码                     | HTTP | 含义                |

| ----------------------- | ---: | ----------------- |

| `PROJECT\_NOT\_FOUND`     |  404 | 指定项目不存在           |

| `PROJECT\_ACCESS\_DENIED` |  403 | 当前用户无权访问该项目       |

| `PROJECT\_ARCHIVED`      |  409 | 已归档项目不允许执行当前操作    |

| `PROJECT\_NAME\_EXISTS`   |  409 | 同一用户下存在不允许重复的项目名称 |



第一阶段可以允许项目名称重复。如果代码允许重复，则不得使用 `PROJECT\_NAME\_EXISTS`。



\## 8. 素材与上传错误码



| 错误码                     | HTTP | 含义            |

| ----------------------- | ---: | ------------- |

| `FILE\_REQUIRED`         |  400 | 缺少必填上传文件      |

| `EMPTY\_FILE`            |  400 | 上传文件为空        |

| `UNSUPPORTED\_FILE\_TYPE` |  400 | 文件扩展名或媒体类型不支持 |

| `FILE\_CONTENT\_MISMATCH` |  400 | 文件内容与扩展名不符    |

| `INVALID\_FILENAME`      |  400 | 文件名不合法或无法安全保存 |

| `FILE\_TOO\_LARGE`        |  413 | 上传文件超过大小限制    |

| `ASSET\_NOT\_FOUND`       |  404 | 素材记录或素材文件不存在  |

| `ASSET\_ACCESS\_DENIED`   |  403 | 当前用户无权访问该素材   |

| `FILE\_SAVE\_FAILED`      |  500 | 文件保存失败        |



现有上传错误可以先统一映射为 `VALIDATION\_ERROR`，再逐步细化为上述错误码。



不得为了快速接入而根据中文错误文本反向猜测错误码。应在异常类型或抛出位置明确指定。



\## 9. 任务错误码



| 错误码                           | HTTP | 含义             |

| ----------------------------- | ---: | -------------- |

| `INVALID\_JOB\_ID`              |  400 | `job\_id` 格式不合法 |

| `JOB\_NOT\_FOUND`               |  404 | 任务不存在          |

| `JOB\_ACCESS\_DENIED`           |  403 | 当前用户无权访问该任务    |

| `JOB\_ALREADY\_RUNNING`         |  409 | 任务已排队或正在运行     |

| `JOB\_ALREADY\_COMPLETED`       |  409 | 已完成任务不允许直接重复分析 |

| `JOB\_STATE\_CONFLICT`          |  409 | 当前任务状态不允许执行操作  |

| `JOB\_DELETE\_CONFLICT`         |  409 | 排队中或运行中的任务不能删除 |

| `JOB\_INPUT\_NOT\_FOUND`         |  404 | 任务输入视频不存在      |

| `JOB\_DATA\_CORRUPTED`          |  500 | `job.json` 已损坏 |

| `JOB\_RECOVERED\_AFTER\_RESTART` |  409 | 服务重启后任务被标记为失败  |

| `JOB\_CREATE\_FAILED`           |  500 | 任务工作区或任务记录创建失败 |

| `JOB\_SYNC\_FAILED`             |  500 | 文件任务与数据库索引同步失败 |



`JOB\_RECOVERED\_AFTER\_RESTART` 主要用于持久化错误原因或日志，不一定直接作为某次 HTTP 响应返回。



\## 10. 分析与模型错误码



| 错误码                              | HTTP | 含义            |

| -------------------------------- | ---: | ------------- |

| `ANALYSIS\_ALREADY\_RUNNING`       |  409 | 同一任务分析已在执行    |

| `VIDEO\_DECODE\_FAILED`            |  400 | 视频无法解码或视频信息无效 |

| `VIDEO\_HAS\_NO\_FRAMES`            |  400 | 视频没有可分析画面     |

| `MODEL\_NOT\_FOUND`                |  503 | YOLO 模型文件不存在  |

| `MODEL\_LOAD\_FAILED`              |  503 | YOLO 模型加载失败   |

| `INFERENCE\_FAILED`               |  500 | 模型推理异常        |

| `ANALYSIS\_FAILED`                |  500 | 未进一步分类的分析失败   |

| `ANALYSIS\_SCHEDULER\_UNAVAILABLE` |  503 | 后台任务调度器不可用    |



后台分析失败时，HTTP 请求可能已经返回 `202`。此类错误应写入：



```text

job.json

jobs.error\_code

jobs.error\_message

```



查询任务详情时由前端读取。



不得因为分析失败而生成假报告、假关键帧或假检测结果。



\## 11. 报告与审核错误码



| 错误码                         | HTTP | 含义                         |

| --------------------------- | ---: | -------------------------- |

| `REPORT\_NOT\_FOUND`          |  404 | 分析报告不存在                    |

| `REPORT\_NOT\_READY`          |  409 | 分析报告尚未生成                   |

| `REPORT\_DATA\_CORRUPTED`     |  500 | `analysis\_report.json` 已损坏 |

| `INVALID\_REVIEW\_STATUS`     |  400 | 内容级三态值不合法                  |

| `INVALID\_KEYFRAME\_DECISION` |  400 | 关键帧决策不是 `keep/skip`        |

| `INVALID\_SEGMENT\_BOUNDARY`  |  400 | 片段起止时间不合法                  |

| `REVIEW\_NOT\_FOUND`          |  404 | 审核记录不存在                    |

| `REVIEW\_ACCESS\_DENIED`      |  403 | 当前用户无权查看或修改审核              |

| `REVIEW\_CONFLICT`           |  409 | 当前任务状态不允许审核                |



内容级三态只允许：



```text

approved

pending

rejected

```



关键帧决策只允许：



```text

keep

skip

```



二者含义不同，不得混用。



\## 12. FFmpeg 与粗剪错误码



| 错误码                        | HTTP | 含义             |

| -------------------------- | ---: | -------------- |

| `FFMPEG\_NOT\_AVAILABLE`     |  501 | 本机未检测到 FFmpeg  |

| `FFPROBE\_NOT\_AVAILABLE`    |  501 | 本机未检测到 FFprobe |

| `ROUGH\_CUT\_NOT\_READY`      |  409 | 任务或报告尚未满足粗剪条件  |

| `ROUGH\_CUT\_INVALID\_RANGE`  |  400 | 粗剪起止时间不合法      |

| `ROUGH\_CUT\_FAILED`         |  500 | FFmpeg 执行失败    |

| `ROUGH\_CUT\_OUTPUT\_MISSING` |  500 | 命令结束后未找到输出文件   |



FFmpeg 缺失时必须明确失败，不得创建空文件或假视频作为成功结果。



\## 13. Agent 错误码



| 错误码                         | HTTP | 含义                        |

| --------------------------- | ---: | ------------------------- |

| `AGENT\_ALREADY\_RUNNING`     |  409 | 同一任务已有活动 Agent 调用         |

| `AGENT\_CALL\_NOT\_FOUND`      |  404 | Agent 调用记录不存在             |

| `AGENT\_ACCESS\_DENIED`       |  403 | 当前用户无权访问该调用               |

| `AGENT\_SERVICE\_UNAVAILABLE` |  503 | Agent 或模型服务不可用            |

| `AGENT\_TIMEOUT`             |  503 | Agent 调用超时                |

| `AGENT\_OUTPUT\_INVALID`      |  500 | Agent 输出不符合固定 JSON Schema |

| `AGENT\_TOOL\_FAILED`         |  500 | Agent 工具节点执行失败            |

| `AGENT\_RESULT\_SAVE\_FAILED`  |  500 | Agent 结果或调用日志保存失败         |

| `KNOWLEDGE\_NO\_MATCH`        |  409 | 知识库没有有效命中                 |

| `LOW\_CONFIDENCE\_RESULT`     |  409 | 结果置信度不足，需要人工复核            |



以下情况不应伪装为 `completed`：



```text

知识库无命中

模型超时

结构化解析失败

工具节点失败

关键字段缺失

低置信度未被规则接受

```



可以将 Agent 调用状态设为：



```text

failed

needs\_review

```



并保存对应错误码。



\## 14. 知识库错误码



| 错误码                             | HTTP | 含义              |

| ------------------------------- | ---: | --------------- |

| `KNOWLEDGE\_DOCUMENT\_NOT\_FOUND`  |  404 | 知识文档不存在         |

| `KNOWLEDGE\_ACCESS\_DENIED`       |  403 | 无权访问项目知识文档      |

| `KNOWLEDGE\_DOCUMENT\_INVALID`    |  400 | 文档格式或来源信息不完整    |

| `KNOWLEDGE\_INDEX\_NOT\_READY`     |  409 | 向量索引尚未就绪        |

| `KNOWLEDGE\_INDEX\_FAILED`        |  500 | 文档切分或向量索引失败     |

| `EMBEDDING\_SERVICE\_UNAVAILABLE` |  503 | Embedding 服务不可用 |



\## 15. 数据库错误码



| 错误码                            | HTTP | 含义                  |

| ------------------------------ | ---: | ------------------- |

| `DATABASE\_UNAVAILABLE`         |  503 | 数据库暂时无法连接或打开        |

| `DATABASE\_BUSY`                |  503 | SQLite 长时间被锁，超过等待时间 |

| `DATABASE\_CONSTRAINT\_ERROR`    |  409 | 唯一约束、外键或检查约束冲突      |

| `DATABASE\_WRITE\_FAILED`        |  500 | 数据库写入失败             |

| `DATABASE\_READ\_FAILED`         |  500 | 数据库读取失败             |

| `DATABASE\_MIGRATION\_FAILED`    |  500 | 数据库初始化或迁移失败         |

| `DATABASE\_VERSION\_UNSUPPORTED` |  500 | 数据库版本高于当前程序支持范围     |



不得直接将 SQLite 原始错误文本返回给前端。



服务端日志可以记录原异常，但日志中仍需避免输出密码和密钥。



\## 16. 建议的异常结构



Day 2 可建立统一业务异常基类：



```python

class ApiError(Exception):

&#x20;   def \_\_init\_\_(

&#x20;       self,

&#x20;       error\_code: str,

&#x20;       message: str,

&#x20;       status\_code: int,

&#x20;       details: dict | None = None,

&#x20;   ) -> None:

&#x20;       super().\_\_init\_\_(message)

&#x20;       self.error\_code = error\_code

&#x20;       self.message = message

&#x20;       self.status\_code = status\_code

&#x20;       self.details = details

```



示例：



```python

raise ApiError(

&#x20;   error\_code="AUTH\_REQUIRED",

&#x20;   message="请先登录",

&#x20;   status\_code=401,

)

```



统一错误处理器返回：



```python

@app.errorhandler(ApiError)

def handle\_api\_error(exc: ApiError):

&#x20;   payload = {

&#x20;       "ok": False,

&#x20;       "error": exc.message,

&#x20;       "error\_code": exc.error\_code,

&#x20;   }

&#x20;   if exc.details:

&#x20;       payload\["details"] = exc.details

&#x20;   return jsonify(payload), exc.status\_code

```



这只是 Day 2 实现建议，Day 1 不直接修改现有异常体系。



\## 17. 与现有异常的兼容映射



建议初始映射：



| 现有异常或场景                  | 初始错误码                  |

| ------------------------ | ---------------------- |

| `FileValidationError`    | `VALIDATION\_ERROR`     |

| `InvalidJobIdError`      | `INVALID\_JOB\_ID`       |

| `JobNotFoundError`       | `JOB\_NOT\_FOUND`        |

| `JobStateConflictError`  | `JOB\_STATE\_CONFLICT`   |

| `CorruptDataError`       | `DATA\_CORRUPTED`       |

| `RequestEntityTooLarge`  | `REQUEST\_TOO\_LARGE`    |

| Flask `NotFound`         | `ROUTE\_NOT\_FOUND`      |

| Flask `MethodNotAllowed` | `METHOD\_NOT\_ALLOWED`   |

| 未处理异常                    | `INTERNAL\_ERROR`       |

| FFmpeg 缺失                | `FFMPEG\_NOT\_AVAILABLE` |



第一阶段先完成稳定映射，后续再根据抛出位置细分，不要一次大范围改写所有异常类。



\## 18. 前端处理规则



前端处理顺序：



```text

先读取 HTTP 状态

→ 再读取 error\_code

→ 向用户展示 error

→ 根据需要展示 details

```



示例：



```javascript

if (response.error\_code === "AUTH\_REQUIRED") {

&#x20; // 跳转登录页或显示登录提示

}

```



禁止：



```javascript

if (response.error.includes("登录")) {

&#x20; // 不稳定的中文文本匹配

}

```



\## 19. 测试要求



每个新增错误码至少验证：



1\. HTTP 状态正确；

2\. `ok` 为 `false`；

3\. `error\_code` 与文档一致；

4\. `error` 是可读字符串；

5\. 不返回绝对路径或堆栈；

6\. 同一错误在重复请求下保持稳定；

7\. 未登录与越权能够区分 `401` 和 `403`；

8\. 后台失败能够写入任务或 Agent 调用记录；

9\. 数据损坏不会导致整个 Flask 服务退出；

10\. 现有成功响应不因错误码接入而发生无关变化。



\## 20. Day 1 冻结规则



Day 1 冻结以下规则：



\* 错误码使用大写蛇形命名；

\* 失败响应保留 `ok: false` 和 `error`；

\* 新增稳定字段 `error\_code`；

\* 字段级错误使用可选 `details`；

\* 未登录使用 `401`；

\* 已登录但越权使用 `403`；

\* 资源不存在使用 `404`；

\* 状态冲突使用 `409`；

\* 本机缺少 FFmpeg 保持 `501`；

\* 外部 Agent、Embedding 或模型服务不可用使用 `503`；

\* 未处理异常使用 `INTERNAL\_ERROR`，不泄露堆栈；

\* 错误码变化必须同步修改 `docs/API.md` 和相关测试；

\* 未实现的错误码不得写成已经通过测试。
