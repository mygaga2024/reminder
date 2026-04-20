# 使用Python基础镜像
FROM python:3.9-slim

WORKDIR /app

# 安装 gosu
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# 创建基础目录
RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 确保脚本可执行
RUN chmod +x /app/entrypoint.sh

# 运行时由 entrypoint.sh 处理用户权限
ENTRYPOINT ["/app/entrypoint.sh"]