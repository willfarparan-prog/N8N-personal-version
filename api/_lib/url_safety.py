"""Network destination validation shared by outbound nodes."""
import ipaddress
import socket
from urllib.parse import urlparse

def is_safe_public_https_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        return all(ipaddress.ip_address(item[4][0]).is_global for item in socket.getaddrinfo(parsed.hostname, None))
    except (socket.gaierror, ValueError):
        return False
