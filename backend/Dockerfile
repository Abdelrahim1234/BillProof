FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY scripts ./scripts
COPY data ./data
COPY start.sh ./start.sh

RUN uv sync --no-dev --frozen
RUN chmod +x ./start.sh

ENV STORAGE_BACKEND=file
ENV PORT=8000
EXPOSE 8000

CMD ["./start.sh"]
