"""Rate-limit keying.

The API sits behind the Next.js proxy, so every request arrives from the proxy's address.
Keying limits on that address puts the whole site — and the admin — in one shared bucket:
ten visitors loading the calendar exhaust `/events/weekly` for everyone, and one failed
login attempt anywhere spends the 5/minute budget for all users.

So: trust `X-Forwarded-For` only when the immediate peer is a proxy we trust, and pick the
rightmost address that isn't itself a trusted proxy — the leftmost entry is client-supplied
and can be forged to dodge the limit or frame another IP.
"""
import ipaddress
import logging
import os

from fastapi import Request
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Loopback and RFC1918 by default: the proxy runs next to the API, not on the public internet.
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def _networks() -> list[ipaddress._BaseNetwork]:
    nets = []
    for raw in os.getenv("TRUSTED_PROXIES", _DEFAULT_TRUSTED).split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXIES: ignoring invalid entry %r", raw)
    return nets


TRUSTED_NETWORKS = _networks()


def _is_trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED_NETWORKS)


def client_ip(request: Request) -> str:
    """The address rate limits should count against."""
    peer = get_remote_address(request)
    if not _is_trusted(peer):
        # Direct connection — the peer is the client, headers are not to be believed.
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Rightmost entry that isn't a trusted proxy: everything to its left was supplied
        # by an untrusted hop and could be anything.
        for candidate in reversed([p.strip() for p in forwarded.split(",") if p.strip()]):
            if not _is_trusted(candidate):
                try:
                    ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                return candidate

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip and not _is_trusted(real_ip):
        try:
            ipaddress.ip_address(real_ip)
            return real_ip
        except ValueError:
            pass

    # Proxy sent nothing usable — fall back to the peer so the limit still applies.
    return peer
