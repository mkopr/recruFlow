import logging
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from app.connectors import we_work_remotely
from app.connectors.we_work_remotely import (
    WE_WORK_REMOTELY_RSS_URL,
    _extract_rss_items,
    _join_location,
    _parse_posted_at,
    _parse_salary_ceiling,
    _split_company_and_title,
    fetch_page,
    map_offer,
)
from app.ingestion.normalize import WE_WORK_REMOTELY
from app.ingestion.registry import CONNECTOR_REGISTRY

_FIXTURE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>We Work Remotely</title>
    <item>
      <title>Acme Corp: Senior Backend Engineer</title>
      <region>Anywhere in the World</region>
      <country></country>
      <state>California</state>
      <skills>Python, Django, PostgreSQL</skills>
      <category>Programming</category>
      <type>Full-Time</type>
      <description>&lt;p&gt;&lt;strong&gt;Headquarters:&lt;/strong&gt; San Francisco&lt;/p&gt;\
&lt;p&gt;&lt;strong&gt;Up to USD 120,000&lt;/strong&gt; per year&lt;/p&gt;</description>
      <pubDate>Tue, 14 Jul 2026 15:29:26 +0000</pubDate>
      <guid>https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer</guid>
      <link>https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer</link>
    </item>
    <item>
      <title>Widgets Inc: Product Designer</title>
      <region>Anywhere in the World</region>
      <country>Germany</country>
      <state></state>
      <skills></skills>
      <category>Design</category>
      <type>Contract</type>
      <description>&lt;p&gt;A great design role, no pay details here.&lt;/p&gt;</description>
      <pubDate>Mon, 13 Jul 2026 09:00:00 +0000</pubDate>
      <guid>https://weworkremotely.com/remote-jobs/widgets-inc-product-designer</guid>
      <link>https://weworkremotely.com/remote-jobs/widgets-inc-product-designer</link>
    </item>
  </channel>
</rss>
"""

_FIXTURE_RSS_EMPTY_CHANNEL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel></channel></rss>
"""

_FIXTURE_RSS_NO_CHANNEL = """<?xml version="1.0" encoding="UTF-8"?>
<foo></foo>
"""


def test_extract_rss_items_returns_one_dict_per_item() -> None:
    root = ET.fromstring(_FIXTURE_RSS)

    items = _extract_rss_items(root, url=WE_WORK_REMOTELY_RSS_URL)

    assert items is not None
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Acme Corp: Senior Backend Engineer"
    assert first["region"] == "Anywhere in the World"
    assert first["country"] is None
    assert first["state"] == "California"
    assert first["skills"] == "Python, Django, PostgreSQL"
    assert first["category"] == "Programming"
    assert first["type"] == "Full-Time"
    assert first["pubDate"] == "Tue, 14 Jul 2026 15:29:26 +0000"
    assert (
        first["guid"] == "https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer"
    )
    assert (
        first["link"] == "https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer"
    )
    assert "Up to USD 120,000" in (first["description"] or "")


def test_extract_rss_items_returns_empty_list_for_channel_with_no_items() -> None:
    root = ET.fromstring(_FIXTURE_RSS_EMPTY_CHANNEL)

    items = _extract_rss_items(root, url=WE_WORK_REMOTELY_RSS_URL)

    assert items == []


def test_extract_rss_items_returns_none_when_no_channel_element() -> None:
    root = ET.fromstring(_FIXTURE_RSS_NO_CHANNEL)

    items = _extract_rss_items(root, url=WE_WORK_REMOTELY_RSS_URL)

    assert items is None


def test_fetch_page_returns_none_and_logs_unexpected_feed_shape_when_extraction_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        we_work_remotely, "fetch_xml", lambda *a, **kw: ET.fromstring(_FIXTURE_RSS_NO_CHANNEL)
    )

    with caplog.at_level(logging.ERROR):
        result = fetch_page(cursor=0, page_size=1)

    assert result is None
    assert any(
        "We Work Remotely returned unexpected feed shape" in record.message
        for record in caplog.records
    )


def test_fetch_page_returns_none_when_fetch_xml_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(we_work_remotely, "fetch_xml", lambda *a, **kw: None)

    result = fetch_page(cursor=0, page_size=1)

    assert result is None


def test_fetch_page_returns_items_and_none_cursor_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = ET.fromstring(_FIXTURE_RSS)
    monkeypatch.setattr(we_work_remotely, "fetch_xml", lambda *a, **kw: root)

    result = fetch_page(cursor=0, page_size=1)

    assert result is not None
    items, next_cursor = result
    assert len(items) == 2
    assert next_cursor is None


def test_split_company_and_title_hit() -> None:
    company, job_title = _split_company_and_title("Acme Corp: Senior Backend Engineer")

    assert company == "Acme Corp"
    assert job_title == "Senior Backend Engineer"


def test_split_company_and_title_miss_returns_none_company_and_full_title() -> None:
    company, job_title = _split_company_and_title("Senior Backend Engineer (no colon)")

    assert company is None
    assert job_title == "Senior Backend Engineer (no colon)"


