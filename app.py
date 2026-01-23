# app.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from src.ui.router import run_app

st.set_page_config(page_title="Dividends Up", layout="wide")
run_app()
