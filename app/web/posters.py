"""Posters for the browser: the sites the page may load pictures from (`img-src`). The address of a picture is made by
`app.tracker.posters` (shared with the bot card); the browser takes the pictures straight from the sites."""

import ipaddress
from urllib.parse import urlsplit

from app.tracker.core import IGDB_IMAGE_SITE, TMDB_IMAGE_SITE, shikimori_site


def image_sources(shikimori_base_url: str) -> tuple[str, ...]:
    """The sites pictures may be loaded from, for `img-src`: TMDb, IGDB, and Shikimori with its subdomains (the address
    is the start of SHIKIMORI_BASE_URL). A base address that is not an `https` site gives only TMDb and IGDB."""
    return (TMDB_IMAGE_SITE, IGDB_IMAGE_SITE, *_site_with_subdomains(shikimori_base_url))


def _site_with_subdomains(address: str) -> tuple[str, ...]:
    site = shikimori_site(address)
    if site is None:
        return ()
    try:
        ipaddress.ip_address(urlsplit(site).hostname or "")
    except ValueError:
        return (site, site.replace("https://", "https://*.", 1))
    return (site,)  # an address of numbers has no subdomains