def test_split_company_and_title_handles_none_and_empty() -> None:
    assert _split_company_and_title(None) == (None, "")
    assert _split_company_and_title("") == (None, "")


def test_parse_salary_ceiling_hit() -> None:
    description = (
        "<p><strong>Headquarters:</strong> Edinburgh</p>"
        "<p><strong>Up to USD 80,000</strong>&nbsp;per year, on a full time contract</p>"
    )

    assert _parse_salary_ceiling(description) == 80000


def test_parse_salary_ceiling_miss_logs_debug_not_error(caplog: pytest.LogCaptureFixture) -> None:
    description = "<p>A great role with no compensation details mentioned here.</p>"

    with caplog.at_level(logging.DEBUG, logger="app.connectors.we_work_remotely"):
        result = _parse_salary_ceiling(description)

    assert result is None
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_parse_salary_ceiling_handles_none_and_empty_description() -> None:
    assert _parse_salary_ceiling(None) is None
    assert _parse_salary_ceiling("") is None


def test_join_location_joins_non_empty_parts_in_order() -> None:
    raw = {"region": "Anywhere in the World", "country": "Germany", "state": None}

    assert _join_location(raw) == "Anywhere in the World, Germany"


def test_join_location_returns_none_when_all_parts_empty() -> None:
    assert _join_location({"region": None, "country": None, "state": None}) is None


def test_join_location_preserves_strings_longer_than_255_chars() -> None:
    """BUG44: WWR postings open to a long list of regions produced a joined location over
    255 chars, which used to fail Offer schema validation and drop the whole posting -- the
    join itself must not truncate; the fix widened Offer.location instead (see
    test_offer_schema.py)."""
    raw = {
        "region": "Anywhere in the World",
        "country": ", ".join(f"Country {i}" for i in range(30)),
        "state": "Delaware",
    }

    result = _join_location(raw)

    assert result is not None
    assert len(result) > 255
    assert result.startswith("Anywhere in the World, Country 0")
    assert result.endswith("Delaware")


def test_parse_posted_at_parses_rfc822_date() -> None:
    result = _parse_posted_at("Tue, 14 Jul 2026 15:29:26 +0000")

    assert result == "2026-07-14T15:29:26+00:00"


def test_parse_posted_at_handles_missing_and_malformed_values() -> None:
    assert _parse_posted_at(None) is None
    assert _parse_posted_at("") is None
    assert _parse_posted_at("not a date") is None


def test_map_offer_maps_all_known_fields() -> None:
    raw: dict[str, Any] = {
        "title": "Acme Corp: Senior Backend Engineer",
        "link": "https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer",
        "guid": "https://weworkremotely.com/remote-jobs/acme-corp-senior-backend-engineer",
        "pubDate": "Tue, 14 Jul 2026 15:29:26 +0000",
        "region": "Anywhere in the World",
        "country": None,
        "state": "California",
        "skills": "Python, Django, PostgreSQL",
        "category": "Programming",
        "type": "Full-Time",
        "description": (
            "<p><strong>Headquarters:</strong> San Francisco</p>"
            "<p><strong>Up to USD 120,000</strong> per year</p>"
        ),
    }

    result = map_offer(1, raw)

    assert result["source_id"] == 1
    assert result["external_id"] == raw["guid"]
    assert result["canonical_url"] == raw["link"]
    assert result["title"] == "Senior Backend Engineer"
    assert result["company"] == "Acme Corp"
    assert result["location"] == "Anywhere in the World, California"
    assert result["remote"] is True
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] == 120000
    assert result["salary_currency"] == "USD"
    assert result["contract_type"] is None
    assert result["posted_at"] == "2026-07-14T15:29:26+00:00"
    assert result["description"] == raw["description"]
    assert result["industry_tags"] == ["Programming", "Python", "Django", "PostgreSQL"]


def test_map_offer_handles_missing_optional_fields() -> None:
    result = map_offer(1, {})

    assert result["source_id"] == 1
    assert result["external_id"] is None
    assert result["canonical_url"] is None
    assert result["title"] == ""
    assert result["company"] == ""
    assert result["location"] is None
    assert result["remote"] is True
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_currency"] == "USD"
    assert result["contract_type"] is None
    assert result["posted_at"] is None
    assert result["description"] is None
    assert result["industry_tags"] == []


def test_map_offer_remote_is_always_true() -> None:
    assert map_offer(1, {})["remote"] is True
    assert map_offer(1, {"title": "Acme: Engineer"})["remote"] is True


def test_map_offer_seniority_and_contract_type_always_none() -> None:
    result = map_offer(1, {"title": "Acme: Senior Engineer", "type": "Full-Time"})

    assert result["seniority"] is None
    assert result["contract_type"] is None


def test_we_work_remotely_registered_in_connector_registry() -> None:
    assert WE_WORK_REMOTELY in CONNECTOR_REGISTRY
    assert CONNECTOR_REGISTRY[WE_WORK_REMOTELY].label == "We Work Remotely"
