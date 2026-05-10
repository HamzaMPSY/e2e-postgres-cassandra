from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


CONNECT_URL = os.environ.get("CONNECT_URL", "http://connect:8083").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8080").rstrip("/")
JOLOKIA_URL = os.environ.get("JOLOKIA_URL", "").rstrip("/")
TRANSFORMER_METRICS_URL = os.environ.get("TRANSFORMER_METRICS_URL", "").rstrip("/")
PORT = int(os.environ.get("EXPORTER_PORT", "8080"))


class MetricsCollector:
    def __init__(
        self,
        connect_url: str,
        dashboard_url: str,
        jolokia_url: str = "",
        transformer_metrics_url: str = "",
    ):
        self._connect_url = connect_url.rstrip("/")
        self._dashboard_url = dashboard_url.rstrip("/")
        self._jolokia_url = jolokia_url.rstrip("/")
        self._transformer_metrics_url = transformer_metrics_url.rstrip("/")

    def collect(self) -> str:
        metrics: list[str] = [
            "# HELP omnicare_exporter_up Exporter process health.",
            "# TYPE omnicare_exporter_up gauge",
            "omnicare_exporter_up 1",
        ]
        metrics.extend(self._connect_metrics())
        metrics.extend(self._debezium_jmx_metrics())
        metrics.extend(self._transformer_quality_metrics())
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

    def _debezium_jmx_metrics(self) -> list[str]:
        metrics = [
            "# HELP omnicare_debezium_jmx_up Debezium Jolokia/JMX availability.",
            "# TYPE omnicare_debezium_jmx_up gauge",
            "# HELP omnicare_debezium_source_lag_milliseconds Debezium streaming source lag.",
            "# TYPE omnicare_debezium_source_lag_milliseconds gauge",
            "# HELP omnicare_debezium_events_seen_total Debezium events seen by connector.",
            "# TYPE omnicare_debezium_events_seen_total counter",
            "# HELP omnicare_debezium_events_filtered_total Debezium events filtered by connector.",
            "# TYPE omnicare_debezium_events_filtered_total counter",
        ]
        if not self._jolokia_url:
            metrics.append("omnicare_debezium_jmx_up 0")
            return metrics

        try:
            metrics.append("omnicare_debezium_jmx_up 1")
            metrics.extend(debezium_jolokia_metrics(self._jolokia_url))
        except Exception as exc:
            metrics.append("omnicare_debezium_jmx_up 0")
            metrics.append(
                f'omnicare_observability_error{{component="debezium_jmx",message="{label_value(str(exc))}"}} 1'
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
            "# HELP omnicare_data_quality_check_passed Dashboard data quality check pass state.",
            "# TYPE omnicare_data_quality_check_passed gauge",
            "# HELP omnicare_data_quality_check_status Dashboard data quality check status by state.",
            "# TYPE omnicare_data_quality_check_status gauge",
            "# HELP omnicare_data_quality_check_detail_value Numeric dashboard data quality check details.",
            "# TYPE omnicare_data_quality_check_detail_value gauge",
            "# HELP omnicare_data_quality_overall_status Dashboard data quality overall status.",
            "# TYPE omnicare_data_quality_overall_status gauge",
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
            metrics.extend(data_quality_metrics(payload.get("dataQuality") or {}))
        except Exception as exc:
            metrics.append("omnicare_dashboard_api_up 0")
            metrics.append(
                f'omnicare_observability_error{{component="dashboard",message="{label_value(str(exc))}"}} 1'
            )
        return metrics

    def _transformer_quality_metrics(self) -> list[str]:
        metrics = [
            "# HELP omnicare_quality_dlq_records_total Transformer DLQ records visible to quality monitoring.",
            "# TYPE omnicare_quality_dlq_records_total counter",
            "# HELP omnicare_quality_quarantine_records_total Transformer validation rejects visible to quality monitoring.",
            "# TYPE omnicare_quality_quarantine_records_total counter",
        ]
        if not self._transformer_metrics_url:
            metrics.extend(
                [
                    "omnicare_quality_dlq_records_total 0",
                    "omnicare_quality_quarantine_records_total 0",
                ]
            )
            return metrics
        try:
            text = http_text(self._transformer_metrics_url)
            metrics.append(
                "omnicare_quality_dlq_records_total "
                f"{prometheus_metric_sum(text, 'omnicare_transformer_dlq_records_total')}"
            )
            metrics.append(
                "omnicare_quality_quarantine_records_total "
                f"{prometheus_metric_sum(text, 'omnicare_transformer_validation_rejects_total')}"
            )
        except Exception as exc:
            metrics.extend(
                [
                    "omnicare_quality_dlq_records_total 0",
                    "omnicare_quality_quarantine_records_total 0",
                    f'omnicare_observability_error{{component="transformer_metrics",message="{label_value(str(exc))}"}} 1',
                ]
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


def data_quality_metrics(data_quality: Any) -> list[str]:
    if not isinstance(data_quality, dict):
        return []
    overall = str(data_quality.get("overallStatus") or "unknown")
    metrics = [
        (
            f'omnicare_data_quality_overall_status{{status="{label_value(status)}"}} '
            f"{1 if overall == status else 0}"
        )
        for status in ("pass", "warn", "fail")
    ]
    checks = data_quality.get("checks") or []
    if not isinstance(checks, list):
        return metrics
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = label_value(str(check.get("name") or "unknown"))
        status = str(check.get("status") or "unknown")
        metrics.append(
            f'omnicare_data_quality_check_passed{{check="{name}",status="{label_value(status)}"}} '
            f"{1 if status == 'pass' else 0}"
        )
        for expected_status in ("pass", "warn", "fail"):
            metrics.append(
                "omnicare_data_quality_check_status"
                f'{{check="{name}",status="{expected_status}"}} '
                f"{1 if status == expected_status else 0}"
            )
        details = check.get("details") or {}
        if isinstance(details, dict):
            for key, value in sorted(details.items()):
                if isinstance(value, int | float) and not isinstance(value, bool):
                    metrics.append(
                        "omnicare_data_quality_check_detail_value"
                        f'{{check="{name}",metric="{label_value(str(key))}"}} '
                        f"{numeric(value)}"
                    )
    return metrics


def prometheus_metric_sum(text: str, metric_name: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, raw_value = line.partition(" ")
        if name == metric_name or name.startswith(f"{metric_name}{{"):
            total += numeric(raw_value.strip())
    return total


def debezium_jolokia_metrics(jolokia_url: str) -> list[str]:
    pattern = "debezium.*:type=connector-metrics,context=*,*"
    search = http_json(f"{jolokia_url}/search/{quote(pattern, safe=':,*=')}")
    mbeans = search.get("value") if isinstance(search, dict) else []
    if not isinstance(mbeans, list):
        raise RuntimeError("Jolokia search did not return a list")

    metrics: list[str] = []
    for mbean in sorted(str(item) for item in mbeans):
        payload = http_json(f"{jolokia_url}/read/{quote(mbean, safe='')}")
        values = payload.get("value") if isinstance(payload, dict) else {}
        if not isinstance(values, dict):
            continue
        labels = debezium_labels(mbean)
        lag = _first_metric_value(
            values,
            ("MilliSecondsBehindSource", "MillisecondsBehindSource"),
        )
        if lag is not None:
            metrics.append(
                f"omnicare_debezium_source_lag_milliseconds{labels} {lag}"
            )
        events_seen = _metric_value(values, "TotalNumberOfEventsSeen")
        if events_seen is not None:
            metrics.append(f"omnicare_debezium_events_seen_total{labels} {events_seen}")
        events_filtered = _metric_value(values, "NumberOfEventsFiltered")
        if events_filtered is not None:
            metrics.append(
                f"omnicare_debezium_events_filtered_total{labels} {events_filtered}"
            )
    return metrics


def debezium_labels(mbean: str) -> str:
    domain, _, properties = mbean.partition(":")
    parsed: dict[str, str] = {"domain": domain}
    for item in properties.split(","):
        key, separator, value = item.partition("=")
        if separator:
            parsed[key] = value

    connector = parsed.get("server") or parsed.get("connector") or parsed.get("name") or "unknown"
    context = parsed.get("context") or "unknown"
    return (
        f'{{connector="{label_value(connector)}",'
        f'context="{label_value(context)}",'
        f'domain="{label_value(parsed.get("domain", "unknown"))}"}}'
    )


def _metric_value(values: dict[str, Any], name: str) -> float | None:
    value = values.get(name)
    if value is None:
        return None
    return numeric(value)


def _first_metric_value(values: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        metric = _metric_value(values, name)
        if metric is not None:
            return metric
    return None


def http_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str) -> str:
    request = Request(url, headers={"Accept": "text/plain"})
    with urlopen(request, timeout=8) as response:
        return response.read().decode("utf-8")


def label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class Handler(BaseHTTPRequestHandler):
    collector = MetricsCollector(
        CONNECT_URL,
        DASHBOARD_URL,
        JOLOKIA_URL,
        TRANSFORMER_METRICS_URL,
    )

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
