# ---- build the UI ----
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY web/ ./
RUN npx vite build --outDir /out --emptyOutDir

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -r -u 10001 -d /srv litesql \
 && mkdir -p /data && chown litesql /data
COPY app/ ./app/
COPY --from=web /out ./app/static
USER litesql
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/api/health'%os.getenv('PORT','8080'),timeout=4)" || exit 1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips '*' --no-access-log"]
