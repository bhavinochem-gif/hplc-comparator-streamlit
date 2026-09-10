import pandas as pd
import streamlit as st

from comparator import HplcComparator
from excel_exporter import ExcelExporter
from parser import HplcPdfParser

st.set_page_config(page_title="HPLC Analytical Comparator", layout="wide")

st.title("📊 HPLC Multi-Batch Comparison Matrix")
st.markdown("Automated multi-batch peak table extraction directly into the synchronized vertical matrix layout.")

uploaded_files = st.file_uploader(
    "Upload HPLC Analysis PDF Reports (Dionex Chromeleon, Waters Empower, Agilent OpenLab)",
    type=["pdf"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("Upload 2 or more HPLC PDF reports to generate the vertical comparison matrix.")
    st.stop()

# Parse PDFs
parser = HplcPdfParser()
reports = []
for f in uploaded_files:
    content = f.read()
    rep = parser.parse(content, f.name)
    reports.append(rep)

# Ingestion Diagnostics Drawer
with st.expander("🔍 Ingestion Status & Peaks Extracted", expanded=True):
    for r in reports:
        if len(r.peaks) > 0:
            st.success(f"**Batch:** `{r.batch_id}` | Peaks Extracted: **{len(r.peaks)}**")
        else:
            st.error(f"**{r.file_name}** — ⚠️ 0 peaks detected. Ensure this is an electronic PDF printout.")

total_peaks = sum(len(r.peaks) for r in reports)
if total_peaks == 0:
    st.error("No chromatographic peak tables could be extracted. Please ensure the files are digital PDFs with selectable text.")
    st.stop()

# Comparison Parameter
col1, _ = st.columns([1, 2])
with col1:
    rrt_tolerance = st.slider(
        "RRT Alignment Window (± RRT)",
        min_value=0.003,
        max_value=0.025,
        value=0.010,
        step=0.001,
        format="%.3f"
    )

# Build Matrix
result = HplcComparator.build_comparison(reports=reports, rrt_tolerance=rrt_tolerance)

# Construct On-Screen Table
table_headers = ["Peak name", "Ret.Time", "Rel.Ret.Time"] + result.batch_names
table_data = []

for r in result.rows:
    row_dict = {
        "Peak name": r.name,
        "Ret.Time": r.rt_str,
        "Rel.Ret.Time": r.rrt_str,
    }
    for b_name in result.batch_names:
        val = r.batch_values.get(b_name, "")
        row_dict[b_name] = str(val) if val != "" else ""
    table_data.append(row_dict)

df_display = pd.DataFrame(table_data)

def style_table(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for row_idx in df.index:
        is_main = result.rows[row_idx].is_main
        for b_name in result.batch_names:
            val = df.loc[row_idx, b_name]
            if val != "" and val is not None:
                try:
                    num = float(val)
                    if is_main:
                        styles.loc[row_idx, b_name] = "background-color: #dcfce7; color: #166534; font-weight: bold;"
                    elif num >= 0.10:
                        styles.loc[row_idx, b_name] = "background-color: #fed7aa; color: #9a3412; font-weight: bold;"
                    elif num >= 0.05:
                        styles.loc[row_idx, b_name] = "background-color: #fef9c3; color: #854d0e; font-weight: bold;"
                except ValueError:
                    pass
    return styles

st.subheader("Vertical Analytical Comparison Matrix")

# Visual Legend
st.markdown("""
<div style="display: flex; gap: 20px; font-size: 0.85rem; margin-bottom: 12px;">
  <div><span style="background-color: #dcfce7; padding: 3px 10px; border-radius: 3px; border: 1px solid #86efac; font-weight: bold; color: #166534;">■</span> Main API Peak (RRT = 1.000)</div>
  <div><span style="background-color: #fef9c3; padding: 3px 10px; border-radius: 3px; border: 1px solid #fde047; font-weight: bold; color: #854d0e;">■</span> Impurity &ge; 0.05% (ICH Reporting)</div>
  <div><span style="background-color: #fed7aa; padding: 3px 10px; border-radius: 3px; border: 1px solid #fdba74; font-weight: bold; color: #9a3412;">■</span> Impurity &ge; 0.10% (ICH Identification)</div>
</div>
""", unsafe_allow_html=True)

st.dataframe(
    df_display.style.apply(style_table, axis=None),
    use_container_width=True,
    hide_index=True
)

# Export Excel
excel_data = ExcelExporter.generate(result)
st.download_button(
    label="📥 Download Formatted Comparison (.xlsx)",
    data=excel_data,
    file_name="HPLC_Vertical_Comparison_Matrix.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
