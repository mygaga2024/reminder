# Life Reminder (定时提醒助手)

🚀 **一个基于 Python 和 Docker 的高颜值、多功能生活提醒系统。**

## ✨ 核心特性

- **专业级 UI/UX**：设计美观，支持 **黑暗模式 (Dark Mode)**。
- **数据安全防护**：针对极空间 (ZSpace) 等 NAS 环境优化，内置 **“权限拒绝即停机”** 保护机制，彻底杜绝因权限抖动导致的数据清空。
- **持久化稳固**：内置持久化健康监测与自动刷盘 (fsync) 技术，确保数据真实落盘。
- **多渠道推送**：支持 **企业微信、钉钉、飞书** 以及 **短信/电话**。
- **执行日志 (Journal)**：内置统计图表，记录提醒的触发和实际完成情况。
- **灵活提醒规则**：支持一次性、每日、每周与工作日提醒。
- **工作日判断**：可结合中国法定节假日规则执行工作日提醒。

## 🛠 快速开始

### 方式 A：标准部署 (适用于云服务器/桌面)
只需创建一个 `docker-compose.yaml` 文件，内容如下：

```yaml
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
```

### 方式 B：极空间 (ZSpace) / NAS 部署 (重要)
针对 NAS 环境下的权限锁定问题，请遵循以下配置：

1.  **极空间权限设置**：在【文件管理】中，右键点击映射目录 `data` ->【属性】->【权限设置】，**务必勾选“合规目录最大读写权限”**。
2.  **强制绝对路径**：在极空间 Docker 中，强烈建议使用宿主机的 **绝对路径**（请在极空间文件管理器中右键目录->属性->复制完整路径）。
3.  **Compose 配置**：建议将 `PUID/PGID` 设为 `0` (root) 以确保容器能穿透 ACL。

```yaml
services:
  reminder:
    image: ghcr.io/mygaga2024/reminder:latest
    container_name: life-reminder
    environment:
      - PUID=0
      - PGID=0
      - TZ=Asia/Shanghai
    ports:
      - "5000:5000"
    volumes:
      - /此处替换为极空间文件管理器中查看到的完整绝对路径/data:/app/data
```

## 🔍 故障诊断 (针对极空间用户)

如果您在容器重启后发现数据丢失或 UI 顶部显示 **“持久化锁定”** 警告，请运行以下专项诊断脚本：

```bash
docker exec -it life-reminder bash /app/scripts/diagnose_zspace.sh
```

脚本会自动检测物理写入权、UID/GID 冲突并提供修复建议。

## 📖 使用指南
1. 访问 `http://localhost:5000` 进入管理面板。
2. 在 **设置** 中配置你的 Webhook 机器人（企业微信/钉钉/飞书）或短信/电话通知。
3. 在 **主页** 点击底部导航栏中间的 `+` 按钮，即可创建你的第一个智能提醒。

---
*Created by [mygaga2024](https://github.com/mygaga2024)*
