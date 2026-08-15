"""User-safe web application errors."""

class WebAppError(RuntimeError):
    """An expected error whose message is safe to display."""
