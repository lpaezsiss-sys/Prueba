#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
------------
Etapa 2 — Layout y Dashboard HMI (Streamlit) para planta de embotellado
con 5 estaciones y 3 pulmones de acumulación.

Fuentes de datos:
  - Modbus TCP (vivo): estados de 5 máquinas, fallas, BPH, pulmones
  - SQLite embalaje_completo.db: histórico de registros_planta

Arranque:
  python servidor_simulado.py
  python cliente_lectura.py
  streamlit run dashboard.py --server.port 8501
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pymodbus.client import ModbusTcpClient

from base_datos import DB_PATH, init_db

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
PLC_IP = "127.0.0.1"
PLC_PORT = 5020
SLAVE_ID = 1
BPH_NOMINAL = 2400  # Capacidad nominal para estimar OEE/rendimiento

st.set_page_config(
    page_title="HMI Planta Embotellado",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# Estilos HMI (tarjetas de estación / badges)
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(180deg, #0f172a 0%, #1e293b 45%, #0f172a 100%); }
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    h1, h2, h3, p, label, span, div { color: #e2e8f0 !important; }
    [data-testid="stMetricValue"] { color: #f8fafc !important; }
    [data-testid="stMetricLabel"] { color: #94a3b8 !important; }
    .station-card {
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 0.85rem 0.7rem;
        background: rgba(15, 23, 42, 0.85);
        min-height: 140px;
        text-align: center;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }
    .station-card.critical {
        border: 2px solid #38bdf8;
        background: linear-gradient(180deg, rgba(14,165,233,0.18), rgba(15,23,42,0.9));
    }
    .station-title { font-weight: 700; font-size: 0.95rem; margin-bottom: 0.35rem; }
    .station-sub { font-size: 0.75rem; color: #94a3b8 !important; margin-bottom: 0.55rem; }
    .badge-on {
        display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
        background: #14532d; color: #86efac !important; font-weight: 700; font-size: 0.85rem;
        border: 1px solid #22c55e;
    }
    .badge-off {
        display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
        background: #7f1d1d; color: #fecaca !important; font-weight: 700; font-size: 0.85rem;
        border: 1px solid #ef4444;
    }
    .buffer-chip {
        border: 1px dashed #64748b; border-radius: 10px; padding: 0.55rem 0.35rem;
        text-align: center; background: rgba(30, 41, 59, 0.7); min-height: 140px;
    }
    .status-operando {
        background: #14532d; border: 1px solid #22c55e; color: #bbf7d0 !important;
        padding: 0.55rem 1rem; border-radius: 10px; font-weight: 800; display: inline-block;
    }
    .status-alerta {
        background: #78350f; border: 1px solid #f59e0b; color: #fde68a !important;
        padding: 0.55rem 1rem; border-radius: 10px; font-weight: 800; display: inline-block;
    }
    .status-paro {
        background: #7f1d1d; border: 1px solid #ef4444; color: #fecaca !important;
        padding: 0.55rem 1rem; border-radius: 10px; font-weight: 800; display: inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# CAPA DE DATOS (Modbus vivo + SQLite histórico)
# =============================================================================
def leer_estado_modbus() -> dict[str, Any] | None:
    """Lectura en vivo del PLC/simulador (no bloquea más de un RTT TCP)."""
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT, timeout=1)
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
            "cnt_llen": int(r[1]),
            "cnt_palet": int(r[2]),
            "pulmon_1": int(r[10]),
            "pulmon_2": int(r[11]),
            "pulmon_3": int(r[12]),
            "bph": int(r[20]),
        }
    except Exception:
        return None
    finally:
        client.close()


def escribir_coil(address: int, valor: bool) -> bool:
    """Escritura Modbus de un coil (comandos HMI / fallas)."""
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT, timeout=1)
    try:
        if not client.connect():
            return False
        result = client.write_coil(address, bool(valor), slave=SLAVE_ID)
        return not result.isError()
    except Exception:
        return False
    finally:
        client.close()


def cargar_historial(limit: int = 120) -> pd.DataFrame:
    """Últimos N registros desde embalaje_completo.db (tabla registros_planta)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=1)
        df = pd.read_sql_query(
            """
            SELECT timestamp, st_llenadora, st_etiq, st_palet,
                   pulmon_1, pulmon_2, pulmon_3,
                   cnt_llenadora, cnt_paletizadora
            FROM registros_planta
            ORDER BY id DESC
            LIMIT ?
            """,
            conn,
            params=(int(limit),),
        )
        conn.close()
        if not df.empty:
            df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


def color_pulmon(nivel: int) -> str:
    """Código de color SCADA: verde / amarillo / rojo."""
    if nivel > 85:
        return "#ef4444"
    if nivel > 60:
        return "#f59e0b"
    return "#22c55e"


def estado_global(e: dict[str, Any]) -> tuple[str, str]:
    """
    Clasifica el estado de línea:
      OPERANDO | ALERTA | PARO
    """
    saturado = max(e["pulmon_1"], e["pulmon_2"], e["pulmon_3"]) > 85
    falla = e["falla_etiq"] or e["falla_palet"]
    critico_off = not e["st_llen"]

    if critico_off or (not e["st_etiq"] and not e["st_palet"]):
        return "PARO", "status-paro"
    if saturado or falla or not e["st_desp"] or not e["st_encaj"] or not e["st_palet"]:
        return "ALERTA", "status-alerta"
    return "OPERANDO", "status-operando"


def estimar_oee(bph: int) -> float:
    """Rendimiento estimado = BPH actual / BPH nominal * 100."""
    if BPH_NOMINAL <= 0:
        return 0.0
    return round(min(100.0, max(0.0, (bph / BPH_NOMINAL) * 100.0)), 1)


def gauge_pulmon(nombre: str, nivel: int) -> go.Figure:
    """Indicador radial Plotly 0-100% con umbrales de color."""
    nivel = int(min(100, max(0, nivel)))
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=nivel,
            number={"suffix": "%", "font": {"size": 28, "color": "#f8fafc"}},
            title={"text": nombre, "font": {"size": 14, "color": "#cbd5e1"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#94a3b8"},
                "bar": {"color": color_pulmon(nivel)},
                "bgcolor": "#0f172a",
                "borderwidth": 1,
                "bordercolor": "#334155",
                "steps": [
                    {"range": [0, 60], "color": "rgba(34,197,94,0.18)"},
                    {"range": [60, 85], "color": "rgba(245,158,11,0.20)"},
                    {"range": [85, 100], "color": "rgba(239,68,68,0.22)"},
                ],
                "threshold": {
                    "line": {"color": "#f87171", "width": 3},
                    "thickness": 0.8,
                    "value": 85,
                },
            },
        )
    )
    fig.update_layout(
        margin=dict(l=18, r=18, t=40, b=10),
        height=230,
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e2e8f0"},
    )
    return fig


def tarjeta_estacion(titulo: str, subtitulo: str, on: bool, critica: bool = False) -> None:
    """Tarjeta visual de una estación del sinóptico."""
    clase = "station-card critical" if critica else "station-card"
    badge = (
        '<span class="badge-on">🟢 ON</span>'
        if on
        else '<span class="badge-off">🔴 OFF / FALLA</span>'
    )
    st.markdown(
        f"""
        <div class="{clase}">
          <div class="station-title">{titulo}</div>
          <div class="station-sub">{subtitulo}</div>
          {badge}
        </div>
        """,
        unsafe_allow_html=True,
    )


def chip_pulmon(nombre: str, nivel: int) -> None:
    """Indicador compacto de pulmón entre estaciones."""
    color = color_pulmon(nivel)
    st.markdown(
        f"""
        <div class="buffer-chip">
          <div style="font-size:0.72rem;color:#94a3b8!important;">{nombre}</div>
          <div style="font-size:1.35rem;font-weight:800;color:{color}!important;margin:0.35rem 0;">
            {int(nivel)}%
          </div>
          <div style="height:8px;background:#1e293b;border-radius:999px;overflow:hidden;">
            <div style="width:{int(min(100,max(0,nivel)))}%;height:100%;background:{color};"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SIDEBAR — control SCADA / fallas Modbus
# =============================================================================
with st.sidebar:
    st.header("Panel de Comandos")
    st.caption(f"Modbus `{PLC_IP}:{PLC_PORT}` · DB `{DB_PATH.name}`")
    intervalo = st.slider("Intervalo de refresco (s)", 1.0, 2.0, 1.5, 0.1)

    st.markdown("---")
    st.subheader("Inyección de Fallas")

    if st.button("Simular Paro por Cambio de Rollo en Etiquetadora", use_container_width=True):
        ok = escribir_coil(10, True)
        st.toast("Coil 10 = True (falla etiquetadora)" if ok else "Error Modbus", icon="⚠️")

    if st.button("Simular Falta de Pallets en Paletizadora", use_container_width=True):
        ok = escribir_coil(11, True)
        st.toast("Coil 11 = True (falla paletizadora)" if ok else "Error Modbus", icon="⚠️")

    if st.button("Restablecer Planta", use_container_width=True, type="primary"):
        ok = escribir_coil(10, False) and escribir_coil(11, False)
        st.toast("Fallas limpiadas (coils 10/11 = False)" if ok else "Error Modbus", icon="✅")

    st.markdown("---")
    st.caption(
        "Umbrales de pulmón: verde 0–60% · amarillo 61–85% · rojo >85% (saturación)."
    )


# =============================================================================
# LECTURA DE ESTADO
# =============================================================================
estado = leer_estado_modbus()
historial = cargar_historial(120)

if estado is None:
    st.error(
        "Sin conexión Modbus TCP. Arranca `python servidor_simulado.py` en el puerto 5020."
    )
    time.sleep(float(intervalo))
    st.rerun()

linea, css_linea = estado_global(estado)
oee = estimar_oee(estado["bph"])


# =============================================================================
# 1) ENCABEZADO + KPIs
# =============================================================================
st.title("HMI SCADA — Planta de Embotellado / Envasado")
st.caption(
    "Línea de 5 estaciones con 3 pulmones de acumulación · Datos vivos Modbus + histórico SQLite"
)

c_status, c_kpi1, c_kpi2, c_kpi3 = st.columns([1.3, 1, 1, 1])
with c_status:
    st.markdown("**Estado global de línea**")
    st.markdown(f'<div class="{css_linea}">{linea}</div>', unsafe_allow_html=True)
    detalle = []
    if estado["falla_etiq"]:
        detalle.append("Falla etiquetadora activa")
    if estado["falla_palet"]:
        detalle.append("Falta de pallets activa")
    if max(estado["pulmon_1"], estado["pulmon_2"], estado["pulmon_3"]) > 85:
        detalle.append("Pulmón en saturación")
    st.caption(" · ".join(detalle) if detalle else "Sin alarmas activas")

with c_kpi1:
    st.metric("Producción Total Llenadora", f"{estado['cnt_llen']:,} u".replace(",", "."))
with c_kpi2:
    st.metric("Producción Final Paletizadora", f"{estado['cnt_palet']:,} cajas".replace(",", "."))
with c_kpi3:
    st.metric(
        "Eficiencia / Rendimiento",
        f"{oee:.1f}% OEE",
        delta=f"{estado['bph']} BPH",
    )

st.markdown("---")


# =============================================================================
# 2) LAYOUT SINÓPTICO DE PLANTA
# =============================================================================
st.subheader("Sinóptico de planta — flujo de 5 estaciones")

desp, p1c, llen, p2c, etiq, encaj, p3c, palet = st.columns([2, 1.1, 2.2, 1.1, 2, 2, 1.1, 2])

with desp:
    tarjeta_estacion("1. Despaletizado", "Entrada de envases", estado["st_desp"])
with p1c:
    chip_pulmon("Pulmón 1", estado["pulmon_1"])
with llen:
    tarjeta_estacion(
        "2. Lavadora / Llenadora",
        "MÁQUINA CRÍTICA",
        estado["st_llen"],
        critica=True,
    )
with p2c:
    chip_pulmon("Pulmón 2", estado["pulmon_2"])
with etiq:
    tarjeta_estacion("3. Etiquetadora", "Identificación", estado["st_etiq"])
with encaj:
    tarjeta_estacion("4. Encajonadora", "Formación de cajas", estado["st_encaj"])
with p3c:
    chip_pulmon("Pulmón 3", estado["pulmon_3"])
with palet:
    tarjeta_estacion("5. Paletizadora", "Salida de pallets", estado["st_palet"])

st.markdown("---")


# =============================================================================
# 3) GAUGES PLOTLY DE PULMONES
# =============================================================================
st.subheader("Monitoreo en tiempo real de pulmones")
g1, g2, g3 = st.columns(3)
with g1:
    st.plotly_chart(
        gauge_pulmon("Pulmón 1 — Pre-Llenadora", estado["pulmon_1"]),
        use_container_width=True,
        config={"displayModeBar": False},
    )
with g2:
    st.plotly_chart(
        gauge_pulmon("Pulmón 2 — Post-Llenadora / Pre-Etiquetadora", estado["pulmon_2"]),
        use_container_width=True,
        config={"displayModeBar": False},
    )
with g3:
    st.plotly_chart(
        gauge_pulmon("Pulmón 3 — Pre-Paletizadora", estado["pulmon_3"]),
        use_container_width=True,
        config={"displayModeBar": False},
    )

st.markdown("---")


# =============================================================================
# 4) TENDENCIAS HISTÓRICAS + TABLA
# =============================================================================
st.subheader("Tendencias históricas de pulmones")

if historial.empty:
    st.info(
        "Esperando histórico en `embalaje_completo.db`. "
        "Arranca también `python cliente_lectura.py`."
    )
else:
    fig_hist = go.Figure()
    for col, nombre, color in [
        ("pulmon_1", "Pulmón 1", "#38bdf8"),
        ("pulmon_2", "Pulmón 2", "#a78bfa"),
        ("pulmon_3", "Pulmón 3", "#34d399"),
    ]:
        fig_hist.add_trace(
            go.Scatter(
                x=historial["timestamp"],
                y=historial[col],
                mode="lines",
                name=nombre,
                line=dict(width=2, color=color),
            )
        )
    fig_hist.add_hline(y=85, line_dash="dash", line_color="#ef4444", annotation_text="Saturación 85%")
    fig_hist.add_hline(y=60, line_dash="dot", line_color="#f59e0b", annotation_text="Pre-alarma 60%")
    fig_hist.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.55)",
        font={"color": "#e2e8f0"},
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(title="Tiempo", gridcolor="#334155"),
        yaxis=dict(title="% ocupación", range=[0, 100], gridcolor="#334155"),
        hovermode="x unified",
    )
    st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False})

    with st.expander("Últimos registros SQLite"):
        st.dataframe(historial.iloc[::-1].head(50), use_container_width=True, hide_index=True)

# Botonera inferior (además del sidebar) para operación en pantalla completa
st.markdown("### Control rápido de fallas (Modbus)")
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Paro cambio de rollo (Etiquetadora)", key="btn_falla_etiq", use_container_width=True):
        escribir_coil(10, True)
with b2:
    if st.button("Falta de pallets (Paletizadora)", key="btn_falla_pal", use_container_width=True):
        escribir_coil(11, True)
with b3:
    if st.button("Restablecer planta", key="btn_reset", use_container_width=True):
        escribir_coil(10, False)
        escribir_coil(11, False)


# =============================================================================
# 5) AUTO-REFRESCO SCADA
# =============================================================================
time.sleep(float(intervalo))
st.rerun()
