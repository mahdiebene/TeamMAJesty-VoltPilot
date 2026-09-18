"""Runtime-only secrets and validated, deliberately small configuration surface."""

import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = ""
    attempt_seconds: float = 10.0
    deadline_seconds: float = 25.0
    concurrency: int = 2
    max_pending: int = 6
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (not math.isfinite(self.deadline_seconds) or not 0 < self.deadline_seconds < 30
                or not math.isfinite(self.attempt_seconds)
                or not 0 < self.attempt_seconds <= self.deadline_seconds):
            raise ValueError("Invalid request timeout configuration")
        if not 1 <= self.concurrency <= self.max_pending <= 32:
            raise ValueError("Invalid concurrency configuration")
        if self.base_url:
            url = urlsplit(self.base_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment):
                raise ValueError("Model base URL must be credential-free HTTPS")
        if any(c in self.api_key for c in "\r\n"):
            raise ValueError("Invalid API key format")
        for origin in self.cors_origins:
            url = urlsplit(origin)
            if (url.scheme not in ("https", "http") or not url.hostname
                    or url.username or url.password or url.path or url.query or url.fragment
                    or any(c.isspace() for c in origin) or "*" in origin):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
            if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Remote browser origins must use HTTPS")
            _ = url.port  # Reject malformed ports before accepting configuration.

    @property
    def ready(self) -> bool:
        return all(value.strip() for value in (self.api_key, self.base_url, self.model))

    @classmethod
    def from_environment(cls) -> "Settings":
        # No implicit .env loading and no printing of configuration/secret values.
        try:
            return cls(
                api_key=os.getenv("LLM_API_KEY", ""),
                base_url=os.getenv("LLM_BASE_URL", ""),
                model=os.getenv("LLM_MODEL", ""),
                attempt_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "10")),
                deadline_seconds=float(os.getenv("REQUEST_DEADLINE_SECONDS", "25")),
                concurrency=int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")),
                max_pending=int(os.getenv("MAX_PENDING_REQUESTS", "6")),
                cors_origins=tuple(origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",")
                                   if origin.strip()),
            )
        except (ValueError, OverflowError):
            raise ValueError("Invalid GridWise environment configuration") from None