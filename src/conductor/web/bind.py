"""Where the dashboard binds its socket.

Split out of the call sites so the three of them cannot drift: the live
dashboard is constructed in both ``run_workflow_async`` and
``resume_workflow_async`` (``cli/run.py``), and the replay dashboard in
``cli/app.py``. Conductor's run/resume parity rule already covers the first
two; the replay path is the one an earlier local `sed` over ``host="127.0.0.1"``
missed, which is exactly the drift a shared helper removes.
"""

from __future__ import annotations

import os

DASHBOARD_HOST_ENV = "CONDUCTOR_WEB_HOST"
"""Environment variable naming the interface the dashboard binds to."""

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
"""Loopback, and the value used whenever the variable is unset or empty."""


def resolve_dashboard_host() -> str:
    """Return the interface the dashboard should bind to.

    ``127.0.0.1`` unless :data:`DASHBOARD_HOST_ENV` names another one, so
    behaviour is unchanged for anyone who does not set it. An empty or
    whitespace-only value is treated as unset rather than as a request to
    bind every interface, since an exported-but-empty variable is far more
    often a shell accident than an intent to expose the dashboard.

    Two things this deliberately does not do. It does not validate the
    value — an unbindable host surfaces as uvicorn's own startup error,
    which names the address, where a pre-flight check here could only
    repeat it worse. And it does not widen
    :func:`conductor.web.auth.allowed_hosts`: the ``Host`` header still has
    to name the bound interface (or a loopback alias), so a dashboard bound
    to ``0.0.0.0`` answers only ``localhost`` requests and returns 403 to
    every LAN browser. Set the concrete LAN address rather than
    ``0.0.0.0`` — that address then joins the allowed set and the guard
    keeps doing its job.

    Returns:
        The host string to hand to ``WebDashboard`` / ``ReplayDashboard``.
    """
    return os.environ.get(DASHBOARD_HOST_ENV, "").strip() or DEFAULT_DASHBOARD_HOST
