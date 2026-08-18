"""Export session cookies from a browser profile to a Netscape cookies.txt file."""

import logging
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Optional

from yt_dlp.cookies import YDLLogger, extract_cookies_from_browser

logger = logging.getLogger(__name__)


def refresh(browser: str, output: Path, logger_instance: Optional[YDLLogger] = None) -> None:
    """Extract cookies from the given browser and write them to `output`."""
    logger.info("extracting cookies from browser: %s", browser)
    jar = extract_cookies_from_browser(browser, logger=logger_instance or YDLLogger())
    out = MozillaCookieJar(str(output))
    for cookie in jar:
        out.set_cookie(cookie)
    out.save(ignore_discard=True, ignore_expires=True)
    logger.info("wrote %d cookies to %s", len(jar), output)
