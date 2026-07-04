from __future__ import annotations

import math
from pathlib import Path

from quote_core import Arc, Line, QuoteRates, analyze_dxf, build_closed_components


SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "sample.dxf"


def test_arc_component_area_and_perimeter_are_exact() -> None:
    segments = [
        Line("CUT", 0, 5, 20, 5),
        Arc("CUT", 20, 0, 5, 90, -90, -180),
        Line("CUT", 20, -5, 0, -5),
        Arc("CUT", 0, 0, 5, -90, 90, -180),
    ]

    components = build_closed_components(segments)

    assert len(components) == 1
    assert components[0].closed
    assert math.isclose(components[0].area_mm2, 20 * 10 + math.pi * 25, rel_tol=1e-12)
    assert math.isclose(components[0].length_mm, 40 + 2 * math.pi * 5, rel_tol=1e-12)


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


def test_closed_polyline_keeps_source_order() -> None:
    points = [(0, 0), (60, 0), (60, 20), (100, 20), (20, 80), (0, 50), (0, 0)]
    segments = [
        Line("CUT", a[0], a[1], b[0], b[1], path_id=1)
        for a, b in zip(points, points[1:])
    ]

    components = build_closed_components(segments)

    assert len(components) == 1
    assert components[0].closed
    assert components[0].points == points
    assert math.isclose(components[0].area_mm2, 4500.0, rel_tol=1e-12)


def test_insert_block_geometry_is_expanded(tmp_path: Path) -> None:
    dxf = tmp_path / "insert_block.dxf"
    dxf.write_text(
        "\n".join([
            "0", "SECTION", "2", "BLOCKS",
            "0", "BLOCK", "2", "PART", "8", "0",
            "0", "LWPOLYLINE", "8", "0", "70", "1",
            "10", "0", "20", "0",
            "10", "100", "20", "0",
            "10", "100", "20", "50",
            "10", "0", "20", "50",
            "0", "ENDBLK",
            "0", "ENDSEC",
            "0", "SECTION", "2", "ENTITIES",
            "0", "INSERT", "8", "CUT", "2", "PART", "10", "10", "20", "20",
            "0", "ENDSEC", "0", "EOF",
        ]),
        encoding="utf-8",
    )

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 1
    assert result.basic_geometries[0].bbox == (10.0, 20.0, 110.0, 70.0)
    assert math.isclose(result.basic_geometries[0].area_mm2, 5000.0, rel_tol=1e-9)


def test_ellipse_geometry_is_approximated(tmp_path: Path) -> None:
    dxf = tmp_path / "ellipse.dxf"
    dxf.write_text(
        "\n".join([
            "0", "SECTION", "2", "ENTITIES",
            "0", "ELLIPSE", "8", "CUT",
            "10", "0", "20", "0",
            "11", "50", "21", "0",
            "40", "0.5", "41", "0", "42", str(math.tau),
            "0", "ENDSEC", "0", "EOF",
        ]),
        encoding="utf-8",
    )

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 1
    assert result.basic_geometries[0].kind == "外轮廓"
    assert result.basic_geometries[0].area_mm2 > 3800
    assert result.skipped_counts["approx_type:ELLIPSE"] == 1


def test_region_only_dxf_reports_actionable_warning(tmp_path: Path) -> None:
    dxf = tmp_path / "region_only.dxf"
    dxf.write_text(
        "\n".join([
            "0", "SECTION", "2", "ENTITIES",
            "0", "POINT", "8", "CUT", "10", "0", "20", "0",
            "0", "REGION", "8", "CUT",
            "0", "VIEWPORT", "8", "CUT",
            "0", "ENDSEC", "0", "EOF",
        ]),
        encoding="utf-8",
    )

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 0
    assert result.basic_geometries == []
    assert result.skipped_counts["unsupported_type:REGION"] == 1
    assert any("文件已打开" in warning for warning in result.warnings)
    assert any("未发现可用切割曲线实体" in warning for warning in result.warnings)


