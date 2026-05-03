# Life Reminder — AGENTS.md

> 版本: 1.0 | 项目: Life Reminder (定时提醒助手)
> 部署目标: NAS (极空间/群晖/威联通) / Docker

---

## 1. 项目速览

| 项 | 值 |
|---|---|
| 项目类型 | 个人定时提醒 SPA 应用 |
| Python 版本 | 3.11 |
| Web 框架 | Flask 3.0.0 + Waitress 3.0.2 |
| 调度引擎 | APScheduler 3.10.4 (BackgroundScheduler) |
| 持久化 | JSON 文件 (原子写入 + fsync) |
| 前端 | 单文件 Vanilla JS SPA (Chart.js + SortableJS + lunar-js) |
| 容器 | Docker Compose (单服务) |
| 测试 | pytest (44 用例) |
| 版本 | v3.2.15 |

---

## 2. 项目结构

```
reminder/
├── main.py                     # 入口：Flask app 创建、DB 加载、调度器启动
├── app/                        # 后端模块包
│   ├── __init__.py
│   ├── config.py               # VERSION、环境变量、logger、常量
│   ├── persistence.py          # load_json / save_json / 健康检查 / db_lock
│   ├── calendar_utils.py       # is_china_workday / get_next_workday
│   ├── auth.py                 # require_api_key 装饰器 + validate_reminder_input
│   ├── notifier.py             # notify_engine → 多渠道 Webhook + 日志
│   ├── scheduler.py            # update_scheduler → 清除+重建所有 APScheduler Job
│   └── api.py                  # register_routes → 所有 Flask 端点
├── templates/
│   └── index.html              # 前端 SPA (1697 行, CDN 依赖, 无构建工具)
├── tests/
│   ├── conftest.py             # pytest fixtures (临时 DATA_DIR)
│   ├── test_persistence.py     # 8 tests
│   ├── test_calendar.py        # 6 tests
│   ├── test_notifier.py        # 8 tests
│   └── test_api.py             # 17 tests
├── scripts/
│   ├── diagnose_zspace.sh      # ZSpace 权限诊断
│   ├── check_env.sh            # 环境检查
│   └── test_2100_leap.py       # 2100 年闰年回归测试
├── Dockerfile                  # python:3.11-slim + gosu + tzdata
├── docker-compose.yaml         # 单服务, PUID/PGID, ZSPACE_COMPAT
├── entrypoint.sh               # PUID/PGID 用户切换 + 权限回退
├── requirements.txt            # 全部锁定版本
├── project_status.md           # 开发进度参考
└── DEVELOPMENT_PROTOCOL.md     # 本地开发协议 (不入 git)
```

---

## 3. 环境感知

### 3.1 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `/app/data` | 持久化数据目录 |
| `APP_PORT` | `5000` | 服务端口 |
| `TZ` | `Asia/Shanghai` | 时区 |
| `API_KEY` | `""` (空=不启用) | API 认证密钥 |
| `WX_APPID` | `""` | 微信小程序 AppID |
| `WX_SECRET` | `""` | 微信小程序 Secret |
| `PUID` | `0` | 容器运行用户 UID |
| `PGID` | `0` | 容器运行用户 GID |
| `ZSPACE_COMPAT` | `false` | 极空间兼容模式 |

### 3.2 Docker 约束
- 入口点：`/app/entrypoint.sh` → `exec python main.py`
- 数据卷：`./data:/app/data`（NAS 用户必须使用绝对路径）
- 日志驱动：json-file, 10MB 滚动, 保留 3 个文件
- `chown` 在 NAS 上允许静默失败（ACL 锁），不得中断启动
- 目标架构：默认 `linux/amd64`，CI 中未启用多平台构建

### 3.3 NAS 兼容性
- 优先使用 `os.getenv("DATA_DIR")`，禁止硬编码绝对路径
- 持久化层内置物理写入测试（`.write_test`）
- 文件损坏自动备份为 `.corrupt_YYYYMMDDHHMMSS`

---

## 4. 行为准则

