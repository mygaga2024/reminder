# 定时提醒助手 (Reminder Service)

这是一个基于 Python 和 Docker 的轻量级定时提醒服务。

## 功能特点
- **灵活定时**：支持多个时间点触发，支持 **秒级精度**。
- **多种模式**：
  - **每日** (Daily): `09:00:00`
  - **每周/工作日** (Weekly/Weekday): `mon-fri 09:00:00`
  - **特定日期** (Specific Date): `2026-04-10 10:00:00`
- **多种通知**：支持邮件提醒和 Webhook 推送。
- **持久化**：自动记录提醒历史，保留在本地 `./data` 目录。

## 快速开始

### 1. 配置
编辑 `docker-compose.yaml` 中的 `environment` 部分，修改 `REMINDER_RULES`：
- 支持逗号分隔多个规则。
- 星期支持缩写 (mon, tue, wed, thu, fri, sat, sun) 或范围 (mon-fri)。

### 2. 运行

#### 方式 A：直接拉取预构建镜像 (推荐)
如果你不想下载源码，可以直接创建一个 `docker-compose.yaml` 并填入以下内容：
```yaml
services:
  reminder:
    image: ghcr.io/mygaga2024/longlive:v1.0.0
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
```
*注：请将 `${YOUR_GITHUB_USERNAME}` 替换为你的 GitHub 用户名。*

#### 方式 B：从源码构建运行
```bash
docker compose up -d --build
```

### 3. 查看日志
```bash
docker logs -f reminder-container
```

## 目录结构
- `reminder.py`: 核心逻辑脚本。
- `Dockerfile`: 容器镜像定义。
- `docker-compose.yaml`: 容器编排配置。
- `data/`: 存储提醒历史纪录。
- `requirements.txt`: Python 依赖。
