FROM python:3.11-slim

WORKDIR /app
COPY app /app

ENV DASHBOARD_PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
