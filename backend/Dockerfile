FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY scripts ./scripts
COPY data ./data
COPY start.sh ./start.sh

RUN uv sync --no-dev --frozen

ENV DATABASE_URL=sqlite:///./billproof.db
# Hosts like Railway and Fly inject $PORT; start.sh honours it and falls back to 8000.
ENV PORT=8000
EXPOSE 8000

RUN chmod +x ./start.sh
CMD ["./start.sh"]
