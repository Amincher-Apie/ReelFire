\# ReelFire 数据库设计



\## 1. 设计目标



ReelFire 在保留现有文件型任务和分析报告机制的基础上，引入 SQLite 保存用户、项目、素材元数据、任务归属、人工审核和 Agent 调用日志。



数据库的主要作用是：



\* 支持注册、登录和权限校验；

\* 建立用户、项目、素材和任务之间的归属关系；

\* 保存三态人工审核结果；

\* 保存 Agent 工具调用和错误信息；

\* 支持历史查询、统计和报告生成；

\* 避免把大文件和完整视觉分析数据重复存入数据库。



\## 2. 技术选择



数据库类型：



```text

SQLite

```



数据库文件建议位置：



```text

instance/reelfire.db

```



代码中不得写死开发者本机绝对路径。



Flask 应通过应用 instance 目录生成数据库路径，例如：



```python

database\_path = Path(app.instance\_path) / "reelfire.db"

```



SQLite 是嵌入式数据库，不需要单独安装和启动数据库服务。Python 标准库已包含 `sqlite3` 模块。



\## 3. 数据存储边界



\### 3.1 SQLite 保存



```text

users

projects

assets

jobs

reviews

agent\_calls

knowledge\_documents

```



\### 3.2 文件系统继续保存



```text

原始视频

关键帧

检测结果图

job.json

analysis\_report.json

粗剪视频

HTML/PDF 报告

模型文件

向量索引文件

```



数据库不保存视频、图片、模型或报告文件的二进制内容。



数据库只保存这些文件的相对路径、业务归属、状态和必要元数据。



\## 4. 实体关系



```text

users 1 ─── N projects



projects 1 ─── N assets



assets 1 ─── N jobs



jobs 1 ─── N reviews



jobs 1 ─── N agent\_calls



projects 1 ─── N knowledge\_documents

```



其中：



\* 一个用户可以拥有多个项目；

\* 一个项目可以包含多个素材；

\* 一个素材可以因为重新分析或使用不同参数产生多个任务；

\* 一个任务可以产生多次审核记录；

\* 一个任务可以产生多次 Agent 调用记录；

\* 知识库文档可以属于一个项目，也可以作为全局公共文档。



\## 5. users 表



\### 5.1 用途



保存系统账户和身份信息。



\### 5.2 字段



| 字段              | 类型      | 约束                        | 说明         |

| --------------- | ------- | ------------------------- | ---------- |

| `id`            | INTEGER | PRIMARY KEY AUTOINCREMENT | 用户内部编号     |

| `username`      | TEXT    | NOT NULL UNIQUE           | 登录用户名      |

| `password\_hash` | TEXT    | NOT NULL                  | 密码哈希，不保存明文 |

| `display\_name`  | TEXT    | NULL                      | 页面显示名称     |

| `role`          | TEXT    | NOT NULL DEFAULT `user`   | 用户角色       |

| `is\_active`     | INTEGER | NOT NULL DEFAULT 1        | 是否允许登录     |

| `created\_at`    | TEXT    | NOT NULL                  | 创建时间       |

| `updated\_at`    | TEXT    | NOT NULL                  | 更新时间       |

| `last\_login\_at` | TEXT    | NULL                      | 最近登录时间     |



\### 5.3 约束



`role` 当前允许：



```text

user

admin

```



`is\_active` 使用：



```text

0 = 禁用

1 = 启用

```



密码必须使用 Werkzeug 密码哈希工具或等价安全实现：



```python

generate\_password\_hash()

check\_password\_hash()

```



不得保存明文密码。



\## 6. projects 表



\### 6.1 用途



保存用户创建的媒体分析项目。



\### 6.2 字段



| 字段            | 类型      | 约束                        | 说明                   |

| ------------- | ------- | ------------------------- | -------------------- |

| `id`          | INTEGER | PRIMARY KEY AUTOINCREMENT | 项目内部编号               |

| `owner\_id`    | INTEGER | NOT NULL, FOREIGN KEY     | 项目所有者                |

| `name`        | TEXT    | NOT NULL                  | 项目名称                 |

