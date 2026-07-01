from __future__ import annotations

import math
from pathlib import Path

from quote_core import QuoteRates, analyze_dxf


SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "sample.dxf"


def test_sample_dxf_geometry_and_metadata() -> None:
    result = analyze_dxf(SAMPLE, rates=QuoteRates(), dedupe_identical=True)

    assert result.drawing_no == "400V2-BFD-009"
    assert result.material_hint == "铝板"
    assert result.profiles_all_count == 2
    assert result.profiles_used_count == 1
    assert result.duplicate_groups == [2]
    assert len(result.basic_geometries) == 2
    assert result.basic_geometries[0].kind == "外轮廓"
    assert result.basic_geometries[0].area_mm2 > 0
    assert result.basic_geometries[0].perimeter_mm > 0
    assert result.basic_geometries[0].centroid is not None

    row = result.quote_rows[0]
    assert row.size_mm == "980.0×100.0"
    assert row.hole_count == 25
    assert row.pierce_count == 26
    assert math.isclose(row.cut_length_m, 4.0509290379, rel_tol=1e-6)
    assert math.isclose(row.gross_area_mm2, 98000.0, rel_tol=1e-9)
    assert math.isclose(row.net_area_mm2, 84351.5357817, rel_tol=1e-6)


def test_sample_quote_formula_default_rates() -> None:
    rates = QuoteRates(
        material="Q235",
        thickness_mm=10,
        quantity=2,
        density_g_cm3=7.85,
        material_price_per_kg=4.0,
        scrap_price_per_kg=2.0,
        cut_price_per_meter=5.0,
        pierce_price_each=0.0,
        other_process_fee_each=0.0,
        profit_rate=0.0,
        tax_rate=0.0,
    )
    result = analyze_dxf(SAMPLE, rates=rates, dedupe_identical=True)
    row = result.quote_rows[0]

    expected_material_fee = row.gross_weight_kg * rates.material_price_per_kg
    expected_scrap_credit = max(row.gross_weight_kg - row.net_weight_kg, 0) * rates.scrap_price_per_kg
    expected_cut_fee = row.cut_length_m * rates.cut_price_per_meter
    expected_unit_price = expected_material_fee - expected_scrap_credit + expected_cut_fee

    assert math.isclose(row.material_fee_each, expected_material_fee, rel_tol=1e-9)
    assert math.isclose(row.scrap_credit_each, expected_scrap_credit, rel_tol=1e-9)
    assert math.isclose(row.cut_fee_each, expected_cut_fee, rel_tol=1e-9)
    assert math.isclose(row.unit_price, expected_unit_price, rel_tol=1e-9)
    assert math.isclose(row.amount, expected_unit_price * 2, rel_tol=1e-9)


def test_can_disable_dedupe() -> None:
    result = analyze_dxf(SAMPLE, rates=QuoteRates(), dedupe_identical=False)
    assert result.profiles_all_count == 2
    assert result.profiles_used_count == 2
    assert len(result.quote_rows) == 2


def test_classic_polyline_vertex_dxf_is_supported(tmp_path: Path) -> None:
    dxf = tmp_path / "classic_polyline.dxf"
    dxf.write_text(
        "\n".join([
            "0", "SECTION", "2", "ENTITIES",
            "0", "POLYLINE", "8", "CUT", "66", "1", "70", "1",
            "0", "VERTEX", "8", "CUT", "10", "0", "20", "0",
            "0", "VERTEX", "8", "CUT", "10", "100", "20", "0",
            "0", "VERTEX", "8", "CUT", "10", "100", "20", "50",
            "0", "VERTEX", "8", "CUT", "10", "0", "20", "50",
            "0", "SEQEND", "0", "ENDSEC", "0", "EOF",
        ]),
        encoding="utf-8",
    )

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 1
    assert result.open_path_count == 0
    assert len(result.basic_geometries) == 1
    assert result.basic_geometries[0].kind == "外轮廓"
    assert math.isclose(result.basic_geometries[0].area_mm2, 5000.0, rel_tol=1e-9)
    assert math.isclose(result.basic_geometries[0].perimeter_mm, 300.0, rel_tol=1e-9)
    assert len(result.quote_rows) == 1
