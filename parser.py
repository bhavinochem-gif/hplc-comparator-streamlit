import io
import re
from dataclasses import dataclass, field
from pathlib import Path
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


@dataclass
class HplcReport:
    file_name: str
    sample_name: Optional[str] = None
    batch_id: str = ""
    detected_wavelengths: Set[int] = field(default_factory=set)
    peaks: List[Peak] = field(default_factory=list)

    def add_peak(self, peak: Peak):
        self.peaks.append(peak)


class HplcPdfParser:
    INJECTION_PATTERN = re.compile(
        r"(?:Injection\s*Name|Sample\s*Name|Sample\s*ID)\s*[:=\-\t]+\s*([^\r\n|,]+)", re.I
    )
    BATCH_PATTERN = re.compile(
        r"Batch\s*(?:No|ID)?\s*[:=\-\t]+\s*([^\r\n|,]+)", re.I
    )

    # Header synonyms across vendors (Chromeleon, Waters, Agilent, Shimadzu)
    HEADER_SYNONYMS = {
        "rt": ["ret.time", "ret time", "ret. time", "rt (min)", "rt [min]", "r.t.", "rt", "time"],
        "rrt": ["rel.ret. time", "rel.ret", "rel ret", "rel. ret.", "rrt", "rel. r.t.", "relative retention time"],
        "pct_area": ["area %", "% area", "%area", "area%", "area percent", "% of total", "percent area"],
        "area": ["area", "area µau*sec", "area mau*s", "area(counts)"],
        "name": ["peak name", "compound name", "component", "name"],
    }

    def parse(self, file_bytes: bytes, filename: str) -> HplcReport:
        clean_file_title = Path(filename).stem.strip()
        report = HplcReport(file_name=filename, batch_id=clean_file_title)
        raw_lines: List[str] = []

        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for page in pdf.pages:
                        words = page.extract_words(y_tolerance=3, x_tolerance=3)
                        if words:
                            lines_dict = {}
                            for w in words:
                                top_key = round(w['top'] / 3.0) * 3.0
                                lines_dict.setdefault(top_key, []).append(w)

                            for top_k in sorted(lines_dict.keys()):
                                line_words = sorted(lines_dict[top_k], key=lambda x: x['x0'])
                                line_str = " ".join([w['text'] for w in line_words]).strip()
                                if line_str:
                                    raw_lines.append(line_str)
            except Exception:
                pass

        if not raw_lines:
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                for page in reader.pages:
                    txt = page.extract_text() or ""
                    for line in txt.splitlines():
                        cl = line.strip()
                        if cl:
                            raw_lines.append(cl)
            except Exception:
                pass

        # Identify column sequence from the header row
        col_order = self._detect_column_order(raw_lines)

        for line in raw_lines:
            self._extract_metadata(line, report)
            self._parse_table_line(line, report, col_order)

        if not report.batch_id or report.batch_id.lower() in ["n.a.", "na", "none", "nil"]:
            report.batch_id = report.sample_name or clean_file_title

        return report

    def _detect_column_order(self, lines: List[str]) -> Dict[str, int]:
        for line in lines[:25]:
            low = line.lower()
            if any(k in low for k in self.HEADER_SYNONYMS["rt"]) and any(k in low for k in self.HEADER_SYNONYMS["pct_area"]):
                tokens = low.split()
                mapping = {}
                for idx, t in enumerate(tokens):
                    for col_key, synonyms in self.HEADER_SYNONYMS.items():
                        if any(s in t for s in synonyms) and col_key not in mapping:
                            mapping[col_key] = idx
                if "rt" in mapping:
                    return mapping
        return {}

    def _extract_metadata(self, line: str, report: HplcReport):
        if not report.sample_name:
            m_inj = self.INJECTION_PATTERN.search(line)
            if m_inj:
                val = m_inj.group(1).strip()
                if val and val.lower() != "n.a.":
                    report.sample_name = val
                    report.batch_id = val

        m_bat = self.BATCH_PATTERN.search(line)
        if m_bat:
            b_val = m_bat.group(1).strip()
            if b_val and b_val.lower() not in ["n.a.", "na", "none"]:
                report.batch_id = b_val

    def _parse_table_line(self, line: str, report: HplcReport, col_order: Dict[str, int]):
        clean = line.strip()
        lower = clean.lower()

        if not clean or lower.startswith("total") or "ret.time" in lower or "area %" in lower or "height" in lower:
            return

        clean = re.sub(r"(\d+\.\d{2,4})([A-Za-z])", r"\1 \2", clean)
        clean = re.sub(r"(\.\d{2,4})(\d+\.\d+)", r"\1 \2", clean)

        tokens = clean.split()
        if len(tokens) < 3:
            return

        if not tokens[0].isdigit():
            return

        try:
            rt = float(tokens[1].replace(",", ""))
            if not (0.2 <= rt <= 250.0):
                return
        except ValueError:
            return

        # Strip trailing integration flags (BMB*, BM*, MB, etc.)
        if not re.match(r"^\d+(?:\.\d+)?$", tokens[-1].replace(",", "")):
            tokens.pop()

        trailing_floats = []
        idx = len(tokens) - 1
        while idx >= 2:
            t = tokens[idx].replace(",", "")
            try:
                trailing_floats.append(float(t))
                idx -= 1
            except ValueError:
                break

        trailing_floats.reverse()
        name_tokens = tokens[2:idx + 1]
        raw_name = " ".join(name_tokens).strip()
        name = "" if not raw_name or raw_name.lower() in ["unk", "unknown", "--", "n.a."] else raw_name

        area = 0.0
        pct_area = 0.0
        rrt = None

        if len(trailing_floats) >= 4:
            area = trailing_floats[0]
            pct_area = trailing_floats[1]
            rrt = trailing_floats[3]
        elif len(trailing_floats) == 3:
            area = trailing_floats[0]
            pct_area = trailing_floats[1]
            rrt = trailing_floats[2] if trailing_floats[2] <= 5.0 else None
        elif len(trailing_floats) == 2:
            area = trailing_floats[0]
            pct_area = trailing_floats[1]

        if 0.0 <= pct_area <= 100.0:
            report.add_peak(Peak(
                name=name,
                retention_time=rt,
                area=area,
                percent_area=pct_area,
                rel_rt=rrt
            ))
