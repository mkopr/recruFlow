import xml.etree.ElementTree as ET

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _parse_sitemap_locs(xml_text: str, tag: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [loc.text.strip() for loc in root.findall(f"sm:{tag}/sm:loc", _SITEMAP_NS) if loc.text]
