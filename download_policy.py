from urllib.parse import urljoin, urlsplit


_DIRECT_HOSTS = {
    "drive.google.com",
    "docs.google.com",
    # Google Drive currently serves public downloads from this host.
    "drive.usercontent.google.com",
}


def is_allowed_pdf_url(url: str) -> bool:
    """Allow only HTTPS Google Drive download hosts used by the admin command."""
    if not url or len(url) > 4096:
        return False
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        return False
    if port not in (None, 443):
        return False
    return host in _DIRECT_HOSTS or host == "googleusercontent.com" or host.endswith(".googleusercontent.com")


def safe_redirect_url(current_url: str, location: str) -> str:
    target = urljoin(current_url, location or "")
    if not is_allowed_pdf_url(target):
        raise ValueError("Google Drive redirected to a disallowed download host")
    return target
