"""Error types. Every message is safe to show to the LLM and the user: no secrets, no stack traces."""


class ToolError(Exception):
    """A clean, user-facing failure of a Agent Studio tool."""


class ConfigError(ToolError):
    """tools.yaml missing/invalid, unknown connection, or a secret env var not set."""


class NotAllowed(ToolError):
    """The request is outside the allowlist or the read-only/approval policy."""


class ToolTimeout(ToolError):
    """The call exceeded its timeout."""


class UpstreamError(ToolError):
    """The target system answered with an error or could not be reached."""
