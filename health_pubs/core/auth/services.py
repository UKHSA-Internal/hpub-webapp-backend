import os
import glob
import browser_cookie3

from django.conf import settings

from ..utils import logging_utils

LOGGER = logging_utils.get_logger(__name__)


def list_chrome_profiles() -> list[str]:
    chrome_path = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    patterns = [
        os.path.join(chrome_path, "*", "Network", "Cookies"),
        os.path.join(chrome_path, "*", "Cookies"),
        os.path.join(chrome_path, "Default", "Network", "Cookies"),
        os.path.join(chrome_path, "Default", "Cookies"),
    ]
    profiles: list[str] = []
    for pattern in patterns:
        profiles.extend(glob.glob(pattern))
    return sorted(set(profile for profile in profiles if os.path.exists(profile)))


def get_cookies_from_chrome(cookies_path: str, domain_name: str):
    cookie_jar = browser_cookie3.chrome(cookie_file=cookies_path, domain_name=domain_name)
    cookies: dict[str, str] = {}
    for cookie in cookie_jar:
        if cookie.value is not None and domain_name in cookie.domain:
            cookies[cookie.name] = cookie.value
    return cookies


def get_access_token_from_browser():
    LOGGER.info('get_access_token_from_browser')
    domain = settings.HPUB_FRONT_END_URL
    LOGGER.debug(domain)
    for chrome_profile in list_chrome_profiles():
        LOGGER.debug(chrome_profile)
        cookies = get_cookies_from_chrome(chrome_profile, domain)
        if 'long_term_token' in cookies:
            access_token = cookies['long_term_token']
            return access_token
    return None