| `description` | TEXT    | NULL                      | 项目说明                 |

| `game\_type`   | TEXT    | NULL                      | CS:GO、CS2、Valorant 等 |

| `status`      | TEXT    | NOT NULL DEFAULT `active` | 项目状态                 |

| `created\_at`  | TEXT    | NOT NULL                  | 创建时间                 |

| `updated\_at`  | TEXT    | NOT NULL                  | 更新时间                 |



\### 6.3 关系



```text

projects.owner\_id → users.id

```



\### 6.4 状态



当前允许：



```text

active

archived

```



删除用户时不应直接遗留无主项目。课程 Demo 中可优先禁止删除仍有项目的用户。



\## 7. assets 表



\### 7.1 用途



保存上传素材的业务元数据和文件索引。



视频文件本身仍保存在文件系统中。



\### 7.2 字段



| 字段              | 类型      | 约束                        | 说明           |

| --------------- | ------- | ------------------------- | ------------ |

| `id`            | INTEGER | PRIMARY KEY AUTOINCREMENT | 素材内部编号       |

| `project\_id`    | INTEGER | NOT NULL, FOREIGN KEY     | 所属项目         |

| `original\_name` | TEXT    | NOT NULL                  | 用户上传时的文件名    |

| `stored\_path`   | TEXT    | NOT NULL                  | 相对于项目目录的安全路径 |

| `media\_type`    | TEXT    | NOT NULL DEFAULT `video`  | 素材类型         |

| `mime\_type`     | TEXT    | NULL                      | MIME 类型      |

| `size\_bytes`    | INTEGER | NOT NULL                  | 文件大小         |

| `sha256`        | TEXT    | NULL                      | 文件摘要         |

| `duration`      | REAL    | NULL                      | 视频时长         |

| `width`         | INTEGER | NULL                      | 视频宽度         |

| `height`        | INTEGER | NULL                      | 视频高度         |

| `fps`           | REAL    | NULL                      | 帧率           |

| `source`        | TEXT    | NULL                      | 素材来源         |

| `license\_note`  | TEXT    | NULL                      | 授权或教学用途说明    |

| `created\_at`    | TEXT    | NOT NULL                  | 创建时间         |

| `updated\_at`    | TEXT    | NOT NULL                  | 更新时间         |



\### 7.3 关系



```text

assets.project\_id → projects.id

```



\### 7.4 路径规则



`stored\_path` 必须保存相对路径，例如：



```text

outputs/20260724\_160000\_ab12cd34/input/demo.mp4

```



不得保存：



```text

D:\\Workspace\\ynu\_ai\_training\\ReelFire\\outputs\\...

```



所有路径在访问前仍需执行目录边界检查。



\## 8. jobs 表



\### 8.1 用途



建立 SQLite 业务记录与现有 `JobService` 文件任务之间的关联。



数据库中的 `jobs` 表不能取代：



```text

job.json

analysis\_report.json

```



\### 8.2 字段



| 字段                 | 类型      | 约束                        | 说明              |

| ------------------ | ------- | ------------------------- | --------------- |

| `id`               | INTEGER | PRIMARY KEY AUTOINCREMENT | 数据库任务编号         |

| `job\_id`           | TEXT    | NOT NULL UNIQUE           | 现有文件型公开任务编号     |

| `project\_id`       | INTEGER | NOT NULL, FOREIGN KEY     | 所属项目            |

| `asset\_id`         | INTEGER | NOT NULL, FOREIGN KEY     | 使用的素材           |

| `created\_by`       | INTEGER | NOT NULL, FOREIGN KEY     | 发起用户            |

| `status`           | TEXT    | NOT NULL                  | 任务状态索引          |

| `job\_json\_path`    | TEXT    | NOT NULL                  | `job.json` 相对路径 |

| `report\_json\_path` | TEXT    | NULL                      | 分析报告相对路径        |

| `rough\_cut\_path`   | TEXT    | NULL                      | 粗剪结果相对路径        |

| `error\_code`       | TEXT    | NULL                      | 稳定错误码           |

