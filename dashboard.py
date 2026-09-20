#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
------------
Dashboard Streamlit — planta completa con 3 pulmones.

Muestra estados de máquinas, niveles de acumulación, contadores, BPH
y permite inyectar fallas en etiquetadora / paletizadora (coils 10/11).

Arranque:
  1) python servidor_simulado.py
  2) python cliente_lectura.py
  3) streamlit run dashboard.py
"""

from __future__ import annotations

import sqlite3
import time

import pandas as pd
import streamlit as st
from pymodbus.client import ModbusTcpClient

from base_datos import DB_PATH, init_db

st.set_page_config(
    page_title="Planta Embalaje — 3 Pulmones",
    page_icon="🏭",
    layout="wide",
)

PLC_IP = "127.0.0.1"
PLC_PORT = 5020
SLAVE_ID = 1

init_db()


def escribir_coil(address: int, valor: bool) -> bool:
    """Escribe un coil Modbus (fallas HMI)."""
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    try:
        if not client.connect():
            return False
        r = client.write_coil(address, bool(valor), slave=SLAVE_ID)
        return not r.isError()
    finally:
        client.close()


def leer_planta_modbus() -> dict | None:
    """Lectura directa al PLC/simulador (fuente en vivo para el HMI)."""
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    try:
        if not client.connect():
            return None
        coils = client.read_coils(0, 12, slave=SLAVE_ID)
        regs = client.read_holding_registers(0, 21, slave=SLAVE_ID)
        if coils.isError() or regs.isError():
            return None
        b, r = coils.bits, regs.registers
        return {
            "st_desp": bool(b[0]),
            "st_llen": bool(b[1]),
            "st_etiq": bool(b[2]),
            "st_encaj": bool(b[3]),
            "st_palet": bool(b[4]),
            "falla_etiq": bool(b[10]),
            "falla_palet": bool(b[11]),
            "cnt_desp": int(r[0]),
            "cnt_llen": int(r[1]),
            "cnt_palet": int(r[2]),
            "pulmon_1": int(r[10]),
            "pulmon_2": int(r[11]),
            "pulmon_3": int(r[12]),
            "velocidad_bph": int(r[20]),
        }
    finally:
        client.close()


def obtener_historial_db(limit: int = 50) -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            f"""
            SELECT timestamp, st_llen, st_etiq, st_palet,
                   cnt_llen, cnt_palet, pulmon_1, pulmon_2, pulmon_3, velocidad_bph
            FROM registros_planta
            ORDER BY id DESC LIMIT {int(limit)}
            """,
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def badge_maquina(nombre: str, on: bool) -> None:
    if on:
        st.success(f"{nombre}: ON")
    else:
        st.error(f"{nombre}: OFF")


def barra_pulmon(nombre: str, nivel: int) -> None:
    nivel = int(min(100, max(0, nivel)))
    st.markdown(f"**{nombre}** — {nivel}%")
    st.progress(nivel / 100.0)
    # Estado explícito en cada refresh (evita sensación de aviso “pegado”)
    if nivel >= 90:
        st.warning("Saturación ≥ 90% (interlock activo)")
    elif nivel >= 70:
        st.info("Nivel alto — vigilar acumulación")
    else:
        st.caption("Nivel normal")


# ------------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------------
st.title("Dashboard — Línea completa (3 pulmones)")
st.caption(f"Modbus {PLC_IP}:{PLC_PORT} · Histórico `{DB_PATH.name}`")
st.markdown("---")

estado = leer_planta_modbus()
if estado is None:
    st.error("Sin conexión Modbus. Arranca `python servidor_simulado.py`.")
    time.sleep(1.5)
    st.rerun()

# --- Máquinas ---
st.subheader("Estados de máquinas")
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    badge_maquina("Despaletizador", estado["st_desp"])
with c2:
    badge_maquina("Llenadora", estado["st_llen"])
with c3:
    badge_maquina("Etiquetadora", estado["st_etiq"])
with c4:
    badge_maquina("Encajonadora", estado["st_encaj"])
with c5:
    badge_maquina("Paletizadora", estado["st_palet"])

# --- KPIs ---
k1, k2, k3 = st.columns(3)
k1.metric("Contador llenadora", estado["cnt_llen"])
k2.metric("Contador palets", estado["cnt_palet"])
k3.metric("Velocidad BPH", estado["velocidad_bph"])

st.markdown("---")

# --- Pulmones ---
st.subheader("Pulmones de acumulación")
p1, p2, p3 = st.columns(3)
with p1:
    barra_pulmon("Pulmón 1 (pre-llenadora)", estado["pulmon_1"])
with p2:
    barra_pulmon("Pulmón 2 (pre-etiquetadora)", estado["pulmon_2"])
with p3:
    barra_pulmon("Pulmón 3 (pre-paletizadora)", estado["pulmon_3"])

st.markdown("---")

# --- Fallas HMI ---
st.subheader("Simulación de fallas (escritura Modbus)")
f1, f2 = st.columns(2)
with f1:
    if estado["falla_etiq"]:
        if st.button("Recuperar Etiquetadora", use_container_width=True):
            escribir_coil(10, False)
            st.toast("falla_etiq = 0")
    else:
        if st.button("Inyectar FALLA Etiquetadora", use_container_width=True):
            escribir_coil(10, True)
            st.toast("falla_etiq = 1 — observa cómo sube Pulmón 2")

with f2:
    if estado["falla_palet"]:
        if st.button("Recuperar Paletizadora", use_container_width=True):
            escribir_coil(11, False)
            st.toast("falla_palet = 0")
    else:
        if st.button("Inyectar FALLA Paletizadora", use_container_width=True):
            escribir_coil(11, True)
            st.toast("falla_palet = 1 — observa cómo sube Pulmón 3")

st.markdown("---")

# --- Histórico ---
st.subheader("Histórico (SQLite)")
df = obtener_historial_db()
if not df.empty:
    chart_df = df.iloc[::-1].copy()
    st.line_chart(
        chart_df.set_index("timestamp")[["pulmon_1", "pulmon_2", "pulmon_3", "cnt_llen"]]
    )
    with st.expander("Últimos registros"):
        st.dataframe(df, use_container_width=True)
else:
    st.info("Sin histórico aún. Arranca también `python cliente_lectura.py`.")

time.sleep(1.5)
st.rerun()
