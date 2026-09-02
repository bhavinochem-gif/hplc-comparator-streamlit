from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from parser import HplcReport, Peak


@dataclass
class AlignedPeakRow:
    rt: float
    rrt: float
    rrf: float
    peak_name: str
    is_main_peak: bool
    sample_areas: Dict[str, str]
    corrected_sample_areas: Dict[str, str]


@dataclass
class ComparisonResult:
    sample_headers: List[str]
    main_peak_rt: float
    active_wavelength: Optional[int]
    available_wavelengths: List[int]
    rows: List[AlignedPeakRow]
    total_impurities: Dict[str, str]
    corrected_total_impurities: Dict[str, str]
    mass_balance: Dict[str, str]


class HplcComparator:

    @staticmethod
    def build_comparison(
        reports: List[HplcReport],
        rt_tolerance: float = 0.05,
        target_main_rt: Optional[float] = None,
        target_wavelength: Optional[int] = None,
        rrf_map: Optional[Dict[float, float]] = None
    ) -> ComparisonResult:
        rrf_map = rrf_map or {}

        # 1. Available Wavelengths
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

        # 3. Cluster RTs
        ref_rts: List[float] = []
        for p_list in filtered_peaks.values():
            for p in p_list:
                if not any(abs(p.retention_time - ref) <= rt_tolerance for ref in ref_rts):
                    ref_rts.append(p.retention_time)
        ref_rts.sort()

        # 4. Resolve Main Peak
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
                tot_area = 0.0
                count = 0
                for r in reports:
                    for p in filtered_peaks[r.file_name]:
                        if abs(p.retention_time - rt) <= rt_tolerance:
                            tot_area += p.percent_area
                            count += 1
                            break
                avg_area = (tot_area / len(reports)) if reports else 0.0
                if avg_area > max_avg_area:
                    max_avg_area = avg_area
                    best_rt = rt
            main_peak_rt = best_rt

        # 5. Build Headers
        sample_headers = []
        for r in reports:
            label = r.sample_name or r.file_name
            if r.batch_id:
                label += f" ({r.batch_id})"
            if r.cds_source != "GENERIC":
                label += f" [{r.cds_source.replace('_', ' ')}]"
            sample_headers.append(label)

        # 6. Aligned Rows
        rows: List[AlignedPeakRow] = []
        for rt in ref_rts:
            is_main = abs(rt - main_peak_rt) <= rt_tolerance
            rrt = round(rt / main_peak_rt, 3) if main_peak_rt > 0 else 1.0

            rrf = 1.0
            if not is_main:
                for k_rt, k_rrf in rrf_map.items():
                    if abs(k_rt - rt) <= rt_tolerance:
                        rrf = k_rrf if k_rrf > 0 else 1.0
                        break

            peak_name = "Main Peak (API)" if is_main else "Unknown"
            for p_list in filtered_peaks.values():
                for p in p_list:
                    if abs(p.retention_time - rt) <= rt_tolerance and p.name.lower() != "unknown":
                        peak_name = p.name
                        break

            raw_areas = {}
            for i, r in enumerate(reports):
                header = sample_headers[i]
                match = next((p for p in filtered_peaks[r.file_name] if abs(p.retention_time - rt) <= rt_tolerance), None)
                raw_areas[header] = f"{match.percent_area:.3f}" if match else "ND"

            rows.append(AlignedPeakRow(
                rt=round(rt, 3),
                rrt=rrt,
                rrf=rrf,
                peak_name=peak_name,
                is_main_peak=is_main,
                sample_areas=raw_areas,
                corrected_sample_areas={}
            ))

        # 7. Apply RRF Corrections: % w/w
        for header in sample_headers:
            sum_corr_area = 0.0
            for row in rows:
                v = row.sample_areas.get(header, "ND")
                if v != "ND":
                    sum_corr_area += (float(v) / row.rrf)

            for row in rows:
                v = row.sample_areas.get(header, "ND")
                if v == "ND":
                    row.corrected_sample_areas[header] = "ND"
                else:
                    raw_val = float(v)
                    corr_val = ((raw_val / row.rrf) / sum_corr_area * 100.0) if sum_corr_area > 0 else raw_val
                    row.corrected_sample_areas[header] = f"{corr_val:.3f}"

        # 8. Totals
        total_impurities = {}
        corr_total_impurities = {}
        mass_balance = {}

        for header in sample_headers:
            raw_imp = 0.0
            corr_imp = 0.0
            total_mass = 0.0
            for row in rows:
                raw_v = row.sample_areas.get(header, "ND")
                corr_v = row.corrected_sample_areas.get(header, "ND")
                if raw_v != "ND":
                    r_f = float(raw_v)
                    c_f = float(corr_v)
                    total_mass += c_f
                    if not row.is_main_peak:
                        raw_imp += r_f
                        corr_imp += c_f

            total_impurities[header] = f"{raw_imp:.3f}"
            corr_total_impurities[header] = f"{corr_imp:.3f}"
            mass_balance[header] = f"{total_mass:.3f}"

        return ComparisonResult(
            sample_headers=sample_headers,
            main_peak_rt=round(main_peak_rt, 3),
            active_wavelength=active_wavelength,
            available_wavelengths=available_wl_list,
            rows=rows,
            total_impurities=total_impurities,
            corrected_total_impurities=corr_total_impurities,
            mass_balance=mass_balance
        )
