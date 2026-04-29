FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY README.md ./README.md
COPY src ./src
COPY static ./static
COPY tests/products.csv ./tests/products.csv

RUN uv sync --frozen --no-dev

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "voice_commerce.main:app", "--host", "0.0.0.0", "--port", "8000"]
