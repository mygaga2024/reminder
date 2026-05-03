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
| `WX_APPID` | (空) | 微信小程序 AppID |
| `WX_SECRET` | (空) | 微信小程序 Secret |
| `ZSPACE_COMPAT` | `false` | 极空间 NAS 兼容模式 |

### API Key 认证

```yaml
environment:
  - API_KEY=your-secret-key
```

设置后，所有 `/api/*` 请求需携带 `X-API-Key` 头。前端通过 `?api_key=xxx` URL 参数访问。

### 极空间 (ZSpace) 部署

```yaml
environment:
  - ZSPACE_COMPAT=true   # 启用 ACL 绕过与多重写入降级
```

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
├── templates/index.html     # Vanilla JS SPA 前端
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
