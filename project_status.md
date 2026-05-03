# Project Status — Life Reminder

> 最后更新: 2026-05-03 | 当前版本: v3.2.15

---

## 1. 项目概述

基于 Python + Docker 的定时提醒助手，支持多渠道 Webhook 推送，可在主流 NAS（绿联/群晖/威联通/极空间）上部署。

## 2. 当前架构

```
reminder/
├── main.py                    # 入口点
├── app/                       # 后端模块包
│   ├── config.py              # 配置、日志、常量、环境变量
│   ├── persistence.py         # JSON 文件读写、原子写入、健康检查
│   ├── calendar_utils.py      # 中国法定节假日判断
│   ├── auth.py                # API Key 认证 + 输入校验
│   ├── notifier.py            # 通知引擎 (WeCom/DingTalk/Lark/SMS/Voice)
│   ├── scheduler.py           # APScheduler 调度管理
│   └── api.py                 # Flask 路由 (REST API)
├── templates/index.html       # 前端 SPA (Vanilla JS + Chart.js + SortableJS)
├── tests/                     # 测试套件 (44 用例)
├── scripts/                   # 诊断脚本
├── Dockerfile                 # Python 3.11-slim
├── docker-compose.yaml        # 标准部署（绿联/群晖/威联通）
├── entrypoint.sh              # NAS 权限适配（PUID/PGID/UMASK）
└── requirements.txt           # 全部锁定版本
```

## 3. 已完成功能

- [x] 提醒 CRUD（创建/编辑/删除/完成标记）
- [x] 重复模式：一次性 / 每日 / 每周(自选) / 工作日(含中国法定节假日)
- [x] Webhook 推送：企业微信 / 钉钉 / 飞书 / 短信网关 / 语音网关
- [x] 一次性任务自动删除 + 调度器清理
- [x] JSON 文件持久化 + 原子写入 + fsync 防数据丢失
- [x] 持久化健康监测（物理写入测试、挂载检测、损坏自动备份）
- [x] 前端：任务排序（时间/优先级/创建/手动拖拽）
- [x] 前端：农历日历选择器、日期语义标签（今天/明天/后天）
- [x] 前端：深色/浅色模式切换
- [x] 通知日志系统（触发记录 + 完成标记 + 图表统计）
- [x] API Key 认证中间件
- [x] 服务端输入校验
- [x] 日志敏感信息脱敏 (WX_SECRET)
- [x] NAS 权限兼容：UMASK=000 + 子目录回退 + 多重写入降级
- [x] CI/CD：GitHub Actions 多分支自动构建推送 GHCR
- [x] NAS 专项：权限诊断脚本

## 4. 部署矩阵

| NAS 品牌 | 型号 | 状态 | 特殊配置 |
|---|---|---|---|
| 绿联 (UGREEN) | DXP4800 Plus | 生产运行中 | 默认配置即可 |
| 极空间 (ZSpace) | 待适配 | 已知权限问题 | 需开启 `ZSPACE_COMPAT=true` |

### 通用部署
```yaml
environment:
  - TZ=Asia/Shanghai
  - PUID=0
  - PGID=0
  - UMASK=000
```

### 极空间专属
```yaml
environment:
  # ... 通用配置 ...
  - ZSPACE_COMPAT=true   # 启用 ACL 绕过策略
```

## 5. 技术栈

| 层 | 技术 | 版本 |
|---|---|---|
| Runtime | Python | 3.11-slim |
| Web | Flask + Waitress | 3.0.0 / 3.0.2 |
| 调度 | APScheduler | 3.10.4 |
| HTTP | requests | 2.32.3 |
| 日历 | chinese-calendar | 1.10.0 |
| 前端 | Vanilla JS + Chart.js + SortableJS + lunar-javascript | CDN |
| 容器 | Docker + Gosu | — |

## 6. 测试覆盖

- **测试框架**: pytest 8.3.4
- **用例数**: 44 (全部通过)
- **覆盖模块**: persistence(8) / calendar(6) / notifier(8) / api(17) / auth(3) / wxlogin(2)

## 7. 安全性

| 项 | 状态 |
|---|---|
| API Key 认证 | 已实现 |
| 输入校验 | 已实现 |
| WX_SECRET 脱敏 | 已实现 |
| HTTPS | 需反向代理 |
| CSRF | 未实现 |
| Rate Limiting | 未实现 |

## 8. 待优化项

### 高优先级
- [ ] 极空间适配测试验证
- [ ] HTTPS 支持
- [ ] 请求频率限制

### 中优先级
- [ ] 前端构建工具
- [ ] SQLite 替代 JSON
- [ ] 多架构构建 (arm64)
- [ ] Docker 健康检查端点

### 低优先级
- [ ] i18n 国际化
- [ ] PWA 离线支持
- [ ] 邮件通知渠道
- [ ] 提醒分组/标签

## 9. 本地开发

```bash
pip install -r requirements.txt
python main.py                            # 启动服务
python3 -m pytest tests/ -v               # 运行测试
```

## 10. 版本历史摘要

| 版本 | 关键变更 |
|---|---|
| v3.2.15 | 模块化重构、Bug修复、认证/校验、SMS通知、UMASK适配、Python 3.11 |
| v3.2.14 | 日历范围扩展至2100年、时间确认拦截 |
| v3.2.9 | 安全漏洞修复、线程安全锁、一次性任务清理 |
| v3.2.0 | 专业排序、农历日历、日期语义标签 |

## 11. 代码同步状态

| 位置 | 版本 | 说明 |
|---|---|---|
| 本地 (macOS) | v3.2.15 | 开发主分支 |
| GitHub (ghcr.io) | v3.2.14 | 待推送 v3.2.15 |
| 绿联 NAS | v3.2.14 | 生产运行 `ghcr.io/mygaga2024/reminder:latest` |
| 极空间 | — | 待适配部署 |
