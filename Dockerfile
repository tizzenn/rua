FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RUA_HOST=0.0.0.0 RUA_PORT=8000 RUA_DB=/data/rua.sqlite3 RUA_CONFIG_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data && chown -R 10001:10001 /app /data
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["python", "server.py"]
