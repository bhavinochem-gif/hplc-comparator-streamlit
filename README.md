# HPLC Multi-Batch Impurity Matrix Comparator

A Streamlit analytical platform designed to parse multi-vendor HPLC PDF reports (Thermo/Dionex Chromeleon, Waters Empower, Agilent OpenLab) and compile them into a standardized horizontal impurity matrix.

## Features

- **Automated Peak Parsing:** Extracts Retention Time (RT), Relative Retention Time (RRT), Peak Name, and Area % directly from digital PDF exports.
- **RRT-Based Alignment:** Dynamic tolerance window (±0.010 RRT default) eliminates chromatography column drift issues.
- **Incremental Merging:** Upload a previously exported matrix spreadsheet (`.xlsx`) alongside new PDFs to append new batch injections and detect new impurity columns.
- **ICH Q3A Color Flagging:** Highlights API peaks (Green), Identification Threshold ≥ 0.10% (Soft Orange), and Reporting Threshold ≥ 0.05% (Soft Yellow).
- **Frozen Header Panes:** Excel workbooks locked at `D4` for easy horizontal scrolling across high-dimensional impurity columns.

## Local Installation

```bash
pip install -r requirements.txt
streamlit run app.py
