from __future__ import annotations

import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: dict[str, int] = defaultdict(int)
        self._dlq_records: dict[str, int] = defaultdict(int)
        self._rows_written = 0
        self._write_latency_count = 0
        self._write_latency_sum = 0.0
        self._write_latency_max = 0.0

    def record_success(self, rows_written: int) -> None:
        with self._lock:
            self._messages["success"] += 1
            self._rows_written += rows_written

    def record_dlq(self, source_topic: str) -> None:
        with self._lock:
            self._messages["dlq"] += 1
            self._dlq_records[source_topic] += 1

    def observe_cassandra_write(self, elapsed_seconds: float) -> None:
        with self._lock:
            self._write_latency_count += 1
            self._write_latency_sum += elapsed_seconds
            self._write_latency_max = max(self._write_latency_max, elapsed_seconds)

    def render_prometheus(self) -> str:
        with self._lock:
            messages = dict(self._messages)
            dlq_records = dict(self._dlq_records)
            rows_written = self._rows_written
            latency_count = self._write_latency_count
            latency_sum = self._write_latency_sum
            latency_max = self._write_latency_max

        lines = [
            "# HELP omnicare_transformer_up Transformer process health.",
            "# TYPE omnicare_transformer_up gauge",
            "omnicare_transformer_up 1",
            "# HELP omnicare_transformer_messages_processed_total Processed CDC messages by result.",
            "# TYPE omnicare_transformer_messages_processed_total counter",
        ]
        for result in ("success", "dlq"):
            lines.append(
                f'omnicare_transformer_messages_processed_total{{result="{result}"}} '
                f"{messages.get(result, 0)}"
            )

        lines.extend(
            [
                "# HELP omnicare_transformer_rows_written_total Cassandra star-schema rows written.",
                "# TYPE omnicare_transformer_rows_written_total counter",
                f"omnicare_transformer_rows_written_total {rows_written}",
                "# HELP omnicare_transformer_dlq_records_total DLQ records by source topic.",
                "# TYPE omnicare_transformer_dlq_records_total counter",
            ]
        )
        for topic, count in sorted(dlq_records.items()):
            lines.append(
                f'omnicare_transformer_dlq_records_total{{source_topic="{_label_value(topic)}"}} {count}'
            )

        lines.extend(
            [
                "# HELP omnicare_transformer_cassandra_write_latency_seconds Cassandra write latency summary.",
                "# TYPE omnicare_transformer_cassandra_write_latency_seconds summary",
                f"omnicare_transformer_cassandra_write_latency_seconds_count {latency_count}",
                f"omnicare_transformer_cassandra_write_latency_seconds_sum {latency_sum:.9f}",
                f"omnicare_transformer_cassandra_write_latency_seconds_max {latency_max:.9f}",
            ]
        )
        return "\n".join(lines) + "\n"


def start_metrics_server(registry: MetricsRegistry, host: str, port: int) -> ThreadingHTTPServer:
    handler = _handler(registry)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _handler(registry: MetricsRegistry) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send("ok\n", "text/plain")
                return
            if self.path == "/metrics":
                self._send(registry.render_prometheus(), "text/plain; version=0.0.4")
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return MetricsHandler


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
