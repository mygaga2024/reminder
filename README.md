# Life Reminder (定时提醒助手)

🚀 **一个基于 Python 和 Docker 的高颜值、多功能生活提醒系统。**

## ✨ 核心特性

- **专业级 UI/UX**：设计美观，支持 **黑暗模式 (Dark Mode)**。
- **多渠道推送**：支持 **企业微信、钉钉、飞书** 以及 **短信/电话**。
- **执行日志 (Journal)**：内置统计图表，记录提醒的触发和实际完成情况。
- **多语言支持**：支持 **简体中文** 与 **English** 一键切换。
- **智能识别 (NLP)**：支持通过自然语言（如 "下午三点提醒我"）自动解析时间。
- **高度便携**：一键 Docker 部署，所有配置通过 Web 界面完成。

## 🛠 快速开始

### 方式 A：直接运行 (推荐)
只需创建一个 `docker-compose.yaml` 文件，内容如下：

```yaml
services:
  reminder:
    image: ghcr.io/mygaga2024/reminder:latest
    container_name: reminder
    restart: always
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
```

执行启动命令：
```bash
docker compose up -d
```

### 方式 B：从源码构建
```bash
git clone https://github.com/mygaga2024/reminder.git
cd reminder
docker compose up -d --build
```

## 📖 使用指南
1. 访问 `http://localhost:5000` 进入管理面板。
2. 在 **设置** 中配置你的 Webhook 机器人（企业微信/钉钉/飞书）或短信/电话通知。
3. 在 **主页** 点击底部导航栏中间的 `+` 按钮，即可创建你的第一个智能提醒。

---
*Created by [mygaga2024](https://github.com/mygaga2024)*
