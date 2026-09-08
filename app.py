import pandas as pd
import streamlit as st

from comparator import HplcComparator
from excel_exporter import ExcelExporter
from parser import HplcPdfParser

st.set_page_config(page_title="HPLC Vertical Impurity Comparator", layout="wide")

st.title("🔬 HPLC Vertical Impurity Matrix Comparator")
st.markdown("Multi-batch analytical impurity profiling with automatic filename-based batch tracking, strict RRT priority matching, and incremental Excel workbook merging.")

col_up1, col_up2 = st.columns([1, 1])

with col_up1:
    existing_excel_file = st.file_uploader(
        "📂 (Optional) Upload Existing Vertical Matrix (.xlsx)",
        type=["xlsx"],
        help="Upload an existing vertical matrix. New PDF batches will append as columns to the right."
    )

with col_up2:
    new_pdf_files = st.file_uploader(
        "📄 Upload New HPLC PDF Reports (Chromeleon, Waters, Agilent, Shimadzu)",
        type=["pdf"],
        accept_multiple_files=True
    )

if not existing_excel_file and not new_pdf_files:
    st.info("Upload new HPLC PDF reports, or upload an existing Excel matrix to append additional batches.")
    st.stop()

with st.expander("⚙️ Optional: Custom Impurity RRT Specifications", expanded=False):
    st.write("Map target RRT windows to chemical impurity names:")
    default_specs = (
        "RIM-IMP-B, 0.850, 0.890\n"
        "RIM-IMP-A, 0.940, 0.980\n"
        "Degradant-1, 1.250, 1.310\n"
        "Dimer-Impurity, 1.750, 1.850"
    )
    spec_text = st.text_area("Format: Name, Min RRT, Max RRT (one per line)", value=default_specs, height=105)

custom_spec_list = []
for line in spec_text.strip().splitlines():
    parts = [p.strip() for p in line.split(",") if p.strip()]
    if len(parts) >= 3:
        try:
            custom_spec_list.append({
                "name": parts[0],
                "rrt_min": float(parts[1]),
                "rrt_max": float(parts[2])
            })
        except ValueError:
            pass

parser = HplcPdfParser()
new_reports = []
if new_pdf_files:
    for f in new_pdf_files:
        content = f.read()
        rep = parser.parse(content, f.name)
        new_reports.append(rep)

with st.expander("🔍 Ingestion Log & Extracted Batch Status", expanded=True):
    if existing_excel_file:
        st.info(f"Loaded existing comparison workbook: **{existing_excel_file.name}**")
    for r in new_reports:
        if len(r.peaks) > 0:
            st.success(f"**Batch:** `{r.batch_id}` | Source: `{r.cds_source}` | Peaks Extracted: **{len(r.peaks)}**")
        else:
            st.error(f"**Batch:** `{r.batch_id}` — ⚠️ 0 peaks detected. Ensure it is a vector digital PDF.")

col1, col2, col3 = st.columns([1, 1, 1.2])

all_detected_wl = set()
for r in new_reports:
    all_detected_wl.update(r.detected_wavelengths)
available_wl_list = sorted(list(all_detected_wl))

with col1:
    rrt_tolerance = st.slider(
        "RRT Matching Tolerance (± RRT)",
        min_value=0.002,
        max_value=0.030,
        value=0.015,
        step=0.001,
        format="%.3f"
    )

with col2:
    wl_options = ["All Channels"] + [f"{wl} nm" for wl in available_wl_list]
    selected_wl_label = st.selectbox("Channel / Wavelength", options=wl_options, index=0)
    selected_wl = int(selected_wl_label.replace(" nm", "")) if selected_wl_label != "All Channels" else None

excel_bytes_input = existing_excel_file.read() if existing_excel_file else None

preview = HplcComparator.build_or_merge_vertical_matrix(
    new_reports=new_reports,
    existing_excel_bytes=excel_bytes_input,
    rrt_tolerance=rrt_tolerance,
    target_main_rt=None,
    target_wavelength=selected_wl,
    custom_specs=custom_spec_list
)

