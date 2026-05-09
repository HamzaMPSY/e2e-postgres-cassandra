from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from omnicare_cdc.config import AppConfig
from omnicare_cdc.main import _consumer_settings


class ConfigTest(unittest.TestCase):
    def test_builds_secure_kafka_settings_from_env(self) -> None:
        env = {
            "KAFKA_BOOTSTRAP_SERVERS": "broker:9093",
            "KAFKA_GROUP_ID": "secure-transformer",
            "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
            "KAFKA_SASL_MECHANISM": "SCRAM-SHA-512",
            "KAFKA_SASL_USERNAME": "transformer",
            "KAFKA_SASL_PASSWORD": "change_me_transformer",
            "KAFKA_SSL_CA_LOCATION": "/certs/ca.pem",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        settings = _consumer_settings(config)

        self.assertEqual(settings["bootstrap.servers"], "broker:9093")
        self.assertEqual(settings["group.id"], "secure-transformer")
        self.assertEqual(settings["security.protocol"], "SASL_SSL")
        self.assertEqual(settings["sasl.mechanism"], "SCRAM-SHA-512")
        self.assertEqual(settings["sasl.username"], "transformer")
        self.assertEqual(settings["sasl.password"], "change_me_transformer")
        self.assertEqual(settings["ssl.ca.location"], "/certs/ca.pem")


if __name__ == "__main__":
    unittest.main()
