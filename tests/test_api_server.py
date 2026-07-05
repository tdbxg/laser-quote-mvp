from __future__ import annotations

import math
from pathlib import Path

from fastapi.testclient import TestClient

from api_server import app


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data" / "sample.dxf"


def _simple_dxf_bytes() -> bytes:
    return "\n".join([
        "0", "SECTION", "2", "ENTITIES",
        "0", "LWPOLYLINE", "8", "CUT", "70", "1",
        "10", "0", "20", "0",
        "10", "100", "20", "0",
        "10", "100", "20", "50",
        "10", "0", "20", "50",
        "0", "TEXT", "8", "TEXT", "1", "400V2-BFD-009",
        "0", "ENDSEC", "0", "EOF",
    ]).encode("utf-8")


def test_analyze_api_returns_geometry_without_pricing() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/analyze",
        files={"files": ("sample.dxf", _simple_dxf_bytes(), "application/dxf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["file_count"] == 1
    assert data["summary"]["total_profiles"] >= 1
    assert data["summary"]["total_area_mm2"] > 0
    assert data["summary"]["quote_row_count"] == 0
    assert data["summary"]["total_amount"] == 0
    assert data["geometry_rows"]
    assert data["geometry_rows"][0]["area_mm2"] > 0
    assert data["geometry_rows"][0]["perimeter_mm"] > 0
    assert data["geometry_rows"][0]["centroid"] is not None
    assert data["massprop_rows"][0]["area_mm2"] > 0
    assert data["massprop_rows"][0]["perimeter_mm"] > 0
    assert data["quote_rows"] == []
    assert "downloads" not in data


def test_preview_api_returns_all_inner_paths() -> None:
    client = TestClient(app)
    entities = [
        "0", "SECTION", "2", "ENTITIES",
        "0", "LWPOLYLINE", "8", "CUT", "70", "1",
        "10", "0", "20", "0",
        "10", "500", "20", "0",
        "10", "500", "20", "300",
        "10", "0", "20", "300",
    ]
    for i in range(12):
        x = 20 + i * 35
        entities.extend([
            "0", "LWPOLYLINE", "8", "CUT", "70", "1",
            "10", str(x), "20", "20",
            "10", str(x + 12), "20", "20",
            "10", str(x + 12), "20", "40",
            "10", str(x), "20", "40",
        ])
    entities.extend(["0", "ENDSEC", "0", "EOF"])

    response = client.post(
        "/api/analyze",
        files={"files": ("many_inner_paths.dxf", "\n".join(entities).encode("utf-8"), "application/dxf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["preview_rows"]) == 1
    assert len(data["preview_rows"][0]["inner_paths"]) == 12


def test_quote_api_uses_auto_massprop_without_manual_cad_values() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/quote",
        files={"files": ("sample.dxf", _simple_dxf_bytes(), "application/dxf")},
        data={
            "material": "Q235",
            "thickness_mm": "10",
            "quantity": "1",
            "density_g_cm3": "7.85",
            "material_price_per_kg": "4",
            "scrap_price_per_kg": "2",
            "cut_price_per_meter": "5",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["quote_row_count"] == 1
    assert data["summary"]["manual_cad_quote"] is False
    assert data["quote_rows"][0]["net_area_mm2"] == 5000.0
    assert data["massprop_rows"][0]["area_mm2"] == 5000.0
    assert data["downloads"]["xlsx"].endswith("/laser_quote.xlsx")


def test_quote_api_can_use_manual_cad_massprop_values() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/quote",
        files={"files": ("sample.dxf", _simple_dxf_bytes(), "application/dxf")},
        data={
            "thickness_mm": "10",
            "quantity": "2",
            "density_g_cm3": "7.85",
            "material_price_per_kg": "4",
            "cut_price_per_meter": "5",
            "pierce_price_each": "1",
            "manual_area_mm2": "939439.9243",
            "manual_perimeter_mm": "9590.5885",
            "manual_pierce_count": "99",
        },
    )

    assert response.status_code == 200
    data = response.json()
    row = data["quote_rows"][0]
    assert data["summary"]["manual_cad_quote"] is True
    assert row["net_area_mm2"] == 939439.9243
    assert row["gross_area_mm2"] == 939439.9243
    assert math.isclose(row["cut_length_m"], 9.5905885, rel_tol=1e-12)
    assert row["pierce_count"] == 99
    assert row["note"].startswith("人工确认 CAD 数据报价")
    assert data["downloads"]["xlsx"].endswith("/laser_quote.xlsx")

    xlsx_response = client.get(data["downloads"]["xlsx"])
    assert xlsx_response.status_code == 200
    assert xlsx_response.content.startswith(b"PK")


def test_quote_api_can_parse_uploaded_massprop_text() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/quote",
        files=[
            ("files", ("sample.dxf", _simple_dxf_bytes(), "application/dxf")),
            ("massprop_file", ("massprop.txt", "选择对象: 指定对角点: 找到 99 个\n面积:\n  939439.9243\n周长:\n  9590.5885\n".encode("utf-8"), "text/plain")),
        ],
        data={
            "thickness_mm": "10",
            "quantity": "1",
            "density_g_cm3": "7.85",
            "material_price_per_kg": "4",
            "cut_price_per_meter": "5",
            "pierce_price_each": "1",
            "manual_pierce_count": "99",
        },
    )

    assert response.status_code == 200
    row = response.json()["quote_rows"][0]
    assert row["net_area_mm2"] == 939439.9243
    assert math.isclose(row["cut_length_m"], 9.5905885, rel_tol=1e-12)
    assert "选择对象 99 个" in row["note"]


def test_web_index_is_served() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "激光报价助手" in response.text
    assert "/api/quote" in response.text


def test_quote_api_rejects_non_dxf_upload() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/quote",
        files={"files": ("bad.txt", b"not dxf", "text/plain")},
    )

    assert response.status_code == 400
