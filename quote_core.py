"""
DXF 激光切割报价核算核心模块（MVP）

功能：
- 读取 ASCII DXF（支持常见 GBK/UTF-8 编码）
- 过滤图框、文字、标注、中心线图层
- 识别 LINE / ARC / CIRCLE / LWPOLYLINE / SPLINE 等 2D 切割几何
- 自动识别外轮廓、内孔、重复视图
- 计算外形尺寸、切割米数、孔数、穿孔数、净面积、毛面积、毛重、净重
- 按报价参数计算单价和金额
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import argparse
import csv
import json
import math
import re
import sys

KG_DENSITY_FACTOR = 1_000_000.0
EXCLUDED_LAYER_KEYWORDS = ("图框", "标题", "标注", "文字", "中心", "辅助", "虚线", "DIM", "TEXT", "FRAME", "BORDER", "CENTER")


@dataclass
class Line:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def type(self) -> str:
        return "LINE"

    def endpoints(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.x1, self.y1), (self.x2, self.y2)

    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    def points(self, reverse: bool = False) -> List[Tuple[float, float]]:
        pts = [(self.x1, self.y1), (self.x2, self.y2)]
        return list(reversed(pts)) if reverse else pts


@dataclass
class Arc:
    layer: str
    cx: float
    cy: float
    r: float
    start_deg: float
    end_deg: float

    @property
    def type(self) -> str:
        return "ARC"

    def _angle_span_deg(self) -> float:
        span = self.end_deg - self.start_deg
        while span <= 0:
            span += 360.0
        return span

    def endpoints(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        a1 = math.radians(self.start_deg)
        a2 = math.radians(self.end_deg)
        return ((self.cx + self.r * math.cos(a1), self.cy + self.r * math.sin(a1)), (self.cx + self.r * math.cos(a2), self.cy + self.r * math.sin(a2)))

    def length(self) -> float:
        return 2 * math.pi * self.r * self._angle_span_deg() / 360.0

    def points(self, reverse: bool = False, max_step_deg: float = 5.0) -> List[Tuple[float, float]]:
        start = self.start_deg
        end = self.end_deg
        while end <= start:
            end += 360.0
        steps = max(2, int(math.ceil((end - start) / max_step_deg)) + 1)
        pts = []
        for i in range(steps):
            a = start + (end - start) * i / (steps - 1)
            ar = math.radians(a)
            pts.append((self.cx + self.r * math.cos(ar), self.cy + self.r * math.sin(ar)))
        return list(reversed(pts)) if reverse else pts


@dataclass
class Circle:
    layer: str
    cx: float
    cy: float
    r: float

    @property
    def type(self) -> str:
        return "CIRCLE"

    def length(self) -> float:
        return 2 * math.pi * self.r

    def area(self) -> float:
        return math.pi * self.r * self.r


@dataclass
class Polyline:
    layer: str
    points_xy: List[Tuple[float, float]]
    closed: bool = False

    @property
    def type(self) -> str:
        return "LWPOLYLINE"

    def to_lines(self) -> List[Line]:
        if len(self.points_xy) < 2:
            return []
        pts = self.points_xy + ([self.points_xy[0]] if self.closed else [])
        return [Line(self.layer, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]


PathEntity = Line | Arc


def _de_boor_point(degree: int, knots: Sequence[float], controls: Sequence[Tuple[float, float]], t: float) -> Tuple[float, float]:
    n = len(controls) - 1
    if n < 0:
        return (0.0, 0.0)
    if t >= knots[n + 1]:
        return controls[-1]
    k = degree
    for i in range(degree, n + 1):
        if knots[i] <= t < knots[i + 1]:
            k = i
            break
    d = [controls[j] for j in range(k - degree, k + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            left = knots[k - degree + j]
            right = knots[k + 1 + j - r]
            denom = right - left
            alpha = 0.0 if abs(denom) < 1e-12 else (t - left) / denom
            d[j] = ((1 - alpha) * d[j - 1][0] + alpha * d[j][0], (1 - alpha) * d[j - 1][1] + alpha * d[j][1])
    return d[degree]


def spline_to_lines(layer: str, degree: int, knots: Sequence[float], controls: Sequence[Tuple[float, float]], flags: int = 0, samples_per_span: int = 18) -> List[Line]:
    if degree < 1 or len(controls) <= degree or len(knots) < len(controls) + degree + 1:
        return []
    start = knots[degree]
    end = knots[len(controls)]
    if end <= start:
        return []
    span_count = max(1, len({round(k, 9) for k in knots if start < k < end}) + 1)
    sample_count = max(16, span_count * samples_per_span)
    pts = [_de_boor_point(degree, knots, controls, start + (end - start) * i / sample_count) for i in range(sample_count + 1)]
    if flags & 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 0.01:
        pts.append(pts[0])
    return [Line(layer, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]) if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-9]


@dataclass
class PathComponent:
    segments: List[PathEntity]
    points: List[Tuple[float, float]]
    length_mm: float
    area_mm2: float
    bbox: Tuple[float, float, float, float]
    closed: bool


@dataclass
class PartProfile:
    index: int
    outer: PathComponent
    holes: List[Circle] = field(default_factory=list)
    inner_paths: List[PathComponent] = field(default_factory=list)
    duplicate_count: int = 1

    @property
    def width_mm(self) -> float:
        x1, _, x2, _ = self.outer.bbox
        return x2 - x1

    @property
    def height_mm(self) -> float:
        _, y1, _, y2 = self.outer.bbox
        return y2 - y1

    @property
    def outer_area_mm2(self) -> float:
        return self.outer.area_mm2

    @property
    def holes_area_mm2(self) -> float:
        return sum(h.area() for h in self.holes) + sum(h.area_mm2 for h in self.inner_paths)

    @property
    def net_area_mm2(self) -> float:
        return max(0.0, self.outer_area_mm2 - self.holes_area_mm2)

    @property
    def gross_area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    @property
    def cut_length_mm(self) -> float:
        return self.outer.length_mm + sum(h.length() for h in self.holes) + sum(h.length_mm for h in self.inner_paths)

    @property
    def hole_count(self) -> int:
        return len(self.holes) + len(self.inner_paths)

    @property
    def pierce_count(self) -> int:
        return self.hole_count + 1

    def signature(self) -> Tuple[Any, ...]:
        minx, miny, _, _ = self.outer.bbox
        hole_sig = sorted((round(h.cx - minx, 1), round(h.cy - miny, 1), round(h.r, 1)) for h in self.holes)
        inner_sig = sorted((round(p.area_mm2, 1), round(p.length_mm, 1)) for p in self.inner_paths)
        return (round(self.width_mm, 1), round(self.height_mm, 1), round(self.outer_area_mm2, 0), round(self.outer.length_mm, 1), tuple(hole_sig), tuple(inner_sig))


@dataclass
class QuoteRates:
    material: str = "Q235"
    thickness_mm: float = 10.0
    quantity: int = 1
    density_g_cm3: float = 7.85
    material_price_per_kg: float = 4.0
    scrap_price_per_kg: float = 2.0
    cut_price_per_meter: float = 5.0
    pierce_price_each: float = 0.0
    other_process_fee_each: float = 0.0
    profit_rate: float = 0.0
    tax_rate: float = 0.0
    min_charge_each: float = 0.0


@dataclass
class QuoteRow:
    part_index: int
    duplicate_count: int
    drawing_no: str
    name: str
    material: str
    thickness_mm: float
    size_mm: str
    hole_count: int
    pierce_count: int
    cut_length_m: float
    gross_area_mm2: float
    net_area_mm2: float
    gross_weight_kg: float
    net_weight_kg: float
    quantity: int
    cut_fee_each: float
    pierce_fee_each: float
    material_fee_each: float
    scrap_credit_each: float
    other_process_fee_each: float
    base_unit_price: float
    unit_price: float
    amount: float
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProfilePreview:
    part_index: int
    selected_by_default: bool
    duplicate_count: int
    bbox: Tuple[float, float, float, float]
    outer_points: List[Tuple[float, float]]
    hole_circles: List[Dict[str, float]]
    inner_paths: List[List[Tuple[float, float]]]
    size_mm: str
    hole_count: int
    pierce_count: int
    cut_length_m: float
    gross_area_mm2: float
    net_area_mm2: float


@dataclass
class AnalysisResult:
    source_file: str
    drawing_no: str = ""
    name: str = ""
    material_hint: str = ""
    texts: List[str] = field(default_factory=list)
    layer_counts: Dict[str, int] = field(default_factory=dict)
    skipped_counts: Dict[str, int] = field(default_factory=dict)
    profiles_all_count: int = 0
    profiles_used_count: int = 0
    open_path_count: int = 0
    open_path_length_m: float = 0.0
    geometry_bbox: Optional[Tuple[float, float, float, float]] = None
    duplicate_groups: List[int] = field(default_factory=list)
    profile_previews: List[ProfilePreview] = field(default_factory=list)
    quote_rows: List[QuoteRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass
class BatchItemResult:
    source_file: str
    ok: bool
    result: Optional[AnalysisResult] = None
    error: str = ""


@dataclass
class BatchAnalysisResult:
    items: List[BatchItemResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for item in self.items if item.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.items if not item.ok)

    @property
    def quote_rows(self) -> List[QuoteRow]:
        rows: List[QuoteRow] = []
        for item in self.items:
            if item.result:
                rows.extend(item.result.quote_rows)
        return rows

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _decode_dxf(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "cp936", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace")


def read_dxf_pairs(path: str | Path) -> List[Tuple[str, str]]:
    lines = _decode_dxf(Path(path).read_bytes()).splitlines()
    return [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]


def iter_dxf_entities(pairs: Sequence[Tuple[str, str]], section_name: Optional[str] = "ENTITIES") -> Iterable[Tuple[str, List[Tuple[str, str]]]]:
    in_section = section_name is None
    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        if section_name and code == "0" and value == "SECTION" and i + 1 < len(pairs) and pairs[i + 1] == ("2", section_name):
            in_section = True
            i += 2
            continue
        if section_name and in_section and code == "0" and value == "ENDSEC":
            break
        if in_section and code == "0":
            ent_type = value
            data: List[Tuple[str, str]] = []
            i += 1
            while i < len(pairs) and pairs[i][0] != "0":
                data.append(pairs[i])
                i += 1
            yield ent_type, data
            continue
        i += 1


def _last(data: List[Tuple[str, str]], code: str, default: str = "") -> str:
    found = default
    for c, v in data:
        if c == code:
            found = v
    return found


def _floats(data: List[Tuple[str, str]], code: str) -> List[float]:
    out = []
    for c, v in data:
        if c == code:
            try:
                out.append(float(v))
            except ValueError:
                pass
    return out


def _float(data: List[Tuple[str, str]], code: str, default: float = 0.0) -> float:
    try:
        return float(_last(data, code, str(default)))
    except ValueError:
        return default


def _int(data: List[Tuple[str, str]], code: str, default: int = 0) -> int:
    try:
        return int(float(_last(data, code, str(default))))
    except ValueError:
        return default


def clean_text(s: str) -> str:
    s = s.replace("\\P", " ").replace("\\~", " ")
    s = re.sub(r"\\[A-Za-z]+\d*;?", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def extract_all_texts(pairs: Sequence[Tuple[str, str]]) -> List[str]:
    texts: List[str] = []
    for ent_type, data in iter_dxf_entities(pairs, section_name=None):
        if ent_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            s = clean_text("".join(v for c, v in data if c in {"1", "3"}))
            if s:
                texts.append(s)
    seen = set()
    unique = []
    for t in texts:
        if t not in seen:
            unique.append(t)
            seen.add(t)
    return unique


def infer_metadata(texts: Sequence[str]) -> Tuple[str, str, str]:
    drawing_no = ""
    material = ""
    for t in texts:
        compact = t.replace(" ", "")
        if not drawing_no and re.search(r"[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+", compact, re.I):
            drawing_no = compact
        if not material:
            if "Q235" in compact.upper():
                material = "Q235"
            elif "铝板" in compact or compact == "铝":
                material = "铝板"
            elif "不锈钢" in compact or "304" in compact:
                material = "不锈钢"
    candidates = []
    for t in texts:
        compact = t.replace(" ", "")
        if not compact or not re.search(r"[\u4e00-\u9fff]", compact):
            continue
        if any(ch in compact for ch in ("板", "座", "钩", "梁", "架", "件", "盖", "支")):
            candidates.append((2 if len(compact) <= 16 else 0, compact))
    name = max(candidates, default=(0, ""), key=lambda x: x[0])[1]
    return drawing_no, name, material


def layer_excluded(layer: str, extra_keywords: Sequence[str] = ()) -> bool:
    u = layer.upper()
    return any(k.upper() in u for k in tuple(EXCLUDED_LAYER_KEYWORDS) + tuple(extra_keywords))


def parse_cut_entities(pairs: Sequence[Tuple[str, str]], include_layers: Optional[Sequence[str]] = None, exclude_layer_keywords: Sequence[str] = ()) -> Tuple[List[PathEntity], List[Circle], Dict[str, int], Dict[str, int]]:
    include_set = set(include_layers or [])
    segments: List[PathEntity] = []
    circles: List[Circle] = []
    layer_counts: Dict[str, int] = {}
    skipped_counts: Dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped_counts[reason] = skipped_counts.get(reason, 0) + 1

    for ent_type, data in iter_dxf_entities(pairs, "ENTITIES"):
        layer = _last(data, "8", "")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        if include_set and layer not in include_set:
            skip(f"skip_layer:{layer}")
            continue
        if layer_excluded(layer, exclude_layer_keywords):
            skip(f"skip_layer:{layer}")
            continue
        if ent_type == "LINE":
            segments.append(Line(layer, _float(data, "10"), _float(data, "20"), _float(data, "11"), _float(data, "21")))
        elif ent_type == "ARC":
            segments.append(Arc(layer, _float(data, "10"), _float(data, "20"), _float(data, "40"), _float(data, "50"), _float(data, "51")))
        elif ent_type == "CIRCLE":
            r = _float(data, "40")
            if r > 0:
                circles.append(Circle(layer, _float(data, "10"), _float(data, "20"), r))
        elif ent_type == "LWPOLYLINE":
            pts = list(zip(_floats(data, "10"), _floats(data, "20")))
            closed = (_int(data, "70") & 1) == 1
            segments.extend(Polyline(layer, pts, closed).to_lines())
        elif ent_type == "SPLINE":
            lines = spline_to_lines(layer, _int(data, "71", 3), _floats(data, "40"), list(zip(_floats(data, "10"), _floats(data, "20"))), flags=_int(data, "70", 0))
            if lines:
                segments.extend(lines)
                skip("approx_type:SPLINE")
            else:
                skip("unsupported_type:SPLINE")
        else:
            skip(f"skip_type:{ent_type}" if ent_type in {"TEXT", "MTEXT", "DIMENSION", "INSERT", "HATCH"} else f"unsupported_type:{ent_type}")
    return segments, circles, layer_counts, skipped_counts


def point_key(pt: Tuple[float, float], tol: float = 0.01) -> Tuple[int, int]:
    return (int(round(pt[0] / tol)), int(round(pt[1] / tol)))


def shoelace_area(points: Sequence[Tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    pts = list(points)
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    area = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def bbox_of_points(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(pt: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> bool:
    x, y = pt
    inside = False
    pts = list(polygon)
    if not pts:
        return False
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 > y) != (y2 > y):
            xinters = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < xinters:
                inside = not inside
    return inside


def order_component_points(segments: List[PathEntity], tol: float = 0.05) -> List[Tuple[float, float]]:
    if not segments:
        return []
    endpoints = [seg.endpoints() for seg in segments]
    keys = [(point_key(a, tol), point_key(b, tol)) for a, b in endpoints]
    adjacency: Dict[Tuple[int, int], List[int]] = {}
    for i, (ka, kb) in enumerate(keys):
        adjacency.setdefault(ka, []).append(i)
        adjacency.setdefault(kb, []).append(i)
    current_key = keys[0][0]
    used = set()
    pts: List[Tuple[float, float]] = []
    for _ in range(len(segments)):
        candidates = [idx for idx in adjacency.get(current_key, []) if idx not in used]
        if not candidates:
            break
        idx = candidates[0]
        used.add(idx)
        ka, kb = keys[idx]
        seg = segments[idx]
        if current_key == ka:
            next_key = kb
            reverse = False
        else:
            next_key = ka
            reverse = True
        seg_pts = seg.points(reverse=reverse)
        pts.extend(seg_pts[1:] if pts else seg_pts)
        current_key = next_key
    if len(used) != len(segments):
        return []
    if pts and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > tol:
        pts.append(pts[0])
    return pts


def build_closed_components(segments: List[PathEntity], tol: float = 0.05) -> List[PathComponent]:
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def find(a: Tuple[int, int]) -> Tuple[int, int]:
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: Tuple[int, int], b: Tuple[int, int]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    endpoints_by_seg = []
    for seg in segments:
        p1, p2 = seg.endpoints()
        k1, k2 = point_key(p1, tol), point_key(p2, tol)
        endpoints_by_seg.append((k1, k2))
        union(k1, k2)
    comps: Dict[Tuple[int, int], List[int]] = {}
    for idx, (k1, _) in enumerate(endpoints_by_seg):
        comps.setdefault(find(k1), []).append(idx)
    result: List[PathComponent] = []
    for seg_indices in comps.values():
        if len(seg_indices) < 2:
            continue
        degree: Dict[Tuple[int, int], int] = {}
        for idx in seg_indices:
            k1, k2 = endpoints_by_seg[idx]
            degree[k1] = degree.get(k1, 0) + 1
            degree[k2] = degree.get(k2, 0) + 1
        closed = bool(degree) and all(v == 2 for v in degree.values())
        ordered_points = order_component_points([segments[i] for i in seg_indices], tol=tol) if closed else []
        if not ordered_points:
            ordered_points = [pt for i in seg_indices for pt in segments[i].points()]
        result.append(PathComponent([segments[i] for i in seg_indices], ordered_points, sum(segments[i].length() for i in seg_indices), shoelace_area(ordered_points) if closed else 0.0, bbox_of_points(ordered_points), closed))
    return result


def assign_profiles(segments: List[PathEntity], circles: List[Circle], min_outer_area_mm2: float = 1000.0) -> List[PartProfile]:
    comps = build_closed_components(segments)
    closed = [c for c in comps if c.closed and c.area_mm2 > 1]
    outers = sorted([c for c in closed if c.area_mm2 >= min_outer_area_mm2], key=lambda c: c.area_mm2, reverse=True)
    profiles = [PartProfile(i + 1, outer=o) for i, o in enumerate(outers)]
    for circle in circles:
        candidates = [profile for profile in profiles if point_in_polygon((circle.cx, circle.cy), profile.outer.points)]
        if candidates:
            min(candidates, key=lambda p: p.outer.area_mm2).holes.append(circle)
    for comp in closed:
        if comp in outers:
            continue
        center = ((comp.bbox[0] + comp.bbox[2]) / 2, (comp.bbox[1] + comp.bbox[3]) / 2)
        candidates = [profile for profile in profiles if point_in_polygon(center, profile.outer.points)]
        if candidates:
            min(candidates, key=lambda p: p.outer.area_mm2).inner_paths.append(comp)
    return profiles


def deduplicate_profiles(profiles: List[PartProfile]) -> Tuple[List[PartProfile], List[int]]:
    groups: Dict[Tuple[Any, ...], List[PartProfile]] = {}
    for p in profiles:
        groups.setdefault(p.signature(), []).append(p)
    used = []
    sizes = []
    for items in groups.values():
        first = items[0]
        first.duplicate_count = len(items)
        used.append(first)
        sizes.append(len(items))
    used.sort(key=lambda p: p.index)
    return used, sizes


def make_profile_preview(profile: PartProfile, selected_by_default: bool) -> ProfilePreview:
    return ProfilePreview(profile.index, selected_by_default, profile.duplicate_count, profile.outer.bbox, profile.outer.points, [{"cx": h.cx, "cy": h.cy, "r": h.r} for h in profile.holes], [p.points for p in profile.inner_paths], f"{profile.width_mm:.1f}×{profile.height_mm:.1f}", profile.hole_count, profile.pierce_count, profile.cut_length_mm / 1000.0, profile.gross_area_mm2, profile.net_area_mm2)


def calc_quote_row(profile: PartProfile, rates: QuoteRates, drawing_no: str = "", name: str = "") -> QuoteRow:
    gross_w = profile.gross_area_mm2 * rates.thickness_mm * rates.density_g_cm3 / KG_DENSITY_FACTOR
    net_w = profile.net_area_mm2 * rates.thickness_mm * rates.density_g_cm3 / KG_DENSITY_FACTOR
    cut_m = profile.cut_length_mm / 1000.0
    cut_fee = cut_m * rates.cut_price_per_meter
    pierce_fee = profile.pierce_count * rates.pierce_price_each
    material_fee = gross_w * rates.material_price_per_kg
    scrap_credit = max(0.0, gross_w - net_w) * rates.scrap_price_per_kg
    base = material_fee - scrap_credit + cut_fee + pierce_fee + rates.other_process_fee_each
    price = max(rates.min_charge_each, base * (1 + rates.profit_rate) * (1 + rates.tax_rate))
    amount = price * rates.quantity
    return QuoteRow(profile.index, profile.duplicate_count, drawing_no, name or f"零件{profile.index}", rates.material, rates.thickness_mm, f"{profile.width_mm:.1f}×{profile.height_mm:.1f}", profile.hole_count, profile.pierce_count, cut_m, profile.gross_area_mm2, profile.net_area_mm2, gross_w, net_w, rates.quantity, cut_fee, pierce_fee, material_fee, scrap_credit, rates.other_process_fee_each, base, price, amount, "检测到重复视图，已按单件去重" if profile.duplicate_count > 1 else "")


def analyze_dxf(path: str | Path, rates: Optional[QuoteRates] = None, dedupe_identical: bool = True, include_layers: Optional[Sequence[str]] = None) -> AnalysisResult:
    rates = rates or QuoteRates()
    path = Path(path)
    pairs = read_dxf_pairs(path)
    texts = extract_all_texts(pairs)
    drawing_no, inferred_name, material_hint = infer_metadata(texts)
    if material_hint and rates.material == "auto":
        rates.material = material_hint
    segments, circles, layer_counts, skipped_counts = parse_cut_entities(pairs, include_layers=include_layers)
    components = build_closed_components(segments)
    open_components = [c for c in components if not c.closed]
    all_points = [pt for segment in segments for pt in segment.points()]
    geometry_bbox = bbox_of_points(all_points) if all_points else None
    profiles = assign_profiles(segments, circles)
    warnings = []
    if not profiles:
        warnings.append("未识别到闭合外轮廓，请检查 DXF 是否为 1:1 展开切割图，或切割线是否在被过滤图层。")
        if open_components:
            warnings.append(f"已提取开放切割路径 {len(open_components)} 组，总长约 {sum(c.length_mm for c in open_components) / 1000.0:.4f} m；未生成正式报价行，需人工确认是否按开放路径报价。")
    profiles_all_count = len(profiles)
    if dedupe_identical:
        profiles_used, duplicate_groups = deduplicate_profiles(profiles)
    else:
        profiles_used, duplicate_groups = profiles, [1 for _ in profiles]
    if any(n > 1 for n in duplicate_groups):
        warnings.append("检测到疑似重复视图，系统默认按几何相同零件去重；报价前请人工确认数量。")
    used_profile_indices = {p.index for p in profiles_used}
    return AnalysisResult(str(path), drawing_no, inferred_name, material_hint, texts, layer_counts, skipped_counts, profiles_all_count, len(profiles_used), len(open_components), sum(c.length_mm for c in open_components) / 1000.0, geometry_bbox, duplicate_groups, [make_profile_preview(profile, profile.index in used_profile_indices) for profile in profiles], [calc_quote_row(p, rates, drawing_no=drawing_no, name=inferred_name) for p in profiles_used], warnings)


def collect_dxf_paths(paths: Sequence[str | Path]) -> List[Path]:
    out = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(p for p in path.iterdir() if p.suffix.lower() == ".dxf"))
        else:
            out.append(path)
    return out


def analyze_dxf_batch(paths: Sequence[str | Path], rates: Optional[QuoteRates] = None, dedupe_identical: bool = True, include_layers: Optional[Sequence[str]] = None) -> BatchAnalysisResult:
    batch = BatchAnalysisResult()
    for path in collect_dxf_paths(paths):
        try:
            batch.items.append(BatchItemResult(str(path), True, analyze_dxf(path, rates=rates, dedupe_identical=dedupe_identical, include_layers=include_layers)))
        except Exception as exc:
            batch.items.append(BatchItemResult(str(path), False, error=str(exc)))
    return batch


def load_rates(path: Optional[str | Path], overrides: Dict[str, Any]) -> QuoteRates:
    data: Dict[str, Any] = {}
    if path:
        data.update(json.loads(Path(path).read_text(encoding="utf-8")))
    data.update({k: v for k, v in overrides.items() if v is not None})
    return QuoteRates(**data)


def write_csv(result: AnalysisResult, out_path: str | Path) -> None:
    rows = [r.as_dict() for r in result.quote_rows]
    if not rows:
        Path(out_path).write_text("", encoding="utf-8-sig")
        return
    with Path(out_path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_batch_csv(batch: BatchAnalysisResult, out_path: str | Path) -> None:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        if item.result and item.result.quote_rows:
            for row in item.result.quote_rows:
                data = row.as_dict()
                data["source_file"] = item.source_file
                data["status"] = "ok"
                data["warnings"] = "；".join(item.result.warnings)
                rows.append(data)
        else:
            rows.append({"source_file": item.source_file, "status": "error" if not item.ok else "empty", "error": item.error})
    if not rows:
        Path(out_path).write_text("", encoding="utf-8-sig")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with Path(out_path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DXF 激光切割报价核算 MVP")
    parser.add_argument("dxf", nargs="+")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)
    result = analyze_dxf(args.dxf[0])
    print(result.to_json())
    if args.csv:
        write_csv(result, args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