def test_complex_layout_requires_selection_before_quote(tmp_path: Path) -> None:
    dxf = tmp_path / "complex_layout.dxf"
    entities = ["0", "SECTION", "2", "ENTITIES"]
    for i in range(51):
        x = i * 60
        entities.extend([
            "0", "LWPOLYLINE", "8", "CUT", "70", "1",
            "10", str(x), "20", "0",
            "10", str(x + 40), "20", "0",
            "10", str(x + 40), "20", "40",
            "10", str(x), "20", "40",
        ])
    entities.extend(["0", "ENDSEC", "0", "EOF"])
    dxf.write_text("\n".join(entities), encoding="utf-8")

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 51
    assert result.profiles_used_count == 0
    assert result.basic_geometries == []
    assert result.quote_rows == []
    assert len(result.profile_previews) == 51
    assert any("未框选前不自动汇总面积" in warning for warning in result.warnings)

    selected = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True, selection_bbox=(-1, -1, 41, 41))

    assert selected.profiles_all_count == 1
    assert len(selected.basic_geometries) == 1
    assert len(selected.quote_rows) == 1


def test_noisy_layout_frame_is_not_treated_as_part(tmp_path: Path) -> None:
    dxf = tmp_path / "noisy_layout_frame.dxf"
    entities = ["0", "SECTION", "2", "ENTITIES"]

    def add_rect(x: float, y: float, w: float, h: float) -> None:
        entities.extend([
            "0", "LWPOLYLINE", "8", "CUT", "70", "1",
            "10", str(x), "20", str(y),
            "10", str(x + w), "20", str(y),
            "10", str(x + w), "20", str(y + h),
            "10", str(x), "20", str(y + h),
        ])

    add_rect(0, 0, 1000, 500)
    for i in range(60):
        add_rect(20 + (i % 20) * 30, 20 + (i // 20) * 30, 10, 10)
    add_rect(1200, 0, 80, 40)
    add_rect(1400, 0, 80, 40)
    entities.extend(["0", "ENDSEC", "0", "EOF"])
    dxf.write_text("\n".join(entities), encoding="utf-8")

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=False)

    assert result.profiles_all_count == 2
    assert len(result.basic_geometries) == 2
    assert all(g.width_mm == 80 for g in result.basic_geometries)
    assert any("疑似图框" in warning for warning in result.warnings)


def test_point_marks_are_counted_as_unmeasured_holes(tmp_path: Path) -> None:
    dxf = tmp_path / "point_marks.dxf"
    dxf.write_text(
        "\n".join([
            "0", "SECTION", "2", "ENTITIES",
            "0", "LWPOLYLINE", "8", "CUT", "70", "1",
            "10", "0", "20", "0",
            "10", "100", "20", "0",
            "10", "100", "20", "50",
            "10", "0", "20", "50",
            "0", "POINT", "8", "CUT", "10", "20", "20", "20",
            "0", "POINT", "8", "CUT", "10", "80", "20", "20",
            "0", "ENDSEC", "0", "EOF",
        ]),
        encoding="utf-8",
    )

    result = analyze_dxf(dxf, rates=QuoteRates(), dedupe_identical=True)

    assert result.profiles_all_count == 1
    assert result.quote_rows[0].hole_count == 2
    assert result.quote_rows[0].pierce_count == 3
    assert "未扣孔面积" in result.quote_rows[0].note
    assert "POINT 点位孔" in " ".join(result.warnings)

    priced = analyze_dxf(dxf, rates=QuoteRates(point_mark_diameter_mm=10), dedupe_identical=True)
    row = priced.quote_rows[0]

    assert math.isclose(row.net_area_mm2, 5000 - 2 * math.pi * 25, rel_tol=1e-9)
    assert math.isclose(row.cut_length_m, (300 + 2 * math.pi * 10) / 1000, rel_tol=1e-9)
    assert "按 Φ10" in row.note
