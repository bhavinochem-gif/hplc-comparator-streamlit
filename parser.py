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
    SAMPLE_PATTERN = re.compile(
        r"(?i)(?:Sample\s*Name|Sample\s*ID|Injection\s*Name|Sample)\s*[:=\-\t]+\s*([^\r\n|]+)"
    )
    BATCH_PATTERN = re.compile(
        r"(?i)(?:Batch\s*(?:No|ID|Name)?|Lot\s*(?:No|ID)?|Vial\s*#?)\s*[:=\-\t]+\s*([A-Za-z0-9_\-\.]+)"
    )

    CHROMELEON_WL = re.compile(r"(?i)Wavelength\s*[:=\-\t]+\s*(\d{3})\s*nm")
    AGILENT_SIGNAL_WL = re.compile(r"(?i)(?:Sig(?:nal)?\s*\d*[:=]|Sig=)\s*(?:DAD\d*\s*[A-Z],\s*Sig=)?(\d{3})")
    SHIMADZU_CHANNEL_WL = re.compile(r"(?i)(?:PDA\s*Multi\s*\d*\s*\/|Detector\s*[A-Z]-Ch\d*[:\s]+|Channel\s*\d*\s*:\s*)(\d{3})\s*nm")
    WATERS_CHANNEL_WL = re.compile(r"(?i)(?:Channel\s*(?:Description)?[:\s]+|PDA\s+)(\d{3})\s*nm")
    GENERIC_WL = re.compile(r"(?i)\b(?:Wavelength|Channel|Lambda)\s*[:=\-]?\s*(\d{3})\s*nm\b")

    # Chromeleon Peak Row: Peak# | Ret.Time | Peak Name | Area | Area % | Height | Rel.Ret | Type
    CHROMELEON_ROW_PATTERN = re.compile(
        r"^\s*(\d+)\s+(\d+\.\d{2,4})\s+([A-Za-z0-9_\-\s]+?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)(?:\s+(\d+\.\d{2,4}))?(?:\s+([A-Za-z0-9\*_\s]+))?\s*$"
    )
    AGILENT_ROW_PATTERN = re.compile(
        r"^\s*(\d+)?\s+(\d+\.\d{2,4})\s+(?:[A-Za-z]{2,4}|\.\.|--)\s+(?:\d+\.\d{2,4}\s+)?(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})(?:\s+(.+))?$"
    )
    WATERS_ROW_PATTERN = re.compile(
        r"^\s*(\S+)?\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2,4})\s+(\d+(?:\.\d+)?)\s*$"
    )

    @staticmethod
    def detect_cds(text: str) -> str:
        text_lower = text.lower()
        if any(k in text_lower for k in ["chromeleon", "dionex"]):
            return "DIONEX_CHROMELEON"
        if any(k in text_lower for k in ["agilent", "chemstation", "openlab"]):
            return "AGILENT_OPENLAB"
        if any(k in text_lower for k in ["shimadzu", "labsolutions", "lcsolution"]):
            return "SHIMADZU_LABSOLUTIONS"
        if any(k in text_lower for k in ["empower", "waters"]):
            return "WATERS_EMPOWER"
        return "GENERIC"

    @classmethod
    def extract_wavelength(cls, line: str) -> Optional[int]:
        for pattern in [cls.CHROMELEON_WL, cls.AGILENT_SIGNAL_WL, cls.SHIMADZU_CHANNEL_WL, cls.WATERS_CHANNEL_WL, cls.GENERIC_WL]:
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
            if not line or line.startswith("Total"):
                continue

            if not report.sample_name:
                m_sample = self.SAMPLE_PATTERN.search(line)
                if m_sample:
                    report.sample_name = m_sample.group(1).strip()

            if not report.batch_id:
                m_batch = self.BATCH_PATTERN.search(line)
                if m_batch and m_batch.group(1).lower() != "n.a.":
                    report.batch_id = m_batch.group(1).strip()

            detected_wl = self.extract_wavelength(line)
            if detected_wl:
                current_wavelength = detected_wl

            self._parse_peak_line(line, report, current_wavelength)

        if not report.sample_name:
            report.sample_name = re.sub(r"(?i)\.pdf$", "", filename)
        return report

    def _parse_peak_line(self, line: str, report: HplcReport, wavelength: int):
        if self._try_chromeleon(line, report, wavelength):
            return
        if self._try_waters(line, report, wavelength):
            return
        self._try_agilent(line, report, wavelength)

    def _try_chromeleon(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.CHROMELEON_ROW_PATTERN.match(line)
        if m:
            rt = float(m.group(2))
            name = m.group(3).strip()
            area = float(m.group(4))
            pct_area = float(m.group(5))
            height = float(m.group(6))
            rel_rt = float(m.group(7)) if m.group(7) else None
            self._add_peak(report, name, rt, area, pct_area, height, rel_rt, wl)
            return True
        return False

    def _try_agilent(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.AGILENT_ROW_PATTERN.match(line)
        if m:
            name = m.group(6).strip() if m.group(6) else "Unknown"
            self._add_peak(report, name, float(m.group(2)), float(m.group(3)), float(m.group(5)), float(m.group(4)), None, wl)
            return True
        return False

    def _try_waters(self, line: str, report: HplcReport, wl: int) -> bool:
        m = self.WATERS_ROW_PATTERN.match(line)
        if m:
            name = m.group(1).strip() if m.group(1) else "Unknown"
            self._add_peak(report, name, float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)), None, wl)
            return True
        return False

    @staticmethod
    def _add_peak(report: HplcReport, name: str, rt: float, area: float, pct_area: float, height: float, rel_rt: Optional[float], wl: int):
        if rt > 0.0 and 0.0 <= pct_area <= 100.0 and area >= 0.0:
            report.add_peak(Peak(
                name=name,
                retention_time=rt,
                area=area,
                percent_area=pct_area,
                height=height,
                rel_rt=rel_rt,
                wavelength=wl
            ))
