"""Offline verification of the test execution contract machinery."""

from __future__ import annotations

import socket
import unittest

from tests.isolation_support import (
    TEST_ENV_OVERRIDES,
    install_network_guard,
)


class TestEnvPinRegistryTests(unittest.TestCase):
    def test_pin_registry_matches_contracts_doc(self) -> None:
        from pathlib import Path

        contracts = (Path(__file__).resolve().parent.parent / "docs" / "CONTRACTS.md").read_text(
            encoding="utf-8"
        )
        for key in TEST_ENV_OVERRIDES:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", contracts)


class NetworkGuardTests(unittest.TestCase):
    def tearDown(self) -> None:
        install_network_guard()

    def test_blocks_non_loopback_connect(self) -> None:
        install_network_guard()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                sock.connect(("example.com", 80))
            self.assertIn("Test Execution Contract violation", str(ctx.exception))
        finally:
            sock.close()

    def test_allows_loopback_connect(self) -> None:
        install_network_guard()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Connection refused is fine — guard must not block loopback.
            with self.assertRaises(OSError):
                sock.connect(("127.0.0.1", 1))
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