| `error\_message`    | TEXT    | NULL                      | 可读错误摘要          |

| `created\_at`       | TEXT    | NOT NULL                  | 创建时间            |

| `started\_at`       | TEXT    | NULL                      | 开始时间            |

| `completed\_at`     | TEXT    | NULL                      | 完成时间            |

| `updated\_at`       | TEXT    | NOT NULL                  | 更新时间            |



\### 8.3 关系



```text

jobs.project\_id → projects.id

jobs.asset\_id → assets.id

jobs.created\_by → users.id

```



\### 8.4 状态



第一阶段保持兼容现有状态：



```text

created

queued

running

completed

failed

```



暂不直接修改现有 `JobService` 状态名称。



后续 Agent 执行状态应保存到 `agent\_calls`，避免把 CV 任务状态与 Agent 工具状态混在同一个字段中。



\## 9. reviews 表



\### 9.1 用途



保存人工三态审核、标签、备注和片段调整。



人工审核结果是最终业务结果，不能被后续 Agent 调用静默覆盖。



\### 9.2 字段



| 字段               | 类型      | 约束                        | 说明        |

| ---------------- | ------- | ------------------------- | --------- |

| `id`             | INTEGER | PRIMARY KEY AUTOINCREMENT | 审核记录编号    |

| `job\_id`         | INTEGER | NOT NULL, FOREIGN KEY     | 对应数据库任务   |

| `reviewer\_id`    | INTEGER | NOT NULL, FOREIGN KEY     | 审核用户      |

| `status`         | TEXT    | NOT NULL                  | 三态审核结果    |

| `labels\_json`    | TEXT    | NULL                      | 人工标签 JSON |

| `note`           | TEXT    | NULL                      | 审核备注      |

| `segments\_json`  | TEXT    | NULL                      | 调整后的片段    |

| `keyframes\_json` | TEXT    | NULL                      | 关键帧审核结果   |

| `created\_at`     | TEXT    | NOT NULL                  | 创建时间      |

| `updated\_at`     | TEXT    | NOT NULL                  | 更新时间      |



\### 9.3 审核状态



数据库统一使用：



```text

approved

pending

rejected

```



含义：



| 值          | 中文含义 |

| ---------- | ---- |

| `approved` | 通过   |

| `pending`  | 待复核  |

| `rejected` | 不通过  |



不得同时出现：



```text

pass

reviewing

failed

keep

skip

```



其中 `keep/skip` 只用于单个关键帧决策，不代表内容级三态审核。



\### 9.4 关系



```text

reviews.job\_id → jobs.id

reviews.reviewer\_id → users.id

```



允许一个任务存在多条审核历史。



查询当前审核结果时，按最新 `updated\_at` 或最大 `id` 获取。



\## 10. agent\_calls 表



\### 10.1 用途



保存 Agent 调用状态、工具轨迹、耗时、错误和输出位置。



该表记录真实调用，不得保存编造的成功结果。



\### 10.2 字段



| 字段                | 类型      | 约束                        | 说明             |

| ----------------- | ------- | ------------------------- | -------------- |

| `id`              | INTEGER | PRIMARY KEY AUTOINCREMENT | 调用编号           |

| `job\_id`          | INTEGER | NOT NULL, FOREIGN KEY     | 对应任务           |

| `requested\_by`    | INTEGER | NULL, FOREIGN KEY         | 发起用户           |

| `status`          | TEXT    | NOT NULL                  | 调用状态           |

| `model\_name`      | TEXT    | NULL                      | 模型名称           |

| `prompt\_version`  | TEXT    | NULL                      | Prompt 版本      |

| `input\_summary`   | TEXT    | NULL                      | 输入摘要           |

| `output\_summary`  | TEXT    | NULL                      | 输出摘要           |

| `tool\_trace\_json` | TEXT    | NULL                      | 三个工具的轨迹        |

| `references\_json` | TEXT    | NULL                      | 知识来源和条目 ID     |

| `result\_path`     | TEXT    | NULL                      | Agent 结果文件相对路径 |

| `duration\_ms`     | INTEGER | NULL                      | 调用耗时           |

