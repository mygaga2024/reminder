# 使用Python基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件 (包含 templates 等)
COPY . .

# 运行提醒服务
CMD ["python", "reminder.py"]