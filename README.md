# HPLC Vertical Impurity Matrix Comparator

A Streamlit analytical platform designed to parse multi-vendor HPLC PDF reports (Thermo/Dionex Chromeleon, Waters Empower, Agilent OpenLab, Shimadzu LabSolutions) and compile them into a standardized vertical impurity matrix.

## Features

- **Filename-Based Batch Tracking:** Automatically pulls clean batch identifiers from uploaded PDF filenames without relying on inconsistent internal header keys.
- **Strict RRT-Priority Matching:** Clustered alignment using Relative Retention Time minimizes chromatography drift issues; native RRT values take precedence over calculated ratios.
- **Vertical Matrix Structure:** Rows represent individual impurities (Sr. No., Name of Impurity, Mean RT, RRT); columns represent batches side-by-side.
- **Custom Specification Lookup:** Optional interactive configuration window maps target RRT windows to compound names.
- **Incremental Merging:** Upload a previously exported `HPLC_Vertical_Impurity_Matrix.xlsx` alongside new PDF runs to append new batch columns and insert newly detected impurities.
- **ICH Q3A Color Flagging:** API Peak (Mint Green), Identification Threshold $\ge 0.10\%$ (Soft Orange), Reporting Threshold $\ge 0.05\%$ (Soft Yellow), and Summary Metrics (Cool Slate).
- **Freeze Panes:** Excel workbooks are locked at `E2` for horizontal scrolling across multiple batch columns.

## Local Installation

```bash
pip install -r requirements.txt
streamlit run app.py
