from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import csv
import json
import math
import re

KG_DENSITY_FACTOR = 1_000_000.0
EXCLUDED_LAYER_KEYWORDS = ("图框", "标题", "标注", "文字", "中心", "辅助", "虚线", "DIM", "TEXT", "FRAME", "BORDER", "CENTER")


@dataclass
class Line:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float

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

    def _span(self) -> float:
        span = self.end_deg - self.start_deg
        while span <= 0:
            span += 360
        return span

    def endpoints(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        a1, a2 = math.radians(self.start_deg), math.radians(self.end_deg)
        return ((self.cx + self.r * math.cos(a1), self.cy + self.r * math.sin(a1)), (self.cx + self.r * math.cos(a2), self.cy + self.r * math.sin(a2)))

    def length(self) -> float:
        return 2 * math.pi * self.r * self._span() / 360.0

    def points(self, reverse: bool = False, max_step_deg: float = 5.0) -> List[Tuple[float, float]]:
        end = self.end_deg
        while end <= self.start_deg:
            end += 360
        steps = max(2, int(math.ceil((end - self.start_deg) / max_step_deg)) + 1)
        pts = []
        for i in range(steps):
            a = math.radians(self.start_deg + (end - self.start_deg) * i / (steps - 1))
            pts.append((self.cx + self.r * math.cos(a), self.cy + self.r * math.sin(a)))
        return list(reversed(pts)) if reverse else pts


@dataclass
class Circle:
    layer: str
    cx: float
    cy: float
    r: float

    def length(self) -> float:
        return 2 * math.pi * self.r

    def area(self) -> float:
        return math.pi * self.r * self.r


@dataclass
class PathComponent:
    segments: List[Line | Arc]
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
        return self.outer.bbox[2] - self.outer.bbox[0]

    @property
    def height_mm(self) -> float:
        return self.outer.bbox[3] - self.outer.bbox[1]

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
        return self.outer.length_mm + sum(h.length() for h in self.holes) + sum(p.length_mm for p in self.inner_paths)

    @property
    def hole_count(self) -> int:
        return len(self.holes) + len(self.inner_paths)

    @property
    def pierce_count(self) -> int:
        return self.hole_count + 1

    def signature(self) -> Tuple[Any, ...]:
        minx, miny, _, _ = self.outer.bbox
        return (round(self.width_mm, 1), round(self.height_mm, 1), round(self.outer_area_mm2, 0), round(self.outer.length_mm, 1), tuple(sorted((round(h.cx - minx, 1), round(h.cy - miny, 1), round(h.r, 1)) for h in self.holes)), tuple(sorted((round(p.area_mm2, 1), round(p.length_mm, 1)) for p in self.inner_paths)))


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
    quote_open_paths: bool = False


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
class BasicGeometry:
    geometry_index: int
    kind: str
    closed: bool
    approximate: bool
    area_mm2: float
    perimeter_mm: float
    bbox: Tuple[float, float, float, float]
    width_mm: float
    height_mm: float
    centroid: Optional[Tuple[float, float]]
    inertia_centroid_x_mm4: Optional[float]
    inertia_centroid_y_mm4: Optional[float]
    inertia_centroid_xy_mm4: Optional[float]
    radius_gyration_x_mm: Optional[float]
    radius_gyration_y_mm: Optional[float]
    note: str = ""


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
    basic_geometries: List[BasicGeometry] = field(default_factory=list)
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


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "cp936", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", errors="replace")


def read_dxf_pairs(path: str | Path) -> List[Tuple[str, str]]:
    lines = _decode(Path(path).read_bytes()).splitlines()
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
    out = default
    for c, v in data:
        if c == code:
            out = v
    return out


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
    s = re.sub(r"\\[A-Za-z]+\d*;?", "", s).replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def extract_all_texts(pairs: Sequence[Tuple[str, str]]) -> List[str]:
    texts: List[str] = []
    for ent_type, data in iter_dxf_entities(pairs, None):
        if ent_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            value = clean_text("".join(v for c, v in data if c in {"1", "3"}))
            if value and value not in texts:
                texts.append(value)
    return texts


def infer_metadata(texts: Sequence[str]) -> Tuple[str, str, str]:
    drawing_no = ""
    material = ""
    name = ""
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
        if not name and re.search(r"[\u4e00-\u9fff]", compact) and any(ch in compact for ch in "板座钩梁架件盖支"):
            name = compact
    return drawing_no, name, material


def layer_excluded(layer: str, extra_keywords: Sequence[str] = ()) -> bool:
    u = layer.upper()
    return any(k.upper() in u for k in tuple(EXCLUDED_LAYER_KEYWORDS) + tuple(extra_keywords))


def _de_boor_point(degree: int, knots: Sequence[float], controls: Sequence[Tuple[float, float]], t: float) -> Tuple[float, float]:
    n = len(controls) - 1
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
            left, right = knots[k - degree + j], knots[k + 1 + j - r]
            alpha = 0.0 if abs(right - left) < 1e-12 else (t - left) / (right - left)
            d[j] = ((1 - alpha) * d[j - 1][0] + alpha * d[j][0], (1 - alpha) * d[j - 1][1] + alpha * d[j][1])
    return d[degree]


def spline_to_lines(layer: str, degree: int, knots: Sequence[float], controls: Sequence[Tuple[float, float]], flags: int = 0, samples_per_span: int = 60) -> List[Line]:
    if degree < 1 or len(controls) <= degree or len(knots) < len(controls) + degree + 1:
        return []
    start, end = knots[degree], knots[len(controls)]
    if end <= start:
        return []
    span_count = max(1, len({round(k, 9) for k in knots if start < k < end}) + 1)
    sample_count = max(16, span_count * samples_per_span)
    pts = [_de_boor_point(degree, knots, controls, start + (end - start) * i / sample_count) for i in range(sample_count + 1)]
    if flags & 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 0.01:
        pts.append(pts[0])
    return [Line(layer, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]) if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-9]


