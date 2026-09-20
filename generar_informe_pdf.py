#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_informe_pdf.py
----------------------
Genera un Informe Técnico PDF (SCADA + Ladder PLC Delta) a partir de
las métricas almacenadas en embalaje_completo.db.

Uso:
  python generar_informe_pdf.py

Salida:
  Informe_Tecnico_SCADA_PLC_Delta.pdf
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from base_datos import DB_PATH

DB_NAME = DB_PATH.name
PDF_NAME = "Informe_Tecnico_SCADA_PLC_Delta.pdf"
PDF_PATH = Path(__file__).resolve().parent / PDF_NAME


def obtener_metricas_db() -> dict:
    """Agrega KPIs desde registros_planta para el resumen ejecutivo."""
    if not DB_PATH.exists():
        return {
            "total_registros": 0,
            "cnt_llen": 0,
            "cnt_palet": 0,
            "p1_avg": 0,
            "p2_avg": 0,
            "p3_avg": 0,
        }

    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*),
                   MAX(cnt_llenadora),
                   MAX(cnt_paletizadora),
                   AVG(pulmon_1),
                   AVG(pulmon_2),
                   AVG(pulmon_3)
            FROM registros_planta
            """
        )
        row = c.fetchone()
    finally:
        conn.close()

    return {
        "total_registros": row[0] or 0,
        "cnt_llen": row[1] or 0,
        "cnt_palet": row[2] or 0,
        "p1_avg": round(row[3] or 0, 1),
        "p2_avg": round(row[4] or 0, 1),
        "p3_avg": round(row[5] or 0, 1),
    }


def dibujar_escalon_ladder(titulo: str, diagrama_texto: str, descripcion: str) -> Drawing:
    """Dibuja un peldaño Ladder estilizado (rieles + rung) para el PDF."""
    d = Drawing(460, 90)
    # Rieles de alimentación (L / N o +24V / 0V)
    d.add(Line(10, 5, 10, 85, strokeColor=colors.HexColor("#1e293b"), strokeWidth=3))
    d.add(Line(450, 5, 450, 85, strokeColor=colors.HexColor("#1e293b"), strokeWidth=3))

    # Línea de peldaño
    d.add(Line(10, 45, 450, 45, strokeColor=colors.HexColor("#0284c7"), strokeWidth=1.5))

    # Caja central de representación
    d.add(
        Rect(
            60,
            20,
            340,
            50,
            fillColor=colors.HexColor("#f8fafc"),
            strokeColor=colors.HexColor("#94a3b8"),
            strokeWidth=1,
        )
    )

    d.add(
        String(
            70,
            52,
            f"RUNG: {titulo}",
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor("#0f172a"),
        )
    )
    d.add(
        String(
            70,
            37,
            f"LADDER: {diagrama_texto}",
            fontName="Courier-Bold",
            fontSize=9,
            fillColor=colors.HexColor("#0369a1"),
        )
    )
    d.add(
        String(
            70,
            25,
            f"LÓGICA: {descripcion}",
            fontName="Helvetica-Oblique",
            fontSize=8,
            fillColor=colors.HexColor("#475569"),
        )
    )
    return d


def generar_pdf() -> Path:
    """Construye el PDF técnico completo y lo guarda en el directorio del proyecto."""
    metricas = obtener_metricas_db()
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
    )
    h2_style = ParagraphStyle(
        "H2Style",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0284c7"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )

    # --- HEADER ---
    story.append(
        Paragraph(
            "INFORME TÉCNICO: SISTEMA SCADA & CONTROL LADDER PLC DELTA",
            title_style,
        )
    )
    story.append(
        Paragraph(
            "Planta de Embotellado Completa (5 Estaciones + 3 Pulmones) | "
            f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
            f"Fuente: {DB_NAME}",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 15))

    # --- 1. RESUMEN EJECUTIVO ---
    story.append(Paragraph("1. Resumen de Operación de Planta", h2_style))
    story.append(
        Paragraph(
            "Se ha validado la simulación continua del proceso de envasado con control "
            "por balanceo de masa. La Llenadora (máquina crítica) se mantiene protegida "
            "ante paradas en estaciones adyacentes mediante 3 pulmones dinámicos de "
            "acumulación. Los datos provienen del cliente Modbus TCP a 1 Hz y del HMI Streamlit.",
            body_style,
        )
    )
    story.append(Spacer(1, 10))

    data_metrics = [
        ["Métrica de Operación", "Valor Registrado en DB", "Estado / Observación"],
        [
            "Total Muestras SCADA",
            f"{metricas['total_registros']} registros",
            "Lectura continua 1 Hz",
        ],
        [
            "Prod. Acumulada Llenadora",
            f"{metricas['cnt_llen']} envases",
            "Máquina Crítica",
        ],
        [
            "Prod. Final Paletizadora",
            f"{metricas['cnt_palet']} cajas",
            "Producto Terminado",
        ],
        [
            "Ocupación Prom. Pulmón 1",
            f"{metricas['p1_avg']}%",
            "Pre-Llenadora",
        ],
        [
            "Ocupación Prom. Pulmón 2",
            f"{metricas['p2_avg']}%",
            "Post-Llenadora",
        ],
        [
            "Ocupación Prom. Pulmón 3",
            f"{metricas['p3_avg']}%",
            "Pre-Paletizadora",
        ],
    ]
    t_metrics = Table(data_metrics, colWidths=[6.5 * cm, 5.5 * cm, 6.0 * cm])
    t_metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")],
                ),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ]
        )
    )
    story.append(t_metrics)
    story.append(Spacer(1, 15))

    # --- 2. MAPEO MODBUS / DELTA (alineado con servidor_simulado.py) ---
    story.append(
        Paragraph("2. Tabla de Mapeo de Memoria (PLC Delta DVP / AH / AS)", h2_style)
    )
    story.append(
        Paragraph(
            "Convención: Coils = bits M; Holding Registers = palabras D. "
            "Direcciones 0-based en pymodbus (zero_mode=True).",
            body_style,
        )
    )
    story.append(Spacer(1, 6))

    data_map = [
        ["Variable Python", "Modbus TCP", "Memoria Delta", "Tipo", "Función Industrial"],
        ["st_despaletizador", "Coil 0", "M0", "BOOL", "Estado Despaletizador (ON/OFF)"],
        ["st_llenadora", "Coil 1", "M1", "BOOL", "Estado Llenadora (Máquina Crítica)"],
        ["st_etiquetadora", "Coil 2", "M2", "BOOL", "Estado Etiquetadora"],
        ["st_encajonadora", "Coil 3", "M3", "BOOL", "Estado Encajonadora"],
        ["st_paletizadora", "Coil 4", "M4", "BOOL", "Estado Paletizadora"],
        ["cmd_falla_etiq", "Coil 10", "M10", "BOOL", "Inyección de Falla desde HMI"],
        ["cmd_falla_palet", "Coil 11", "M11", "BOOL", "Falta de pallets desde HMI"],
        ["cnt_llenadora", "HR 1", "D1", "INT", "Contador de Envases Procesados"],
        ["cnt_paletizadora", "HR 2", "D2", "INT", "Contador de Cajas / Pallets"],
        ["pulmon_1_pct", "HR 10", "D10", "INT", "Nivel Pulmón 1 Pre-Llenadora (%)"],
        ["pulmon_2_pct", "HR 11", "D11", "INT", "Nivel Pulmón 2 Post-Llenadora (%)"],
        ["pulmon_3_pct", "HR 12", "D12", "INT", "Nivel Pulmón 3 Pre-Paletizadora (%)"],
        ["velocidad_bph", "HR 20", "D20", "INT", "Velocidad estimada (botellas/hora)"],
    ]
    t_map = Table(data_map, colWidths=[4.0 * cm, 2.8 * cm, 2.8 * cm, 1.6 * cm, 6.8 * cm])
    t_map.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f0f9ff")],
                ),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(t_map)
    story.append(Spacer(1, 15))

    # --- 3. LADDER ISPSoft ---
    story.append(
        Paragraph("3. Código Ladder para ISPSoft (Lógica de Interlocks)", h2_style)
    )
    story.append(
        Paragraph(
            "Representación en diagramas de peldaños (Rungs) para programar "
            "directamente en el PLC Delta (ISPSoft / DIADesigner):",
            body_style,
        )
    )
    story.append(Spacer(1, 10))

    story.append(
        dibujar_escalon_ladder(
            "0001 - Control Etiquetadora con Falla HMI",
            "|--[/M10]--------------------------------( M2 )--|",
            "Si M10 (Falla HMI) es False, la Etiquetadora M2 opera normalmente.",
        )
    )
    story.append(Spacer(1, 8))

    story.append(
        dibujar_escalon_ladder(
            "0002 - Interlock Protección Llenadora (Pulmón 2)",
            "|--[>= D11 K90]-------------------------( RST M1 )--|",
            "Si Pulmón 2 (D11) >= 90%, se resetea M1 (paro preventivo Llenadora).",
        )
    )
    story.append(Spacer(1, 8))

    story.append(
        dibujar_escalon_ladder(
            "0003 - Interlock Alimentación (Pulmón 1)",
            "|--[>= D10 K90]-------------------------( RST M0 )--|",
            "Si Pulmón 1 (D10) >= 90%, frena el Despaletizador M0.",
        )
    )
    story.append(Spacer(1, 8))

    story.append(
        dibujar_escalon_ladder(
            "0004 - Interlock Pre-Paletizadora (Pulmón 3)",
            "|--[>= D12 K90]-------------------------( RST M3 )--|",
            "Si Pulmón 3 (D12) >= 90%, frena la Encajonadora M3.",
        )
    )

    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            "Nota: Este informe documenta la lógica validada en el simulador Python "
            "(pymodbus). Al migrar al PLC Delta físico, conservar el mismo mapa M/D "
            "y cambiar solo IP/puerto en cliente_lectura.py y dashboard.py.",
            body_style,
        )
    )

    doc.build(story)
    print(f"[OK] Reporte PDF generado exitosamente: {PDF_PATH}")
    return PDF_PATH


if __name__ == "__main__":
    generar_pdf()
