"""Request helpers shared by API routers."""

from __future__ import annotations

from ipaddress import ip_address, ip_network

from fastapi import Request

from app.config import config


def get_client_ip(request: Request) -> str | None:
    """Return a stable client IP, trusting forwarded headers only from known proxies."""
    direct_host = request.client.host if request.client else None
    if not direct_host:
        return None

    if _is_trusted_proxy(direct_host):
        forwarded_for = request.headers.get("x-forwarded-for")
        forwarded_ip = _first_forwarded_ip(forwarded_for)
        if forwarded_ip:
            return forwarded_ip

    return _normalize_ip(direct_host)


def should_use_secure_auth_cookie(request: Request) -> bool:
    """Return whether auth cookies should be marked Secure for this request."""
    if not config.auth_cookie_secure:
        return False
    if config.is_production:
        return True
    return _request_is_https(request)


def _request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True

    direct_host = request.client.host if request.client else None
    if direct_host and _is_trusted_proxy(direct_host):
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        proto = forwarded_proto.split(",", 1)[0].strip().lower()
        return proto == "https"

    return False


def _first_forwarded_ip(forwarded_for: str | None) -> str | None:
    if not forwarded_for:
        return None
    for value in forwarded_for.split(","):
        normalized = _normalize_ip(value.strip())
        if normalized:
            return normalized
    return None


def _is_trusted_proxy(host: str) -> bool:
    normalized_host = _normalize_ip(host)
    if not normalized_host:
        return False

    host_ip = ip_address(normalized_host)
    for raw_entry in config.auth_trusted_proxy_ips.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            network = ip_network(entry, strict=False)
        except ValueError:
            continue
        if host_ip in network:
            return True
    return False


def _normalize_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ip_address(value))
    except ValueError:
        return None