### 4.1 修改前审查
- 修改任何 `.py` 文件前，确认它被哪些模块 import
- 修改 API 端点前，确认 `index.html` 中对应的 `fetch()` 调用
- 修改 `index.html` 前，确认对应的后端端点签名

### 4.2 契约锁定
- API 端点路径和 JSON 字段名一经确定，严禁随意修改
- `config.json` 数据结构 (`reminders`/`settings`/`users`) 严禁破坏性变更
- 模块间调用约定：
  - `api.py` → 调用 `persistence.save_json`、`scheduler.update_scheduler`
  - `scheduler.py` → 接收 `notify_fn` 回调（参数签名固定为 `(reminder)`）
  - `notifier.py` → 不直接调用 `scheduler`，通过参数注入

### 4.3 原子化修改
- 严禁一次性修改超过 **5 个文件**
- 严禁删除既有 **日志/错误处理代码**
- 必须输出 **完整可运行代码**，禁止使用 `...` 占位符

### 4.4 测试覆盖
- 修改逻辑代码后，必须运行 `python3 -m pytest tests/ -v`
- 新增功能必须追加对应模块的测试用例
- 当前基准：44 测试，全部通过

---

## 5. 常见开发场景

### 5.1 新增 Webhook 渠道
1. 在 `app/notifier.py` 的 `_send_webhooks()` 中添加平台 handler
2. 在 `templates/index.html` 的 Settings 区添加配置 UI
3. 在 `app/auth.py` 中无额外变更（Webhook URL 校验已有）
4. 追加 `tests/test_notifier.py` 中的测试用例

### 5.2 新增提醒重复模式
1. `app/config.py` → `VALID_REPEAT_MODES` 集合
2. `app/scheduler.py` → `_build_trigger()` 添加触发逻辑
3. `app/notifier.py` → `notify_engine()` 添加过滤逻辑（如工作日跳过）
4. `templates/index.html` → `repeatMode` chips + `createTask()` 重复值映射
5. `app/auth.py` → `validate_reminder_input()` 校验
6. `tests/test_api.py` + `tests/test_notifier.py` 追加测试

### 5.3 修改前端 UI
- 所有动态内容优先使用 `textContent` 而非 `innerHTML`
- 所有 `fetch()` 调用必须使用 `apiHeaders()` 自动附加 API Key
- 修改 CSS 变量在 `:root` / `[data-theme="light"]` 中同步
- 版本号在页脚 `#appVersion` 和 `versionHistory` 数组两处更新

### 5.4 升级依赖
- **必须先获得用户确认**
- 仅升级有明确 CVE 或功能需要的包
- 升级后运行全量测试确认无破坏性变更

---

## 6. 错误处理约定

| 场景 | 处理方式 |
|---|---|
| JSON 解析失败 | 创建 `.corrupt_` 备份，抛出 `RuntimeError` 拒绝启动 |
| 权限不足 | 抛出 `RuntimeError` 拒绝启动（防止空数据覆盖） |
| 空数据写入拦截 | `save_json` 检测空 reminders + 非空文件 → 拦截 |
| Webhook 推送失败 | `try-except` 捕获，记录日志，不中断其他渠道 |
| 调度任务构建失败 | `try-except` 捕获单条，记录日志，继续处理下一条 |
| 一次性任务通知后 | `notify_engine` 自动移除调度 Job + 数据库记录 |

---

## 7. 交付与验证规范

每次完成任务后必须输出：

### 7.1 变更列表
```
[变更文件]
- app/xxx.py: 修改原因
- templates/index.html: 修改原因
```

### 7.2 验证结果
- 运行 `python3 -m pytest tests/ -v` 并贴出通过/失败数量
- 若涉及前端 UI，说明手动验证步骤

### 7.3 环境提示
- 若涉及 `docker-compose.yaml` 或 `Dockerfile` 变更，高亮显示
- 若涉及新环境变量，列出变量名和默认值

---

## 8. 引用规则

项目根目录的规则文件（优先级自上而下）：
1. `DEVELOPMENT_PROTOCOL.md` — 开发与修改约束协议（本地，不入 git）
2. `project_status.md` — 项目进度参考
3. `AGENTS.md` — 本文件，AI Agent 速查手册
