import pandas as pd

from scripts import analyze_entity_profiles as aep
from scripts import analyze_fec_crossref as afc
from scripts import analyze_lobbying_crossref as alc
from scripts import download_aafaf as da
from scripts import build_financial_flows_master as bffm


def test_normalize_entity_profiles():
    assert aep._normalize("Acme, Inc.") == "ACME"
    assert aep._normalize("  ") == ""
    assert aep._normalize(None) == ""


def test_normalize_fec():
    assert afc._normalize("Foo LLC") == "FOO"
    assert afc._normalize("Bar & Sons") == "BAR SONS"


def test_merge_pipe_and_year_range():
    s = pd.Series(["x|y", "y|z"])
    assert alc._merge_pipe(s, 5) == "x|y|z"
    yrs = pd.Series(["2019", "2021", "2020"])
    assert alc._year_range(yrs) == "2019-2021"
    assert alc._year_range(pd.Series([None, ""])) == ""


def test_find_excel_links():
    html = '<a href="/files/report.xlsx">file</a><a href="http://example.com/data.csv">csv</a>'
    links = da._find_excel_links(html, da.AAFAF_REPORTS_URL)
    assert any('report.xlsx' in l for l in links)
    assert 'http://example.com/data.csv' in links


def test_row_and_fid():
    row = bffm._row(foo="bar")
    assert set(bffm.FLOW_COLUMNS).issubset(set(row.keys()))
    fid = bffm._fid()
    assert isinstance(fid, str) and len(fid) == 12
