from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from parser import HplcReport, Peak


@dataclass
class MatrixRow:
    name: str
    rt_str: str
    rrt_str: str
    rrt_numeric: float
    is_main: bool
    batch_values: Dict[str, any]


@dataclass
class ComparisonResult:
    batch_names: List[str]
    rows: List[MatrixRow]


class HplcComparator:

    @classmethod
    def build_comparison(
        cls,
        reports: List[HplcReport],
        rrt_tolerance: float = 0.010
    ) -> ComparisonResult:
        # Enforce unique batch headers
        batch_names: List[str] = []
        for r in reports:
            b_id = r.batch_id or r.file_name.replace(".pdf", "")
            if b_id in batch_names:
                cnt = 2
                while f"{b_id}_{cnt}" in batch_names:
                    cnt += 1
                b_id = f"{b_id}_{cnt}"
            batch_names.append(b_id)

        # Map each batch's peaks with calculated RRT fallback
        batch_peaks: Dict[str, List[tuple]] = {}
        for b_name, rep in zip(batch_names, reports):
            if not rep.peaks:
                batch_peaks[b_name] = []
                continue

            # API main peak (peak with highest % area, typically > 90%)
            main_peak = max(rep.peaks, key=lambda p: p.percent_area)
            main_rt = main_peak.retention_time

            items = []
            for p in rep.peaks:
                if p.rel_rt is not None and p.rel_rt > 0:
                    rrt_val = round(p.rel_rt, 3)
                elif main_rt > 0:
                    rrt_val = round(p.retention_time / main_rt, 3)
                else:
                    rrt_val = 1.0
                items.append((p, rrt_val))
            batch_peaks[b_name] = items

        # Cluster master peaks across all uploaded batches
        master_clusters: List[Dict[str, any]] = []

        for b_name in batch_names:
            for p, rrt_val in batch_peaks[b_name]:
                match = None
                best_diff = 999.0
                for c in master_clusters:
                    diff = abs(c["rrt"] - rrt_val)
                    if diff <= rrt_tolerance and diff < best_diff:
                        best_diff = diff
                        match = c

                if match:
                    match["rts"].append(p.retention_time)
                    match["rrts"].append(rrt_val)
                    if not match["name"] and p.name:
                        match["name"] = p.name
                else:
                    is_main = abs(rrt_val - 1.0) <= 0.008 or p.name.upper() == "RIM"
                    master_clusters.append({
                        "rrt": rrt_val,
                        "rts": [p.retention_time],
                        "rrts": [rrt_val],
                        "name": p.name,
                        "is_main": is_main
                    })

        # Sort rows ascending by RRT
        master_clusters.sort(key=lambda x: x["rrt"])

        final_rows: List[MatrixRow] = []

        for item in master_clusters:
            mean_rt = float(np.mean(item["rts"]))
            mean_rrt = float(np.mean(item["rrts"]))

            if item["is_main"]:
                mean_rrt = 1.000

            # Match values for each batch column
            b_vals: Dict[str, any] = {}
            for b_name in batch_names:
                best_p = None
                best_d = 999.0
                for p, p_rrt in batch_peaks[b_name]:
                    d = abs(p_rrt - mean_rrt)
                    if d <= rrt_tolerance and d < best_d:
                        best_d = d
                        best_p = p

                if best_p:
                    # In Image 2, 0.00% is displayed as 0
                    b_vals[b_name] = 0 if best_p.percent_area == 0.0 else best_p.percent_area
                else:
                    b_vals[b_name] = ""

            final_rows.append(MatrixRow(
                name=item["name"],
                rt_str=f"{mean_rt:.3f}".rstrip('0').rstrip('.') if f"{mean_rt:.3f}".endswith('0') else f"{mean_rt:.3f}",
                rrt_str=f"{mean_rrt:.3f}",
                rrt_numeric=mean_rrt,
                is_main=item["is_main"],
                batch_values=b_vals
            ))

        return ComparisonResult(batch_names=batch_names, rows=final_rows)
