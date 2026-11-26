import csv
import json
import sqlite3
import zipfile

import pytest

from studio_tools.core import files, web
from studio_tools.core.errors import ConfigError, NotAllowed

OWNER = "0b8f3c2e-1111-2222-3333-444455556666"
ROWS = [{"country": "A", "budget": 1.5, "tags": ["x"]}, {"country": "B", "budget": 2, "note": "late"}]


@pytest.fixture
def area(write_cfg, tmp_path):
    write_cfg({"files": {"root": str(tmp_path / "files")}, "web": {"enabled": False}})
    return tmp_path / "files" / OWNER


def test_sqlite_with_several_tables(area):
    out = files.save_dataset(OWNER, {"tables": {"posture": ROWS, "sources": [{"url": "u"}]}}, "sqlite", "defence posture")
    con = sqlite3.connect(area / out["file"])
    assert con.execute('SELECT country, budget, tags, note FROM posture ORDER BY country').fetchall() == [
        ("A", 1.5, '["x"]', None), ("B", 2, None, "late")]
    assert con.execute("SELECT count(*) FROM sources").fetchone() == (1,)
    assert out["tables"] == {"posture": 2, "sources": 1} and out["file"].startswith("defence posture-")


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json"])
def test_other_formats(area, fmt):
    out = files.save_dataset(OWNER, {"rows": ROWS}, fmt, "d")
    p = area / out["file"]
    if fmt == "csv":
        rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
        assert [r["country"] for r in rows] == ["A", "B"] and rows[1]["note"] == "late"
    elif fmt == "json":
        assert json.loads(p.read_text(encoding="utf-8"))[0]["country"] == "A"
    else:
        from openpyxl import load_workbook
        assert load_workbook(p).active["A2"].value == "A"


def test_bad_data_and_limits(area):
    with pytest.raises(NotAllowed):
        files.save_dataset(OWNER, {"rows": "nope"}, "csv", "x")
    with pytest.raises(NotAllowed):
        files.save_dataset(OWNER, {"rows": ROWS}, "exe", "x")
    with pytest.raises(NotAllowed):
        files.save_dataset(OWNER, {"rows": ROWS * 3}, "csv", "x", max_rows=5)
    with pytest.raises(ConfigError):
        files.save_dataset(None, {"rows": ROWS}, "csv", "x")


def test_owner_folders_are_separate_and_names_cannot_escape(area):
    out = files.save_dataset(OWNER, {"rows": ROWS}, "json", "../../etc/passwd")
    assert (area / out["file"]).is_file() and "/" not in out["file"]
    with pytest.raises(NotAllowed):
        files.resolve("someone-else", out["file"])
    with pytest.raises(NotAllowed):
        files.resolve(OWNER, "../" + OWNER + "/" + "missing.json")


def test_zip_bundle(area):
    a = files.save_dataset(OWNER, {"rows": ROWS}, "csv", "a")["file"]
    b = files.save_dataset(OWNER, {"rows": ROWS}, "json", "b")["file"]
    out = files.archive(OWNER, [a, b, " "], "zip", "news")
    assert sorted(zipfile.ZipFile(area / out["file"]).namelist()) == sorted([a, b])
    with pytest.raises(NotAllowed):
        files.archive(OWNER, ["nope.csv"], "zip", "x")


def test_web_is_off_unless_the_deployment_enables_it(area):
    with pytest.raises(NotAllowed, match="switched off"):
        web.fetch("https://example.org")


def test_web_refuses_internal_addresses_and_other_schemes(write_cfg):
    write_cfg({"web": {"enabled": True}})
    for url in ("http://127.0.0.1:7860/api/v1/flows", "http://10.1.2.3/", "file:///etc/passwd", "ftp://x.org/"):   # release-ok: blocked-address samples
        with pytest.raises(NotAllowed):
            web.fetch(url)


def test_web_allow_list(write_cfg):
    write_cfg({"web": {"enabled": True, "allow_domains": ["example.org"], "allow_private": True}})
    with pytest.raises(NotAllowed, match="not in the allowed"):
        web._check_url("https://evil.com/", web._cfg())
    assert web._check_url("https://news.example.org/a", web._cfg())


def test_feed_and_sitemap_parsing():
    rss = b"""<?xml version="1.0"?><rss><channel><item><title>T1</title><link>https://n.org/1</link>
      <pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Body&lt;/p&gt;</description></item></channel></rss>"""
    items = web._feed(rss, "https://n.org/feed")
    assert items == [{"title": "T1", "url": "https://n.org/1", "published": "Mon, 03 Nov 2026 10:00:00 GMT", "summary": "Body"}]
    sm = b"""<?xml version="1.0"?><urlset><url><loc>https://n.org/a</loc><lastmod>2026-11-01</lastmod></url></urlset>"""
    assert web._feed(sm, "https://n.org/sitemap.xml") == [{"url": "https://n.org/a", "updated": "2026-11-01"}]
    assert web._links('<a href="/x">X</a><a href="#top">t</a>', "https://n.org/") == [{"text": "X", "url": "https://n.org/x"}]
