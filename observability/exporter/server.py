from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONNECT_URL = os.environ.get("CONNECT_URL", "http://connect:8083").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8080").rstrip("/")
PORT = int(os.environ.get("EXPORTER_PORT", "8080"))


class MetricsCollector:
    def __init__(self, connect_url: str, dashboard_url: str):
        self._connect_url = connect_url.rstrip("/")
        self._dashboard_url = dashboard_url.rstrip("/")

    def collect(self) -> str:
        metrics: list[str] = [
            "# HELP omnicare_exporter_up Exporter process health.",
            "# TYPE omnicare_exporter_up gauge",
            "omnicare_exporter_up 1",
        ]
        metrics.extend(self._connect_metrics())
        metrics.extend(self._dashboard_metrics())
        return "\n".join(metrics) + "\n"

    def _connect_metrics(self) -> list[str]:
        metrics = [
            "# HELP omnicare_kafka_connect_up Kafka Connect REST API availability.",
            "# TYPE omnicare_kafka_connect_up gauge",
            "# HELP omnicare_connector_running Debezium connector running state.",
            "# TYPE omnicare_connector_running gauge",
            "# HELP omnicare_connector_task_running Debezium connector task running state.",
            "# TYPE omnicare_connector_task_running gauge",
        ]
        try:
            names = http_json(f"{self._connect_url}/connectors")
            metrics.append("omnicare_kafka_connect_up 1")
            if not isinstance(names, list):
                raise RuntimeError("Kafka Connect /connectors did not return a list")
            for name in sorted(str(item) for item in names):
                status = http_json(f"{self._connect_url}/connectors/{name}/status")
                metrics.extend(connector_metrics(name, status))
        except Exception as exc:
            metrics.append("omnicare_kafka_connect_up 0")
            metrics.append(
                f'omnicare_observability_error{{component="connect",message="{label_value(str(exc))}"}} 1'
            )
        return metrics

    def _dashboard_metrics(self) -> list[str]:
        metrics = [
            "# HELP omnicare_dashboard_api_up Dashboard API availability.",
            "# TYPE omnicare_dashboard_api_up gauge",
            "# HELP omnicare_pipeline_snapshot_generated_at_seconds Dashboard snapshot generation epoch.",
            "# TYPE omnicare_pipeline_snapshot_generated_at_seconds gauge",
            "# HELP omnicare_pipeline_summary_value Current dashboard summary values.",
            "# TYPE omnicare_pipeline_summary_value gauge",
        ]
        try:
            payload = http_json(f"{self._dashboard_url}/api/dashboard")
            metrics.append("omnicare_dashboard_api_up 1")
            generated_at = numeric(payload.get("generatedAt"))
            metrics.append(f"omnicare_pipeline_snapshot_generated_at_seconds {generated_at}")
            summary = payload.get("summary") or {}
            for name, value in sorted(summary.items()):
                metrics.append(
                    f'omnicare_pipeline_summary_value{{metric="{label_value(name)}"}} {numeric(value)}'
                )
        except Exception as exc:
            metrics.append("omnicare_dashboard_api_up 0")
            metrics.append(
                f'omnicare_observability_error{{component="dashboard",message="{label_value(str(exc))}"}} 1'
            )
        return metrics


def connector_metrics(name: str, status: Any) -> list[str]:
    connector = status.get("connector") if isinstance(status, dict) else {}
    tasks = status.get("tasks") if isinstance(status, dict) else []
    connector_state = connector.get("state") if isinstance(connector, dict) else None
    metrics = [
        (
            f'omnicare_connector_running{{connector="{label_value(name)}"}} '
            f"{1 if connector_state == 'RUNNING' else 0}"
        )
    ]
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = label_value(str(task.get("id", "unknown")))
            state = task.get("state")
            metrics.append(
                f'omnicare_connector_task_running{{connector="{label_value(name)}",task="{task_id}"}} '
                f"{1 if state == 'RUNNING' else 0}"
            )
    return metrics


def http_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class Handler(BaseHTTPRequestHandler):
    collector = MetricsCollector(CONNECT_URL, DASHBOARD_URL)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send("ok\n", content_type="text/plain")
            return
        if self.path == "/metrics":
            self._send(self.collector.collect(), content_type="text/plain; version=0.0.4")
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("EXPORTER_ACCESS_LOG", "false").lower() == "true":
            super().log_message(format, *args)

    def _send(self, body: str, *, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"OmniCare metrics exporter listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
