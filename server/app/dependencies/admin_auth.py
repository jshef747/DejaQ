from app.dependencies.management_auth import ManagementAuthContext


def require_management_auth() -> ManagementAuthContext:
    """FastAPI dependency: resolve the management auth context.

    Always returns an unauthenticated dev-admin context — local development
    only. The management API surface is protected by loopback binding
    (AdminLoopbackMiddleware), not by a credential.
    """
    return ManagementAuthContext.local_dev()
