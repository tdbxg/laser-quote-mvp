from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from excel_export import write_quote_xlsx
from quote_core import AnalysisResult, BatchAnalysisResult, QuoteRates, QuoteRow, analyze_dxf_batch, write_batch_csv


app = FastAPI(title="Laser Quote API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOB_ROOT = Path(tempfile.gettempdir()) / "laser_quote_api_jobs"
DOWNLOAD_NAMES = {"batch_quote.csv", "laser_quote.xlsx"}

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>激光报价助手</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f3f4f6; color: #111827; }
    .shell { max-width: 1120px; margin: 0 auto; padding: 28px 18px 48px; }
    .hero { background: #111827; color: white; border-radius: 12px; padding: 28px; }
    .hero h1 { margin: 0 0 10px; font-size: 30px; }
    .hero p { margin: 0; color: #d1d5db; line-height: 1.6; }
    .panel { background: white; border: 1px solid #e5e7eb; border-radius: 10px; margin-top: 18px; padding: 22px; }
    .grid { display: grid; gap: 14px; grid-template-columns: repeat(4, minmax(0, 1fr)); }
    label { display: grid; gap: 6px; color: #374151; font-size: 14px; }
    input, select { border: 1px solid #d1d5db; border-radius: 8px; font-size: 15px; padding: 10px 11px; }
    input[type=file] { padding: 9px; background: #f9fafb; }
    button { border: 0; border-radius: 8px; background: #2563eb; color: white; cursor: pointer; font-size: 16px; font-weight: 700; padding: 12px 18px; }
    button:disabled { background: #93c5fd; cursor: wait; }
    .actions { align-items: center; display: flex; flex-wrap: wrap; gap: 12px; margin-top: 18px; }
    .links a { color: #2563eb; font-weight: 700; margin-right: 14px; }
    .summary { display: grid; gap: 10px; grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .metric { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }
    .metric b { display: block; font-size: 22px; margin-top: 4px; }
    .warn { background: #fffbeb; border-color: #f59e0b; }
    .ok { background: #ecfdf5; border-color: #10b981; }
    .table-wrap { overflow-x: auto; }
    table { border-collapse: collapse; min-width: 980px; width: 100%; }
    th, td { border-bottom: 1px solid #e5e7eb; font-size: 13px; padding: 10px 8px; text-align: left; vertical-align: top; }
    th { background: #f9fafb; color: #374151; }
    .muted { color: #6b7280; }
    .hint { color: #6b7280; font-size: 13px; line-height: 1.5; margin: 12px 0 0; }
    @media (max-width: 760px) { .grid, .summary { grid-template-columns: 1fr 1fr; } .hero h1 { font-size: 24px; } }
    @media (max-width: 520px) { .grid, .summary { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero"><h1>激光报价助手</h1><p>上传 DXF，先提取基础几何信息，再确认参数并计算待确认报价。</p></section>
    <section class="panel">
      <form id="quoteForm">
        <div class="grid"><label>DXF 文件<input name="files" type="file" accept=".dxf" multiple required /></label></div>
        <div class="actions"><button id="analyzeBtn" type="button">1. 提取 DXF 信息</button><span id="message" class="muted"></span></div>
        <div id="pricingFields" style="display:none">
          <p class="hint">先确认下方 DXF 基础信息，再修改报价参数并计算金额。这些数值是系统默认值，不是从 DXF 自动读取。</p>
          <div class="grid">
            <label>材质 默认值<input name="material" value="Q235" /></label>
            <label>厚度 mm 默认值<input name="thickness_mm" type="number" step="0.01" value="10" /></label>
            <label>数量 默认值<input name="quantity" type="number" step="1" value="1" /></label>
            <label>密度 g/cm3 默认值<input name="density_g_cm3" type="number" step="0.0001" value="7.85" /></label>
            <label>材料价 元/kg 默认值<input name="material_price_per_kg" type="number" step="0.01" value="4" /></label>
            <label>废料价 元/kg 默认值<input name="scrap_price_per_kg" type="number" step="0.01" value="2" /></label>
            <label>切割价 元/m 默认值<input name="cut_price_per_meter" type="number" step="0.01" value="5" /></label>
            <label>穿孔价 元/次 默认值<input name="pierce_price_each" type="number" step="0.01" value="0" /></label>
            <label>其他工序 元/件 默认值<input name="other_process_fee_each" type="number" step="0.01" value="0" /></label>
            <label>利润率 默认值<input name="profit_rate" type="number" step="0.0001" value="0" /></label>
            <label>税率 默认值<input name="tax_rate" type="number" step="0.0001" value="0" /></label>
            <label>开放路径<input name="quote_open_paths" type="checkbox" value="true" checked />按切割费生成待确认报价</label>
          </div>
          <div class="actions"><button id="submitBtn" type="submit">2. 计算待确认报价</button><span id="downloadLinks" class="links"></span></div>
        </div>
      </form>
    </section>
    <section id="result" style="display:none">
      <section class="panel"><h2>汇总</h2><div id="summary" class="summary"></div></section>
      <section id="accuracyPanel" class="panel"><h2>准确性状态</h2><p id="accuracyText"></p></section>
      <section class="panel"><h2>基础几何信息</h2><div class="table-wrap"><table id="geometryTable"></table></div></section>
      <section class="panel"><h2>文件状态</h2><div class="table-wrap"><table id="statusTable"></table></div></section>
      <section class="panel"><h2>报价明细</h2><div class="table-wrap"><table id="quoteTable"></table></div></section>
    </section>
  </main>
  <script>
    const form = document.getElementById("quoteForm");
    const analyzeButton = document.getElementById("analyzeBtn");
    const button = document.getElementById("submitBtn");
    const message = document.getElementById("message");
    const result = document.getElementById("result");
    const downloads = document.getElementById("downloadLinks");
    const pricingFields = document.getElementById("pricingFields");
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    function table(el, headers, rows) { const body = rows.length ? rows.map(r => "<tr>" + headers.map(h => `<td>${esc(typeof h[1] === "function" ? h[1](r) : r[h[1]])}</td>`).join("") + "</tr>").join("") : `<tr><td colspan="${headers.length}">没有识别到可显示数据，请查看“文件状态”的跳过实体、图层和错误原因。</td></tr>`; el.innerHTML = "<thead><tr>" + headers.map(h => `<th>${esc(h[0])}</th>`).join("") + "</tr></thead><tbody>" + body + "</tbody>"; }
    function renderData(data, mode) {
      result.style.display = "block";
      const s = data.summary, isAnalyze = mode === "analyze";
      document.getElementById("summary").innerHTML = [["文件", s.file_count], [isAnalyze ? "有效轮廓" : "报价行", isAnalyze ? (s.total_profiles || 0) : s.quote_row_count], [isAnalyze ? "总面积" : "切割米数", isAnalyze ? `${s.total_area_mm2 || 0} mm²` : s.total_cut_length_m + " m"], [isAnalyze ? "需复核" : "待确认金额", isAnalyze ? (data.accuracy.requires_review_count || 0) : "￥" + s.total_amount]].map(x => `<div class="metric"><span>${esc(x[0])}</span><b>${esc(x[1])}</b></div>`).join("");
      const a = data.accuracy; document.getElementById("accuracyPanel").className = "panel " + (a.requires_review_count ? "warn" : "ok"); document.getElementById("accuracyText").textContent = `${a.policy} 需人工复核文件数：${a.requires_review_count}；无报价行文件数：${a.empty_result_count}`;
      table(document.getElementById("geometryTable"), [["文件", "source_file"], ["类型", "kind"], ["闭合", r => r.closed ? "是" : "否"], ["需确认", r => r.approximate ? "是" : "否"], ["面积 mm²", r => Number(r.area_mm2 || 0).toFixed(4)], ["周长 mm", r => Number(r.perimeter_mm || 0).toFixed(4)], ["宽×高 mm", r => `${Number(r.width_mm || 0).toFixed(4)}×${Number(r.height_mm || 0).toFixed(4)}`], ["边界框", r => (r.bbox || []).map(v => Number(v).toFixed(4)).join(" , ")], ["质心", r => r.centroid ? r.centroid.map(v => Number(v).toFixed(4)).join(" , ") : ""], ["惯性矩 X/Y mm⁴", r => `${Number(r.inertia_centroid_x_mm4 || 0).toFixed(4)} / ${Number(r.inertia_centroid_y_mm4 || 0).toFixed(4)}`], ["惯性积 XY mm⁴", r => r.inertia_centroid_xy_mm4 == null ? "" : Number(r.inertia_centroid_xy_mm4).toFixed(4)], ["回转半径 X/Y mm", r => `${Number(r.radius_gyration_x_mm || 0).toFixed(4)} / ${Number(r.radius_gyration_y_mm || 0).toFixed(4)}`], ["备注", "note"]], data.geometry_rows || []);
      table(document.getElementById("statusTable"), [["文件", "source_file"], ["成功", r => r.ok ? "是" : "否"], ["需复核", r => r.requires_review ? "是" : "否"], ["有效轮廓", r => `${r.profiles_used_count}/${r.profiles_all_count}`], ["开放路径", r => `${Number(r.open_path_length_m || 0).toFixed(4)} m / ${r.open_path_count || 0} 组`], ["跳过实体", r => JSON.stringify(r.skipped_counts || {})], ["提醒/错误", r => (r.warnings || []).join("；") || r.error]], data.status_rows || []);
      table(document.getElementById("quoteTable"), [["文件", "source_file"], ["图号", "drawing_no"], ["名称", "name"], ["尺寸", "size_mm"], ["孔数", "hole_count"], ["穿孔", "pierce_count"], ["切割m", r => Number(r.cut_length_m || 0).toFixed(4)], ["单价", r => Number(r.unit_price || 0).toFixed(2)], ["金额", r => Number(r.amount || 0).toFixed(2)], ["备注", "note"]], data.quote_rows || []);
      downloads.innerHTML = data.downloads ? `<a href="${data.downloads.csv}">下载 CSV</a><a href="${data.downloads.xlsx}">下载 Excel</a>` : "";
    }
    analyzeButton.addEventListener("click", async () => { analyzeButton.disabled = true; message.textContent = "正在提取 DXF 信息..."; downloads.innerHTML = ""; try { const res = await fetch("/api/analyze", { method: "POST", body: new FormData(form) }); const data = await res.json(); if (!res.ok) throw new Error(data.detail || "提取失败"); renderData(data, "analyze"); pricingFields.style.display = "block"; message.textContent = "DXF 信息提取完成，请确认后计算报价"; } catch (err) { message.textContent = err.message; } finally { analyzeButton.disabled = false; } });
    form.addEventListener("submit", async (event) => { event.preventDefault(); button.disabled = true; message.textContent = "正在上传并核算..."; downloads.innerHTML = ""; try { const res = await fetch("/api/quote", { method: "POST", body: new FormData(form) }); const data = await res.json(); if (!res.ok) throw new Error(data.detail || "核算失败"); renderData(data, "quote"); message.textContent = "核算完成"; } catch (err) { message.textContent = err.message; } finally { button.disabled = false; } });
  </script>
</body>
</html>"""


def _safe_name(name: str) -> str:
    candidate = Path(name).name.strip()
    return candidate or "upload.dxf"


def _result_requires_review(result: AnalysisResult) -> bool:
    return bool(result.warnings or result.skipped_counts or result.profiles_all_count != result.profiles_used_count)


def _status_rows(batch: BatchAnalysisResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        result = item.result
        rows.append({
            "source_file": Path(item.source_file).name,
            "ok": item.ok,
            "requires_review": bool(result and _result_requires_review(result)),
            "profiles_all_count": result.profiles_all_count if result else 0,
            "profiles_used_count": result.profiles_used_count if result else 0,
            "open_path_count": result.open_path_count if result else 0,
            "open_path_length_m": result.open_path_length_m if result else 0,
            "quote_row_count": len(result.quote_rows) if result else 0,
            "skipped_counts": result.skipped_counts if result else {},
            "warnings": result.warnings if result else [],
            "error": item.error,
        })
    return rows


def _quote_rows(batch: BatchAnalysisResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        if not item.result:
            continue
        for row in item.result.quote_rows:
            data = row.as_dict()
            data["source_file"] = Path(item.source_file).name
            rows.append(data)
    return rows


def _geometry_rows(batch: BatchAnalysisResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        if not item.result:
            continue
        for geometry in item.result.basic_geometries:
            data = asdict(geometry)
            data["source_file"] = Path(item.source_file).name
            rows.append(data)
    return rows


def _accuracy_summary(batch: BatchAnalysisResult) -> Dict[str, Any]:
    review_count = 0
    empty_count = 0
    open_path_length_m = 0.0
    for item in batch.items:
        if not item.result:
            continue
        if _result_requires_review(item.result):
            review_count += 1
        if not item.result.quote_rows:
            empty_count += 1
        open_path_length_m += item.result.open_path_length_m
    return {"policy": "自动结果只能作为待确认报价；存在警告、跳过实体、重复视图或无报价行时必须人工复核。", "requires_review_count": review_count, "empty_result_count": empty_count, "open_path_length_m": round(open_path_length_m, 6), "supported_entities": ["LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE", "INSERT"], "unsupported_entities_action": "出现在 skipped_counts 中的实体没有计入切割米数；REGION/POINT/VIEWPORT 不是可直接报价的切割轮廓，正式报价前必须回到 CAD 导出 1:1 边界曲线。"}


def _add_open_path_review_rows(batch: BatchAnalysisResult, rates: QuoteRates) -> None:
    for item in batch.items:
        result = item.result
        if not result or result.quote_rows or result.open_path_length_m <= 0:
            continue
        bbox = result.geometry_bbox
        size_mm = f"{bbox[2] - bbox[0]:.1f}×{bbox[3] - bbox[1]:.1f}" if bbox else "开放路径"
        pierce_count = max(1, result.open_path_count)
        cut_fee = result.open_path_length_m * rates.cut_price_per_meter
        pierce_fee = pierce_count * rates.pierce_price_each
        base = cut_fee + pierce_fee + rates.other_process_fee_each
        unit_price = max(rates.min_charge_each, base * (1 + rates.profit_rate) * (1 + rates.tax_rate))
        result.quote_rows.append(QuoteRow(1, 1, result.drawing_no, result.name or "开放路径待确认", rates.material, rates.thickness_mm, size_mm, 0, pierce_count, result.open_path_length_m, 0.0, 0.0, 0.0, 0.0, rates.quantity, cut_fee, pierce_fee, 0.0, 0.0, rates.other_process_fee_each, base, unit_price, unit_price * rates.quantity, "开放路径按切割费生成待确认报价；未计材料面积/重量，必须人工确认"))
        result.warnings = [w for w in result.warnings if "未生成正式报价" not in w]
        result.warnings.append("开放路径已按切割费生成待确认报价；未计材料面积/重量。")


async def _save_uploads(files: List[UploadFile], job_dir: Path) -> List[Path]:
    upload_dir = job_dir / "uploads"
    upload_dir.mkdir()
    saved_paths: List[Path] = []
    for upload in files:
        filename = _safe_name(upload.filename or "upload.dxf")
        if not filename.lower().endswith(".dxf"):
            raise HTTPException(status_code=400, detail=f"{filename} 不是 DXF 文件")
        path = upload_dir / filename
        path.write_bytes(await upload.read())
        saved_paths.append(path)
    return saved_paths


def _base_summary(batch: BatchAnalysisResult) -> Dict[str, Any]:
    geometries = [g for item in batch.items if item.result for g in item.result.basic_geometries]
    return {"file_count": len(batch.items), "ok_count": batch.ok_count, "error_count": batch.error_count, "quote_row_count": 0, "total_cut_length_m": 0, "total_pierce_count": 0, "total_amount": 0, "total_profiles": sum(item.result.profiles_all_count for item in batch.items if item.result), "total_open_path_count": sum(item.result.open_path_count for item in batch.items if item.result), "total_open_path_length_m": round(sum(item.result.open_path_length_m for item in batch.items if item.result), 4), "total_area_mm2": round(sum(g.area_mm2 for g in geometries), 4), "total_perimeter_mm": round(sum(g.perimeter_mm for g in geometries), 4)}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/api/analyze")
async def analyze(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
    batch = analyze_dxf_batch(await _save_uploads(files, job_dir), rates=QuoteRates(), dedupe_identical=True)
    return {"job_id": job_dir.name, "summary": _base_summary(batch), "accuracy": _accuracy_summary(batch), "geometry_rows": _geometry_rows(batch), "status_rows": _status_rows(batch), "quote_rows": [], "raw": asdict(batch)}


@app.post("/api/quote")
async def quote(files: List[UploadFile] = File(...), material: str = Form("Q235"), thickness_mm: float = Form(10.0), quantity: int = Form(1), density_g_cm3: float = Form(7.85), material_price_per_kg: float = Form(4.0), scrap_price_per_kg: float = Form(2.0), cut_price_per_meter: float = Form(5.0), pierce_price_each: float = Form(0.0), other_process_fee_each: float = Form(0.0), profit_rate: float = Form(0.0), tax_rate: float = Form(0.0), min_charge_each: float = Form(0.0), dedupe_identical: bool = Form(True), quote_open_paths: bool = Form(False)) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
    saved_paths = await _save_uploads(files, job_dir)
    rates = QuoteRates(material=material, thickness_mm=thickness_mm, quantity=quantity, density_g_cm3=density_g_cm3, material_price_per_kg=material_price_per_kg, scrap_price_per_kg=scrap_price_per_kg, cut_price_per_meter=cut_price_per_meter, pierce_price_each=pierce_price_each, other_process_fee_each=other_process_fee_each, profit_rate=profit_rate, tax_rate=tax_rate, min_charge_each=min_charge_each)
    batch = analyze_dxf_batch(saved_paths, rates=rates, dedupe_identical=dedupe_identical)
    if quote_open_paths:
        _add_open_path_review_rows(batch, rates)
    csv_path = job_dir / "batch_quote.csv"
    xlsx_path = job_dir / "laser_quote.xlsx"
    write_batch_csv(batch, csv_path)
    write_quote_xlsx(batch, xlsx_path)
    amount = sum(row.amount for row in batch.quote_rows)
    cut_m = sum(row.cut_length_m * row.quantity for row in batch.quote_rows)
    pierces = sum(row.pierce_count * row.quantity for row in batch.quote_rows)
    job_id = job_dir.name
    return {"job_id": job_id, "summary": {"file_count": len(batch.items), "ok_count": batch.ok_count, "error_count": batch.error_count, "quote_row_count": len(batch.quote_rows), "total_cut_length_m": round(cut_m, 4), "total_pierce_count": pierces, "total_amount": round(amount, 2)}, "accuracy": _accuracy_summary(batch), "geometry_rows": _geometry_rows(batch), "status_rows": _status_rows(batch), "quote_rows": _quote_rows(batch), "raw": asdict(batch), "downloads": {"csv": f"/api/jobs/{job_id}/batch_quote.csv", "xlsx": f"/api/jobs/{job_id}/laser_quote.xlsx"}}


@app.get("/api/jobs/{job_id}/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if "/" in job_id or ".." in job_id or filename not in DOWNLOAD_NAMES:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = JOB_ROOT / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "text/csv" if filename.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=filename, media_type=media_type)