raw_candidates = set(preview.main_peak_rts.values()) if preview.main_peak_rts else set()
candidate_rts = sorted([x for x in raw_candidates if x > 0])
if not candidate_rts:
    candidate_rts = [16.366]

with col3:
    selected_main_rt = st.selectbox(
        "Designate API Reference RT (min)",
        options=candidate_rts,
        index=0,
        format_func=lambda x: f"~{x:.3f} min (Main API)"
    )

result = HplcComparator.build_or_merge_vertical_matrix(
    new_reports=new_reports,
    existing_excel_bytes=excel_bytes_input,
    rrt_tolerance=rrt_tolerance,
    target_main_rt=selected_main_rt,
    target_wavelength=selected_wl,
    custom_specs=custom_spec_list
)

table_rows = []
for r in result.rows:
    row_dict = {
        "Sr. No.": str(r.sr_no),
        "Name of Impurity": r.name,
        "Mean RT (min)": f"{r.mean_rt:.3f}",
        "RRT": f"{r.rrt:.3f}",
    }
    for b_name in result.batch_names:
        val = r.batch_values.get(b_name, "")
        row_dict[b_name] = f"{float(val):.2f}" if val != "" and val is not None else ""
    table_rows.append(row_dict)

for s in result.summary_rows:
    s_dict = {
        "Sr. No.": "",
        "Name of Impurity": s["Name of Impurity"],
        "Mean RT (min)": s["Mean RT (min)"],
        "RRT": s["RRT"],
    }
    for b_name in result.batch_names:
        s_dict[b_name] = f"{float(s[b_name]):.2f}"
    table_rows.append(s_dict)

df_display = pd.DataFrame(table_rows)

def style_vertical_table(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    batch_cols = result.batch_names
    num_data_rows = len(result.rows)

    for r_idx in range(num_data_rows):
        master_row = result.rows[r_idx]
        is_api = master_row.is_main

        for b_name in batch_cols:
            val = df.loc[r_idx, b_name]
            if val != "" and val is not None:
                try:
                    num = float(val)
                    if is_api:
                        styles.loc[r_idx, b_name] = "background-color: #dcfce7; color: #166534; font-weight: bold;"
                    elif num >= 0.10:
                        styles.loc[r_idx, b_name] = "background-color: #fed7aa; color: #9a3412; font-weight: bold;"
                    elif num >= 0.05:
                        styles.loc[r_idx, b_name] = "background-color: #fef9c3; color: #854d0e; font-weight: bold;"
                except ValueError:
                    pass

    for s_idx in range(num_data_rows, len(df)):
        for col in df.columns:
            styles.loc[s_idx, col] = "background-color: #e2e8f0; font-weight: bold; color: #0f172a;"

    return styles

st.subheader("Vertical Impurity Comparison Matrix")

st.markdown("""
<div style="display: flex; gap: 20px; font-size: 0.85rem; margin-bottom: 12px;">
  <div><span style="background-color: #dcfce7; padding: 3px 10px; border-radius: 3px; border: 1px solid #86efac; font-weight: bold; color: #166534;">■</span> Main API Peak (RRT = 1.000)</div>
  <div><span style="background-color: #fef9c3; padding: 3px 10px; border-radius: 3px; border: 1px solid #fde047; font-weight: bold; color: #854d0e;">■</span> Impurity &ge; 0.05% (ICH Reporting)</div>
  <div><span style="background-color: #fed7aa; padding: 3px 10px; border-radius: 3px; border: 1px solid #fdba74; font-weight: bold; color: #9a3412;">■</span> Impurity &ge; 0.10% (ICH Identification)</div>
</div>
""", unsafe_allow_html=True)

st.dataframe(
    df_display.style.apply(style_vertical_table, axis=None),
    use_container_width=True,
    hide_index=True
)

excel_bytes = ExcelExporter.generate(result)
st.download_button(
    label="📥 Download Vertical Comparison Matrix (.xlsx)",
    data=excel_bytes,
    file_name="HPLC_Vertical_Impurity_Matrix.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
