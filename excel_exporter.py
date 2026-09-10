import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from comparator import ComparisonResult


class ExcelExporter:

    @staticmethod
    def generate(res: ComparisonResult) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "HPLC Comparison"
        ws.views.sheetView[0].showGridLines = True

        font_bold = Font(name="Calibri", size=10, bold=True)
        font_regular = Font(name="Calibri", size=10)

        fill_api = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")      # Mint Green
        fill_ident = PatternFill(start_color="FED7AA", end_color="FED7AA", fill_type="solid")    # Orange (>= 0.10%)
        fill_rep = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")      # Yellow (>= 0.05%)

        b_thin = Side(border_style="thin", color="000000")
        border_all = Border(left=b_thin, right=b_thin, top=b_thin, bottom=b_thin)

        # Row 1: Merged 'Batch No.' (A1:C1) and Batch Headers (D1, E1, ...)
        ws.merge_cells("A1:C1")
        cell_batch_lbl = ws.cell(row=1, column=1, value="Batch No.")
        cell_batch_lbl.alignment = Alignment(horizontal="center", vertical="center")
        cell_batch_lbl.font = font_bold

        for c in range(1, 4):
            ws.cell(row=1, column=c).border = border_all

        for idx, b_name in enumerate(res.batch_names, start=4):
            c_hdr = ws.cell(row=1, column=idx, value=b_name)
            c_hdr.alignment = Alignment(horizontal="center", vertical="center")
            c_hdr.font = font_bold
            c_hdr.border = border_all

        # Row 2: Sub-headers matching Image 2
        ws.cell(row=2, column=1, value="Peak name").alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=2, column=2, value="Ret.Time").alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=2, column=3, value="Rel.Ret.Time").alignment = Alignment(horizontal="center", vertical="center")

        for c in range(1, 4):
            ws.cell(row=2, column=c).font = font_bold
            ws.cell(row=2, column=c).border = border_all

        for idx in range(4, 4 + len(res.batch_names)):
            c_sub = ws.cell(row=2, column=idx, value="Area %")
            c_sub.alignment = Alignment(horizontal="center", vertical="center")
            c_sub.font = font_bold
            c_sub.border = border_all

        # Rows 3+: Data rows
        curr_row = 3
        for item in res.rows:
            # Col 1: Peak Name
            c_name = ws.cell(row=curr_row, column=1, value=item.name)
            c_name.alignment = Alignment(horizontal="left", vertical="center")
            c_name.font = font_bold if item.is_main else font_regular
            c_name.border = border_all

            # Col 2: Ret.Time
            try:
                rt_val = float(item.rt_str)
                c_rt = ws.cell(row=curr_row, column=2, value=rt_val)
                c_rt.number_format = "0.000" if len(item.rt_str.split('.')[-1]) > 2 else "0.00"
            except ValueError:
                c_rt = ws.cell(row=curr_row, column=2, value=item.rt_str)
            c_rt.alignment = Alignment(horizontal="center", vertical="center")
            c_rt.font = font_bold if item.is_main else font_regular
            c_rt.border = border_all

            # Col 3: Rel.Ret.Time
            try:
                rrt_val = float(item.rrt_str)
                c_rrt = ws.cell(row=curr_row, column=3, value=rrt_val)
                c_rrt.number_format = "0.000"
            except ValueError:
                c_rrt = ws.cell(row=curr_row, column=3, value=item.rrt_str)
            c_rrt.alignment = Alignment(horizontal="center", vertical="center")
            c_rrt.font = font_bold if item.is_main else font_regular
            c_rrt.border = border_all

            # Col 4+: Batch Area %
            for b_idx, b_name in enumerate(res.batch_names, start=4):
                val = item.batch_values.get(b_name, "")
                cell = ws.cell(row=curr_row, column=b_idx)
                cell.border = border_all

                if val != "":
                    num = float(val)
                    cell.value = num
                    cell.number_format = "0.00" if num != 0 else "0"
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                    # Apply Color Fills
                    if item.is_main:
                        cell.fill = fill_api
                        cell.font = font_bold
                    elif num >= 0.10:
                        cell.fill = fill_ident
                        cell.font = font_bold
                    elif num >= 0.05:
                        cell.fill = fill_rep
                        cell.font = font_bold
                    else:
                        cell.font = font_regular
                else:
                    cell.value = ""

            curr_row += 1

        # Column widths
        ws.column_dimensions["A"].width = 16
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 14

        for i in range(len(res.batch_names)):
            col_letter = get_column_letter(4 + i)
            ws.column_dimensions[col_letter].width = 24

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
