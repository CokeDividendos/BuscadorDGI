# app.py
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.ui.router import run_app  # noqa: E402

st.set_page_config(page_title="Buscador DGI", layout="wide")
run_app()
