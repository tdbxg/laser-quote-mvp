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
    <section class="hero">
      <h1>激光报价助手</h1>
      <p>上传 DXF，自动提取切割米数、孔数、毛重、净重并生成报价。带风险提示的图纸必须人工复核后才能正式报价。</p>
    </section>

    <section class="panel">
      <form id="quoteForm">
        <div class="grid">
          <label>DXF 文件<input name="files" type="file" accept=".dxf" multiple required /></label>
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
        <p class="hint">这些数值是系统默认值，不是从 DXF 自动读取。闭合板件会用材质、厚度、材料价等计算材料费；开放路径只按切割米数、穿孔价、其他工序、利润率和税率生成待确认报价。</p>
        <div class="actions">
          <button id="submitBtn" type="submit">开始核算</button>
          <span id="message" class="muted"></span>
          <span id="downloadLinks" class="links"></span>
        </div>
      </form>
    </section>

    <section id="result" style="display:none">
      <section class="panel">
        <h2>汇总</h2>
        <div id="summary" class="summary"></div>
      </section>
      <section id="accuracyPanel" class="panel">
        <h2>准确性状态</h2>
        <p id="accuracyText"></p>
      </section>
      <section class="panel">
        <h2>文件状态</h2>
        <div class="table-wrap"><table id="statusTable"></table></div>
      </section>
      <section class="panel">
        <h2>报价明细</h2>
        <div class="table-wrap"><table id="quoteTable"></table></div>
      </section>
    </section>
  </main>
  <script>
    const form = document.getElementById("quoteForm");
    const button = document.getElementById("submitBtn");
    const message = document.getElementById("message");
    const result = document.getElementById("result");
    const downloads = document.getElementById("downloadLinks");
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    function table(el, headers, rows) {
      el.innerHTML = "<thead><tr>" + headers.map(h => `<th>${esc(h[0])}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map(r => "<tr>" + headers.map(h => `<td>${esc(typeof h[1] === "function" ? h[1](r) : r[h[1]])}</td>`).join("") + "</tr>").join("") +
        "</tbody>";
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      message.textContent = "正在上传并核算...";
      downloads.innerHTML = "";
      try {
        const res = await fetch("/api/quote", { method: "POST", body: new FormData(form) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "核算失败");
        result.style.display = "block";
        const s = data.summary;
        document.getElementById("summary").innerHTML = [
          ["文件", s.file_count], ["报价行", s.quote_row_count], ["切割米数", s.total_cut_length_m + " m"], ["待确认金额", "￥" + s.total_amount]
        ].map(x => `<div class="metric"><span>${esc(x[0])}</span><b>${esc(x[1])}</b></div>`).join("");
        const a = data.accuracy;
        const accuracyPanel = document.getElementById("accuracyPanel");
        accuracyPanel.className = "panel " + (a.requires_review_count ? "warn" : "ok");
        document.getElementById("accuracyText").textContent = `${a.policy} 需人工复核文件数：${a.requires_review_count}；无报价行文件数：${a.empty_result_count}`;
        table(document.getElementById("statusTable"), [
          ["文件", "source_file"], ["成功", r => r.ok ? "是" : "否"], ["需复核", r => r.requires_review ? "是" : "否"],
          ["有效轮廓", r => `${r.profiles_used_count}/${r.profiles_all_count}`], ["开放路径", r => `${Number(r.open_path_length_m || 0).toFixed(4)} m / ${r.open_path_count || 0} 组`],
          ["跳过实体", r => JSON.stringify(r.skipped_counts || {})],
          ["提醒/错误", r => (r.warnings || []).join("；") || r.error]
        ], data.status_rows || []);
        table(document.getElementById("quoteTable"), [
          ["文件", "source_file"], ["图号", "drawing_no"], ["名称", "name"], ["尺寸", "size_mm"], ["孔数", "hole_count"],
          ["穿孔", "pierce_count"], ["切割m", r => Number(r.cut_length_m || 0).toFixed(4)], ["单价", r => Number(r.unit_price || 0).toFixed(2)],
          ["金额", r => Number(r.amount || 0).toFixed(2)], ["备注", "note"]
        ], data.quote_rows || []);
        downloads.innerHTML = `<a href="${data.downloads.csv}">下载 CSV</a><a href="${data.downloads.xlsx}">下载 Excel</a>`;
        message.textContent = "核算完成";
      } catch (err) {
        message.textContent = err.message;
      } finally {
        button.disabled = false;
      }
    });
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
        rows.append(
            {
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
            }
        )
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
    return {
        "policy": "自动结果只能作为待确认报价；存在警告、跳过实体、重复视图或无报价行时必须人工复核。",
        "requires_review_count": review_count,
        "empty_result_count": empty_count,
        "open_path_length_m": round(open_path_length_m, 6),
        "supported_entities": ["LINE", "ARC", "CIRCLE", "LWPOLYLINE", "SPLINE"],
        "unsupported_entities_action": "出现在 skipped_counts 中的实体没有计入切割米数，正式报价前必须回到 CAD 或预览页核对。",
    }


def _add_open_path_review_rows(batch: BatchAnalysisResult, rates: QuoteRates) -> None:
    for item in batch.items:
        result = item.result
        if not result or result.quote_rows or result.open_path_length_m <= 0:
            continue
        bbox = result.geometry_bbox
        if bbox:
            size_mm = f"{bbox[2] - bbox[0]:.1f}×{bbox[3] - bbox[1]:.1f}"
        else:
            size_mm = "开放路径"
        pierce_count = max(1, result.open_path_count)
        cut_fee = result.open_path_length_m * rates.cut_price_per_meter
        pierce_fee = pierce_count * rates.pierce_price_each
        base = cut_fee + pierce_fee + rates.other_process_fee_each
        unit_price = max(rates.min_charge_each, base * (1 + rates.profit_rate) * (1 + rates.tax_rate))
        result.quote_rows.append(
            QuoteRow(
                part_index=1,
                duplicate_count=1,
                drawing_no=result.drawing_no,
                name=result.name or "开放路径待确认",
                material=rates.material,
                thickness_mm=rates.thickness_mm,
                size_mm=size_mm,
                hole_count=0,
                pierce_count=pierce_count,
                cut_length_m=result.open_path_length_m,
                gross_area_mm2=0.0,
                net_area_mm2=0.0,
                gross_weight_kg=0.0,
                net_weight_kg=0.0,
                quantity=rates.quantity,
                cut_fee_each=cut_fee,
                pierce_fee_each=pierce_fee,
                material_fee_each=0.0,
                scrap_credit_each=0.0,
                other_process_fee_each=rates.other_process_fee_each,
                base_unit_price=base,
                unit_price=unit_price,
                amount=unit_price * rates.quantity,
                note="开放路径按切割费生成待确认报价；未计材料面积/重量，必须人工确认",
            )
        )
        result.warnings = [
            warning for warning in result.warnings
            if "未生成正式报价行" not in warning and "未生成正式报价" not in warning
        ]
        result.warnings.append("开放路径已按切割费生成待确认报价；未计材料面积/重量。")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/api/quote")
async def quote(
    files: List[UploadFile] = File(...),
    material: str = Form("Q235"),
    thickness_mm: float = Form(10.0),
    quantity: int = Form(1),
    density_g_cm3: float = Form(7.85),
    material_price_per_kg: float = Form(4.0),
    scrap_price_per_kg: float = Form(2.0),
    cut_price_per_meter: float = Form(5.0),
    pierce_price_each: float = Form(0.0),
    other_process_fee_each: float = Form(0.0),
    profit_rate: float = Form(0.0),
    tax_rate: float = Form(0.0),
    min_charge_each: float = Form(0.0),
    dedupe_identical: bool = Form(True),
    quote_open_paths: bool = Form(False),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")

    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
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

    rates = QuoteRates(
        material=material,
        thickness_mm=thickness_mm,
        quantity=quantity,
        density_g_cm3=density_g_cm3,
        material_price_per_kg=material_price_per_kg,
        scrap_price_per_kg=scrap_price_per_kg,
        cut_price_per_meter=cut_price_per_meter,
        pierce_price_each=pierce_price_each,
        other_process_fee_each=other_process_fee_each,
        profit_rate=profit_rate,
        tax_rate=tax_rate,
        min_charge_each=min_charge_each,
    )
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
    return {
        "job_id": job_id,
        "summary": {
            "file_count": len(batch.items),
            "ok_count": batch.ok_count,
            "error_count": batch.error_count,
            "quote_row_count": len(batch.quote_rows),
            "total_cut_length_m": round(cut_m, 4),
            "total_pierce_count": pierces,
            "total_amount": round(amount, 2),
        },
        "accuracy": _accuracy_summary(batch),
        "status_rows": _status_rows(batch),
        "quote_rows": _quote_rows(batch),
        "raw": asdict(batch),
        "downloads": {
            "csv": f"/api/jobs/{job_id}/batch_quote.csv",
            "xlsx": f"/api/jobs/{job_id}/laser_quote.xlsx",
        },
    }


@app.get("/api/jobs/{job_id}/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if "/" in job_id or ".." in job_id or filename not in DOWNLOAD_NAMES:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = JOB_ROOT / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "text/csv" if filename.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=filename, media_type=media_type)
