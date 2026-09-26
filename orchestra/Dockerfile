FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first so image layers cache across code changes.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
