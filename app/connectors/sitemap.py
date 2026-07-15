import xml.etree.ElementTree as ET
from typing import Any

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap_locs(xml_text: str, tag: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [loc.text.strip() for loc in root.findall(f"sm:{tag}/sm:loc", _SITEMAP_NS) if loc.text]


def resolve_sitemap_cursor(config: dict[str, Any], url_count: int) -> int:
    """Read a sitemap-enumeration connector's persisted `sitemap_cursor` (BUG41), resetting
    to 0 when it's out of range -- the sitemap shrank, or a previous run walked all the way
    to the end -- so a run always makes forward progress instead of returning an empty page.
    """
    cursor = int(config.get("sitemap_cursor", 0) or 0)
    return cursor if 0 <= cursor < url_count else 0


def next_sitemap_cursor(final_cursor: int | None) -> int:
    """`None` means the run walked to the end of the sitemap -- wrap back to 0 so the next
    run starts a fresh pass instead of resuming past the end forever (BUG41).
    """
    return final_cursor if final_cursor is not None else 0
