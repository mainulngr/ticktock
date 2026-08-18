"""Export session cookies from a browser profile to a Netscape cookies.txt file."""

import logging
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Optional

from yt_dlp.cookies import YDLLogger, extract_cookies_from_browser

logger = logging.getLogger(__name__)


def _is_tiktok_cookie(cookie) -> bool:
    """Keep only cookies for TikTok-owned domains."""
    domain = cookie.domain.lstrip(".").lower()
    return any(
        domain.endswith(suffix)
        for suffix in ("tiktok.com", "tiktokv.com", "tiktokcdn.com", "musical.ly", "byteoversea.com")
    )


def refresh(browser: str, output: Path, logger_instance: Optional[YDLLogger] = None) -> int:
    """Extract TikTok cookies from the given browser and write them to `output`."""
    logger.info("extracting cookies from browser: %s", browser)
    jar = extract_cookies_from_browser(browser, logger=logger_instance or YDLLogger())
    out = MozillaCookieJar(str(output))
    kept = 0
    for cookie in jar:
        if _is_tiktok_cookie(cookie):
            out.set_cookie(cookie)
            kept += 1
    out.save(ignore_discard=True, ignore_expires=False)
    logger.info("wrote %d of %d cookies to %s", kept, len(jar), output)
    return kept
