from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from excel_export import write_quote_xlsx
from quote_core import AUTO_QUOTE_PROFILE_LIMIT, AnalysisResult, BatchAnalysisResult, ProfilePreview, QuoteRates, QuoteRow, analyze_dxf_batch, write_batch_csv


app = FastAPI(title="Laser Quote API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"服务器解析失败：{type(exc).__name__}: {exc}"})

JOB_ROOT = Path(tempfile.gettempdir()) / "laser_quote_api_jobs"
DOWNLOAD_NAMES = {"batch_quote.csv", "laser_quote.xlsx"}
APP_VERSION = os.getenv("RENDER_GIT_COMMIT", "local-dev")[:7]
MAX_COMPLEX_PREVIEW_ROWS = 240

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
    .version { color: #9ca3af; font-size: 13px; margin-top: 10px; }
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
    .preview-box { background: #111827; border-radius: 8px; height: 360px; margin-top: 12px; overflow: hidden; position: relative; }
    .preview-box svg { display: block; height: 100%; width: 100%; }
    .preview-box path, .preview-box circle { fill: none !important; }
    .preview-actions { align-items: center; display: flex; gap: 12px; margin-top: 10px; }
    .preview-tools { display: flex; gap: 8px; }
    .icon-btn { align-items: center; display: inline-flex; height: 38px; justify-content: center; min-width: 38px; padding: 0 12px; }
    .secondary { background: #4b5563; }
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
    <section class="hero"><h1>激光报价助手</h1><p>上传 DXF，先提取基础几何信息，再确认参数并计算待确认报价。</p><div class="version">部署版本：__APP_VERSION__</div></section>
    <section class="panel">
      <form id="quoteForm">
        <div class="grid"><label>DXF 文件<input name="files" type="file" accept=".dxf" multiple required /></label></div>
        <input name="select_min_x" type="hidden" />
        <input name="select_min_y" type="hidden" />
        <input name="select_max_x" type="hidden" />
        <input name="select_max_y" type="hidden" />
        <div class="actions"><button id="analyzeBtn" type="button">1. 提取 DXF 信息</button><span id="message" class="muted"></span></div>
        <div id="pricingFields" style="display:none">
          <p class="hint">先确认下方 DXF 基础信息，再修改报价参数并计算金额。</p>
          <div class="grid">
            <label>材质<input name="material" value="Q235" /></label>
            <label>厚度 mm<input name="thickness_mm" type="number" step="0.01" value="10" /></label>
            <label>数量<input name="quantity" type="number" step="1" value="1" /></label>
            <label>密度 g/cm3<input name="density_g_cm3" type="number" step="0.0001" value="7.85" /></label>
            <label>材料价 元/kg<input name="material_price_per_kg" type="number" step="0.01" value="4" /></label>
            <label>废料价 元/kg<input name="scrap_price_per_kg" type="number" step="0.01" value="2" /></label>
            <label>切割价 元/m<input name="cut_price_per_meter" type="number" step="0.01" value="5" /></label>
            <label>穿孔价 元/次<input name="pierce_price_each" type="number" step="0.01" value="0" /></label>
            <label>其他工序 元/件<input name="other_process_fee_each" type="number" step="0.01" value="0" /></label>
            <label>利润率<input name="profit_rate" type="number" step="0.0001" value="0" /></label>
            <label>税率<input name="tax_rate" type="number" step="0.0001" value="0" /></label>
            <label>开放路径<input name="quote_open_paths" type="checkbox" value="true" checked />按切割费生成待确认报价</label>
          </div>
          <div class="actions"><button id="submitBtn" type="submit">2. 计算待确认报价</button><span id="downloadLinks" class="links"></span></div>
        </div>
      </form>
    </section>
    <section id="result" style="display:none">
      <section class="panel"><h2>汇总</h2><div id="summary" class="summary"></div></section>
      <section class="panel"><h2>图纸预览</h2><p class="hint">拖拽框选有效切割区域后，再次点击“提取 DXF 信息”或“计算待确认报价”。</p><div id="previewBox" class="preview-box"></div><div class="preview-actions"><div class="preview-tools"><button id="zoomIn" class="secondary icon-btn" type="button" title="放大">+</button><button id="zoomOut" class="secondary icon-btn" type="button" title="缩小">-</button><button id="resetView" class="secondary icon-btn" type="button" title="重置视图">重置</button></div><button id="clearSelection" class="secondary" type="button">清除框选</button><span id="selectionText" class="muted"></span></div></section>
      <section id="accuracyPanel" class="panel"><h2>复核提示</h2><p id="accuracyText"></p></section>
      <section class="panel"><h2>基础几何信息</h2><div class="table-wrap"><table id="geometryTable"></table></div></section>
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
    const previewBox = document.getElementById("previewBox");
    const selectionText = document.getElementById("selectionText");
    const selectionInputs = ["select_min_x", "select_min_y", "select_max_x", "select_max_y"].map(name => form.elements[name]);
    let previewState = null;
    let previewRows = [];
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    function table(el, headers, rows) { const body = rows.length ? rows.map(r => "<tr>" + headers.map(h => `<td>${esc(typeof h[1] === "function" ? h[1](r) : r[h[1]])}</td>`).join("") + "</tr>").join("") : `<tr><td colspan="${headers.length}">暂无可显示数据。</td></tr>`; el.innerHTML = "<thead><tr>" + headers.map(h => `<th>${esc(h[0])}</th>`).join("") + "</tr></thead><tbody>" + body + "</tbody>"; }
    function reviewText(data) {
      const rows = data.status_rows || [];
      const messages = [];
      rows.forEach(r => {
        if (r.error) messages.push(`${r.source_file}：${r.error}`);
        (r.review_notes || []).forEach(note => messages.push(`${r.source_file}：${note}`));
      });
      if (messages.length) return messages.join("；");
      return "已识别有效轮廓。自动结果仍建议与原图人工核对后再作为正式报价。";
    }
    async function readResponse(res, fallback) {
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : {}; } catch (err) {
        const plain = text.replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim();
        throw new Error(plain ? `服务器返回错误页：${plain.slice(0, 120)}` : fallback);
      }
      if (!res.ok) throw new Error(data.detail || fallback);
      return data;
    }
    function setSelection(bbox) {
      selectionInputs.forEach((input, i) => { input.disabled = !bbox; input.value = bbox ? Number(bbox[i]).toFixed(6) : ""; });
      selectionText.textContent = bbox ? `已框选：${bbox.map(v => Number(v).toFixed(2)).join(" , ")}` : "";
    }
    function selectedBbox() {
      const values = selectionInputs.map(input => Number(input.value));
      return values.every(Number.isFinite) && selectionInputs.every(input => input.value !== "") ? values : null;
    }
    function pointPath(points) {
      if (!points || points.length < 2) return "";
      return points.map((p, i) => `${i ? "L" : "M"}${Number(p[0]).toFixed(4)},${Number(p[1]).toFixed(4)}`).join(" ");
    }
    function drawPreview(rows) {
      previewRows = rows;
      if (!rows.length) { previewBox.innerHTML = ""; return; }
      const bboxes = rows.map(r => r.bbox).filter(b => Array.isArray(b) && b.length === 4);
      if (!bboxes.length) { previewBox.innerHTML = ""; return; }
      const minX = Math.min(...bboxes.map(b => b[0])), minY = Math.min(...bboxes.map(b => b[1]));
      const maxX = Math.max(...bboxes.map(b => b[2])), maxY = Math.max(...bboxes.map(b => b[3]));
      const pad = Math.max(maxX - minX, maxY - minY) * 0.03 || 1;
      const view = [minX - pad, minY - pad, maxX - minX + pad * 2, maxY - minY + pad * 2];
      const current = selectedBbox();
      const strokeWidth = Math.max(view[2], view[3]) / 2400;
      const shapes = rows.map((r) => {
        if (r.outer_points && r.outer_points.length > 1) {
          const outer = `<path d="${pointPath(r.outer_points)}" style="fill:none!important" stroke="#34d399" stroke-width="${strokeWidth}" vector-effect="non-scaling-stroke" opacity="0.78"></path>`;
          const inners = (r.inner_paths || []).map(path => `<path d="${pointPath(path)}" style="fill:none!important" stroke="#fbbf24" stroke-width="${strokeWidth}" vector-effect="non-scaling-stroke" opacity="0.82"></path>`).join("");
          const holes = (r.hole_circles || []).map(c => `<circle cx="${c.cx}" cy="${c.cy}" r="${c.r}" style="fill:none!important" stroke="#fbbf24" stroke-width="${strokeWidth}" vector-effect="non-scaling-stroke" opacity="0.82"></circle>`).join("");
          return outer + inners + holes;
        }
        const b = r.bbox;
        return `<rect x="${b[0]}" y="${b[1]}" width="${Math.max(0.001, b[2]-b[0])}" height="${Math.max(0.001, b[3]-b[1])}" fill="none" stroke="#34d399" stroke-width="${strokeWidth}" vector-effect="non-scaling-stroke"></rect>`;
      }).join("");
      const selected = current ? `<rect id="selectionRect" x="${current[0]}" y="${current[1]}" width="${current[2]-current[0]}" height="${current[3]-current[1]}" fill="rgba(37,99,235,.18)" stroke="#60a5fa" stroke-width="${view[2] / 400}" vector-effect="non-scaling-stroke"></rect>` : `<rect id="selectionRect" x="0" y="0" width="0" height="0" fill="rgba(37,99,235,.18)" stroke="#60a5fa" stroke-width="${view[2] / 400}" vector-effect="non-scaling-stroke"></rect>`;
      previewBox.innerHTML = `<svg id="previewSvg" viewBox="${view.join(" ")}" preserveAspectRatio="xMidYMid meet">${shapes}${selected}</svg>`;
      const svg = document.getElementById("previewSvg");
      const selectionRect = document.getElementById("selectionRect");
      previewState = { svg, baseView: view.slice(), view: view.slice(), selectionRect, start: null };
      const setView = (nextView) => {
        previewState.view = nextView;
        svg.setAttribute("viewBox", nextView.join(" "));
      };
      const point = (event) => {
        const pt = svg.createSVGPoint(); pt.x = event.clientX; pt.y = event.clientY;
        const p = pt.matrixTransform(svg.getScreenCTM().inverse());
        return [p.x, p.y];
      };
      const zoomAt = (anchor, factor) => {
        const [x, y, w, h] = previewState.view;
        const nextW = Math.max(previewState.baseView[2] / 200, Math.min(previewState.baseView[2] * 8, w * factor));
        const nextH = Math.max(previewState.baseView[3] / 200, Math.min(previewState.baseView[3] * 8, h * factor));
        const rx = (anchor[0] - x) / w, ry = (anchor[1] - y) / h;
        setView([anchor[0] - nextW * rx, anchor[1] - nextH * ry, nextW, nextH]);
      };
      previewState.zoomCenter = (factor) => zoomAt([previewState.view[0] + previewState.view[2] / 2, previewState.view[1] + previewState.view[3] / 2], factor);
      previewState.reset = () => setView(previewState.baseView.slice());
      svg.addEventListener("wheel", event => { event.preventDefault(); zoomAt(point(event), event.deltaY < 0 ? 0.8 : 1.25); }, { passive: false });
      svg.addEventListener("pointerdown", event => { previewState.start = point(event); svg.setPointerCapture(event.pointerId); });
      svg.addEventListener("pointermove", event => {
        if (!previewState.start) return;
        const p = point(event), x1 = Math.min(previewState.start[0], p[0]), x2 = Math.max(previewState.start[0], p[0]), y1 = Math.min(previewState.start[1], p[1]), y2 = Math.max(previewState.start[1], p[1]);
        selectionRect.setAttribute("x", x1); selectionRect.setAttribute("y", y1); selectionRect.setAttribute("width", x2 - x1); selectionRect.setAttribute("height", y2 - y1);
      });
      svg.addEventListener("pointerup", event => {
        if (!previewState.start) return;
        const p = point(event), bbox = [Math.min(previewState.start[0], p[0]), Math.min(previewState.start[1], p[1]), Math.max(previewState.start[0], p[0]), Math.max(previewState.start[1], p[1])];
        previewState.start = null;
        if ((bbox[2] - bbox[0]) > view[2] * 0.002 && (bbox[3] - bbox[1]) > view[3] * 0.002) setSelection(bbox);
      });
    }
    document.getElementById("zoomIn").addEventListener("click", () => previewState && previewState.zoomCenter(0.8));
    document.getElementById("zoomOut").addEventListener("click", () => previewState && previewState.zoomCenter(1.25));
    document.getElementById("resetView").addEventListener("click", () => previewState && previewState.reset());
    function renderData(data, mode) {
      result.style.display = "block";
      const s = data.summary, isAnalyze = mode === "analyze";
      document.getElementById("summary").innerHTML = [["文件", s.file_count], [isAnalyze ? "候选轮廓" : "报价行", isAnalyze ? (s.total_profiles || 0) : s.quote_row_count], [isAnalyze ? "已确认面积" : "切割米数", isAnalyze ? `${s.total_area_mm2 || 0} mm²` : s.total_cut_length_m + " m"], [isAnalyze ? "需复核" : "待确认金额", isAnalyze ? (data.accuracy.requires_review_count || 0) : "￥" + s.total_amount]].map(x => `<div class="metric"><span>${esc(x[0])}</span><b>${esc(x[1])}</b></div>`).join("");
      const a = data.accuracy; document.getElementById("accuracyPanel").className = "panel " + (a.requires_review_count ? "warn" : "ok"); document.getElementById("accuracyText").textContent = reviewText(data);
      drawPreview(data.preview_rows || data.geometry_rows || []);
      table(document.getElementById("geometryTable"), [["文件", "source_file"], ["类型", "kind"], ["闭合", r => r.closed ? "是" : "否"], ["面积 mm²", r => Number(r.area_mm2 || 0).toFixed(4)], ["周长 mm", r => Number(r.perimeter_mm || 0).toFixed(4)], ["宽×高 mm", r => `${Number(r.width_mm || 0).toFixed(4)}×${Number(r.height_mm || 0).toFixed(4)}`], ["备注", "note"]], data.geometry_rows || []);
      table(document.getElementById("quoteTable"), [["文件", "source_file"], ["图号", "drawing_no"], ["名称", "name"], ["尺寸", "size_mm"], ["孔数", "hole_count"], ["穿孔", "pierce_count"], ["切割m", r => Number(r.cut_length_m || 0).toFixed(4)], ["单价", r => Number(r.unit_price || 0).toFixed(4)], ["金额", r => Number(r.amount || 0).toFixed(4)], ["备注", "note"]], data.quote_rows || []);
      downloads.innerHTML = data.downloads ? `<a href="${data.downloads.csv}">下载 CSV</a><a href="${data.downloads.xlsx}">下载 Excel</a>` : "";
    }
    document.getElementById("clearSelection").addEventListener("click", () => { setSelection(null); drawPreview(previewRows); });
    analyzeButton.addEventListener("click", async () => { analyzeButton.disabled = true; message.textContent = "正在提取 DXF 信息..."; downloads.innerHTML = ""; try { const res = await fetch("/api/analyze", { method: "POST", body: new FormData(form) }); const data = await readResponse(res, "提取失败"); renderData(data, "analyze"); pricingFields.style.display = "block"; message.textContent = "DXF 信息提取完成，请确认后计算报价"; } catch (err) { message.textContent = err.message; } finally { analyzeButton.disabled = false; } });
    form.addEventListener("submit", async (event) => { event.preventDefault(); button.disabled = true; message.textContent = "正在上传并核算..."; downloads.innerHTML = ""; try { const res = await fetch("/api/quote", { method: "POST", body: new FormData(form) }); const data = await readResponse(res, "核算失败"); renderData(data, "quote"); message.textContent = "核算完成"; } catch (err) { message.textContent = err.message; } finally { button.disabled = false; } });
    setSelection(null);
  </script>
</body>
</html>"""


def _safe_name(name: str) -> str:
    candidate = Path(name).name.strip()
    return candidate or "upload.dxf"


def _review_notes(result: AnalysisResult) -> List[str]:
    notes: List[str] = []
    exact_region = bool(result.skipped_counts.get("exact_type:REGION"))
    complex_unselected = result.profiles_all_count > AUTO_QUOTE_PROFILE_LIMIT and not result.basic_geometries and not result.quote_rows
    if result.profiles_all_count != result.profiles_used_count:
        notes.append("检测到疑似重复轮廓，已按默认去重处理，请确认数量。")
    if complex_unselected:
        notes.append("复杂图预览已隐藏超大外框候选；请框选真实切割区域后重新提取。")
    if result.open_path_count:
        notes.append("存在开放路径，请确认是否需要按切割路径报价。")
    for warning in result.warnings:
        if exact_region and "已从 ACIS 边界精确还原" in warning:
            continue
        if warning not in notes:
            notes.append(warning)
    return notes


def _result_requires_review(result: AnalysisResult) -> bool:
    return bool(_review_notes(result))


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
            "review_notes": _review_notes(result) if result else [],
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


def _rounded_point(point: Tuple[float, float]) -> Tuple[float, float]:
    return round(point[0], 4), round(point[1], 4)


def _sample_points(points: List[Tuple[float, float]], max_points: int = 80) -> List[Tuple[float, float]]:
    if len(points) <= max_points:
        return [_rounded_point(point) for point in points]
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return [_rounded_point(point) for point in sampled]


def _visible_previews(result: AnalysisResult) -> List[ProfilePreview]:
    previews = list(result.profile_previews)
    complex_unselected = result.profiles_all_count > AUTO_QUOTE_PROFILE_LIMIT and not result.basic_geometries and not result.quote_rows
    if not complex_unselected:
        return previews
    areas = sorted(preview.gross_area_mm2 for preview in previews)
    if not areas:
        return previews
    large_threshold = areas[max(0, int(len(areas) * 0.95) - 1)]
    visible = [preview for preview in previews if preview.gross_area_mm2 <= large_threshold]
    if not visible:
        visible = previews
    return sorted(visible, key=lambda preview: preview.gross_area_mm2)[:MAX_COMPLEX_PREVIEW_ROWS]


def _preview_rows(batch: BatchAnalysisResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        if not item.result:
            continue
        source_file = Path(item.source_file).name
        for preview in _visible_previews(item.result):
            rows.append({
                "source_file": source_file,
                "part_index": preview.part_index,
                "bbox": tuple(round(value, 4) for value in preview.bbox),
                "outer_points": _sample_points(preview.outer_points),
                "inner_paths": [_sample_points(path, 50) for path in preview.inner_paths[:8]],
                "hole_circles": [{key: round(value, 4) for key, value in circle.items()} for circle in preview.hole_circles[:40]],
            })
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
    return {"requires_review_count": review_count, "empty_result_count": empty_count, "open_path_length_m": round(open_path_length_m, 6)}


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


def _selection_bbox(min_x: Optional[float], min_y: Optional[float], max_x: Optional[float], max_y: Optional[float]) -> Optional[Tuple[float, float, float, float]]:
    values = (min_x, min_y, max_x, max_y)
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = (float(value) for value in values if value is not None)
    if abs(x2 - x1) < 1e-9 or abs(y2 - y1) < 1e-9:
        return None
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _base_summary(batch: BatchAnalysisResult) -> Dict[str, Any]:
    geometries = [g for item in batch.items if item.result for g in item.result.basic_geometries]
    return {"file_count": len(batch.items), "ok_count": batch.ok_count, "error_count": batch.error_count, "quote_row_count": 0, "total_cut_length_m": 0, "total_pierce_count": 0, "total_amount": 0, "total_profiles": sum(item.result.profiles_all_count for item in batch.items if item.result), "total_open_path_count": sum(item.result.open_path_count for item in batch.items if item.result), "total_open_path_length_m": round(sum(item.result.open_path_length_m for item in batch.items if item.result), 4), "total_area_mm2": round(sum(g.area_mm2 for g in geometries), 4), "total_perimeter_mm": round(sum(g.perimeter_mm for g in geometries), 4)}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        INDEX_HTML.replace("__APP_VERSION__", APP_VERSION),
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.post("/api/analyze")
async def analyze(files: List[UploadFile] = File(...), select_min_x: Optional[float] = Form(None), select_min_y: Optional[float] = Form(None), select_max_x: Optional[float] = Form(None), select_max_y: Optional[float] = Form(None)) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
    batch = analyze_dxf_batch(await _save_uploads(files, job_dir), rates=QuoteRates(), dedupe_identical=True, selection_bbox=_selection_bbox(select_min_x, select_min_y, select_max_x, select_max_y))
    return {"job_id": job_dir.name, "summary": _base_summary(batch), "accuracy": _accuracy_summary(batch), "preview_rows": _preview_rows(batch), "geometry_rows": _geometry_rows(batch), "status_rows": _status_rows(batch), "quote_rows": []}


@app.post("/api/quote")
async def quote(files: List[UploadFile] = File(...), material: str = Form("Q235"), thickness_mm: float = Form(10.0), quantity: int = Form(1), density_g_cm3: float = Form(7.85), material_price_per_kg: float = Form(4.0), scrap_price_per_kg: float = Form(2.0), cut_price_per_meter: float = Form(5.0), pierce_price_each: float = Form(0.0), other_process_fee_each: float = Form(0.0), profit_rate: float = Form(0.0), tax_rate: float = Form(0.0), min_charge_each: float = Form(0.0), dedupe_identical: bool = Form(True), quote_open_paths: bool = Form(False), select_min_x: Optional[float] = Form(None), select_min_y: Optional[float] = Form(None), select_max_x: Optional[float] = Form(None), select_max_y: Optional[float] = Form(None)) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
    saved_paths = await _save_uploads(files, job_dir)
    rates = QuoteRates(material=material, thickness_mm=thickness_mm, quantity=quantity, density_g_cm3=density_g_cm3, material_price_per_kg=material_price_per_kg, scrap_price_per_kg=scrap_price_per_kg, cut_price_per_meter=cut_price_per_meter, pierce_price_each=pierce_price_each, other_process_fee_each=other_process_fee_each, profit_rate=profit_rate, tax_rate=tax_rate, min_charge_each=min_charge_each)
    batch = analyze_dxf_batch(saved_paths, rates=rates, dedupe_identical=dedupe_identical, selection_bbox=_selection_bbox(select_min_x, select_min_y, select_max_x, select_max_y))
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
    return {"job_id": job_id, "summary": {"file_count": len(batch.items), "ok_count": batch.ok_count, "error_count": batch.error_count, "quote_row_count": len(batch.quote_rows), "total_cut_length_m": round(cut_m, 4), "total_pierce_count": pierces, "total_amount": round(amount, 4)}, "accuracy": _accuracy_summary(batch), "preview_rows": _preview_rows(batch), "geometry_rows": _geometry_rows(batch), "status_rows": _status_rows(batch), "quote_rows": _quote_rows(batch), "downloads": {"csv": f"/api/jobs/{job_id}/batch_quote.csv", "xlsx": f"/api/jobs/{job_id}/laser_quote.xlsx"}}


@app.get("/api/jobs/{job_id}/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if "/" in job_id or ".." in job_id or filename not in DOWNLOAD_NAMES:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = JOB_ROOT / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "text/csv" if filename.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=filename, media_type=media_type)
