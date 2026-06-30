from __future__ import annotations

import csv
import math
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from openpyxl import Workbook


app = FastAPI(title="Laser Quote API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOB_ROOT = Path(tempfile.gettempdir()) / "laser_quote_api_jobs"
DOWNLOAD_NAMES = {"batch_quote.csv", "laser_quote.xlsx"}

INDEX_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>激光报价助手</title><style>body{margin:0;background:#f3f4f6;color:#111827;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}.shell{max-width:1120px;margin:0 auto;padding:28px 18px 48px}.hero{background:#111827;color:#fff;border-radius:12px;padding:28px}.hero h1{margin:0 0 10px;font-size:30px}.hero p{margin:0;color:#d1d5db;line-height:1.6}.panel{background:#fff;border:1px solid #e5e7eb;border-radius:10px;margin-top:18px;padding:22px}.grid{display:grid;gap:14px;grid-template-columns:repeat(4,minmax(0,1fr))}label{display:grid;gap:6px;color:#374151;font-size:14px}input{border:1px solid #d1d5db;border-radius:8px;font-size:15px;padding:10px 11px}button{border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;font-size:16px;font-weight:700;padding:12px 18px}.links a{color:#2563eb;font-weight:700;margin-right:14px}.summary{display:grid;gap:10px;grid-template-columns:repeat(4,minmax(0,1fr))}.metric{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px}.metric b{display:block;font-size:22px;margin-top:4px}.warn{background:#fffbeb;border-color:#f59e0b}.ok{background:#ecfdf5;border-color:#10b981}.table-wrap{overflow-x:auto}table{border-collapse:collapse;min-width:980px;width:100%}th,td{border-bottom:1px solid #e5e7eb;font-size:13px;padding:10px 8px;text-align:left;vertical-align:top}th{background:#f9fafb;color:#374151}.muted{color:#6b7280}@media(max-width:760px){.grid,.summary{grid-template-columns:1fr 1fr}}@media(max-width:520px){.grid,.summary{grid-template-columns:1fr}}</style></head><body><main class="shell"><section class="hero"><h1>激光报价助手</h1><p>上传 DXF，自动提取切割米数、孔数、毛重、净重并生成报价。带风险提示的图纸必须人工复核后才能正式报价。</p></section><section class="panel"><form id="quoteForm"><div class="grid"><label>DXF 文件<input name="files" type="file" accept=".dxf" multiple required></label><label>材质<input name="material" value="Q235"></label><label>厚度 mm<input name="thickness_mm" type="number" step="0.01" value="10"></label><label>数量<input name="quantity" type="number" step="1" value="1"></label><label>密度 g/cm3<input name="density_g_cm3" type="number" step="0.0001" value="7.85"></label><label>材料价 元/kg<input name="material_price_per_kg" type="number" step="0.01" value="4"></label><label>废料价 元/kg<input name="scrap_price_per_kg" type="number" step="0.01" value="2"></label><label>切割价 元/m<input name="cut_price_per_meter" type="number" step="0.01" value="5"></label><label>穿孔价 元/次<input name="pierce_price_each" type="number" step="0.01" value="0"></label><label>其他工序 元/件<input name="other_process_fee_each" type="number" step="0.01" value="0"></label><label>利润率<input name="profit_rate" type="number" step="0.0001" value="0"></label><label>税率<input name="tax_rate" type="number" step="0.0001" value="0"></label></div><p><button id="submitBtn" type="submit">开始核算</button> <span id="message" class="muted"></span> <span id="downloadLinks" class="links"></span></p></form></section><section id="result" style="display:none"><section class="panel"><h2>汇总</h2><div id="summary" class="summary"></div></section><section id="accuracyPanel" class="panel"><h2>准确性状态</h2><p id="accuracyText"></p></section><section class="panel"><h2>文件状态</h2><div class="table-wrap"><table id="statusTable"></table></div></section><section class="panel"><h2>报价明细</h2><div class="table-wrap"><table id="quoteTable"></table></div></section></section></main><script>const form=document.getElementById('quoteForm'),button=document.getElementById('submitBtn'),message=document.getElementById('message'),result=document.getElementById('result'),downloads=document.getElementById('downloadLinks');const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function table(el,headers,rows){el.innerHTML='<thead><tr>'+headers.map(h=>`<th>${esc(h[0])}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+headers.map(h=>`<td>${esc(typeof h[1]==='function'?h[1](r):r[h[1]])}</td>`).join('')+'</tr>').join('')+'</tbody>'}form.addEventListener('submit',async e=>{e.preventDefault();button.disabled=true;message.textContent='正在上传并核算...';downloads.innerHTML='';try{const res=await fetch('/api/quote',{method:'POST',body:new FormData(form)});const data=await res.json();if(!res.ok)throw new Error(data.detail||'核算失败');result.style.display='block';const s=data.summary;document.getElementById('summary').innerHTML=[['文件',s.file_count],['报价行',s.quote_row_count],['切割米数',s.total_cut_length_m+' m'],['合计金额','￥'+s.total_amount]].map(x=>`<div class="metric"><span>${esc(x[0])}</span><b>${esc(x[1])}</b></div>`).join('');const a=data.accuracy,p=document.getElementById('accuracyPanel');p.className='panel '+(a.requires_review_count?'warn':'ok');document.getElementById('accuracyText').textContent=`${a.policy} 需人工复核文件数：${a.requires_review_count}；无报价行文件数：${a.empty_result_count}`;table(document.getElementById('statusTable'),[['文件','source_file'],['成功',r=>r.ok?'是':'否'],['需复核',r=>r.requires_review?'是':'否'],['有效轮廓',r=>`${r.profiles_used_count}/${r.profiles_all_count}`],['跳过实体',r=>JSON.stringify(r.skipped_counts||{})],['提醒/错误',r=>(r.warnings||[]).join('；')||r.error]],data.status_rows||[]);table(document.getElementById('quoteTable'),[['文件','source_file'],['尺寸','size_mm'],['孔数','hole_count'],['穿孔','pierce_count'],['切割m',r=>Number(r.cut_length_m||0).toFixed(4)],['单价',r=>Number(r.unit_price||0).toFixed(2)],['金额',r=>Number(r.amount||0).toFixed(2)],['备注','note']],data.quote_rows||[]);downloads.innerHTML=`<a href="${data.downloads.csv}">下载 CSV</a><a href="${data.downloads.xlsx}">下载 Excel</a>`;message.textContent='核算完成'}catch(err){message.textContent=err.message}finally{button.disabled=false}})</script></body></html>"""


@dataclass
class Rates:
    material: str
    thickness_mm: float
    quantity: int
    density_g_cm3: float
    material_price_per_kg: float
    scrap_price_per_kg: float
    cut_price_per_meter: float
    pierce_price_each: float
    other_process_fee_each: float
    profit_rate: float
    tax_rate: float
    min_charge_each: float


def decode_dxf(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "cp936", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", errors="replace")


def pairs(text: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in text.splitlines()]
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def entities(ps: list[tuple[str, str]]):
    in_entities = False
    i = 0
    while i < len(ps):
        if ps[i] == ("0", "SECTION") and i + 1 < len(ps) and ps[i + 1] == ("2", "ENTITIES"):
            in_entities = True
            i += 2
            continue
        if in_entities and ps[i] == ("0", "ENDSEC"):
            break
        if in_entities and ps[i][0] == "0":
            typ = ps[i][1]
            data = []
            i += 1
            while i < len(ps) and ps[i][0] != "0":
                data.append(ps[i])
                i += 1
            yield typ, data
            continue
        i += 1


def vals(data, code):
    out = []
    for c, v in data:
        if c == code:
            try:
                out.append(float(v))
            except ValueError:
                pass
    return out


def val(data, code, default=0.0):
    found = default
    for c, v in data:
        if c == code:
            found = v
    try:
        return float(found)
    except ValueError:
        return default


def sval(data, code, default=""):
    found = default
    for c, v in data:
        if c == code:
            found = v
    return found


def poly_area(pts):
    if len(pts) < 3:
        return 0.0
    area = 0.0
    closed = pts + [pts[0]] if pts[0] != pts[-1] else pts
    for (x1, y1), (x2, y2) in zip(closed, closed[1:]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def analyze_file(path: Path, rates: Rates) -> dict[str, Any]:
    ps = pairs(decode_dxf(path.read_bytes()))
    paths = []
    circles = []
    skipped: dict[str, int] = {}
    layers: dict[str, int] = {}
    excluded = ("图框", "标题", "标注", "文字", "中心", "辅助", "虚线", "DIM", "TEXT", "FRAME", "BORDER", "CENTER")

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for typ, data in entities(ps):
        layer = sval(data, "8")
        layers[layer] = layers.get(layer, 0) + 1
        if any(k.upper() in layer.upper() for k in excluded):
            skip(f"skip_layer:{layer}")
            continue
        if typ == "CIRCLE":
            r = val(data, "40")
            if r > 0:
                circles.append({"cx": val(data, "10"), "cy": val(data, "20"), "r": r})
        elif typ == "LWPOLYLINE":
            xs, ys = vals(data, "10"), vals(data, "20")
            if len(xs) >= 3 and len(xs) == len(ys):
                pts = list(zip(xs, ys))
                length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:] + [pts[0]]))
                paths.append({"pts": pts, "length": length, "area": poly_area(pts)})
        elif typ == "LINE":
            # 单根直线无法确认闭合轮廓，先作为高风险跳过，避免误报价。
            skip("line_needs_closed_profile")
        elif typ in {"ARC", "SPLINE", "ELLIPSE", "INSERT", "HATCH", "POLYLINE"}:
            skip(f"unsupported_type:{typ}")

    outers = [p for p in paths if p["area"] > 1]
    outers.sort(key=lambda x: x["area"], reverse=True)
    if not outers and circles:
        c = max(circles, key=lambda h: h["r"])
        pts = [(c["cx"] - c["r"], c["cy"] - c["r"]), (c["cx"] + c["r"], c["cy"] + c["r"])]
        outers = [{"pts": pts, "length": 2 * math.pi * c["r"], "area": math.pi * c["r"] ** 2}]
        circles = [h for h in circles if h is not c]

    rows = []
    warnings = []
    if not outers:
        warnings.append("未识别到闭合外轮廓；请上传 1:1 展开 DXF，或人工复核轮廓。")
    for i, outer in enumerate(outers[:1], start=1):
        minx, miny, maxx, maxy = bbox(outer["pts"])
        width, height = maxx - minx, maxy - miny
        inner = [h for h in circles if minx <= h["cx"] <= maxx and miny <= h["cy"] <= maxy]
        holes_area = sum(math.pi * h["r"] ** 2 for h in inner)
        holes_len = sum(2 * math.pi * h["r"] for h in inner)
        gross_area = width * height
        net_area = max(0.0, outer["area"] - holes_area)
        cut_m = (outer["length"] + holes_len) / 1000
        pierces = len(inner) + 1
        gross_w = gross_area * rates.thickness_mm * rates.density_g_cm3 / 1_000_000
        net_w = net_area * rates.thickness_mm * rates.density_g_cm3 / 1_000_000
        material_fee = gross_w * rates.material_price_per_kg
        scrap_credit = max(0.0, gross_w - net_w) * rates.scrap_price_per_kg
        cut_fee = cut_m * rates.cut_price_per_meter
        pierce_fee = pierces * rates.pierce_price_each
        base = material_fee - scrap_credit + cut_fee + pierce_fee + rates.other_process_fee_each
        unit = max(rates.min_charge_each, base * (1 + rates.profit_rate) * (1 + rates.tax_rate))
        rows.append({
            "part_index": i, "source_file": path.name, "drawing_no": "", "name": f"零件{i}", "material": rates.material,
            "thickness_mm": rates.thickness_mm, "size_mm": f"{width:.1f}×{height:.1f}", "hole_count": len(inner),
            "pierce_count": pierces, "cut_length_m": cut_m, "gross_area_mm2": gross_area, "net_area_mm2": net_area,
            "gross_weight_kg": gross_w, "net_weight_kg": net_w, "quantity": rates.quantity, "cut_fee_each": cut_fee,
            "pierce_fee_each": pierce_fee, "material_fee_each": material_fee, "scrap_credit_each": scrap_credit,
            "other_process_fee_each": rates.other_process_fee_each, "base_unit_price": base, "unit_price": unit,
            "amount": unit * rates.quantity, "note": "自动提取结果需人工复核"
        })
    if skipped:
        warnings.append("存在跳过或未支持实体；正式报价前必须人工复核。")
    return {"source_file": path.name, "ok": True, "warnings": warnings, "skipped_counts": skipped, "layer_counts": layers,
            "profiles_all_count": len(outers), "profiles_used_count": len(rows), "quote_rows": rows}


def write_csv(rows, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        if not rows:
            f.write("")
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(rows, out_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "正式报价单"
    ws.append(["图号", "名称", "材质", "厚度(mm)", "规格(mm)", "数量", "单价", "金额", "备注"])
    total = 0
    for r in rows:
        total += r["amount"]
        ws.append([r.get("drawing_no", ""), r.get("name", ""), r.get("material", ""), r.get("thickness_mm", 0), r.get("size_mm", ""), r.get("quantity", 0), round(r.get("unit_price", 0), 2), round(r.get("amount", 0), 2), r.get("note", "")])
    ws.append(["", "", "", "", "", "合计", "", round(total, 2), ""])
    wb.save(out_path)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


@app.post("/api/quote")
async def quote(
    files: list[UploadFile] = File(...), material: str = Form("Q235"), thickness_mm: float = Form(10.0), quantity: int = Form(1),
    density_g_cm3: float = Form(7.85), material_price_per_kg: float = Form(4.0), scrap_price_per_kg: float = Form(2.0),
    cut_price_per_meter: float = Form(5.0), pierce_price_each: float = Form(0.0), other_process_fee_each: float = Form(0.0),
    profit_rate: float = Form(0.0), tax_rate: float = Form(0.0), min_charge_each: float = Form(0.0), dedupe_identical: bool = Form(True)
):
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个 DXF 文件")
    rates = Rates(material, thickness_mm, quantity, density_g_cm3, material_price_per_kg, scrap_price_per_kg, cut_price_per_meter, pierce_price_each, other_process_fee_each, profit_rate, tax_rate, min_charge_each)
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=JOB_ROOT))
    upload_dir = job_dir / "uploads"
    upload_dir.mkdir()
    items = []
    rows = []
    for upload in files:
        name = Path(upload.filename or "upload.dxf").name
        if not name.lower().endswith(".dxf"):
            raise HTTPException(status_code=400, detail=f"{name} 不是 DXF 文件")
        path = upload_dir / name
        path.write_bytes(await upload.read())
        item = analyze_file(path, rates)
        items.append(item)
        rows.extend(item["quote_rows"])
    csv_path, xlsx_path = job_dir / "batch_quote.csv", job_dir / "laser_quote.xlsx"
    write_csv(rows, csv_path)
    write_xlsx(rows, xlsx_path)
    review_count = sum(1 for item in items if item["warnings"] or item["skipped_counts"] or item["profiles_all_count"] != item["profiles_used_count"])
    empty_count = sum(1 for item in items if not item["quote_rows"])
    return {
        "job_id": job_dir.name,
        "summary": {"file_count": len(items), "ok_count": len(items), "error_count": 0, "quote_row_count": len(rows), "total_cut_length_m": round(sum(r["cut_length_m"] * r["quantity"] for r in rows), 4), "total_pierce_count": sum(r["pierce_count"] * r["quantity"] for r in rows), "total_amount": round(sum(r["amount"] for r in rows), 2)},
        "accuracy": {"policy": "自动结果只能作为待确认报价；存在警告、跳过实体、重复视图或无报价行时必须人工复核。", "requires_review_count": review_count, "empty_result_count": empty_count, "supported_entities": ["CIRCLE", "LWPOLYLINE"], "unsupported_entities_action": "出现在 skipped_counts 中的实体没有计入切割米数，正式报价前必须人工核对。"},
        "status_rows": [{"source_file": i["source_file"], "ok": i["ok"], "requires_review": bool(i["warnings"] or i["skipped_counts"]), "profiles_all_count": i["profiles_all_count"], "profiles_used_count": i["profiles_used_count"], "quote_row_count": len(i["quote_rows"]), "skipped_counts": i["skipped_counts"], "warnings": i["warnings"], "error": ""} for i in items],
        "quote_rows": rows,
        "downloads": {"csv": f"/api/jobs/{job_dir.name}/batch_quote.csv", "xlsx": f"/api/jobs/{job_dir.name}/laser_quote.xlsx"}
    }


@app.get("/api/jobs/{job_id}/{filename}")
def download(job_id: str, filename: str):
    if "/" in job_id or ".." in job_id or filename not in DOWNLOAD_NAMES:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = JOB_ROOT / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "text/csv" if filename.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=filename, media_type=media_type)
