import os
import socket
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from database import postgres


class PostgresConnectionConfigTest(unittest.TestCase):
    def tearDown(self):
        postgres._connection_url.cache_clear()

    def test_managed_dns_is_not_pinned_by_default(self):
        postgres._connection_url.cache_clear()
        with patch.object(
            postgres,
            "DATABASE_URL",
            "postgresql://user:secret@example.postgres.database.azure.com/app?sslmode=require",
        ), patch.dict(os.environ, {"POSTGRES_FORCE_IPV4": "0"}, clear=False), patch.object(
            postgres.socket,
            "getaddrinfo",
        ) as resolve:
            value = postgres._connection_url()

        resolve.assert_not_called()
        query = parse_qs(urlsplit(value).query)
        self.assertNotIn("hostaddr", query)
        self.assertEqual(query["connect_timeout"], ["20"])

    def test_ipv4_pin_is_an_explicit_escape_hatch(self):
        postgres._connection_url.cache_clear()
        address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.8", 5432))
        with patch.object(
            postgres,
            "DATABASE_URL",
            "postgresql://user:secret@example.test/app",
        ), patch.dict(os.environ, {"POSTGRES_FORCE_IPV4": "1"}, clear=False), patch.object(
            postgres.socket,
            "getaddrinfo",
            return_value=[address],
        ):
            value = postgres._connection_url()

        self.assertEqual(parse_qs(urlsplit(value).query)["hostaddr"], ["203.0.113.8"])


if __name__ == "__main__":
    unittest.main()
