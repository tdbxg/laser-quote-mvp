from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api_server import app


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data" / "sample.dxf"


def test_analyze_api_returns_geometry_without_pricing() -> None:
    client = TestClient(app)

    with SAMPLE.open("rb") as f:
        response = client.post(
            "/api/analyze",
            files={"files": ("sample.dxf", f, "application/dxf")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["file_count"] == 1
    assert data["summary"]["total_profiles"] >= 1
    assert data["summary"]["quote_row_count"] == 0
    assert data["summary"]["total_amount"] == 0
    assert data["quote_rows"] == []
    assert "downloads" not in data


def test_quote_api_returns_traceable_result_and_downloads() -> None:
    client = TestClient(app)

    with SAMPLE.open("rb") as f:
        response = client.post(
            "/api/quote",
            files={"files": ("sample.dxf", f, "application/dxf")},
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
    assert data["quote_rows"][0]["drawing_no"] == "400V2-BFD-009"
    assert data["status_rows"][0]["requires_review"] is True
    assert data["accuracy"]["requires_review_count"] == 1
    assert data["downloads"]["xlsx"].endswith("/laser_quote.xlsx")

    xlsx_response = client.get(data["downloads"]["xlsx"])
    assert xlsx_response.status_code == 200
    assert xlsx_response.content.startswith(b"PK")


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
