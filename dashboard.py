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
        b, r = list(coils.bits[:12]), list(regs.registers[:21])
        return {
            "coils": b,
            "registers": r,
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


def _estado_isa_estacion(
    on: bool,
    *,
    falla: bool = False,
    interlock: bool = False,
) -> tuple[str, str, str]:
    """
    Devuelve (fill, border, etiqueta) según ISA-101 alto rendimiento.
      ON        -> gris/verde suave
      Interlock -> amarillo (bloqueo por pulmón)
      Falla/OFF -> rojo (titila suavemente)
    """
    if on:
        return "#86efac", "#166534", "ON"
    if interlock and not falla:
        return "#facc15", "#a16207", "INTERLOCK"
    # Titileo rojo para falla/paro (alterna con el refresco SCADA)
    if int(time.time() * 2) % 2 == 0:
        return "#ef4444", "#991b1b", "FALLA" if falla else "OFF"
    return "#7f1d1d", "#450a0a", "FALLA" if falla else "OFF"


def crear_grafico_mimico(coils: list, registers: list) -> go.Figure:
    """
    Diagrama mímico industrial interactivo (ISA-101) de la línea completa.

    Flujo:
      [Despaletizador]──(P1)──>[Llenadora]──(P2)──>[Etiquetadora]
          ──>[Encajonadora]──(P3)──>[Paletizadora]
    """
    st_desp = bool(coils[0])
    st_llen = bool(coils[1])
    st_etiq = bool(coils[2])
    st_encaj = bool(coils[3])
    st_palet = bool(coils[4])
    falla_etiq = bool(coils[10]) if len(coils) > 10 else False
    falla_palet = bool(coils[11]) if len(coils) > 11 else False

    p1 = int(registers[10]) if len(registers) > 10 else 0
    p2 = int(registers[11]) if len(registers) > 11 else 0
    p3 = int(registers[12]) if len(registers) > 12 else 0
    p1 = max(0, min(100, p1))
    p2 = max(0, min(100, p2))
    p3 = max(0, min(100, p3))

    # Clasificación OFF: falla vs interlock por saturación de pulmón aguas abajo
    fill_d, border_d, tag_d = _estado_isa_estacion(
        st_desp, interlock=(not st_desp and p1 >= 90)
    )
    fill_l, border_l, tag_l = _estado_isa_estacion(
        st_llen, interlock=(not st_llen and p2 >= 90)
    )
    fill_e, border_e, tag_e = _estado_isa_estacion(st_etiq, falla=falla_etiq)
    fill_c, border_c, tag_c = _estado_isa_estacion(
        st_encaj, interlock=(not st_encaj and p3 >= 90)
    )
    fill_p, border_p, tag_p = _estado_isa_estacion(st_palet, falla=falla_palet)

    # Geometría compacta para que quepan 5 estaciones + 3 tanques sin recorte
    #   Desp──P1──Llen──P2──Etiq────Encaj──P3──Palet
    estaciones = [
        {"name": "Despaletizador", "x": 9, "fill": fill_d, "border": border_d, "tag": tag_d, "critica": False},
        {"name": "Llenadora", "x": 29, "fill": fill_l, "border": border_l, "tag": tag_l, "critica": True},
        {"name": "Etiquetadora", "x": 49, "fill": fill_e, "border": border_e, "tag": tag_e, "critica": False},
        {"name": "Encajonadora", "x": 69, "fill": fill_c, "border": border_c, "tag": tag_c, "critica": False},
        {"name": "Paletizadora", "x": 89, "fill": fill_p, "border": border_p, "tag": tag_p, "critica": False},
    ]
    w_est, h_est, y_est = 9.0, 8.0, 6.5

    # Segmentos de cinta: activo si la estación aguas arriba está ON
    cintas = [
        {"x0": 13.8, "x1": 24.2, "activo": st_desp},   # Desp -> Llen (vía P1)
        {"x0": 33.8, "x1": 44.2, "activo": st_llen},   # Llen -> Etiq (vía P2)
        {"x0": 53.8, "x1": 64.2, "activo": st_etiq},   # Etiq -> Encaj
        {"x0": 73.8, "x1": 84.2, "activo": st_encaj},  # Encaj -> Palet (vía P3)
    ]

    pulmones = [
        {"label": "P1", "titulo": "Pulmón 1", "x": 19.0, "nivel": p1},
        {"label": "P2", "titulo": "Pulmón 2", "x": 39.0, "nivel": p2},
        {"label": "P3", "titulo": "Pulmón 3", "x": 79.0, "nivel": p3},
    ]

    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []

    # Base de cinta transportadora (riel)
    shapes.append(
        dict(
            type="rect",
            x0=5,
            x1=96,
            y0=9.6,
            y1=11.0,
            fillcolor="#1f2937",
            line=dict(color="#374151", width=1),
            layer="below",
        )
    )

    for cinta in cintas:
        color = "#38bdf8" if cinta["activo"] else "#4b5563"
        width = 4 if cinta["activo"] else 2
        shapes.append(
            dict(
                type="line",
                x0=cinta["x0"],
                x1=cinta["x1"],
                y0=10.3,
                y1=10.3,
                line=dict(color=color, width=width),
                layer="below",
            )
        )
        # Punta de flecha simple
        shapes.append(
            dict(
                type="path",
                path=(
                    f"M {cinta['x1']-1.2} {10.3 + 0.7} "
                    f"L {cinta['x1']} {10.3} "
                    f"L {cinta['x1']-1.2} {10.3 - 0.7} Z"
                ),
                fillcolor=color,
                line=dict(color=color, width=0),
                layer="below",
            )
        )

    # Estaciones (bloques de proceso)
    for est in estaciones:
        x0 = est["x"] - w_est / 2
        x1 = est["x"] + w_est / 2
        y0, y1 = y_est, y_est + h_est
        shapes.append(
            dict(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=est["fill"],
                line=dict(
                    color="#38bdf8" if est["critica"] else est["border"],
                    width=4 if est["critica"] else 2,
                ),
                layer="above",
            )
        )
        # Etiqueta de nombre
        annotations.append(
            dict(
                x=est["x"],
                y=y1 + 1.2,
                text=f"<b>{est['name']}</b>"
                + (" ★ CRÍTICA" if est["critica"] else ""),
                showarrow=False,
                font=dict(size=12, color="#e5e7eb"),
                xanchor="center",
            )
        )
        # Badge de estado
        annotations.append(
            dict(
                x=est["x"],
                y=y_est + h_est / 2,
                text=f"<b>{est['tag']}</b>",
                showarrow=False,
                font=dict(size=13, color="#111827"),
                xanchor="center",
                yanchor="middle",
            )
        )

    # Pulmones = tanques verticales con nivel dinámico (siempre visibles, incluso al 0%)
    tank_w, tank_h, tank_y0 = 5.0, 11.0, 12.2
    for pul in pulmones:
        x0 = pul["x"] - tank_w / 2
        x1 = pul["x"] + tank_w / 2
        y0 = tank_y0
        y1 = tank_y0 + tank_h
        nivel = pul["nivel"]
        fill_h = tank_h * (nivel / 100.0)
        # Contorno del tanque
        shapes.append(
            dict(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor="#020617",
                line=dict(color="#e5e7eb", width=2),
                layer="above",
            )
        )
        # Marcas de escala 60% / 85%
        for pct, col in ((60, "#22c55e"), (85, "#ef4444")):
            yy = y0 + tank_h * (pct / 100.0)
            shapes.append(
                dict(
                    type="line",
                    x0=x0,
                    x1=x1,
                    y0=yy,
                    y1=yy,
                    line=dict(color=col, width=1, dash="dot"),
                    layer="above",
                )
            )
        # Nivel líquido (mínimo visual de 2% para que el tanque se note vacío)
        visible_h = max(fill_h, tank_h * 0.02)
        shapes.append(
            dict(
                type="rect",
                x0=x0 + 0.2,
                x1=x1 - 0.2,
                y0=y0 + 0.2,
                y1=y0 + 0.2 + visible_h,
                fillcolor=color_pulmon(nivel) if nivel > 0 else "#1f2937",
                line=dict(width=0),
                layer="above",
            )
        )
        # Etiqueta % encima del tanque
        annotations.append(
            dict(
                x=pul["x"],
                y=y1 + 1.1,
                text=f"<b>{pul['label']} {nivel}%</b>",
                showarrow=False,
                font=dict(size=13, color=color_pulmon(nivel) if nivel > 0 else "#e5e7eb"),
                xanchor="center",
            )
        )
        annotations.append(
            dict(
                x=pul["x"],
                y=y1 + 2.5,
                text=pul["titulo"],
                showarrow=False,
                font=dict(size=10, color="#d1d5db"),
                xanchor="center",
            )
        )

    # Leyenda ISA-101 compacta
    annotations.append(
        dict(
            x=50,
            y=1.2,
            text=(
                "<b>ISA-101</b> &nbsp; "
                "Verde/gris = ON &nbsp;|&nbsp; "
                "Amarillo = Interlock (pulmón) &nbsp;|&nbsp; "
                "Rojo = Falla/Paro &nbsp;|&nbsp; "
                "Cinta azul = flujo activo"
            ),
            showarrow=False,
            font=dict(size=11, color="#9ca3af"),
            xanchor="center",
        )
    )

    fig = go.Figure()
    # Trace invisible para fijar el viewport
    fig.add_trace(
        go.Scatter(
            x=[0, 100],
            y=[0, 30],
            mode="markers",
            marker=dict(size=1, opacity=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        shapes=shapes,
        annotations=annotations,
        height=460,
        margin=dict(l=8, r=8, t=16, b=8),
        paper_bgcolor="#111827",
        plot_bgcolor="#1e1e1e",
        font=dict(color="#e5e7eb"),
        autosize=True,
        xaxis=dict(
            range=[0, 100],
            visible=False,
            showgrid=False,
            zeroline=False,
            fixedrange=True,
            constrain="domain",
        ),
        yaxis=dict(
            range=[0, 30],
            visible=False,
            showgrid=False,
            zeroline=False,
            fixedrange=True,
            constrain="domain",
        ),
        dragmode=False,
        uirevision="mimico-planta",
    )
    return fig


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
# 2) DIAGRAMA MÍMICO INDUSTRIAL (ISA-101)
# =============================================================================
st.subheader("Diagrama mímico de planta — flujo continuo")
st.plotly_chart(
    crear_grafico_mimico(estado["coils"], estado["registers"]),
    use_container_width=True,
    config={"displayModeBar": False, "staticPlot": False},
)

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
