# Life Reminder · 定时提醒助手

基于 Python + Docker 的高颜值、多功能生活提醒系统。支持多渠道 Webhook 推送，可在主流 NAS（绿联/群晖/威联通/极空间）上部署。

[![Docker Pulls](https://img.shields.io/docker/pulls/mygaga2024/reminder)](https://github.com/mygaga2024/reminder/pkgs/container/reminder)

## 核心特性

- **精美 UI**：iOS 风格 SPA 界面，支持深色/浅色模式切换
- **灵活调度**：一次性 / 每日 / 每周(自选) / 工作日(含中国法定节假日)
- **多渠道推送**：企业微信 / 钉钉 / 飞书 / 短信网关 / 语音电话
- **智能日历**：农历显示、日期语义标签（今天/明天/后天）
- **任务管理**：多维度排序（时间/优先级/创建/手动拖拽）
- **执行日志**：内置 Chart.js 图表统计，日志隐藏与删除
- **数据安全**：原子写入 + fsync、文件损坏自动备份、空数据写入拦截
- **NAS 兼容**：UMASK 权限适配、子目录回退、多重写入降级策略
- **API 认证**：可选的 API Key 中间件 + 服务端输入校验

## 快速开始

```yaml
# docker-compose.yaml
services:
  reminder:
    image: ghcr.io/mygaga2024/reminder:latest
    container_name: life-reminder
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
      - PUID=0
      - PGID=0
      - UMASK=000
```

```bash
docker compose up -d
# 访问 http://localhost:5000
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TZ` | `Asia/Shanghai` | 时区 |
| `PUID` | `0` | 容器运行用户 UID |
| `PGID` | `0` | 容器运行用户 GID |
| `UMASK` | `000` | 新文件权限掩码 |
| `APP_PORT` | `5000` | 服务端口 |
| `DATA_DIR` | `/app/data` | 数据持久化目录 |
| `API_KEY` | (空，不启用) | API 认证密钥 |
| `ALLOW_REGISTRATION` | `true` | 是否允许自助注册新账号 |
| `LOG_RETENTION_DAYS` | `30` | 通知记录保留天数（下次推送时清理更早记录） |
| `WX_APPID` | (空) | 微信小程序 AppID |
| `WX_SECRET` | (空) | 微信小程序 Secret |
| `ZSPACE_COMPAT` | `false` | 极空间 NAS 兼容模式 |

### API Key 认证

```yaml
environment:
  - API_KEY=your-secret-key
```

设置后，所有 `/api/*` 请求需携带 `X-API-Key` 头。前端通过 `?api_key=xxx` URL 参数访问。

### 多账号（注册 / 登录 / 数据隔离）

首次打开页面时若系统尚未注册任何账号，仍以原有「开放模式」运行，页面顶部会出现注册入口。

1. 点击「去注册」，填写用户名与密码（用户名 2-32 位中文/字母/数字/_/-，密码至少 6 位）
2. 首个账号可勾选「继承当前（未登录模式）下的提醒与历史记录」，把开放模式数据迁移到该账号
3. 注册成功后自动登录，此后所有页面必须登录访问，各账号的提醒、设置、通知历史相互隔离
4. 忘记密码需由管理员清理 `config.json` 中对应账号记录（无邮件找回功能）

登录后可在「设置 → 昵称」设置显示用昵称：首页问候语会显示成「下午好，昵称」，账号卡片与设置页同步显示；留空即恢复显示登录用户名。昵称仅用于展示，不改变登录用户名，长度上限 20 个字符。

## 提醒重复模式

| 模式 | 说明 | 触发规则 |
|---|---|---|
| 每天 | 每日固定时刻 | 每天 HH:MM |
| 工作日 | 仅中国法定工作日（自动跳过周末与法定节假日） | 周一至周五 + 节假日判断 |
| 自选星期 | 每周指定的若干天 | 每周选中的星期 |
| 每月 | 每月指定日期，或「最后一天」 | 每月 DD 日 / 月末 |
| 每年 | 生日、纪念日等公历年度重复 | 每年 M 月 D 日 |
| 农历每年 | 农历生日、传统节日，支持闰月 | 每年农历 MM 月 DD 日 |
| 仅一次 | 指定日期时间提醒一次，触发后自动删除 | 单次 |

说明：

- 农历每年依赖 `lunar_python`（与前端 `lunar-javascript` 同源算法）；若镜像缺少该依赖，农历模式会被服务端拒绝并提示，其余模式不受影响。
- 「每年 2 月 29 日」仅在有 2 月 29 日的年份触发；「每月 31 日」在当月无 31 日时跳过。
- 农历某月无 30 日（或闰月规格与实际闰月不一致）的年份不会触发。

关闭自助注册（已有账号仍可正常登录）：

```yaml
environment:
  - ALLOW_REGISTRATION=false
```

账号数据保存在 `data/config.json` 的 `users` 字段中，密码使用 PBKDF2-HMAC-SHA256（20 万次迭代 + 随机盐）哈希存储，会话 token 仅保存 SHA-256 摘要，有效期 30 天。

### 账号与数据维护

| 功能 | 位置 | 说明 |
|---|---|---|
| 修改昵称 | 设置 → 昵称 | 首页问候语显示，留空恢复用户名 |
| 修改密码 | 设置 → 账号卡片 🔑 | 改密后其他设备需重新登录 |
| 退出其他设备 | 设置 → 退出其他设备 | 注销该账号全部会话并给当前设备换发新 token |
| 注销账号 | 设置 → 注销账号 | 需「用户名 + 密码」二次确认，账号内提醒与历史一并删除且不可恢复 |
| 导出备份 | 设置 → 导出备份 | 下载当前账号的提醒 / 历史 / 设置 JSON |
| 导入备份 | 设置 → 导入备份 | 按「标题+时间+重复」去重后新增，不覆盖现有数据 |
| Webhook 测试 | 各推送渠道配置页 | 一键发送测试消息，可用未保存的地址直接验证 |
| 稍后提醒 | 历史记录 ⏰ | 基于该条记录创建 10 分钟后的一次性任务 |
| 标记已处理 | 历史记录 ✓ | 单独标记某次通知是否已处理 |

### 极空间 (ZSpace) 部署

极空间 NAS 使用内核级 ACL 限制 Docker 卷写入。启用 `ZSPACE_COMPAT` 后，系统会自动执行以下策略：

1. **umask 000** — 所有新文件获得 777 权限
2. **子目录回退** — 根挂载点不可写时，自动使用卷内 `store/` 子目录
3. **三重写入降级** — tempfile → 同名.tmp → 直接覆盖，确保数据落盘
4. **自动数据迁移** — 切换存储路径时自动迁移已有数据

```yaml
# docker-compose.yaml — 极空间专用
services:
  reminder:
    image: ghcr.io/mygaga2024/reminder:latest
    container_name: life-reminder
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      # 极空间请使用绝对路径，例如:
      # /共享文件夹名称/docker/reminder/data:/app/data
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
      - PUID=0
      - PGID=0
      - UMASK=000
      - ZSPACE_COMPAT=true
```

> 极空间用户请注意：在文件管理器中，右键映射目录 →「属性」→「权限设置」→ 勾选「合规目录最大读写权限」。

## 使用指南

1. 访问管理面板，底部导航栏切换首页/数据/日志/设置
2. 点击 **+** 创建提醒：填写名称 → 选择时间 → 选择重复模式 → 设置优先级
3. 在 **设置** 中配置 Webhook 机器人（企业微信/钉钉/飞书/短信/语音）
4. 首页拖拽排序任务，点击对勾标记完成

## 架构

```
reminder/
├── main.py                  # Flask 应用入口
├── app/
│   ├── config.py            # 环境变量、常量、日志
│   ├── persistence.py       # JSON 读写、原子写入、健康检查
│   ├── calendar_utils.py    # 中国法定节假日判断
│   ├── auth.py              # API Key 认证、输入校验
│   ├── notifier.py          # 多渠道 Webhook 通知引擎
│   ├── scheduler.py         # APScheduler 调度管理
│   └── api.py               # REST API 路由
├── templates/
│   ├── index.html           # SPA 页面骨架
│   ├── app.css              # 样式表（/app.css）
│   └── app.js               # 前端逻辑（/app.js）
├── tests/                   # pytest 44 用例
├── Dockerfile               # python:3.11-slim
└── docker-compose.yaml
```

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/state` | 获取完整状态 |
| `POST` | `/api/reminders` | 创建提醒 |
| `PUT` | `/api/reminders/<id>` | 更新提醒 |
| `DELETE` | `/api/reminders/<id>` | 删除提醒 |
| `POST` | `/api/settings` | 更新设置 |
| `DELETE` | `/api/logs/<id>` | 删除日志 |
| `POST` | `/api/logs/hide/<id>` | 隐藏日志 |
| `POST` | `/api/wxlogin` | 微信登录 |

## 故障诊断

```bash
# 查看容器日志
docker logs life-reminder --tail 50

# 极空间权限诊断
docker exec -it life-reminder bash /app/scripts/diagnose_zspace.sh

# 数据完整性检查
docker exec life-reminder ls -la /app/data/
```

## 本地开发

```bash
pip install -r requirements.txt
python main.py                    # 启动服务
python3 -m pytest tests/ -v       # 44 测试
```

## 技术栈

Python 3.11 · Flask 3.0 · Waitress 3.0.2 · APScheduler 3.10.4 · requests 2.32.3 · Chart.js · SortableJS · lunar-javascript

---

*Made with ♥ by [mygaga2024](https://github.com/mygaga2024)*
