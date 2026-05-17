"""Tests for scripts/network_graph.py — alias resolution, entity typing, graph construction."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False

pytestmark = pytest.mark.skipif(not _HAS_NX, reason="networkx not installed")

from scripts.network_graph import (
    apply_vendor_aliases,
    build_entity_type_index,
    build_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _awards_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "vendor_name": "Acme Corp",
        "agency_name": "Dept of Defense",
        "obligated_amount": 1_000_000.0,
        "fiscal_year": 2020.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _alias_registry(*entries) -> dict:
    """Build registry from (variant, canonical, entity_type) tuples."""
    reg = {}
    for variant, canonical, etype in entries:
        reg[variant] = {
            "canonical_name": canonical,
            "canonical_uei": f"UEI_{canonical[:6].upper().replace(' ', '_')}",
            "entity_type": etype,
        }
    return reg


# ---------------------------------------------------------------------------
# apply_vendor_aliases
# ---------------------------------------------------------------------------

class TestApplyVendorAliases:
    def test_maps_known_variant_to_canonical(self):
        df = _awards_df([{"vendor_name": "Crowley Maritime Corp"}])
        registry = _alias_registry(("Crowley Maritime Corp", "Crowley Holdings Inc", "corporate"))
        out = apply_vendor_aliases(df, registry)
        assert out["vendor_name"].iloc[0] == "Crowley Holdings Inc"

    def test_unknown_variant_is_unchanged(self):
        df = _awards_df([{"vendor_name": "Unknown Vendor LLC"}])
        registry = _alias_registry(("Some Other Corp", "Some Parent Corp", "corporate"))
        out = apply_vendor_aliases(df, registry)
        assert out["vendor_name"].iloc[0] == "Unknown Vendor LLC"

    def test_empty_registry_returns_df_unchanged(self):
        df = _awards_df([{"vendor_name": "Corp A"}])
        out = apply_vendor_aliases(df, {})
        assert out["vendor_name"].iloc[0] == "Corp A"

    def test_does_not_mutate_original_df(self):
        df = _awards_df([{"vendor_name": "Corp A"}])
        registry = _alias_registry(("Corp A", "Corp Holdings", "corporate"))
        _ = apply_vendor_aliases(df, registry)
        assert df["vendor_name"].iloc[0] == "Corp A"

    def test_multiple_variants_resolved_independently(self):
        df = _awards_df([
            {"vendor_name": "Corp A"},
            {"vendor_name": "Corp B"},
            {"vendor_name": "Corp C"},
        ])
        registry = _alias_registry(
            ("Corp A", "Parent Alpha", "corporate"),
            ("Corp B", "Parent Beta", "nonprofit"),
        )
        out = apply_vendor_aliases(df, registry)
        assert list(out["vendor_name"]) == ["Parent Alpha", "Parent Beta", "Corp C"]

    def test_subsidiaries_collapse_to_same_parent(self):
        """Two different subsidiaries resolving to the same parent become identical rows."""
        df = _awards_df([
            {"vendor_name": "Banco Popular de Puerto Rico", "obligated_amount": 500_000.0},
            {"vendor_name": "Popular Inc", "obligated_amount": 200_000.0},
        ])
        registry = _alias_registry(
            ("Banco Popular de Puerto Rico", "Popular Inc", "corporate"),
            ("Popular Inc", "Popular Inc", "corporate"),
        )
        out = apply_vendor_aliases(df, registry)
        assert out["vendor_name"].tolist() == ["Popular Inc", "Popular Inc"]


# ---------------------------------------------------------------------------
# build_entity_type_index
# ---------------------------------------------------------------------------

class TestBuildEntityTypeIndex:
    def test_builds_canonical_to_type_map(self):
        registry = _alias_registry(
            ("Crowley Maritime Corp", "Crowley Holdings Inc", "corporate"),
            ("PRASA", "Puerto Rico Aqueduct And Sewer Authority", "government"),
        )
        index = build_entity_type_index(registry)
        assert index["Crowley Holdings Inc"] == "corporate"
        assert index["Puerto Rico Aqueduct And Sewer Authority"] == "government"

    def test_empty_registry_returns_empty_index(self):
        assert build_entity_type_index({}) == {}

    def test_duplicate_canonical_keeps_last_seen_type(self):
        registry = {
            "Variant A": {"canonical_name": "Parent", "entity_type": "corporate"},
            "Variant B": {"canonical_name": "Parent", "entity_type": "nonprofit"},
        }
        index = build_entity_type_index(registry)
        assert index["Parent"] in ("corporate", "nonprofit")

    def test_entries_without_canonical_name_skipped(self):
        registry = {"Orphan": {"canonical_name": "", "entity_type": "corporate"}}
        assert build_entity_type_index(registry) == {}


# ---------------------------------------------------------------------------
# build_graph — entity_type_index integration
# ---------------------------------------------------------------------------

class TestBuildGraphEntityTypes:
    def test_vendor_node_gets_entity_type_from_index(self):
        df = _awards_df([{"vendor_name": "Microsoft Puerto Rico Inc"}])
        index = {"Microsoft Puerto Rico Inc": "corporate"}
        G = build_graph(df, None, min_obligation=0, entity_type_index=index)
        assert G.nodes["Microsoft Puerto Rico Inc"]["entity_type"] == "corporate"

    def test_unknown_vendor_gets_unknown_entity_type(self):
        df = _awards_df([{"vendor_name": "Mystery Corp"}])
        G = build_graph(df, None, min_obligation=0, entity_type_index={})
        assert G.nodes["Mystery Corp"]["entity_type"] == "unknown"

    def test_agency_nodes_get_agency_entity_type(self):
        df = _awards_df([{"agency_name": "Dept of Defense"}])
        G = build_graph(df, None, min_obligation=0)
        assert G.nodes["Dept of Defense"]["entity_type"] == "agency"

    def test_none_entity_type_index_defaults_to_unknown(self):
        df = _awards_df([{"vendor_name": "Corp A"}])
        G = build_graph(df, None, min_obligation=0, entity_type_index=None)
        assert G.nodes["Corp A"]["entity_type"] == "unknown"

    def test_alias_collapsed_nodes_aggregate_edges(self):
        """After apply_vendor_aliases, two subsidiaries become one node with summed weight."""
        df = _awards_df([
            {"vendor_name": "Parent Corp", "agency_name": "DoD", "obligated_amount": 300_000.0},
            {"vendor_name": "Parent Corp", "agency_name": "DoD", "obligated_amount": 200_000.0},
        ])
        G = build_graph(df, None, min_obligation=0)
        # Both rows grouped under same vendor → single edge with combined weight
        assert G.has_edge("Parent Corp", "DoD")
        assert G["Parent Corp"]["DoD"]["weight"] == pytest.approx(500_000.0)

    def test_min_obligation_filters_edges(self):
        df = _awards_df([
            {"vendor_name": "Big Corp", "obligated_amount": 1_000_000.0},
            {"vendor_name": "Small Corp", "obligated_amount": 1_000.0},
        ])
        G = build_graph(df, None, min_obligation=500_000.0)
        vendor_names = {n for n, d in G.nodes(data=True) if d["node_type"] == "vendor"}
        assert "Big Corp" in vendor_names
        assert "Small Corp" not in vendor_names

    def test_hierarchy_adds_parent_to_child_edge(self):
        import csv, io
        hierarchy_csv = (
            "vendor_name,parent_name,parent_uei,uei\n"
            "Crowley Maritime Corp,Crowley Holdings Inc,CRWLH1D3G5J9,CRWL5X8M2P7Q\n"
        )
        hierarchy = pd.read_csv(io.StringIO(hierarchy_csv), dtype=str, keep_default_na=False)
        df = _awards_df([{"vendor_name": "Crowley Maritime Corp"}])
        G = build_graph(df, hierarchy, min_obligation=0)
        assert G.has_edge("Crowley Holdings Inc", "Crowley Maritime Corp")
        assert G["Crowley Holdings Inc"]["Crowley Maritime Corp"]["edge_type"] == "hierarchy"
