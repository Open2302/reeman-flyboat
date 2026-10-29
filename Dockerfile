# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# The runtime stage depends on this stage: a failed test stops the image build.
FROM base AS test
COPY backend/server.py backend/test_server.py ./backend/
COPY code/ ./code/
RUN python backend/test_server.py

FROM base AS runtime
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir /data \
    && chown app:app /data
COPY --from=test --chown=app:app /app/backend/server.py ./backend/server.py
COPY --from=test --chown=app:app /app/code/ ./code/
ENV DATA_DIR=/data
USER app:app
EXPOSE 8000
CMD ["python", "backend/server.py", "--host", "0.0.0.0", "--port", "8000"]
