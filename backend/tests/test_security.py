"""Tests for client-IP resolution used by the rate limiter."""

from starlette.requests import Request

from app.middleware.security import _client_ip


def _request(headers: dict[str, str], peer: str = "10.0.0.5") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/news",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 12345),
        }
    )


class TestClientIp:
    def test_trusted_proxy_header_wins(self):
        req = _request({"X-Orbis-Client-IP": "203.0.113.7", "X-Forwarded-For": "1.1.1.1"})
        assert _client_ip(req, trusted=True) == "203.0.113.7"

    def test_proxy_header_ignored_when_untrusted(self):
        req = _request({"X-Orbis-Client-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.2"})
        assert _client_ip(req) == "198.51.100.2"

    def test_uses_rightmost_forwarded_entry(self):
        """The left entries are client-supplied; the ingress appends the real peer last."""
        req = _request({"X-Forwarded-For": "6.6.6.6, 198.51.100.2"})
        assert _client_ip(req) == "198.51.100.2"

    def test_falls_back_to_socket_peer(self):
        assert _client_ip(_request({})) == "10.0.0.5"


class TestMiddlewareTrust:
    """The proxy's client-IP header is honoured only for a matched, configured key."""

    def _resolved_ip(self, monkeypatch, configured_key: str, headers: dict[str, str]) -> str:
        from app.middleware import security

        monkeypatch.setattr(security.settings, "api_key", configured_key)
        return security._rate_limit_ip(_request(headers))

    def test_trusted_with_matching_key(self, monkeypatch):
        headers = {"X-API-Key": "k", "X-Orbis-Client-IP": "203.0.113.7"}
        assert self._resolved_ip(monkeypatch, "k", headers) == "203.0.113.7"

    def test_not_trusted_when_no_key_configured(self, monkeypatch):
        headers = {"X-Orbis-Client-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.2"}
        assert self._resolved_ip(monkeypatch, "", headers) == "198.51.100.2"
