# SKG 库存核对平台 —— 应用镜像
# 运行时代码以 bind mount 挂载（见 docker-compose.yml），镜像本身只备依赖；
# 这里仍 COPY 一份代码，保证不挂载时也能独立运行。
FROM python:3.12-slim

WORKDIR /app

# 依赖单独一层：requirements 不变即复用缓存。国内源避免境内构建超时。
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt

# 应用代码（compose 用 bind mount 覆盖，改文件即生效）
COPY app/ ./app/
COPY etl/ ./etl/
COPY sql/ ./sql/

EXPOSE 8061
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8061"]