def parse_cut_entities(pairs: Sequence[Tuple[str, str]], include_layers: Optional[Sequence[str]] = None, exclude_layer_keywords: Sequence[str] = ()) -> Tuple[List[Line | Arc], List[Circle], Dict[str, int], Dict[str, int]]:
    include_set = set(include_layers or [])
    segments: List[Line | Arc] = []
    circles: List[Circle] = []
    layer_counts: Dict[str, int] = {}
    skipped: Dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

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
            if len(pts) >= 2:
                if _int(data, "70") & 1:
                    pts.append(pts[0])
                segments.extend(Line(layer, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
        elif ent_type == "SPLINE":
            lines = spline_to_lines(layer, _int(data, "71", 3), _floats(data, "40"), list(zip(_floats(data, "10"), _floats(data, "20"))), _int(data, "70", 0))
            if lines:
                segments.extend(lines)
                skip("approx_type:SPLINE")
            else:
                skip("unsupported_type:SPLINE")
        else:
            skip(f"skip_type:{ent_type}" if ent_type in {"TEXT", "MTEXT", "DIMENSION", "INSERT", "HATCH"} else f"unsupported_type:{ent_type}")
    return segments, circles, layer_counts, skipped


def point_key(pt: Tuple[float, float], tol: float = 0.01) -> Tuple[int, int]:
    return (int(round(pt[0] / tol)), int(round(pt[1] / tol)))


def shoelace_area(points: Sequence[Tuple[float, float]]) -> float:
    pts = list(points)
    if len(pts) < 3:
        return 0.0
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))) / 2.0


def polygon_mass_properties(points: Sequence[Tuple[float, float]]) -> Dict[str, Optional[float]]:
    pts = list(points)
    if len(pts) < 3:
        return {"area": 0.0, "cx": None, "cy": None, "ix_c": None, "iy_c": None, "ixy_c": None, "rx": None, "ry": None}
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    twice_area = cx_acc = cy_acc = ix_acc = iy_acc = ixy_acc = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx_acc += (x0 + x1) * cross
        cy_acc += (y0 + y1) * cross
        ix_acc += (y0 * y0 + y0 * y1 + y1 * y1) * cross
        iy_acc += (x0 * x0 + x0 * x1 + x1 * x1) * cross
        ixy_acc += (2 * x0 * y0 + x0 * y1 + x1 * y0 + 2 * x1 * y1) * cross
    signed_area = twice_area / 2.0
    if abs(signed_area) < 1e-9:
        return {"area": 0.0, "cx": None, "cy": None, "ix_c": None, "iy_c": None, "ixy_c": None, "rx": None, "ry": None}
    cx = cx_acc / (6.0 * signed_area)
    cy = cy_acc / (6.0 * signed_area)
    area = abs(signed_area)
    ix_c = abs(ix_acc / 12.0 - signed_area * cy * cy)
    iy_c = abs(iy_acc / 12.0 - signed_area * cx * cx)
    ixy_c = ixy_acc / 24.0 - signed_area * cx * cy
    return {"area": area, "cx": cx, "cy": cy, "ix_c": ix_c, "iy_c": iy_c, "ixy_c": ixy_c, "rx": math.sqrt(ix_c / area), "ry": math.sqrt(iy_c / area)}


