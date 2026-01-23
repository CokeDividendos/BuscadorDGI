from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# Evita el clásico ModuleNotFoundError en Streamlit Cloud
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Buscador DGI", layout="wide")

# Import robusto
try:
    from src.ui.router import run_app  # type: ignore
except ModuleNotFoundError:
    from ui.router import run_app  # type: ignore

run_app()
