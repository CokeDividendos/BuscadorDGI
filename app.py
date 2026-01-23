# app.py
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# Asegura que /src y el root estén primeros en sys.path (evita colisiones)
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Dividends Up", layout="wide")

# Import robusto (funciona si llamas como src.ui.router o ui.router)
try:
    from src.ui.router import run_app  # type: ignore
except ModuleNotFoundError:
    from ui.router import run_app  # type: ignore

run_app()
