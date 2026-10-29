from __future__ import annotations

import os
from dataclasses import dataclass

from mcp.server.transport_security import TransportSecuritySettings

LOCAL_HOSTS = ("localhost:*", "127.0.0.1:*", "[::1]:*")


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./sns.db"
    # Host headers the MCP endpoint accepts (DNS rebinding protection). "*" disables the check.
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS

    @classmethod
    def from_env(cls) -> Settings:
        hosts = os.environ.get("SNS_ALLOWED_HOSTS")
        return cls(
            database_url=os.environ.get("SNS_DATABASE_URL", cls.database_url),
            allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()) if hosts else LOCAL_HOSTS,
        )

    def transport_security(self) -> TransportSecuritySettings:
        if "*" in self.allowed_hosts:
            return TransportSecuritySettings(enable_dns_rebinding_protection=False)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(self.allowed_hosts),
            allowed_origins=[f"{scheme}://{host}" for host in self.allowed_hosts for scheme in ("http", "https")],
        )
