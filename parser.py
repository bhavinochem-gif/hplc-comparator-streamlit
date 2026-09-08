import io
import re
from dataclasses import dataclass, field
from pathlib import Path
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
    height: float = 0.0
    rel_rt: Optional[float] = None
    wavelength: int = 0


@dataclass
class HplcReport:
    file_name: str
    sample_name: Optional[str] = None
    batch_id: str = ""
    cds_source: str = "GENERIC"
    detected_wavelengths: Set[int] = field(default_factory=set)
    peaks: List[Peak] = field(default_factory=list)

    def add_peak(self, peak: Peak):
        self.peaks.append(peak)
        if peak.wavelength > 0:
            self.detected_wavelengths.add(peak.wavelength)


class HplcPdfParser:
    INJECTION_PATTERNS = [
        re.compile(r"(?:Injection\s*Name|Sample\s*Name|Sample\s*ID|Sample\s*Description)\s*[:=\-\t]+\s*([^\r\n|,]+)", re.I),
        re.compile(r"Data\s*File\s*[:=\-\t]+\s*([A-Za-z0-9_\-\./#]+)", re.I),
    ]

    WAVELENGTH_PATTERNS = [
        re.compile(r"Wavelength\s*[:=\-\t]?\s*(\d{3})\s*nm", re.I),
        re.compile(r"(?:Sig(?:nal)?|DAD\d*[A-Z]?|Channel)\s*[:=\-\t,]?\s*(?:Sig=)?(\d{3})\s*nm?", re.I),
        re.compile(r"PDA\s*Multi\s*\d*\s*/\s*(\d{3})\s*nm", re.I),
    ]

    def parse(self, file_bytes: bytes, filename: str) -> HplcReport:
        clean_batch_name = Path(filename).stem.strip()
        report = HplcReport(file_name=filename, batch_id=clean_batch_name)

        raw_lines: List[str] = []

        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for page in pdf.pages:
                        txt = page.extract_text(layout=False) or ""
                        for line in txt.splitlines():
                            cl = line.strip()
                            if cl:
                                raw_lines.append(cl)
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

        for line in raw_lines:
            self._extract_metadata(line, report)
            self._parse_line(line, report)

        return report

    def _extract_metadata(self, line: str, report: HplcReport):
        if not report.sample_name:
            for pat in self.INJECTION_PATTERNS:
                m = pat.search(line)
                if m:
                    report.sample_name = m.group(1).strip()
                    break

        for pat in self.WAVELENGTH_PATTERNS:
            for m in pat.finditer(line):
                try:
                    wl = int(m.group(1))
                    if 190 <= wl <= 800:
                        report.detected_wavelengths.add(wl)
                except Exception:
                    pass

        lower = line.lower()
        if "chromeleon" in lower or "dionex" in lower:
            report.cds_source = "DIONEX_CHROMELEON"
        elif "openlab" in lower or "chemstation" in lower or "agilent" in lower:
            report.cds_source = "AGILENT_OPENLAB"
        elif "labsolutions" in lower or "shimadzu" in lower:
            report.cds_source = "SHIMADZU_LABSOLUTIONS"
        elif "empower" in lower or "waters" in lower:
            report.cds_source = "WATERS_EMPOWER"

    def _parse_line(self, line: str, report: HplcReport):
        clean_line = line.strip()
        lower_line = clean_line.lower()

        if not clean_line or lower_line.startswith("total") or "ret.time" in lower_line or "area %" in lower_line:
            return

        # Separate numeric values stuck to letters or adjacent decimals
        clean_line = re.sub(r"(\d+\.\d{2,4})([A-Za-z])", r"\1 \2", clean_line)
        clean_line = re.sub(r"(\.\d{2,4})(\d+\.\d+)", r"\1 \2", clean_line)

        tokens = clean_line.split()
        if len(tokens) < 3:
            return

        # Strip non-numeric peak integration types from the right
        if not re.match(r"^\d+(?:\.\d+)?$", tokens[-1].replace(",", "")):
            tokens.pop()

        if len(tokens) < 3:
            return

        # Discard leading peak index number if present
        if tokens[0].isdigit() and len(tokens) > 3:
            try:
                val = float(tokens[1].replace(",", ""))
                if 0.2 <= val <= 250.0:
                    tokens.pop(0)
            except ValueError:
                pass

        rt = None
        name = "Unk"
        try:
            val = float(tokens[0].replace(",", ""))
            if 0.2 <= val <= 250.0:
                rt = val
                tokens.pop(0)
        except ValueError:
            name = tokens.pop(0)
            try:
                rt = float(tokens.pop(0).replace(",", ""))
            except (ValueError, IndexError):
                return

        if rt is None:
            return

        trailing_nums = []
        while tokens:
            t = tokens[-1].replace(",", "")
            try:
                num = float(t)
                trailing_nums.append(num)
                tokens.pop()
            except ValueError:
                break

        trailing_nums.reverse()

        if tokens:
            name = " ".join(tokens).strip()
        if not name or name.lower() in ["unk", "unknown", "--", "n.a."]:
            name = "Unk"

        area = 0.0
        pct_area = 0.0
        height = 0.0
        rel_rt = None

        if len(trailing_nums) >= 4:
            area = trailing_nums[0]
            pct_area = trailing_nums[1]
            height = trailing_nums[2]
            rel_rt = trailing_nums[3]
        elif len(trailing_nums) == 3:
            if 0.0 <= trailing_nums[1] <= 100.0 and trailing_nums[2] > 100.0:
                area = trailing_nums[0]
                pct_area = trailing_nums[1]
                height = trailing_nums[2]
            elif 0.0 <= trailing_nums[2] <= 100.0:
                area = trailing_nums[0]
                height = trailing_nums[1]
                pct_area = trailing_nums[2]
            else:
                area = trailing_nums[0]
                pct_area = trailing_nums[1]
        elif len(trailing_nums) == 2:
            area = trailing_nums[0]
            pct_area = trailing_nums[1]
        elif len(trailing_nums) == 1:
            pct_area = trailing_nums[0]

        if 0.0 <= pct_area <= 100.0:
            report.add_peak(Peak(
                name=name,
                retention_time=rt,
                area=area,
                percent_area=pct_area,
                height=height,
                rel_rt=rel_rt
            ))
