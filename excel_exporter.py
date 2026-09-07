import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from comparator import BatchComparisonResult


class ExcelExporter:

    @staticmethod
    def generate(res: BatchComparisonResult) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Impurity Comparison"
        ws.views.sheetView[0].showGridLines = True

        font_header_title = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_subhead = Font(name="Calibri", size=10, bold=True, color="1E293B")
        font_bold = Font(name="Calibri", size=10, bold=True)
        font_regular = Font(name="Calibri", size=10)

        fill_navy = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        fill_sub = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

        fill_api = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        font_api = Font(name="Calibri", size=10, bold=True, color="166534")

        fill_ident = PatternFill(start_color="FED7AA", end_color="FED7AA", fill_type="solid")
        font_ident = Font(name="Calibri", size=10, bold=True, color="9A3412")

        fill_rep = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
        font_rep = Font(name="Calibri", size=10, bold=True, color="854D0E")

        b_thin = Side(border_style="thin", color="CBD5E1")
        b_dark = Side(border_style="thin", color="64748B")
        border_all = Border(left=b_thin, right=b_thin, top=b_thin, bottom=b_thin)
        border_header = Border(left=b_thin, right=b_thin, top=b_dark, bottom=b_dark)

        ws.freeze_panes = "D4"

        ws.merge_cells("A1:A3")
        ws.cell(row=1, column=1, value="Sr. No.").alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.merge_cells("B1:B3")
        ws.cell(row=1, column=2, value="Batch No. / Injection Name").alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.cell(row=1, column=3, value="Name of Impurity").alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=2, column=3, value="RT (min)").alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=3, column=3, value="RRT").alignment = Alignment(horizontal="center", vertical="center")

        start_col = 4
        num_peaks = len(res.master_columns)

        for i, col in enumerate(res.master_columns):
            c_idx = start_col + i
            ws.cell(row=1, column=c_idx, value=col.peak_name or "")

            c_rt = ws.cell(row=2, column=c_idx, value=col.rt)
            c_rt.number_format = "0.000"

            c_rrt = ws.cell(row=3, column=c_idx, value=col.rrt)
            c_rrt.number_format = "0.000"

        for c in range(1, start_col + num_peaks):
            c1 = ws.cell(row=1, column=c)
            c1.font = font_header_title
            c1.fill = fill_navy
            c1.border = border_header
            c1.alignment = Alignment(horizontal="center", vertical="center")

            for r in [2, 3]:
                cell = ws.cell(row=r, column=c)
                cell.font = font_subhead
                cell.fill = fill_sub
                cell.border = border_header
                cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, b_row in enumerate(res.batch_rows, start=4):
            is_even = (r_idx % 2 == 0)
            row_base_fill = fill_zebra if is_even else fill_white

            c_sr = ws.cell(row=r_idx, column=1, value=b_row["Sr. No."])
            c_sr.alignment = Alignment(horizontal="center", vertical="center")
            c_sr.font = font_bold
            c_sr.fill = row_base_fill
            c_sr.border = border_all

            c_b = ws.cell(row=r_idx, column=2, value=b_row["Batch No."])
            c_b.alignment = Alignment(horizontal="left", vertical="center")
            c_b.font = font_bold
            c_b.fill = row_base_fill
            c_b.border = border_all

            c_blank = ws.cell(row=r_idx, column=3, value="")
            c_blank.fill = row_base_fill
            c_blank.border = border_all

            for i, col in enumerate(res.master_columns):
                c_idx = start_col + i
                val = b_row.get(col.rrt, "")
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.border = border_all

                if val != "":
                    num_val = float(val)
                    cell.value = num_val
                    cell.number_format = "0.00" if num_val != 0 else "0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                    if col.is_main_peak:
                        cell.fill = fill_api
                        cell.font = font_api
                    elif num_val >= 0.10:
                        cell.fill = fill_ident
                        cell.font = font_ident
                    elif num_val >= 0.05:
                        cell.fill = fill_rep
                        cell.font = font_rep
                    else:
                        cell.fill = row_base_fill
                        cell.font = font_regular
                else:
                    cell.value = ""
                    cell.fill = row_base_fill

        ws.column_dimensions["A"].width = 9
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 18
        for i in range(num_peaks):
            col_letter = openpyxl.utils.get_column_letter(start_col + i)
            ws.column_dimensions[col_letter].width = 11

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
