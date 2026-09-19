FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY scripts ./scripts
COPY data ./data

RUN uv sync --no-dev --frozen

ENV DATABASE_URL=sqlite:///./billproof.db
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "billproof.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
