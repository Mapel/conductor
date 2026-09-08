"""Where the dashboard binds, and that every call site asks the same helper."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conductor.web.bind import (
    DASHBOARD_HOST_ENV,
    DEFAULT_DASHBOARD_HOST,
    resolve_dashboard_host,
)


class TestResolveDashboardHost:
    def test_unset_stays_on_loopback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the default: nobody who ignores the variable
        gets a dashboard on a wider interface than before."""
        monkeypatch.delenv(DASHBOARD_HOST_ENV, raising=False)
        assert resolve_dashboard_host() == DEFAULT_DASHBOARD_HOST == "127.0.0.1"

    def test_a_named_host_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DASHBOARD_HOST_ENV, "192.168.1.50")
        assert resolve_dashboard_host() == "192.168.1.50"

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_blank_is_treated_as_unset(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exported-but-empty variable is a shell accident far more often
        than a request to bind everything. Passing ``""`` to uvicorn binds all
        interfaces, so the empty case must not fall through."""
        monkeypatch.setenv(DASHBOARD_HOST_ENV, value)
        assert resolve_dashboard_host() == DEFAULT_DASHBOARD_HOST

    def test_surrounding_whitespace_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DASHBOARD_HOST_ENV, "  0.0.0.0\n")
        assert resolve_dashboard_host() == "0.0.0.0"


class TestEveryBindSiteUsesTheHelper:
    """A source scan, because the failure mode is a *missed* call site.

    The predecessor of this helper was a local `sed` over ``host="127.0.0.1"``
    in ``cli/run.py``. It covered the run and resume dashboards and silently
    missed the replay one in ``cli/app.py``, which then stayed loopback-only
    with no error anywhere. A behavioural test of the two known sites could
    not have caught that; only enumerating the sites can.
    """

    _DASHBOARDS = frozenset({"WebDashboard", "ReplayDashboard"})

    @staticmethod
    def _dashboard_constructions() -> list[tuple[str, int, ast.keyword | None]]:
        """Return ``(file, line, host_kwarg)`` for every dashboard construction."""
        src_root = Path(__file__).resolve().parents[2] / "src" / "conductor"
        found: list[tuple[str, int, ast.keyword | None]] = []
        for path in src_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id not in TestEveryBindSiteUsesTheHelper._DASHBOARDS:
                    continue
                host = next((k for k in node.keywords if k.arg == "host"), None)
                found.append((str(path.relative_to(src_root)), node.lineno, host))
        return found

    def test_the_scan_finds_the_known_sites(self) -> None:
        """Negative control: a scan that quietly matches nothing would report
        "all clear" forever."""
        sites = self._dashboard_constructions()
        files = {f for f, _, _ in sites}
        assert files == {"cli/run.py", "cli/app.py"}, sites
        assert len([s for s in sites if s[0] == "cli/run.py"]) == 2, sites

    def test_no_site_hardcodes_a_host(self) -> None:
        offenders = [
            f"{f}:{line}"
            for f, line, host in self._dashboard_constructions()
            if host is not None and isinstance(host.value, ast.Constant)
        ]
        assert not offenders, f"dashboard host hardcoded at: {offenders}"

    def test_every_site_calls_the_helper(self) -> None:
        for f, line, host in self._dashboard_constructions():
            assert host is not None, f"{f}:{line} passes no host= at all"
            assert isinstance(host.value, ast.Call), f"{f}:{line} host= is not a call"
            assert isinstance(host.value.func, ast.Name), f"{f}:{line}"
            assert host.value.func.id == "resolve_dashboard_host", f"{f}:{line}"


class TestHostGuardInteraction:
    """`0.0.0.0` binds everywhere and is reachable from nowhere but loopback.

    Documented on the helper, asserted here so the claim cannot rot: the
    ``Host`` guard builds its allowlist from the *bound* host and explicitly
    drops the wildcard, so a LAN browser's ``Host`` header is refused. Naming
    the concrete address is what actually works.
    """

    def test_wildcard_bind_refuses_a_lan_host_header(self) -> None:
        from conductor.web.auth import check_origin_host

        reason = check_origin_host({"host": "192.168.1.50:8000"}, "0.0.0.0", 8000)
        assert reason is not None
        assert "not allowed" in reason

    def test_naming_the_address_admits_it(self) -> None:
        from conductor.web.auth import check_origin_host

        assert check_origin_host({"host": "192.168.1.50:8000"}, "192.168.1.50", 8000) is None

    def test_loopback_still_works_either_way(self) -> None:
        from conductor.web.auth import check_origin_host

        for bound in ("0.0.0.0", "192.168.1.50", "127.0.0.1"):
            assert check_origin_host({"host": "127.0.0.1:8000"}, bound, 8000) is None
