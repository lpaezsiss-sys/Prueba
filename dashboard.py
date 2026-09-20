#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
------------
Dashboard web en tiempo real (Streamlit) para la línea de embalaje.

Muestra:
  - Estado del motor (ON/OFF)
  - Contador de piezas
  - Alarma (paro prolongado)
  - Botonera HMI (arranque / paro vía Modbus)
  - Histórico y gráfica desde SQLite

Orden típico de arranque:
  1) python servidor_simulado.py
  2) python cliente_lectura.py   # llena embalaje.db
  3) streamlit run dashboard.py  # este archivo

Para el PLC Delta real: cambia solo PLC_IP y PLC_PORT (igual que el cliente).
"""

from __future__ import annotations

import sqlite3
import time

import pandas as pd
import streamlit as st
from pymodbus.client import ModbusTcpClient

from base_datos import DB_PATH, init_db

# ------------------------------------------------------------------------------
# CONFIGURACIÓN DE LA PÁGINA Y MODBUS
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Control Línea de Embalaje",
    page_icon="🏭",
    layout="wide",
)

# Mismas variables que en cliente_lectura.py (cámbialas para el PLC real)
PLC_IP = "127.0.0.1"
PLC_PORT = 5020  # 5020 = simulador | 502 = PLC Delta típico
SLAVE_ID = 1

# Asegura que la tabla exista aunque aún no hayas corrido el cliente
init_db()

# ------------------------------------------------------------------------------
# FUNCIONES AUXILIARES (COMUNICACIÓN Y BASE DE DATOS)
# ------------------------------------------------------------------------------


def enviar_pulso_modbus(coil_address: int) -> bool:
    """
    Envía un pulso (escribe True) a un coil del PLC / simulador.

    Coil 2: Botón Arranque | Coil 3: Botón Paro
    El servidor simulado (o tu ladder en el Delta) interpreta el pulso y
    resetea el bit; por eso no hace falta escribir False desde aquí.
    """
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    try:
        if not client.connect():
            return False
        result = client.write_coil(coil_address, True, slave=SLAVE_ID)
        time.sleep(0.1)
        return not result.isError()
    finally:
        client.close()


def obtener_historial_db() -> pd.DataFrame:
    """Obtiene los últimos 50 registros de la base de datos SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT timestamp, motor_encendido, contador_piezas, alarma_activa "
            "FROM registros_produccion ORDER BY id DESC LIMIT 50",
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


# ------------------------------------------------------------------------------
# INTERFAZ GRÁFICA (DASHBOARD)
# ------------------------------------------------------------------------------
st.title("🏭 Dashboard de Control - Línea de Embalaje Industrial")
st.caption(f"Origen de datos: `{DB_PATH.name}` · Comandos Modbus → {PLC_IP}:{PLC_PORT}")
st.markdown("---")

df_historial = obtener_historial_db()

if not df_historial.empty:
    # El historial viene ORDER BY id DESC → la fila 0 es la más reciente
    ultimo_registro = df_historial.iloc[0]
    motor_on = bool(ultimo_registro["motor_encendido"])
    piezas = int(ultimo_registro["contador_piezas"])
    alarma_on = bool(ultimo_registro["alarma_activa"])
else:
    motor_on, piezas, alarma_on = False, 0, False

# --- PANEL SUPERIOR: ESTADOS Y MÉTRICAS ---
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Estado del Motor")
    if motor_on:
        st.success("🟢 MOTOR OPERANDO (ON)")
    else:
        st.error("🔴 MOTOR DETENIDO (OFF)")

with col2:
    st.subheader("Producción Total")
    st.metric(label="Piezas Procesadas", value=f"{piezas} pcs")

with col3:
    st.subheader("Sistema de Alarmas")
    if alarma_on:
        st.warning("⚠️ ALERTA: PARO PROLONGADO (>10s)")
    else:
        st.info("✅ SISTEMA NORMAL")

st.markdown("---")

# --- PANEL INTERMEDIO: CONTROL MANUAL (BOTONERA HMI) ---
st.subheader("🎛️ Control Manual de Planta")
col_btn1, col_btn2, _ = st.columns([1, 1, 2])

with col_btn1:
    if st.button("🟢 ARRANCAR LÍNEA", use_container_width=True):
        ok = enviar_pulso_modbus(coil_address=2)  # Coil 2 = Botón Arranque
        if ok:
            st.toast("Comando de ARRANQUE enviado al PLC", icon="✅")
        else:
            st.toast("No se pudo conectar al PLC/simulador", icon="⚠️")

with col_btn2:
    if st.button("🔴 PARAR LÍNEA", use_container_width=True):
        ok = enviar_pulso_modbus(coil_address=3)  # Coil 3 = Botón Paro
        if ok:
            st.toast("Comando de PARO enviado al PLC", icon="🛑")
        else:
            st.toast("No se pudo conectar al PLC/simulador", icon="⚠️")

st.markdown("---")

# --- PANEL INFERIOR: HISTORIAL Y GRÁFICOS DE TENDENCIA ---
st.subheader("📊 Histórico de Producción en Tiempo Real")

if not df_historial.empty:
    # Invertimos para que el eje X vaya de antiguo → reciente en la gráfica
    df_chart = df_historial.iloc[::-1].copy()
    st.line_chart(df_chart.set_index("timestamp")["contador_piezas"])

    with st.expander("Ver tabla de últimos 50 registros"):
        st.dataframe(df_historial, use_container_width=True)
else:
    st.info(
        "Esperando primeros registros en la base de datos `embalaje.db`... "
        "Arranca también `python cliente_lectura.py`."
    )

# Auto-refresh cada ~1.5 s (polling simple de Streamlit)
time.sleep(1.5)
st.rerun()
