import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from pypdf import PdfReader

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


@dataclass
class Peak:
    name: str
    retention_time: float
    area: float
    percent_area: float
    height: float = 0.0
    rel_rt: Optional[float] = None
    wavelength: int = 0


@dataclass
class HplcReport:
    file_name: str
    sample_name: Optional[str] = None
    batch_id: Optional[str] = None
    cds_source: str = "GENERIC"
    detected_wavelengths: Set[int] = field(default_factory=set)
    peaks: List[Peak] = field(default_factory=list)

    def add_peak(self, peak: Peak):
        self.peaks.append(peak)
        if peak.wavelength > 0:
            self.detected_wavelengths.add(peak.wavelength)


class HplcPdfParser:
    """Universal multi-vendor parser supporting Thermo/Chromeleon, Agilent,

    Shimadzu, and Waters Empower with dynamic column order detection.
    """

    # Multi-vendor Metadata Patterns
    INJECTION_PATTERNS = [
        re.compile(r"(?:Injection\s*Name|Sample\s*Name|Sample\s*ID|Sample\s*Description|Sample)\s*[:=\-\t]+\s*([^\r\n|,]+)", re.I),
        re.compile(r"Data\s*File\s*[:=\-\t]+\s*([A-Za-z0-9_\-\./#]+)", re.I),
    ]

    BATCH_PATTERNS = [
        re.compile(r"(?:Batch\s*(?:No|ID|Name)?|Lot\s*(?:No|ID)?|Vial\s*#?)\s*[:=\-\t]+\s*([A-Za-z0-9_\-\./#]+)", re.I),
    ]

    WAVELENGTH_PATTERNS = [
        re.compile(r"Wavelength\s*[:=\-\t]?\s*(\d{3})\s*nm", re.I),
        re.compile(r"(?:Sig(?:nal)?|DAD\d*[A-Z]?|Channel)\s*[:=\-\t,]?\s*(?:Sig=)?(\d{3})\s*nm?", re.I),
        re.compile(r"PDA\s*Multi\s*\d*\s*/\s*(\d{3})\s*nm", re.I),
    ]

    # Header Column Keywords
    HEADER_MAP = {
        "rt": ["ret.time", "ret time", "ret. time", "rt(min)", "rt [min]", "r.t.", "rt", "time"],
        "rrt": ["rel.ret. time", "rel.ret", "rel ret", "rel. ret.", "rrt", "rel. r.t.", "relative retention time"],
        "pct_area": ["area %", "% area", "%area", "area%", "area percent", "% of total", "percent area", "area percent%"],
        "area": ["area", "area µau*sec", "area mau*s", "area(counts)", "area [mau*s]"],
        "height": ["height", "height µau", "height mau", "hgt"],
        "name": ["peak name", "compound name", "component", "name", "peak"],
    }

    def parse(self, file_bytes: bytes, filename: str) -> HplcReport:
        report = HplcReport(file_name=filename)

        # 1. Primary Strategy: Coordinate-aware layout extraction via pdfplumber
        if HAS_PDFPLUMBER:
            try:
                self._parse_with_pdfplumber(file_bytes, report)
            except Exception:
                pass

        # 2. Fallback Strategy: Layout stream extraction via pypdf
        if len(report.peaks) == 0:
            self._parse_with_pypdf(file_bytes, report)

        # Fallback naming logic if Batch ID is missing or 'n.a.'
        if not report.batch_id or report.batch_id.lower() in ["n.a.", "na", "none", "nil", ""]:
            report.batch_id = report.sample_name or filename.replace(".pdf", "")

        return report

    def _parse_with_pdfplumber(self, file_bytes: bytes, report: HplcReport):
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"

                # Extract tables with explicit text boundaries
                tables = page.extract_tables({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 3,
                }) or []

                for table in tables:
                    self._process_table_grid(table, report)

            self._extract_metadata(full_text, report)

    def _process_table_grid(self, table: List[List[str]], report: HplcReport):
        if not table or len(table) < 2:
            return

        col_index_map: Dict[str, int] = {}
        header_row_idx = -1

        # Scan top rows to dynamically detect header positions
        for r_idx, row in enumerate(table[:5]):
            row_str_cells = [str(c).lower().strip() if c else "" for c in row]
            detected = self._identify_header_indices(row_str_cells)
            if "rt" in detected and ("pct_area" in detected or "area" in detected):
                col_index_map = detected
                header_row_idx = r_idx
                break

        if not col_index_map or header_row_idx == -1:
            # Fallback: process rows as raw lines
            for row in table:
                joined_line = " ".join([str(c) for c in row if c])
                self._parse_free_line(joined_line, report)
            return

        # Read data rows based on dynamically detected header positions
        for row in table[header_row_idx + 1:]:
            if not row or len(row) <= max(col_index_map.values()):
                continue

            row_str = " ".join([str(c) for c in row if c]).lower()
            if row_str.startswith("total") or "total" in row_str:
                continue

            try:
                # Extract RT
                raw_rt = self._clean_number(row[col_index_map["rt"]])
                if raw_rt is None or not (0.2 <= raw_rt <= 200.0):
                    continue

                # Extract % Area
                raw_pct = None
                if "pct_area" in col_index_map:
                    raw_pct = self._clean_number(row[col_index_map["pct_area"]])

                # Extract Area
                raw_area = 0.0
                if "area" in col_index_map:
                    val = self._clean_number(row[col_index_map["area"]])
                    raw_area = val if val is not None else 0.0

                # Extract RRT
                raw_rrt = None
                if "rrt" in col_index_map:
                    raw_rrt = self._clean_number(row[col_index_map["rrt"]])

                # Extract Height
                raw_height = 0.0
                if "height" in col_index_map:
                    val = self._clean_number(row[col_index_map["height"]])
                    raw_height = val if val is not None else 0.0

                # Extract Name
                name = "Unk"
                if "name" in col_index_map and row[col_index_map["name"]]:
                    c_name = str(row[col_index_map["name"]]).strip()
                    if c_name and not c_name.replace(".", "").isdigit():
                        name = c_name

                # If % Area is missing but Area is present, assign it temporarily
                if raw_pct is None:
                    raw_pct = raw_area

                if 0.0 <= raw_pct <= 100.0:
                    report.add_peak(Peak(
                        name=name,
                        retention_time=raw_rt,
                        area=raw_area,
                        percent_area=raw_pct,
                        height=raw_height,
                        rel_rt=raw_rrt
                    ))
            except Exception:
                continue

    def _identify_header_indices(self, cells: List[str]) -> Dict[str, int]:
        mapping = {}
        for idx, cell in enumerate(cells):
            clean_cell = cell.replace("\n", " ").strip()
            # 1. RRT check
            if any(k in clean_cell for k in self.HEADER_MAP["rrt"]):
                mapping["rrt"] = idx
            # 2. % Area check
            elif any(k in clean_cell for k in self.HEADER_MAP["pct_area"]):
                mapping["pct_area"] = idx
            # 3. RT check
            elif any(k in clean_cell for k in self.HEADER_MAP["rt"]):
                mapping["rt"] = idx
            # 4. Area check
            elif any(k in clean_cell for k in self.HEADER_MAP["area"]):
                mapping["area"] = idx
            # 5. Height check
            elif any(k in clean_cell for k in self.HEADER_MAP["height"]):
                mapping["height"] = idx
            # 6. Name check
            elif any(k in clean_cell for k in self.HEADER_MAP["name"]):
                mapping["name"] = idx
        return mapping

    def _parse_with_pypdf(self, file_bytes: bytes, report: HplcReport):
        reader = PdfReader(io.BytesIO(file_bytes))
        full_text = ""
        for page in reader.pages:
            try:
                txt = page.extract_text(extraction_mode="layout") or page.extract_text() or ""
            except Exception:
                txt = page.extract_text() or ""
            full_text += txt + "\n"

            for line in txt.splitlines():
                self._parse_free_line(line.strip(), report)

        self._extract_metadata(full_text, report)

    def _parse_free_line(self, line: str, report: HplcReport):
        if not line or line.lower().startswith("total") or "ret.time" in line.lower() or "area %" in line.lower():
            return

        # Separate concatenated numbers and names (e.g., '14.291RIM-IMP-B' -> '14.291 RIM-IMP-B')
        line = re.sub(r"(\d+\.\d{2,4})([A-Za-z])", r"\1 \2", line)
        # Separate concatenated numbers (e.g., '11.6500.712' -> '11.650 0.712')
        line = re.sub(r"(\.\d{2,4})(\d+\.\d+)", r"\1 \2", line)

        tokens = line.split()
        if len(tokens) < 3:
            return

        # Handle leading row index
        start_idx = 1 if tokens[0].isdigit() else 0
        if start_idx >= len(tokens):
            return

        # First valid float is RT
        first_num = self._clean_number(tokens[start_idx])
        if first_num is None or not (0.2 <= first_num <= 200.0):
            return
        rt = first_num

        # Collect all remaining trailing floats
        end_idx = len(tokens) - 1
        # Strip trailing non-numeric peak integration types (e.g., 'BMB*', 'BB', 'MM')
        if end_idx > start_idx and self._clean_number(tokens[end_idx]) is None:
            end_idx -= 1

        numeric_values = []
        name_tokens = []

        # Backward collection of numbers
        while end_idx > start_idx:
            val = self._clean_number(tokens[end_idx])
            if val is not None:
                numeric_values.append(val)
                end_idx -= 1
            else:
                break

        # Remaining middle tokens form peak name
        name_tokens = tokens[start_idx + 1:end_idx + 1]
        name = " ".join(name_tokens).strip() if name_tokens else "Unk"

        if not numeric_values:
            return

        # Adaptive assignment based on numeric counts
        pct_area = None
        area = 0.0
        rel_rt = None
        height = 0.0

        if len(numeric_values) >= 4:
            # Layout: Area, %Area, Height, RelRet
            rel_rt = numeric_values[0]
            height = numeric_values[1]
            pct_area = numeric_values[2]
            area = numeric_values[3]
        elif len(numeric_values) == 3:
            # Layout: Area, %Area, Height
            height = numeric_values[0]
            pct_area = numeric_values[1]
            area = numeric_values[2]
        elif len(numeric_values) == 2:
            # Layout: Area, %Area
            pct_area = numeric_values[0]
            area = numeric_values[1]
        elif len(numeric_values) == 1:
            pct_area = numeric_values[0]

        if pct_area is not None and (0.0 <= pct_area <= 100.0):
            report.add_peak(Peak(
                name=name,
                retention_time=rt,
                area=area,
                percent_area=pct_area,
                height=height,
                rel_rt=rel_rt
            ))

    def _extract_metadata(self, text: str, report: HplcReport):
        # Sample / Injection Name
        if not report.sample_name:
            for pat in self.INJECTION_PATTERNS:
                m = pat.search(text)
                if m:
                    report.sample_name = m.group(1).strip()
                    break

        # Batch ID
        if not report.batch_id:
            for pat in self.BATCH_PATTERNS:
                m = pat.search(text)
                if m:
                    val = m.group(1).strip()
                    if val.lower() not in ["n.a.", "na", "none", "nil"]:
                        report.batch_id = val
                        break

        # Wavelength
        for pat in self.WAVELENGTH_PATTERNS:
            for m in pat.finditer(text):
                try:
                    wl = int(m.group(1))
                    if 190 <= wl <= 800:
                        report.detected_wavelengths.add(wl)
                except Exception:
                    pass

        # CDS Software Signature
        lower = text.lower()
        if "chromeleon" in lower or "dionex" in lower:
            report.cds_source = "DIONEX_CHROMELEON"
        elif "openlab" in lower or "chemstation" in lower or "agilent" in lower:
            report.cds_source = "AGILENT_OPENLAB"
        elif "labsolutions" in lower or "shimadzu" in lower:
            report.cds_source = "SHIMADZU_LABSOLUTIONS"
        elif "empower" in lower or "waters" in lower:
            report.cds_source = "WATERS_EMPOWER"

    @staticmethod
    def _clean_number(val: any) -> Optional[float]:
        if val is None:
            return None
        s = str(val).replace(",", "").strip()
        m = re.search(r"[-+]?\d*\.?\d+", s)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return None
