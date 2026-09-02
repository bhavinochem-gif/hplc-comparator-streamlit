import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set
from pypdf import PdfReader


@dataclass
class Peak:
    name: str
    retention_time: float
    area: float
    percent_area: float
    height: float
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
    SAMPLE_PATTERN = re.compile(
        r"(?i)(?:Sample\s*Name|Sample\s*ID|Sample)\s*[:=\t]+\s*([^\r\n|]+)"
    )
    BATCH_PATTERN = re.compile(
        r"(?i)(?:Batch\s*(?:No|ID|Name)?|Lot\s*(?:No|ID)?|Vial\s*#?)\s*[:=\t]+\s*([A-Za-z0-9_\-\.]+)"
    )

    # Wavelength / Channel Signals
    AGILENT_SIGNAL_WL = re.compile(
        r"(?i)(?:Sig(?:nal)?\s*\d*[:=]|Sig=)\s*(?:DAD\d*\s*[A-Z],\s*Sig=)?(\d{3})"
    )
    SHIMADZU_CHANNEL_WL = re.compile(
        r"(?i)(?:PDA\s*Multi\s*\d*\s*\/|Detector\s*[A-Z]-Ch\d*[:\s]+|Channel\s*\d*\s*:\s*)(\d{3})\s*nm"
    )
    WATERS_CHANNEL_WL = re.compile(
        r"(?i)(?:Channel\s*(?:Description)?[:\s]+|PDA\s+)(\d{3})\s*nm"
    )
    GENERIC_WL = re.compile(r"(?i)\b(?:Wavelength|Channel|Lambda)\s*[:=]?\s*(\d{3})\s*nm\b")

    # Multi-Vendor Peak Row Regexes
    AGILENT_ROW_PATTERN = re.compile(
        r"^\s*(\d+)?\s+(\d+\.\d{2,4})\s+(?:[A-Za-z]{2,4}|\.\.|--)\s+(?:\d+\.\d{2,4}\s+)?(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})(?:\s+(.+))?$"
    )
    AGILENT_ALT_PATTERN = re.compile(
        r"^\s*(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})(?:\s+(.+))?$"
    )
    SHIMADZU_NAMED_PATTERN = re.compile(
        r"^\s*\d+\s+([A-Za-z0-9_\-\s]+?)\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})\s*$"
    )
    SHIMADZU_STD_PATTERN = re.compile(
        r"^\s*\d+\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})(?:\s+(.+))?\s*$"
    )
    WATERS_ROW_PATTERN = re.compile(
        r"^\s*(\S+)?\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s*$"
    )

    @staticmethod
    def detect_cds(text: str) -> str:
        text_lower = text.lower()
        if any(k in text_lower for k in ["agilent", "chemstation", "openlab"]):
            return "AGILENT_OPENLAB"
        if any(k in text_lower for k in ["shimadzu", "labsolutions", "lcsolution"]):
            return "SHIMADZU_LABSOLUTIONS"
        if any(k in text_lower for k in ["empower", "waters"]):
            return "WATERS_EMPOWER"
        return "GENERIC"

    @classmethod
    def extract_wavelength(cls, line: str) -> Optional[int]:
        for pattern in [cls.AGILENT_SIGNAL_WL, cls.SHIMADZU_CHANNEL_WL, cls.WATERS_CHANNEL_WL, cls.GENERIC_WL]:
            m = pattern.search(line)
            if m:
                return int(m.group(1))
        return None

    def parse(self, file_bytes: bytes, filename: str) -> HplcReport:
        report = HplcReport(file_name=filename)
        reader = PdfReader(io.BytesIO(file_bytes))

        full_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                full_text.append(t)
        raw_content = "\n".join(full_text)

        report.cds_source = self.detect_cds(raw_content)
        current_wavelength = 0

        for line in raw_content.splitlines():
            line = line.strip()
            if not line:
                continue

            if not report.sample_name:
                m_sample = self.SAMPLE_PATTERN.search(line)
                if m_sample:
                    report.sample_name = m_sample.group(1).strip()

            if not report.batch_id:
                m_batch = self.BATCH_PATTERN.search(line)
                if m_batch:
                    report.batch_id = m_batch.group(1).strip()

            detected_wl = self.extract_wavelength(line)
            if detected_wl:
                current_wavelength = detected_wl

            self._parse_peak_line(line, report, current_wavelength)

        if not report.sample_name:
            report.sample_name = re.sub(r"(?i)\.pdf$", "", filename)

        return report

    def _parse_peak_line(self, line: str, report: HplcReport, wavelength: int):
        cds = report.cds_source
        if cds == "AGILENT_OPENLAB" and self._try_agilent(line, report, wavelength):
            return
        if cds == "SHIMADZU_LABSOLUTIONS" and self._try_shimadzu(line, report, wavelength):
            return
        if cds == "WATERS_EMPOWER" and self._try_waters(line, report, wavelength):
            return

        if self._try_waters(line, report, wavelength):
            return
        if self._try_shimadzu(line, report, wavelength):
            return
        self._try_agilent(line, report, wavelength)

    def _try_agilent(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.AGILENT_ROW_PATTERN.match(line)
        if m:
            name = m.group(6).strip() if m.group(6) else "Unknown"
            self._add_peak(report, name, float(m.group(2)), float(m.group(3)), float(m.group(5)), float(m.group(4)), wl)
            return True
        m2 = self.AGILENT_ALT_PATTERN.match(line)
        if m2:
            name = m2.group(5).strip() if m2.group(5) else "Unknown"
            self._add_peak(report, name, float(m2.group(1)), float(m2.group(2)), float(m2.group(4)), float(m2.group(3)), wl)
            return True
        return False

    def _try_shimadzu(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.SHIMADZU_NAMED_PATTERN.match(line)
        if m:
            self._add_peak(report, m.group(1).strip(), float(m.group(2)), float(m.group(3)), float(m.group(5)), float(m.group(4)), wl)
            return True
        m2 = self.SHIMADZU_STD_PATTERN.match(line)
        if m2:
            name = m2.group(5).strip() if m2.group(5) else "Unknown"
            self._add_peak(report, name, float(m2.group(1)), float(m2.group(2)), float(m2.group(4)), float(m2.group(3)), wl)
            return True
        return False

    def _try_waters(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.WATERS_ROW_PATTERN.match(line)
        if m:
            name = m.group(1).strip() if m.group(1) else "Unknown"
            self._add_peak(report, name, float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)), wl)
            return True
        return False

    @staticmethod
    def _add_peak(report: HplcReport, name: str, rt: float, area: float, pct_area: float, height: float, wl: int):
        if rt > 0.0 and 0.0 <= pct_area <= 100.0 and area >= 0.0:
            report.add_peak(Peak(
                name=name,
                retention_time=rt,
                area=area,
                percent_area=pct_area,
                height=height,
                wavelength=wl
            ))
