from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import numpy as np
from parser import HplcReport, Peak


@dataclass
class MasterImpurityRow:
    sr_no: int
    name: str
    mean_rt: float
    rrt: float
    is_main: bool
    batch_values: Dict[str, any]


@dataclass
class VerticalComparisonResult:
    rows: List[MasterImpurityRow]
    summary_rows: List[Dict[str, any]]
    batch_names: List[str]
    active_wavelength: Optional[int]
    available_wavelengths: List[int]
    main_peak_rts: Dict[str, float]


class HplcComparator:

    @classmethod
    def build_vertical_matrix(
        cls,
        reports: List[HplcReport],
        rrt_tolerance: float = 0.015,
        target_main_rt: Optional[float] = None,
        target_wavelength: Optional[int] = None,
        custom_specs: Optional[List[Dict[str, any]]] = None
    ) -> VerticalComparisonResult:
        all_wl: Set[int] = set()
        for r in reports:
            all_wl.update(r.detected_wavelengths)
        available_wl_list = sorted(list(all_wl))

        active_wavelength = (
            target_wavelength
            if target_wavelength and target_wavelength > 0
            else (available_wl_list[0] if available_wl_list else None)
        )

        batch_names: List[str] = [r.batch_id for r in reports]

        report_main_rts: Dict[str, float] = {}
        report_peaks_rrt: Dict[str, List[tuple]] = {}

        for r in reports:
            p_list = [
                p for p in r.peaks
                if active_wavelength is None or p.wavelength == 0 or p.wavelength == active_wavelength
            ]
            if not p_list:
                report_main_rts[r.batch_id] = 0.0
                report_peaks_rrt[r.batch_id] = []
                continue

            if target_main_rt and target_main_rt > 0:
                main_rt = min(p_list, key=lambda p: abs(p.retention_time - target_main_rt)).retention_time
            else:
                main_rt = max(p_list, key=lambda p: p.percent_area).retention_time
            report_main_rts[r.batch_id] = main_rt

            rrt_items = []
            for p in p_list:
                if p.rel_rt is not None and p.rel_rt > 0:
                    c_rrt = round(p.rel_rt, 3)
                elif main_rt > 0:
                    c_rrt = round(p.retention_time / main_rt, 3)
                else:
                    c_rrt = 1.0
                rrt_items.append((p, c_rrt))
            report_peaks_rrt[r.batch_id] = rrt_items

        clustered_rows: List[Dict[str, any]] = []

        for b_name in batch_names:
            for p, p_rrt in report_peaks_rrt[b_name]:
                matched = None
                best_diff = 999.0
                for item in clustered_rows:
                    diff = abs(item["rrt"] - p_rrt)
                    if diff <= rrt_tolerance and diff < best_diff:
                        best_diff = diff
                        matched = item

                if matched:
                    matched["rts"].append(p.retention_time)
                    matched["rrts"].append(p_rrt)
                    if (not matched["name"] or matched["name"] == "Unk") and p.name != "Unk":
                        matched["name"] = p.name
                else:
                    is_main = abs(p_rrt - 1.0) <= 0.008
                    clustered_rows.append({
                        "rrt": p_rrt,
                        "rts": [p.retention_time],
                        "rrts": [p_rrt],
                        "name": p.name,
                        "is_main": is_main
                    })

        clustered_rows.sort(key=lambda x: x["rrt"])

        final_rows: List[MasterImpurityRow] = []

        for idx, item in enumerate(clustered_rows, start=1):
            mean_rt = float(np.mean(item["rts"]))
            mean_rrt = float(np.mean(item["rrts"]))

            if item["is_main"]:
                mean_rrt = 1.000

            resolved_name = item["name"]
            if custom_specs:
                for spec in custom_specs:
                    if spec["rrt_min"] <= mean_rrt <= spec["rrt_max"]:
                        resolved_name = spec["name"]
                        break

            if item["is_main"] and (not resolved_name or resolved_name == "Unk"):
                resolved_name = "RIM (Main API)"

            b_values: Dict[str, any] = {}
            for b_name in batch_names:
                p_items = report_peaks_rrt.get(b_name, [])
                best_match = None
                best_d = 999.0
                for p, p_rrt in p_items:
                    d = abs(p_rrt - mean_rrt)
                    if d <= rrt_tolerance and d < best_d:
                        best_d = d
                        best_match = p

                if best_match:
                    b_values[b_name] = 0.0 if best_match.percent_area == 0.0 else best_match.percent_area
                else:
                    b_values[b_name] = ""

            final_rows.append(MasterImpurityRow(
                sr_no=idx,
                name=resolved_name,
                mean_rt=round(mean_rt, 3),
                rrt=round(mean_rrt, 3),
                is_main=item["is_main"],
                batch_values=b_values
            ))

        total_imp = {"Name of Impurity": "Total Impurities (%)", "Mean RT (min)": "-", "RRT": "-"}
        main_assay = {"Name of Impurity": "Main Peak / Assay (%)", "Mean RT (min)": "-", "RRT": "1.000"}
        total_area = {"Name of Impurity": "Total Area (%)", "Mean RT (min)": "-", "RRT": "-"}

        for b_name in batch_names:
            imp_sum = 0.0
            api_val = 0.0
            for r in final_rows:
                v = r.batch_values.get(b_name, "")
                if v != "" and v is not None:
                    try:
                        num = float(v)
                        if r.is_main:
                            api_val += num
                        else:
                            imp_sum += num
                    except ValueError:
                        pass
            total_imp[b_name] = round(imp_sum, 2)
            main_assay[b_name] = round(api_val, 2)
            total_area[b_name] = round(imp_sum + api_val, 2)

        summary_rows = [total_imp, main_assay, total_area]

        return VerticalComparisonResult(
            rows=final_rows,
            summary_rows=summary_rows,
            batch_names=batch_names,
            active_wavelength=active_wavelength,
            available_wavelengths=available_wl_list,
            main_peak_rts=report_main_rts
        )
