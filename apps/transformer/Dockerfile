FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=120

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src

RUN pip install --no-cache-dir .

ENV TRANSFORMER_METRICS_ENABLED=true
ENV TRANSFORMER_METRICS_PORT=8090

EXPOSE 8090

CMD ["omnicare-cdc-transformer"]
