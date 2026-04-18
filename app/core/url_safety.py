import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl

BLOCKED_HOSTS = {"localhost"}


def _get_host(value: AnyHttpUrl | str) -> str:
    if hasattr(value, "host"):
        host = getattr(value, "host", None)
    else:
        host = urlsplit(str(value)).hostname
    return (host or "").lower()


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # 198.18.0.0/15 is reserved for benchmarking, but widely used by local 
    # transparent proxies (e.g. Clash 'Fake IP'). We allow it here to ensure 
    # connectivity in these environments while still blocking true private ranges.
    if isinstance(ip, ipaddress.IPv4Address):
        # Check if IP is in 198.18.0.0/15
        octets = ip.packed
        if octets[0] == 198 and (octets[1] & 0xfe) == 18:
            return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_url(value: AnyHttpUrl | str) -> AnyHttpUrl | str:
    host = _get_host(value)
    if not host:
        raise ValueError("A valid public URL is required.")
    if host in BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError(f"URL host '{host}' is on the blocklist or is a local network address.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return value

    if _is_disallowed_ip(ip):
        raise ValueError(f"The IP address '{ip}' is a private or reserved network address and cannot be accessed.")

    return value


async def ensure_public_url_target(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("A valid public URL is required.")

    validate_public_url(url)

    host = _get_host(url)
    try:
        ipaddress.ip_address(host)
        return url
    except ValueError:
        pass

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_running_loop()

    try:
        results = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise ValueError("Could not resolve URL host.") from exc

    addresses = {item[4][0] for item in results if item[4]}
    if not addresses:
        raise ValueError("Could not resolve URL host.")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if _is_disallowed_ip(ip):
            raise ValueError(f"The resolved IP '{ip}' for host '{host}' is a private network address.")

    return url
