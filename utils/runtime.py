"""Runtime bootstrap shared by the app and command-line scripts.

Keeps local HTTPS behaviour deterministic on macOS by pointing Python clients
at certifi's CA bundle, without disabling certificate verification.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


def configure_runtime() -> None:
    """Configure TLS CA paths and a conservative application logger."""
    try:
        import certifi
    except ImportError:
        certifi = None

    if certifi is not None:
        ca_bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)

    # Avoid reconfiguring host applications that already installed handlers.
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