def bbox_of_points(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(pt: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> bool:
    x, y = pt
    inside = False
    pts = list(polygon)
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
                inside = not inside
    return inside


def order_component_points(segments: List[Line | Arc], tol: float = 0.05) -> List[Tuple[float, float]]:
    endpoints = [seg.endpoints() for seg in segments]
    keys = [(point_key(a, tol), point_key(b, tol)) for a, b in endpoints]
    adjacency: Dict[Tuple[int, int], List[int]] = {}
    for i, (ka, kb) in enumerate(keys):
        adjacency.setdefault(ka, []).append(i)
        adjacency.setdefault(kb, []).append(i)
    current = keys[0][0]
    used = set()
    pts: List[Tuple[float, float]] = []
    for _ in range(len(segments)):
        candidates = [idx for idx in adjacency.get(current, []) if idx not in used]
        if not candidates:
            return []
        idx = candidates[0]
        used.add(idx)
        ka, kb = keys[idx]
        reverse = current != ka
        seg_pts = segments[idx].points(reverse=reverse)
        pts.extend(seg_pts[1:] if pts else seg_pts)
        current = ka if reverse else kb
    if len(used) != len(segments):
        return []
    if pts and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > tol:
        pts.append(pts[0])
    return pts


def build_closed_components(segments: List[Line | Arc], tol: float = 0.05) -> List[PathComponent]:
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
        ordered = order_component_points([segments[i] for i in seg_indices], tol) if closed else []
        if not ordered:
            ordered = [pt for i in seg_indices for pt in segments[i].points()]
        if not closed and len(ordered) >= 3:
            endpoint_gap = math.hypot(ordered[0][0] - ordered[-1][0], ordered[0][1] - ordered[-1][1])
            if endpoint_gap <= max(tol, 0.5) and shoelace_area(ordered) > 1:
                closed = True
        length = sum(segments[i].length() for i in seg_indices)
        result.append(PathComponent([segments[i] for i in seg_indices], ordered, length, shoelace_area(ordered) if closed else 0.0, bbox_of_points(ordered), closed))
    return result


def assign_profiles(segments: List[Line | Arc], circles: List[Circle], min_outer_area_mm2: float = 1000.0) -> List[PartProfile]:
    closed = [c for c in build_closed_components(segments) if c.closed and c.area_mm2 > 1]
    outers = sorted([c for c in closed if c.area_mm2 >= min_outer_area_mm2], key=lambda c: c.area_mm2, reverse=True)
    profiles = [PartProfile(i + 1, outer=o) for i, o in enumerate(outers)]
    for circle in circles:
        candidates = [p for p in profiles if point_in_polygon((circle.cx, circle.cy), p.outer.points)]
        if candidates:
            min(candidates, key=lambda p: p.outer.area_mm2).holes.append(circle)
    for comp in closed:
        if comp in outers:
            continue
        center = ((comp.bbox[0] + comp.bbox[2]) / 2, (comp.bbox[1] + comp.bbox[3]) / 2)
        candidates = [p for p in profiles if point_in_polygon(center, p.outer.points)]
        if candidates:
            min(candidates, key=lambda p: p.outer.area_mm2).inner_paths.append(comp)
    return profiles


def deduplicate_profiles(profiles: List[PartProfile]) -> Tuple[List[PartProfile], List[int]]:
    groups: Dict[Tuple[Any, ...], List[PartProfile]] = {}
    for p in profiles:
        groups.setdefault(p.signature(), []).append(p)
    used: List[PartProfile] = []
    sizes: List[int] = []
    for items in groups.values():
        first = items[0]
        first.duplicate_count = len(items)
        used.append(first)
        sizes.append(len(items))
    used.sort(key=lambda p: p.index)
    return used, sizes


def make_profile_preview(profile: PartProfile, selected_by_default: bool) -> ProfilePreview:
    return ProfilePreview(profile.index, selected_by_default, profile.duplicate_count, profile.outer.bbox, profile.outer.points, [{"cx": h.cx, "cy": h.cy, "r": h.r} for h in profile.holes], [p.points for p in profile.inner_paths], f"{profile.width_mm:.1f}×{profile.height_mm:.1f}", profile.hole_count, profile.pierce_count, profile.cut_length_mm / 1000.0, profile.gross_area_mm2, profile.net_area_mm2)


def make_basic_geometry(index: int, kind: str, points: Sequence[Tuple[float, float]], perimeter_mm: float, bbox: Tuple[float, float, float, float], closed: bool, approximate: bool, note: str) -> BasicGeometry:
    props = polygon_mass_properties(points) if closed else {"area": 0.0, "cx": None, "cy": None, "ix_c": None, "iy_c": None, "ixy_c": None, "rx": None, "ry": None}
    centroid = None if props["cx"] is None or props["cy"] is None else (float(props["cx"]), float(props["cy"]))
    return BasicGeometry(index, kind, closed, approximate, float(props["area"] or 0.0), perimeter_mm, bbox, bbox[2] - bbox[0], bbox[3] - bbox[1], centroid, None if props["ix_c"] is None else float(props["ix_c"]), None if props["iy_c"] is None else float(props["iy_c"]), None if props["ixy_c"] is None else float(props["ixy_c"]), None if props["rx"] is None else float(props["rx"]), None if props["ry"] is None else float(props["ry"]), note)


def make_basic_geometries(profiles: Sequence[PartProfile], open_components: Sequence[PathComponent]) -> List[BasicGeometry]:
    out: List[BasicGeometry] = []
    for profile in profiles:
        out.append(make_basic_geometry(len(out) + 1, "外轮廓", profile.outer.points, profile.outer.length_mm, profile.outer.bbox, True, False, "已识别为闭合外轮廓"))
    for component in open_components:
        gap = math.hypot(component.points[0][0] - component.points[-1][0], component.points[0][1] - component.points[-1][1]) if len(component.points) >= 2 else 999
        near_closed = len(component.points) >= 3 and gap <= 0.5 and shoelace_area(component.points) > 1
        out.append(make_basic_geometry(len(out) + 1, "近似闭合路径" if near_closed else "开放路径", component.points, component.length_mm, component.bbox, near_closed, True, "端点接近闭合，按面域近似提取；正式报价前请人工确认轮廓有效性" if near_closed else "开放切割路径，不能直接计算材料面积"))
    return out


def calc_quote_row(profile: PartProfile, rates: QuoteRates, drawing_no: str = "", name: str = "") -> QuoteRow:
    gross_w = profile.gross_area_mm2 * rates.thickness_mm * rates.density_g_cm3 / KG_DENSITY_FACTOR
    net_w = profile.net_area_mm2 * rates.thickness_mm * rates.density_g_cm3 / KG_DENSITY_FACTOR
    cut_m = profile.cut_length_mm / 1000.0
    cut_fee = cut_m * rates.cut_price_per_meter
    pierce_fee = profile.pierce_count * rates.pierce_price_each
    material_fee = gross_w * rates.material_price_per_kg
    scrap_credit = max(gross_w - net_w, 0) * rates.scrap_price_per_kg
    base = material_fee - scrap_credit + cut_fee + pierce_fee + rates.other_process_fee_each
    price = max(rates.min_charge_each, base * (1 + rates.profit_rate) * (1 + rates.tax_rate))
    return QuoteRow(profile.index, profile.duplicate_count, drawing_no, name or f"零件{profile.index}", rates.material, rates.thickness_mm, f"{profile.width_mm:.1f}×{profile.height_mm:.1f}", profile.hole_count, profile.pierce_count, cut_m, profile.gross_area_mm2, profile.net_area_mm2, gross_w, net_w, rates.quantity, cut_fee, pierce_fee, material_fee, scrap_credit, rates.other_process_fee_each, base, price, price * rates.quantity, "检测到重复视图，已按单件去重" if profile.duplicate_count > 1 else "")


def analyze_dxf(path: str | Path, rates: Optional[QuoteRates] = None, dedupe_identical: bool = True, include_layers: Optional[Sequence[str]] = None) -> AnalysisResult:
    rates = rates or QuoteRates()
    path = Path(path)
    pairs = read_dxf_pairs(path)
    texts = extract_all_texts(pairs)
    drawing_no, name, material_hint = infer_metadata(texts)
    segments, circles, layer_counts, skipped_counts = parse_cut_entities(pairs, include_layers=include_layers)
    components = build_closed_components(segments)
    open_components = [c for c in components if not c.closed]
    all_points = [pt for segment in segments for pt in segment.points()]
    geometry_bbox = bbox_of_points(all_points) if all_points else None
    profiles = assign_profiles(segments, circles)
    warnings: List[str] = []
    if skipped_counts.get("approx_type:SPLINE"):
        warnings.append("检测到 SPLINE 曲线，已按高精度折线近似计算面积/周长；正式报价前请人工核对。")
    if not profiles:
        warnings.append("未识别到闭合外轮廓，请检查 DXF 是否为 1:1 展开切割图，或切割线是否在被过滤图层。")
        if open_components:
            warnings.append(f"已提取开放切割路径 {len(open_components)} 组，总长约 {sum(c.length_mm for c in open_components) / 1000.0:.4f} m；未生成正式报价行，需人工确认是否按开放路径报价。")
    profiles_all_count = len(profiles)
    profiles_used, duplicate_groups = deduplicate_profiles(profiles) if dedupe_identical else (profiles, [1 for _ in profiles])
    if any(n > 1 for n in duplicate_groups):
        warnings.append("检测到疑似重复视图，系统默认按几何相同零件去重；报价前请人工确认数量。")
    used = {p.index for p in profiles_used}
    previews = [make_profile_preview(p, p.index in used) for p in profiles]
    basics = make_basic_geometries(profiles, open_components)
    rows = [calc_quote_row(p, rates, drawing_no, name) for p in profiles_used]
    return AnalysisResult(str(path), drawing_no, name, material_hint, texts, layer_counts, skipped_counts, profiles_all_count, len(profiles_used), len(open_components), sum(c.length_mm for c in open_components) / 1000.0, geometry_bbox, basics, duplicate_groups, previews, rows, warnings)


def collect_dxf_paths(paths: Sequence[str | Path]) -> List[Path]:
    out: List[Path] = []
    for raw in paths:
        path = Path(raw)
        out.extend(sorted(p for p in path.iterdir() if p.suffix.lower() == ".dxf")) if path.is_dir() else out.append(path)
    return out


def analyze_dxf_batch(paths: Sequence[str | Path], rates: Optional[QuoteRates] = None, dedupe_identical: bool = True, include_layers: Optional[Sequence[str]] = None) -> BatchAnalysisResult:
    batch = BatchAnalysisResult()
    for path in collect_dxf_paths(paths):
        try:
            batch.items.append(BatchItemResult(str(path), True, analyze_dxf(path, rates, dedupe_identical, include_layers)))
        except Exception as exc:
            batch.items.append(BatchItemResult(str(path), False, error=str(exc)))
    return batch


def write_csv(result: AnalysisResult, out_path: str | Path) -> None:
    rows = [r.as_dict() for r in result.quote_rows]
    if not rows:
        Path(out_path).write_text("", encoding="utf-8-sig")
        return
    with Path(out_path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)


def write_batch_csv(batch: BatchAnalysisResult, out_path: str | Path) -> None:
    rows: List[Dict[str, Any]] = []
    for item in batch.items:
        if item.result and item.result.quote_rows:
            for row in item.result.quote_rows:
                data = row.as_dict(); data["source_file"] = item.source_file; data["status"] = "ok"; data["warnings"] = "；".join(item.result.warnings); rows.append(data)
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
        writer.writeheader(); writer.writerows(rows)