| `error\_code`      | TEXT    | NULL                      | 稳定错误码          |

| `error\_message`   | TEXT    | NULL                      | 错误摘要           |

| `created\_at`      | TEXT    | NOT NULL                  | 创建时间           |

| `completed\_at`    | TEXT    | NULL                      | 完成时间           |



\### 10.3 状态



统一使用：



```text

queued

running

completed

failed

needs\_review

```



`needs\_review` 表示：



\* 低置信度；

\* 知识库无命中；

\* 结构化结果未通过校验；

\* 模型输出需要人工确认。



\### 10.4 关系



```text

agent\_calls.job\_id → jobs.id

agent\_calls.requested\_by → users.id

```



\## 11. knowledge\_documents 表



\### 11.1 用途



保存知识库文档的来源、权限和索引状态。



实际文档、切分文件或向量索引可以继续保存在文件系统中。



\### 11.2 字段



| 字段                | 类型      | 约束                         | 说明           |

| ----------------- | ------- | -------------------------- | ------------ |

| `id`              | INTEGER | PRIMARY KEY AUTOINCREMENT  | 文档编号         |

| `project\_id`      | INTEGER | NULL, FOREIGN KEY          | 所属项目，空表示全局   |

| `title`           | TEXT    | NOT NULL                   | 文档标题         |

| `source`          | TEXT    | NOT NULL                   | 来源或引用说明      |

| `license\_note`    | TEXT    | NULL                       | 使用许可说明       |

| `document\_path`   | TEXT    | NOT NULL                   | 文档相对路径       |

| `index\_path`      | TEXT    | NULL                       | 向量索引相对路径     |

| `embedding\_model` | TEXT    | NULL                       | Embedding 模型 |

| `chunk\_count`     | INTEGER | NOT NULL DEFAULT 0         | 切分数量         |

| `status`          | TEXT    | NOT NULL DEFAULT `pending` | 索引状态         |

| `error\_message`   | TEXT    | NULL                       | 索引失败原因       |

| `created\_at`      | TEXT    | NOT NULL                   | 创建时间         |

| `updated\_at`      | TEXT    | NOT NULL                   | 更新时间         |



\### 11.3 状态



```text

pending

indexing

ready

failed

```



\### 11.4 关系



```text

knowledge\_documents.project\_id → projects.id

```



`project\_id` 允许为空，表示可被所有项目使用的公共知识。



\## 12. 索引设计



建议建立以下索引：



```sql

CREATE UNIQUE INDEX idx\_users\_username

ON users(username);



CREATE INDEX idx\_projects\_owner

ON projects(owner\_id);



CREATE INDEX idx\_assets\_project

ON assets(project\_id);



CREATE UNIQUE INDEX idx\_jobs\_public\_job\_id

ON jobs(job\_id);



CREATE INDEX idx\_jobs\_project\_status

ON jobs(project\_id, status);



CREATE INDEX idx\_jobs\_asset

ON jobs(asset\_id);



CREATE INDEX idx\_reviews\_job

ON reviews(job\_id, updated\_at);



CREATE INDEX idx\_agent\_calls\_job\_status

ON agent\_calls(job\_id, status);



CREATE INDEX idx\_knowledge\_project\_status

ON knowledge\_documents(project\_id, status);

```



\## 13. 时间格式



第一阶段统一使用带时区的 UTC ISO 8601 字符串，例如：



```text

2026-07-24T08:30:00+00:00

```



API 输出时可以继续返回 ISO 8601 字符串。



不得混用：



```text

本地无时区时间

Unix 秒

Unix 毫秒

不同格式日期字符串

```



如果为了兼容现有 `job.json` 暂时保留本地无时区时间，必须在文档中标明兼容状态，并在数据库层统一转换。



\## 14. 外键和连接初始化



每次打开 SQLite 连接后应启用外键约束：



```sql

PRAGMA foreign\_keys = ON;

```



建议同时设置：



```sql

PRAGMA journal\_mode = WAL;

PRAGMA busy\_timeout = 5000;

```



说明：



\* `foreign\_keys` 启用外键；

