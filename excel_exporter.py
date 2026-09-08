import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from comparator import VerticalComparisonResult


class ExcelExporter:

    @staticmethod
    def generate(res: VerticalComparisonResult) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Vertical Impurity Matrix"
        ws.views.sheetView[0].showGridLines = True

        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_bold = Font(name="Calibri", size=10, bold=True)
        font_regular = Font(name="Calibri", size=10)

        fill_navy = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        fill_summary = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

        fill_api = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        font_api = Font(name="Calibri", size=10, bold=True, color="166534")

        fill_ident = PatternFill(start_color="FED7AA", end_color="FED7AA", fill_type="solid")
        font_ident = Font(name="Calibri", size=10, bold=True, color="9A3412")

        fill_rep = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
        font_rep = Font(name="Calibri", size=10, bold=True, color="854D0E")

        b_thin = Side(border_style="thin", color="CBD5E1")
        b_dark = Side(border_style="medium", color="64748B")
        border_all = Border(left=b_thin, right=b_thin, top=b_thin, bottom=b_thin)
        border_summary = Border(left=b_thin, right=b_thin, top=b_dark, bottom=b_dark)

        # Freeze headers and row descriptions (Columns A-D and Row 1)
        ws.freeze_panes = "E2"

        headers = ["Sr. No.", "Name of Impurity", "Mean RT (min)", "RRT"] + res.batch_names
        ws.append(headers)

        for c_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=c_idx)
            cell.font = font_header
            cell.fill = fill_navy
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_all
        ws.row_dimensions[1].height = 28

        curr_row = 2
        for item in res.rows:
            is_even = (curr_row % 2 == 0)
            base_fill = fill_zebra if is_even else fill_white

            ws.cell(row=curr_row, column=1, value=item.sr_no).alignment = Alignment(horizontal="center")
            ws.cell(row=curr_row, column=2, value=item.name).alignment = Alignment(horizontal="left")

            c_rt = ws.cell(row=curr_row, column=3, value=item.mean_rt)
            c_rt.number_format = "0.000"
            c_rt.alignment = Alignment(horizontal="right")

            c_rrt = ws.cell(row=curr_row, column=4, value=item.rrt)
            c_rrt.number_format = "0.000"
            c_rrt.alignment = Alignment(horizontal="right")

            for c in range(1, 5):
                ws.cell(row=curr_row, column=c).border = border_all
                ws.cell(row=curr_row, column=c).font = font_bold if item.is_main else font_regular
                ws.cell(row=curr_row, column=c).fill = base_fill

            for b_idx, b_name in enumerate(res.batch_names, start=5):
                val = item.batch_values.get(b_name, "")
                cell = ws.cell(row=curr_row, column=b_idx)
                cell.border = border_all

                if val != "":
                    num_val = float(val)
                    cell.value = num_val
                    cell.number_format = "0.00" if num_val != 0 else "0"
                    cell.alignment = Alignment(horizontal="right")

                    if item.is_main:
                        cell.fill = fill_api
                        cell.font = font_api
                    elif num_val >= 0.10:
                        cell.fill = fill_ident
                        cell.font = font_ident
                    elif num_val >= 0.05:
                        cell.fill = fill_rep
                        cell.font = font_rep
                    else:
                        cell.fill = base_fill
                        cell.font = font_regular
                else:
                    cell.value = ""
                    cell.fill = base_fill

            curr_row += 1

        for s_row in res.summary_rows:
            ws.cell(row=curr_row, column=1, value="").border = border_summary
            ws.cell(row=curr_row, column=1).fill = fill_summary

            c_lbl = ws.cell(row=curr_row, column=2, value=s_row["Name of Impurity"])
            c_lbl.font = font_bold
            c_lbl.alignment = Alignment(horizontal="left")
            c_lbl.border = border_summary
            c_lbl.fill = fill_summary

            ws.cell(row=curr_row, column=3, value=s_row["Mean RT (min)"]).alignment = Alignment(horizontal="center")
            ws.cell(row=curr_row, column=3).border = border_summary
            ws.cell(row=curr_row, column=3).fill = fill_summary

            ws.cell(row=curr_row, column=4, value=s_row["RRT"]).alignment = Alignment(horizontal="center")
            ws.cell(row=curr_row, column=4).border = border_summary
            ws.cell(row=curr_row, column=4).fill = fill_summary

            for b_idx, b_name in enumerate(res.batch_names, start=5):
                c_val = ws.cell(row=curr_row, column=b_idx, value=s_row[b_name])
                c_val.font = font_bold
                c_val.number_format = "0.00"
                c_val.alignment = Alignment(horizontal="right")
                c_val.border = border_summary
                c_val.fill = fill_summary

            curr_row += 1

        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 25
        ws.column_dimensions["C"].width = 15
        ws.column_dimensions["D"].width = 12

        for i in range(len(res.batch_names)):
            col_letter = get_column_letter(5 + i)
            ws.column_dimensions[col_letter].width = 22

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
