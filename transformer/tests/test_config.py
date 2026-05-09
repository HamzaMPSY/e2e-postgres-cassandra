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

    def test_builds_business_guardrail_config_from_env(self) -> None:
        env = {
            "MAX_PAYMENT_AMOUNT_CENTS": "250000",
            "PAYMENT_OVERPAY_TOLERANCE_CENTS": "500",
            "REFERENCE_VALIDATION_MODE": "strict",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        self.assertEqual(config.max_payment_amount_cents, 250000)
        self.assertEqual(config.payment_overpay_tolerance_cents, 500)
        self.assertEqual(config.reference_validation_mode, "strict")

    def test_rejects_invalid_reference_validation_mode(self) -> None:
        with patch.dict(os.environ, {"REFERENCE_VALIDATION_MODE": "unsafe"}, clear=False):
            with self.assertRaises(ValueError):
                AppConfig.from_env()


if __name__ == "__main__":
    unittest.main()
