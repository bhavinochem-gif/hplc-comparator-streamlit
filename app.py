import pandas as pd
import streamlit as st

from comparator import HplcComparator
from excel_exporter import ExcelExporter
from parser import HplcPdfParser

st.set_page_config(page_title="HPLC Batch Impurity Matrix Comparator", layout="wide")

st.title("📊 HPLC Batch-wise Impurity Matrix Comparator")
st.markdown("Upload multiple HPLC PDF reports to automatically align retention times and generate the exact matrix spreadsheet layout.")

uploaded_files = st.file_uploader(
    "Upload HPLC PDF Reports",
    type=["pdf"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("Upload 2 or more HPLC PDF reports to generate the comparison matrix.")
    st.stop()

parser = HplcPdfParser()
reports = []
for f in uploaded_files:
    content = f.read()
    rep = parser.parse(content, f.name)
    reports.append(rep)

all_detected_wl = set()
for r in reports:
    all_detected_wl.update(r.detected_wavelengths)
available_wl_list = sorted(list(all_detected_wl))

col1, col2, col3 = st.columns([1, 1, 1.2])
with col1:
    tolerance = st.slider("RT Tolerance Window (± min)", min_value=0.01, max_value=0.20, value=0.05, step=0.01)

with col2:
    wl_options = ["All Channels"] + [f"{wl} nm" for wl in available_wl_list]
    selected_wl_label = st.selectbox("DAD/PDA Channel", options=wl_options, index=0)
    selected_wl = int(selected_wl_label.replace(" nm", "")) if selected_wl_label != "All Channels" else None

# Preview to get candidate RTs
preview = HplcComparator.build_horizontal_matrix(
    reports=reports,
    rt_tolerance=tolerance,
    target_main_rt=None,
    target_wavelength=selected_wl
)
candidate_rts = [col.rt for col in preview.master_columns]

with col3:
    auto_idx = next((i for i, col in enumerate(preview.master_columns) if col.is_main_peak), 0)
    selected_main_rt = st.selectbox(
        "Designate Main API Peak RT (min)",
        options=candidate_rts,
        index=auto_idx,
        format_func=lambda x: f"{x:.3f} min (API)" if any(c.rt == x and c.is_main_peak for c in preview.master_columns) else f"{x:.3f} min"
    )

# Final Matrix Build
matrix_result = HplcComparator.build_horizontal_matrix(
    reports=reports,
    rt_tolerance=tolerance,
    target_main_rt=selected_main_rt,
    target_wavelength=selected_wl
)

# Build Display DataFrame
table_headers = ["Sr. No.", "Batch No.", "Injection Name"] + [f"{col.peak_name}\nRT: {col.rt}\nRRT: {col.rrt}" for col in matrix_result.master_columns]
display_rows = []
for row in matrix_result.batch_rows:
    r_list = [row["Sr. No."], row["Batch No."], row["Injection Name"]]
    for col in matrix_result.master_columns:
        r_list.append(row.get(col.rt, ""))
    display_rows.append(r_list)

df_matrix = pd.DataFrame(display_rows, columns=table_headers)

st.subheader("Comparative Impurity Matrix")
st.dataframe(df_matrix, use_container_width=True, hide_index=True)

# Export to Excel
excel_bytes = ExcelExporter.generate(matrix_result)
st.download_button(
    label="📥 Download Horizontal Matrix Spreadsheet (.xlsx)",
    data=excel_bytes,
    file_name="HPLC_Batch_Impurity_Matrix.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