\* `WAL` 改善单机读写并发；

\* `busy\_timeout` 避免数据库短暂被锁时立即失败。



这些设置不能把 SQLite 变成高并发分布式数据库，课程 Demo 仍以单机运行作为边界。



\## 15. 数据库初始化方案



第一阶段采用版本化 SQL 初始化方案：



```text

database/

├─ schema.sql

└─ migrations/

&#x20;  └─ 001\_initial.sql

```



初始化流程：



```text

创建 Flask instance 目录

→ 打开 instance/reelfire.db

→ 启用 PRAGMA

→ 执行初始 Schema

→ 创建 schema\_version 表

→ 记录迁移版本

```



建议增加：



```text

schema\_version

```



字段：



| 字段           | 类型      | 说明     |

| ------------ | ------- | ------ |

| `version`    | INTEGER | 当前迁移版本 |

| `applied\_at` | TEXT    | 应用时间   |



Day 2 可实现：



```powershell

python -m database.init\_db

```



该命令应满足：



\* 首次运行创建数据库；

\* 重复运行不删除已有数据；

\* 不自动插入虚假业务数据；

\* 测试数据库可以使用临时目录；

\* 失败时返回非零退出码和可读错误；

\* 不在终端打印密码或密钥。



\## 16. 数据库与文件的一致性



创建任务建议采用以下顺序：



```text

验证用户和项目权限

→ 创建文件任务工作区

→ 保存上传文件

→ 写入 job.json

→ 写入 assets 和 jobs 数据库记录

→ 返回 201

```



如果数据库写入失败：



```text

删除刚创建但尚未对外成功返回的任务工作区

→ 返回明确数据库错误

```



分析完成建议采用：



```text

原子写入 analysis\_report.json

→ 更新 job.json

→ 更新数据库任务索引

```



如果数据库索引更新失败：



\* 不删除已经生成的分析文件；

\* 将数据库同步错误写入服务日志；

\* 后续提供重建索引或同步修复方案；

\* 不把真实成功的 CV 报告伪装成不存在。



SQLite 是业务索引和权限来源，分析 JSON 是视觉处理结果来源。双方职责必须明确，避免互相覆盖。



\## 17. 权限规则



普通用户只能访问：



\* 自己创建的项目；

\* 自己项目中的素材；

\* 自己项目产生的任务；

\* 自己项目的审核与 Agent 调用记录。



每次访问任务时，不能只验证公开 `job\_id` 是否存在，还必须验证：



```text

当前登录用户

→ 项目所有者

→ 任务所属项目

```



管理员权限暂时只作为设计保留，Day 2 优先完成普通用户的最小权限闭环。



\## 18. 隐私和公开仓库规则



不得提交：



```text

instance/reelfire.db

\*.db

\*.sqlite

\*.sqlite3

真实用户名和密码

私人邮箱

本机绝对路径

API Key

未脱敏 Agent 输入输出

```



建议 `.gitignore` 包含：



```gitignore

instance/

\*.db

\*.sqlite

\*.sqlite3

```



但修改 `.gitignore` 前必须检查现有规则，避免重复或误忽略需要提交的初始化脚本。



\## 19. Day 1 冻结项



Day 1 冻结以下约定：



\* 数据库使用 SQLite；

\* 数据库文件位于 Flask instance 目录；

\* 不把视频和图片存入数据库 BLOB；

\* 保留现有 `job.json` 和 `analysis\_report.json`；

\* 内容级审核三态使用 `approved/pending/rejected`；

\* 关键帧仍使用现有 `keep/skip`；

\* `job\_id` 继续使用现有公开格式；

\* 数据库中的任务通过 `jobs.job\_id` 关联文件任务；

\* Agent 调用状态与 CV 任务状态分表保存；

\* 所有文件路径保存为相对路径；

\* 用户只能访问自己项目下的数据；

\* Day 2 按本文档实现最小数据库层和初始化命令。



任何字段变化必须同时更新：



```text

docs/DATABASE\_DESIGN.md

docs/API.md

相关测试

前端或 Agent 字段对照

```
