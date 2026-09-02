import pandas as pd
import streamlit as st

from comparator import HplcComparator
from excel_exporter import ExcelExporter
from parser import HplcPdfParser

st.set_page_config(page_title="HPLC Analytical Comparator", layout="wide")

st.title("🔬 HPLC Multi-File Analytical Comparator")
st.markdown("Automated peak extraction, RRT alignment, RRF quantitation, and ICH Q3A impurity profiling.")

# 1. File Upload Dropzone
uploaded_files = st.file_uploader(
    "Upload HPLC Analysis PDF Reports (Waters Empower, Agilent OpenLab, Shimadzu LabSolutions)",
    type=["pdf"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("Upload 2 or more HPLC PDF reports to begin comparative analysis.")
    st.stop()

# 2. Parse Uploaded Files
parser = HplcPdfParser()
reports = []
for f in uploaded_files:
    content = f.read()
    rep = parser.parse(content, f.name)
    reports.append(rep)

# Gather unique wavelengths across files
all_detected_wl = set()
for r in reports:
    all_detected_wl.update(r.detected_wavelengths)
available_wl_list = sorted(list(all_detected_wl))

# 3. Parameters Bar
col1, col2, col3 = st.columns([1, 1, 1.2])

with col1:
    tolerance = st.slider("RT Tolerance Window (± min)", min_value=0.01, max_value=0.20, value=0.05, step=0.01)

with col2:
    wl_options = ["All Channels"] + [f"{wl} nm" for wl in available_wl_list]
    selected_wl_label = st.selectbox("DAD/PDA Channel", options=wl_options, index=0)
    selected_wl = int(selected_wl_label.replace(" nm", "")) if selected_wl_label != "All Channels" else None

# Initial pass to determine candidate peak RTs
preview = HplcComparator.build_comparison(
    reports=reports,
    rt_tolerance=tolerance,
    target_main_rt=None,
    target_wavelength=selected_wl,
    rrf_map={}
)

candidate_rts = [r.rt for r in preview.rows]

with col3:
    auto_idx = candidate_rts.index(preview.main_peak_rt) if preview.main_peak_rt in candidate_rts else 0
    selected_main_rt = st.selectbox(
        "Designate Main API Peak RT (min)",
        options=candidate_rts,
        index=auto_idx,
        format_func=lambda x: f"{x:.3f} min (Auto-detected)" if x == preview.main_peak_rt else f"{x:.3f} min"
    )

# 4. RRF Configuration Drawer
if "rrf_factors" not in st.session_state:
    st.session_state.rrf_factors = {}

with st.expander("⚙️ Relative Response Factor (RRF) Configuration", expanded=False):
    st.caption("Default is 1.000 for all unspecified impurities. API Peak is locked at 1.000.")
    rrf_df_data = []
    for r in preview.rows:
        if not r.is_main_peak:
            current_rrf = st.session_state.rrf_factors.get(r.rt, 1.0)
            rrf_df_data.append({"Peak RT": r.rt, "Peak Name": r.peak_name, "RRF": current_rrf})

    if rrf_df_data:
        rrf_df = pd.DataFrame(rrf_df_data)
        edited_rrf = st.data_editor(
            rrf_df,
            disabled=["Peak RT", "Peak Name"],
            column_config={
                "RRF": st.column_config.NumberColumn(min_value=0.01, max_value=10.0, step=0.01, format="%.3f")
            },
            hide_index=True,
            key="rrf_editor"
        )
        for _, row in edited_rrf.iterrows():
            st.session_state.rrf_factors[row["Peak RT"]] = float(row["RRF"])

# 5. Final Comparison Build
final_result = HplcComparator.build_comparison(
    reports=reports,
    rt_tolerance=tolerance,
    target_main_rt=selected_main_rt,
    target_wavelength=selected_wl,
    rrf_map=st.session_state.rrf_factors
)

# 6. Build Display Dataframe
display_rows = []
for r in final_result.rows:
    row_dict = {
        "Peak RT (min)": f"{r.rt:.3f}",
        "RRT": f"{r.rrt:.3f}",
        "RRF": f"{r.rrf:.3f}",
        "Peak Name": r.peak_name
    }
    for h in final_result.sample_headers:
        row_dict[f"{h} [% w/w]"] = r.corrected_sample_areas.get(h, "ND")
    display_rows.append(row_dict)

df_display = pd.DataFrame(display_rows)

# 7. Apply ICH Q3A Visual Styling
sample_cols = [f"{h} [% w/w]" for h in final_result.sample_headers]


def style_hplc_table(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for idx, row in df.iterrows():
        is_main = row["Peak Name"] == "Main Peak (API)"
        if is_main:
            for c in df.columns:
                styles.loc[idx, c] = "background-color: #dcfce7; font-weight: bold; color: #166534;"
        else:
            for c in sample_cols:
                val_str = row[c]
                if val_str != "ND":
                    val = float(val_str)
                    if val >= 0.10:
                        styles.loc[idx, c] = "background-color: #fed7aa; font-weight: bold; color: #9a3412;"  # Identification
                    elif val >= 0.05:
                        styles.loc[idx, c] = "background-color: #fef9c3; font-weight: 600; color: #854d0e;"   # Reporting
    return styles


st.subheader("Analytical Alignment Matrix")

# Threshold Legend
st.markdown("""
<div style="display: flex; gap: 20px; font-size: 0.85rem; margin-bottom: 10px;">
  <div><span style="background-color: #dcfce7; padding: 2px 8px; border-radius: 3px; border: 1px solid #86efac;"></span> Main API Peak</div>
  <div><span style="background-color: #fef9c3; padding: 2px 8px; border-radius: 3px; border: 1px solid #fde047;"></span> Impurity &ge; 0.05% (ICH Reporting)</div>
  <div><span style="background-color: #fed7aa; padding: 2px 8px; border-radius: 3px; border: 1px solid #fdba74;"></span> Impurity &ge; 0.10% (ICH Identification)</div>
</div>
""", unsafe_allow_html=True)

st.dataframe(df_display.style.apply(style_hplc_table, axis=None), use_container_width=True, hide_index=True)

# 8. Summary KPI Footers
st.subheader("Batch Summary Metrics")
summary_data = []

row_raw = {"Metric": "Raw Total Impurities (%)"}
row_corr = {"Metric": "RRF-Corrected Total Impurities (% w/w)"}
row_mb = {"Metric": "Mass Balance / Total Area (%)"}

for h in final_result.sample_headers:
    row_raw[h] = final_result.total_impurities.get(h, "0.000")
    row_corr[h] = final_result.corrected_total_impurities.get(h, "0.000")
    row_mb[h] = final_result.mass_balance.get(h, "0.000")

summary_data.extend([row_raw, row_corr, row_mb])
df_summary = pd.DataFrame(summary_data)
st.table(df_summary.set_index("Metric"))

# 9. Excel Export Button
excel_bytes = ExcelExporter.generate(final_result)
active_tag = f"{final_result.active_wavelength}nm" if final_result.active_wavelength else "All"

st.download_button(
    label="📥 Export Formatted Comparison (.xlsx)",
    data=excel_bytes,
    file_name=f"HPLC_Analytical_Comparison_{active_tag}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
