import io
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import openpyxl
from parser import HplcReport, Peak


@dataclass
class MasterPeakColumn:
    rrt: float
    rt: float
    peak_name: str
    is_main_peak: bool


@dataclass
class BatchComparisonResult:
    master_columns: List[MasterPeakColumn]
    batch_rows: List[Dict[str, any]]
    active_wavelength: Optional[int]
    available_wavelengths: List[int]
    main_peak_rts: Dict[str, float]


class HplcComparator:

    @staticmethod
    def parse_existing_excel(excel_bytes: bytes) -> Tuple[List[MasterPeakColumn], List[Dict[str, any]]]:
        """Parses an existing HPLC_Batch_Impurity_Matrix.xlsx workbook back into memory."""
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active

        existing_columns: List[MasterPeakColumn] = []
        start_col = 4
        max_col = ws.max_column

        # Read master columns from Rows 1, 2, 3
        for c in range(start_col, max_col + 1):
            name_val = ws.cell(row=1, column=c).value
            rt_val = ws.cell(row=2, column=c).value
            rrt_val = ws.cell(row=3, column=c).value

            if rrt_val is not None:
                try:
                    rrt = round(float(rrt_val), 3)
                    rt = round(float(rt_val), 3) if rt_val is not None else 0.0
                    peak_name = str(name_val).strip() if name_val is not None else ""
                    is_main = abs(rrt - 1.0) < 0.005 or peak_name.upper() == "RIM"
                    existing_columns.append(MasterPeakColumn(
                        rrt=rrt,
                        rt=rt,
                        peak_name=peak_name,
                        is_main_peak=is_main
                    ))
                except ValueError:
                    continue

        # Read batch data rows from Row 4 downwards
        existing_rows: List[Dict[str, any]] = []
        for r in range(4, ws.max_row + 1):
            sr_no = ws.cell(row=r, column=1).value
            batch_no = ws.cell(row=r, column=2).value
            if batch_no is None and sr_no is None:
                continue

            row_dict = {
                "Sr. No.": sr_no or (len(existing_rows) + 1),
                "Batch No.": str(batch_no or "").strip()
            }
            for c_idx, col in enumerate(existing_columns, start=start_col):
                val = ws.cell(row=r, column=c_idx).value
                if val is not None and val != "":
                    try:
                        row_dict[col.rrt] = float(val)
                    except ValueError:
                        row_dict[col.rrt] = val
                else:
                    row_dict[col.rrt] = ""
            existing_rows.append(row_dict)

        return existing_columns, existing_rows

    @classmethod
    def build_or_merge_matrix(
        cls,
        new_reports: List[HplcReport],
        existing_excel_bytes: Optional[bytes] = None,
        rrt_tolerance: float = 0.010,
        target_main_rt: Optional[float] = None,
        target_wavelength: Optional[int] = None
    ) -> BatchComparisonResult:
        existing_cols: List[MasterPeakColumn] = []
        existing_rows: List[Dict[str, any]] = []

        if existing_excel_bytes:
            try:
                existing_cols, existing_rows = cls.parse_existing_excel(existing_excel_bytes)
            except Exception:
                pass

        all_wl: Set[int] = set()
        for r in new_reports:
            all_wl.update(r.detected_wavelengths)
        available_wl_list = sorted(list(all_wl))

        active_wavelength = (
            target_wavelength
            if target_wavelength and target_wavelength > 0
            else (available_wl_list[0] if available_wl_list else None)
        )

        # 1. Resolve Main Peak RT for each injection
        report_main_rts: Dict[str, float] = {}
        report_peaks_rrt: Dict[str, List[Tuple[Peak, float]]] = {}

        for r in new_reports:
            p_list = [
                p for p in r.peaks
                if active_wavelength is None or p.wavelength == 0 or p.wavelength == active_wavelength
            ]
            if not p_list:
                report_main_rts[r.file_name] = 0.0
                report_peaks_rrt[r.file_name] = []
                continue

            if target_main_rt and target_main_rt > 0:
                main_rt = min(p_list, key=lambda p: abs(p.retention_time - target_main_rt)).retention_time
            else:
                main_rt = max(p_list, key=lambda p: p.percent_area).retention_time
            report_main_rts[r.file_name] = main_rt

            # Priority 1: Native CDS Rel.Ret. | Priority 2: Calculated RT / Main_RT
            rrt_items = []
            for p in p_list:
                if p.rel_rt is not None and p.rel_rt > 0:
                    c_rrt = round(p.rel_rt, 3)
                elif main_rt > 0:
                    c_rrt = round(p.retention_time / main_rt, 3)
                else:
                    c_rrt = 1.0
                rrt_items.append((p, c_rrt))
            report_peaks_rrt[r.file_name] = rrt_items

        # 2. Master Column Alignment strictly driven by RRT
        master_columns: List[MasterPeakColumn] = list(existing_cols)

        for r in new_reports:
            for p, p_rrt in report_peaks_rrt[r.file_name]:
                matched = None
                best_diff = 999.0
                for c in master_columns:
                    diff = abs(c.rrt - p_rrt)
                    if diff <= rrt_tolerance and diff < best_diff:
                        best_diff = diff
                        matched = c

                if matched:
                    if not matched.peak_name and p.name.lower() not in ["unk", "unknown", ""]:
                        matched.peak_name = p.name
                else:
                    is_main = abs(p_rrt - 1.0) <= rrt_tolerance
                    name = p.name if p.name.lower() not in ["unk", "unknown", ""] else ("RIM" if is_main else "")
                    master_columns.append(MasterPeakColumn(
                        rrt=p_rrt,
                        rt=round(p.retention_time, 3),
                        peak_name=name,
                        is_main_peak=is_main
                    ))

        # Sort columns in ascending order by RRT
        master_columns.sort(key=lambda c: c.rrt)

        # Pad existing batch rows with any newly discovered impurity columns
        combined_rows: List[Dict[str, any]] = []
        for r in existing_rows:
            updated_r = dict(r)
            for col in master_columns:
                if col.rrt not in updated_r:
                    updated_r[col.rrt] = ""
            combined_rows.append(updated_r)

        # 3. RRT-Priority Optimal 1-to-1 Value Assignment for new batches
        next_sr_no = len(combined_rows) + 1
        for r in new_reports:
            b_label = r.batch_id or r.sample_name or r.file_name
            row_data = {
                "Sr. No.": next_sr_no,
                "Batch No.": b_label
            }
            next_sr_no += 1

            # Candidate pairing: (rrt_difference, peak_object, column_rrt)
            candidate_pairs = []
            for col in master_columns:
                for p, p_rrt in report_peaks_rrt[r.file_name]:
                    diff = abs(p_rrt - col.rrt)
                    if diff <= rrt_tolerance:
                        candidate_pairs.append((diff, p, col.rrt))

            # Sort ascending by RRT distance (absolute priority to lowest RRT delta)
            candidate_pairs.sort(key=lambda x: x[0])

            assigned_peaks = set()
            assigned_cols = set()
            col_assigned_val = {}

            for diff, p, col_rrt in candidate_pairs:
                peak_id = id(p)
                if peak_id not in assigned_peaks and col_rrt not in assigned_cols:
                    assigned_peaks.add(peak_id)
                    assigned_cols.add(col_rrt)
                    col_assigned_val[col_rrt] = 0 if p.percent_area == 0.0 else p.percent_area

            # Assign area percentages or empty string
            for col in master_columns:
                row_data[col.rrt] = col_assigned_val.get(col.rrt, "")

            combined_rows.append(row_data)

        return BatchComparisonResult(
            master_columns=master_columns,
            batch_rows=combined_rows,
            active_wavelength=active_wavelength,
            available_wavelengths=available_wl_list,
            main_peak_rts=report_main_rts
        )
