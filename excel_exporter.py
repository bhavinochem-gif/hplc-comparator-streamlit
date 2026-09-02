import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from comparator import ComparisonResult


class ExcelExporter:

    @staticmethod
    def generate(res: ComparisonResult) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "HPLC Summary"

        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_bold = Font(name="Calibri", size=11, bold=True)
        font_regular = Font(name="Calibri", size=11)
        font_nd = Font(name="Calibri", size=11, italic=True, color="808080")

        fill_header = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        fill_main = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        fill_rep = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")      # >= 0.05%
        fill_ident = PatternFill(start_color="FED7AA", end_color="FED7AA", fill_type="solid")    # >= 0.10%
        fill_sum_imp = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        fill_sum_mb = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")

        b_thin = Side(border_style="thin", color="CBD5E1")
        b_double = Side(border_style="double", color="334155")
        b_medium = Side(border_style="medium", color="64748B")

        std_b = Border(left=b_thin, right=b_thin, top=b_thin, bottom=b_thin)
        imp_b = Border(left=b_thin, right=b_thin, top=b_medium, bottom=b_thin)
        mb_b = Border(left=b_thin, right=b_thin, top=b_thin, bottom=b_double)

        wl_txt = f"{res.active_wavelength} nm" if res.active_wavelength else "All"
        ws.cell(row=1, column=1, value=f"DAD/PDA Channel: {wl_txt} | Ref API RT: {res.main_peak_rt:.3f} min | Quantitation: RRF Corrected % w/w").font = font_bold

        headers = ["Peak RT (min)", "RRT", "RRF", "Peak Name"] + [f"{h} [% w/w]" for h in res.sample_headers]
        for c_idx, h_text in enumerate(headers, start=1):
            c = ws.cell(row=2, column=c_idx, value=h_text)
            c.font = font_header
            c.fill = fill_header
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = std_b

        row_idx = 3
        for r_data in res.rows:
            is_main = r_data.is_main_peak

            c_rt = ws.cell(row=row_idx, column=1, value=r_data.rt)
            c_rrt = ws.cell(row=row_idx, column=2, value=r_data.rrt)
            c_rrf = ws.cell(row=row_idx, column=3, value=r_data.rrf)
            c_name = ws.cell(row=row_idx, column=4, value=r_data.peak_name)

            for c in [c_rt, c_rrt, c_rrf]:
                c.number_format = "0.000"
                c.alignment = Alignment(horizontal="right")
                c.font = font_bold if is_main else font_regular
                c.border = std_b
                if is_main:
                    c.fill = fill_main

            c_name.font = font_bold if is_main else font_regular
            c_name.border = std_b
            if is_main:
                c_name.fill = fill_main

            for s_idx, header in enumerate(res.sample_headers, start=5):
                val_str = r_data.corrected_sample_areas.get(header, "ND")
                cell = ws.cell(row=row_idx, column=s_idx)
                cell.border = std_b

                if val_str == "ND":
                    cell.value = "ND"
                    cell.font = font_nd
                    cell.alignment = Alignment(horizontal="center")
                else:
                    f_val = float(val_str)
                    cell.value = f_val
                    cell.number_format = "0.000"
                    cell.alignment = Alignment(horizontal="right")
                    if is_main:
                        cell.fill = fill_main
                        cell.font = font_bold
                    elif f_val >= 0.10:
                        cell.fill = fill_ident
                        cell.font = font_bold
                    elif f_val >= 0.05:
                        cell.fill = fill_rep
                        cell.font = font_bold
                    else:
                        cell.font = font_regular

            row_idx += 1

        # Summary Footers
        ws.cell(row=row_idx, column=1, value="Raw Total Impurities (%)").font = font_bold
        for col in range(1, 5):
            ws.cell(row=row_idx, column=col).fill = fill_sum_imp
            ws.cell(row=row_idx, column=col).border = imp_b
        for s_idx, h in enumerate(res.sample_headers, start=5):
            c = ws.cell(row=row_idx, column=s_idx, value=float(res.total_impurities.get(h, 0.0)))
            c.font = font_bold
            c.fill = fill_sum_imp
            c.number_format = "0.000"
            c.border = imp_b
            c.alignment = Alignment(horizontal="right")
        row_idx += 1

        ws.cell(row=row_idx, column=1, value="RRF-Corrected Total Impurities (% w/w)").font = font_bold
        for col in range(1, 5):
            ws.cell(row=row_idx, column=col).fill = fill_sum_imp
            ws.cell(row=row_idx, column=col).border = std_b
        for s_idx, h in enumerate(res.sample_headers, start=5):
            c = ws.cell(row=row_idx, column=s_idx, value=float(res.corrected_total_impurities.get(h, 0.0)))
            c.font = font_bold
            c.fill = fill_sum_imp
            c.number_format = "0.000"
            c.border = std_b
            c.alignment = Alignment(horizontal="right")
        row_idx += 1

        ws.cell(row=row_idx, column=1, value="Mass Balance / Total Area (%)").font = font_bold
        for col in range(1, 5):
            ws.cell(row=row_idx, column=col).fill = fill_sum_mb
            ws.cell(row=row_idx, column=col).border = mb_b
        for s_idx, h in enumerate(res.sample_headers, start=5):
            c = ws.cell(row=row_idx, column=s_idx, value=float(res.mass_balance.get(h, 0.0)))
            c.font = font_bold
            c.fill = fill_sum_mb
            c.number_format = "0.000"
            c.border = mb_b
            c.alignment = Alignment(horizontal="right")

        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
