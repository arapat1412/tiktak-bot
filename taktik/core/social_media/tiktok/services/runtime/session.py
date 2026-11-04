"""Package identity owned by one workflow invocation, never inferred from foreground."""

from contextlib import contextmanager
from contextvars import ContextVar

_package = ContextVar("tiktok_session_package", default=None)


def selected_package():
    return _package.get()


@contextmanager
def package_session(package):
    token = _package.set(package)
    try:
        yield
    finally:
        _package.reset(token)
