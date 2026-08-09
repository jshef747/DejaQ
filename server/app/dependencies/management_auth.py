from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagementAuthContext:
    """Identity of a management-API caller.

    There is exactly one caller: the unauthenticated dev-admin. The management
    surface is protected by loopback binding (AdminLoopbackMiddleware), not by a
    credential, so the context carries an identity for /whoami and nothing else.
    """

    email: str | None = None

    @classmethod
    def local_dev(cls) -> "ManagementAuthContext":
        """Dev-admin context used for all management API requests.

        Carries a friendly email so /whoami reads sensibly. Local development
        only — never expose remotely.
        """
        return cls(email="dev@localhost")
