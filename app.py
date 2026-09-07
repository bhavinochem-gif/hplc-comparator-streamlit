import pandas as pd
import streamlit as st

from comparator import HplcComparator
from excel_exporter import ExcelExporter
from parser import HplcPdfParser

st.set_page_config(page_title="HPLC Batch Impurity Matrix Comparator", layout="wide")

st.title("🔬 HPLC Batch-wise Impurity Matrix Comparator")
st.markdown("Automate comparative analytical impurity profiling across multiple batches with dynamic column detection and incremental Excel merging.")

col_up1, col_up2 = st.columns([1, 1])

with col_up1:
    existing_excel_file = st.file_uploader(
        "📂 (Optional) Upload Existing Comparison Matrix (.xlsx)",
        type=["xlsx"],
        help="Upload an existing HPLC comparison spreadsheet to append new PDF data into the same workbook."
    )

with col_up2:
    new_pdf_files = st.file_uploader(
        "📄 Upload New HPLC PDF Reports (Waters, Chromeleon, Agilent, Shimadzu)",
        type=["pdf"],
        accept_multiple_files=True
    )

if not existing_excel_file and not new_pdf_files:
    st.info("Upload new HPLC PDF reports, or upload an existing Excel matrix to append more batches.")
    st.stop()

parser = HplcPdfParser()
new_reports = []
if new_pdf_files:
    for f in new_pdf_files:
        content = f.read()
        rep = parser.parse(content, f.name)
        new_reports.append(rep)

with st.expander("🔍 Extraction Log & Ingested Files Status", expanded=False):
    if existing_excel_file:
        st.info(f"Loaded existing comparison workbook: **{existing_excel_file.name}**")
    for r in new_reports:
        if len(r.peaks) > 0:
            st.success(f"**{r.file_name}** — Injected: `{r.sample_name}` | Batch: `{r.batch_id}` | Software: `{r.cds_source}` | Peaks: **{len(r.peaks)}**")
        else:
            st.error(f"**{r.file_name}** — ⚠️ 0 peaks detected. Ensure it is a vector digital PDF.")

col1, col2, col3 = st.columns([1, 1, 1.2])

all_detected_wl = set()
for r in new_reports:
    all_detected_wl.update(r.detected_wavelengths)
available_wl_list = sorted(list(all_detected_wl))

with col1:
    rrt_tolerance = st.slider(
        "RRT Tolerance Window (± RRT)",
        min_value=0.002,
        max_value=0.030,
        value=0.010,
        step=0.001,
        format="%.3f"
    )

with col2:
    wl_options = ["All Channels"] + [f"{wl} nm" for wl in available_wl_list]
    selected_wl_label = st.selectbox("DAD/PDA Channel", options=wl_options, index=0)
    selected_wl = int(selected_wl_label.replace(" nm", "")) if selected_wl_label != "All Channels" else None

excel_bytes_input = existing_excel_file.read() if existing_excel_file else None

preview = HplcComparator.build_or_merge_matrix(
    new_reports=new_reports,
    existing_excel_bytes=excel_bytes_input,
    rrt_tolerance=rrt_tolerance,
    target_main_rt=None,
    target_wavelength=selected_wl
)

# Filter candidate RTs to positive non-zero values
raw_candidates = set(preview.main_peak_rts.values()) if preview.main_peak_rts else set()
candidate_rts = sorted([x for x in raw_candidates if x > 0])
if not candidate_rts:
    candidate_rts = [16.366]

with col3:
    selected_main_rt = st.selectbox(
        "Reference API Main Peak RT (min)",
        options=candidate_rts,
        index=0,
        format_func=lambda x: f"~{x:.3f} min (API)"
    )

matrix_result = HplcComparator.build_or_merge_matrix(
    new_reports=new_reports,
    existing_excel_bytes=excel_bytes_input,
    rrt_tolerance=rrt_tolerance,
    target_main_rt=selected_main_rt,
    target_wavelength=selected_wl
)

# Header formatting with 3-decimal fixed precision
col_headers = ["Sr. No.", "Batch No."]
for col in matrix_result.master_columns:
    label = col.peak_name if col.peak_name else "Unk"
    col_headers.append(f"{label}\nRT: {col.rt:.3f}\nRRT: {col.rrt:.3f}")

display_rows = []
for row in matrix_result.batch_rows:
    r_vals = [row["Sr. No."], row["Batch No."]]
    for col in matrix_result.master_columns:
        v = row.get(col.rrt, "")
        r_vals.append(v if v != "" else "")
    display_rows.append(r_vals)

df_matrix = pd.DataFrame(display_rows, columns=col_headers)

# Styling function to display ICH Q3A colors directly in Streamlit
def style_matrix_table(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    peak_cols = df.columns[2:]

    for col_idx, col_name in enumerate(peak_cols):
        master_col = matrix_result.master_columns[col_idx]
        is_api = master_col.is_main_peak

        for row_idx in df.index:
            val = df.loc[row_idx, col_name]
            if val != "" and val is not None:
                try:
                    num = float(val)
                    if is_api:
                        styles.loc[row_idx, col_name] = "background-color: #dcfce7; color: #166534; font-weight: bold;"
                    elif num >= 0.10:
                        styles.loc[row_idx, col_name] = "background-color: #fed7aa; color: #9a3412; font-weight: bold;"
                    elif num >= 0.05:
                        styles.loc[row_idx, col_name] = "background-color: #fef9c3; color: #854d0e; font-weight: bold;"
                except ValueError:
                    pass
    return styles

st.subheader("Analytical Impurity Comparison Matrix")

st.markdown("""
<div style="display: flex; gap: 20px; font-size: 0.85rem; margin-bottom: 12px;">
  <div><span style="background-color: #dcfce7; padding: 3px 10px; border-radius: 3px; border: 1px solid #86efac; font-weight: bold; color: #166534;">■</span> Main API Peak (RRT = 1.000)</div>
  <div><span style="background-color: #fef9c3; padding: 3px 10px; border-radius: 3px; border: 1px solid #fde047; font-weight: bold; color: #854d0e;">■</span> Impurity &ge; 0.05% (ICH Reporting)</div>
  <div><span style="background-color: #fed7aa; padding: 3px 10px; border-radius: 3px; border: 1px solid #fdba74; font-weight: bold; color: #9a3412;">■</span> Impurity &ge; 0.10% (ICH Identification)</div>
</div>
""", unsafe_allow_html=True)

st.dataframe(df_matrix.style.apply(style_matrix_table, axis=None), use_container_width=True, hide_index=True)

final_excel_bytes = ExcelExporter.generate(matrix_result)
st.download_button(
    label="📥 Download Updated Comparison Matrix (.xlsx)",
    data=final_excel_bytes,
    file_name="HPLC_Batch_Impurity_Matrix.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
