from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from parser import HplcReport, Peak


@dataclass
class MasterPeakColumn:
    rt: float
    rrt: float
    peak_name: str
    is_main_peak: bool


@dataclass
class BatchComparisonResult:
    master_columns: List[MasterPeakColumn]
    batch_rows: List[Dict[str, any]]  # Each row corresponds to one PDF report
    active_wavelength: Optional[int]
    available_wavelengths: List[int]


class HplcComparator:

    @staticmethod
    def build_horizontal_matrix(
        reports: List[HplcReport],
        rt_tolerance: float = 0.05,
        target_main_rt: Optional[float] = None,
        target_wavelength: Optional[int] = None
    ) -> BatchComparisonResult:
        # 1. Available wavelengths
        all_wl: Set[int] = set()
        for r in reports:
            all_wl.update(r.detected_wavelengths)
        available_wl_list = sorted(list(all_wl))

        active_wavelength = None
        if target_wavelength and target_wavelength > 0:
            active_wavelength = target_wavelength
        elif available_wl_list:
            active_wavelength = available_wl_list[0]

        # 2. Filter peaks by wavelength
        filtered_peaks: Dict[str, List[Peak]] = {}
        for r in reports:
            filtered_peaks[r.file_name] = [
                p for p in r.peaks
                if active_wavelength is None or p.wavelength == 0 or p.wavelength == active_wavelength
            ]

        # 3. Cluster master retention times across all reports
        ref_rts: List[float] = []
        for p_list in filtered_peaks.values():
            for p in p_list:
                if not any(abs(p.retention_time - ref) <= rt_tolerance for ref in ref_rts):
                    ref_rts.append(p.retention_time)
        ref_rts.sort()

        # 4. Resolve main API peak
        main_peak_rt = 0.0
        if target_main_rt and target_main_rt > 0:
            for rt in ref_rts:
                if abs(rt - target_main_rt) <= rt_tolerance:
                    main_peak_rt = rt
                    break

        if main_peak_rt == 0.0 and ref_rts:
            best_rt = ref_rts[0]
            max_avg_area = -1.0
            for rt in ref_rts:
                tot_area = sum(
                    p.percent_area for r in reports
                    for p in filtered_peaks[r.file_name]
                    if abs(p.retention_time - rt) <= rt_tolerance
                )
                avg_area = tot_area / len(reports) if reports else 0.0
                if avg_area > max_avg_area:
                    max_avg_area = avg_area
                    best_rt = rt
            main_peak_rt = best_rt

        # 5. Build Master Columns (representing each Impurity / RT position)
        master_columns: List[MasterPeakColumn] = []
        for rt in ref_rts:
            is_main = abs(rt - main_peak_rt) <= rt_tolerance
            
            # Find best RRT (prefer parsed rel_rt, otherwise compute from main_peak_rt)
            rrt = round(rt / main_peak_rt, 3) if main_peak_rt > 0 else 1.0
            for r in reports:
                match = next((p for p in filtered_peaks[r.file_name] if abs(p.retention_time - rt) <= rt_tolerance and p.rel_rt), None)
                if match and match.rel_rt:
                    rrt = match.rel_rt
                    break

            peak_name = "RIM" if is_main else "Unk"
            for r in reports:
                match = next((p for p in filtered_peaks[r.file_name] if abs(p.retention_time - rt) <= rt_tolerance and p.name.lower() not in ["unk", "unknown"]), None)
                if match:
                    peak_name = match.name
                    break

            master_columns.append(MasterPeakColumn(
                rt=round(rt, 3),
                rrt=round(rrt, 3),
                peak_name=peak_name,
                is_main_peak=is_main
            ))

        # 6. Build Batch Rows (one row per report file)
        batch_rows = []
        for idx, r in enumerate(reports, start=1):
            row_data = {
                "Sr. No.": idx,
                "Batch No.": r.batch_id or r.sample_name or r.file_name,
                "Injection Name": r.sample_name or r.file_name
            }
            for col in master_columns:
                match = next((p for p in filtered_peaks[r.file_name] if abs(p.retention_time - col.rt) <= rt_tolerance), None)
                row_data[col.rt] = f"{match.percent_area:.2f}" if match else ""
            batch_rows.append(row_data)

        return BatchComparisonResult(
            master_columns=master_columns,
            batch_rows=batch_rows,
            active_wavelength=active_wavelength,
            available_wavelengths=available_wl_list
        )
