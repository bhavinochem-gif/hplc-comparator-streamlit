import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set
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
    height: float
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
    INJECTION_PATTERN = re.compile(
        r"(?:Injection\s*Name|Sample\s*Name|Sample\s*ID)\s*[:=\-\t]+\s*([A-Za-z0-9_\-\./#]+)",
        re.IGNORECASE
    )
    BATCH_PATTERN = re.compile(
        r"(?:Batch\s*(?:No|ID|Name)?|Lot\s*(?:No|ID)?)\s*[:=\-\t]+\s*([A-Za-z0-9_\-\./#]+)",
        re.IGNORECASE
    )
    WAVELENGTH_PATTERN = re.compile(
        r"(?:Wavelength|Sig(?:nal)?|Lambda)\s*[:=\-\t]?\s*(\d{3})\s*nm",
        re.IGNORECASE
    )

    def parse(self, file_bytes: bytes, filename: str) -> HplcReport:
        report = HplcReport(file_name=filename)
        raw_lines: List[str] = []

        # Strategy 1: pdfplumber line extraction
        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for page in pdf.pages:
                        txt = page.extract_text(layout=False) or ""
                        for line in txt.splitlines():
                            clean = line.strip()
                            if clean:
                                raw_lines.append(clean)
            except Exception:
                pass

        # Strategy 2: pypdf fallback extraction
        if not raw_lines:
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                for page in reader.pages:
                    txt = page.extract_text() or ""
                    for line in txt.splitlines():
                        clean = line.strip()
                        if clean:
                            raw_lines.append(clean)
            except Exception:
                pass

        for line in raw_lines:
            self._extract_metadata(line, report)
            self._parse_line_tokens(line, report)

        # Fallback to sample name if Batch No is n.a. or missing
        if not report.batch_id or report.batch_id.lower() in ["n.a.", "na", "none", "nil", ""]:
            if report.sample_name:
                report.batch_id = report.sample_name
            else:
                report.batch_id = filename.replace(".pdf", "")

        return report

    def _extract_metadata(self, line: str, report: HplcReport):
        if not report.sample_name:
            m = self.INJECTION_PATTERN.search(line)
            if m:
                report.sample_name = m.group(1).strip()

        if not report.batch_id:
            m = self.BATCH_PATTERN.search(line)
            if m:
                val = m.group(1).strip()
                if val.lower() not in ["n.a.", "na", "none"]:
                    report.batch_id = val

        m_wl = self.WAVELENGTH_PATTERN.search(line)
        if m_wl:
            report.detected_wavelengths.add(int(m_wl.group(1)))

    def _parse_line_tokens(self, line: str, report: HplcReport):
        lower_line = line.lower()
        if lower_line.startswith("total") or "ret.time" in lower_line or "area %" in lower_line:
            return

        # Separate joined numeric RT from alphabetic peak name (e.g., '11.650Unk' -> '11.650 Unk')
        line = re.sub(r"(\d+\.\d{2,4})([A-Za-z])", r"\1 \2", line)
        tokens = line.split()
        if len(tokens) < 4:
            return

        start_idx = 0
        if tokens[0].isdigit():
            start_idx = 1

        if start_idx >= len(tokens):
            return

        rt_token = tokens[start_idx].replace(",", "")
        try:
            rt = float(rt_token)
            if not (0.2 <= rt <= 200.0):
                return
        except ValueError:
            return

        end_idx = len(tokens) - 1

        # Strip Peak Type string (e.g., 'BMB*', 'BM', 'MB', 'M*')
        if end_idx > start_idx and not self._is_float(tokens[end_idx]):
            end_idx -= 1

        # Collect trailing numeric values
        num_stack = []
        while end_idx > start_idx:
            t = tokens[end_idx].replace(",", "")
            if self._is_float(t):
                num_stack.append(float(t))
                end_idx -= 1
            else:
                break

        if len(num_stack) < 2:
            return

        rel_rt = None
        height = 0.0

        if len(num_stack) >= 4:
            rel_rt = num_stack[0]
            height = num_stack[1]
            pct_area = num_stack[2]
            area = num_stack[3]
        elif len(num_stack) == 3:
            height = num_stack[0]
            pct_area = num_stack[1]
            area = num_stack[2]
        else:
            pct_area = num_stack[0]
            area = num_stack[1]

        if not (0.0 <= pct_area <= 100.0):
            return

        name_tokens = tokens[start_idx + 1:end_idx + 1]
        name = " ".join(name_tokens).strip() if name_tokens else "Unk"

        report.add_peak(Peak(
            name=name,
            retention_time=rt,
            area=area,
            percent_area=pct_area,
            height=height,
            rel_rt=rel_rt
        ))

    @staticmethod
    def _is_float(val: str) -> bool:
        clean = val.replace(",", "")
        try:
            float(clean)
            return True
        except ValueError:
            return False
