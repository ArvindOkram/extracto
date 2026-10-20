"""Network address rules. Pure; DNS resolution happens in adapters."""

from __future__ import annotations

import ipaddress


def is_public_ip(ip: str) -> bool:
    """True only for globally routable unicast addresses (not private, loopback, link-local)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast
