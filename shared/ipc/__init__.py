"""Shared IPC primitives — vsock AF_HYPERV + mTLS transport layer."""

from shared.ipc.protocol import (
    AdjudicationRequest,
    AdjudicationResponse,
    MessageFramer,
    MessageType,
    ensure_int,
    require_bool,
    require_dict,
    require_int,
    require_list,
    require_str,
    require_str_list,
)
from shared.ipc.slash_commands import BACKEND_PASSTHROUGH_SLASH_COMMANDS
from shared.ipc.vsock import (
    VsockAddress,
    VsockConfig,
    VsockListener,
    VsockTransport,
    create_client_ssl_context,
    create_server_ssl_context,
)

__all__ = [
    "BACKEND_PASSTHROUGH_SLASH_COMMANDS",
    "AdjudicationRequest",
    "AdjudicationResponse",
    "MessageFramer",
    "MessageType",
    "VsockAddress",
    "VsockConfig",
    "VsockListener",
    "VsockTransport",
    "create_client_ssl_context",
    "create_server_ssl_context",
    "ensure_int",
    "require_bool",
    "require_dict",
    "require_int",
    "require_list",
    "require_str",
    "require_str_list",
]
