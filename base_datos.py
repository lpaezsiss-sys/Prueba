#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
base_datos.py
-------------
Persistencia SQLite de la planta completa (3 pulmones).

Base de datos: embalaje_completo.db
Tabla: registros_planta

Campos guardados (los más útiles para reporte y dashboard):
  - st_llenadora / st_etiq / st_palet
  - pulmon_1 / pulmon_2 / pulmon_3  (% 0-100)
  - cnt_llenadora / cnt_paletizadora
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# Nombre de archivo pedido para el modelo de planta completa
DB_NAME = "embalaje_completo.db"
DB_PATH = Path(__file__).resolve().parent / DB_NAME


def _conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Crea la tabla de registros si no existe."""
    conn = _conectar()
    try:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS registros_planta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                st_llenadora BOOLEAN,
                st_etiq BOOLEAN,
                st_palet BOOLEAN,
                pulmon_1 INTEGER,
                pulmon_2 INTEGER,
                pulmon_3 INTEGER,
                cnt_llenadora INTEGER,
                cnt_paletizadora INTEGER
            )
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_planta_timestamp
            ON registros_planta (timestamp)
            """
        )
        conn.commit()
    finally:
        conn.close()


def guardar_lectura_completa(
    st_llen: bool,
    st_etiq: bool,
    st_palet: bool,
    p1: int,
    p2: int,
    p3: int,
    cnt_llen: int,
    cnt_palet: int,
) -> None:
    """
    Inserta una lectura de la planta en SQLite.

    Parámetros alineados con el cliente Modbus:
      st_llen, st_etiq, st_palet -> estados de máquinas clave
      p1, p2, p3                 -> niveles de pulmones (%)
      cnt_llen, cnt_palet        -> contadores de producción
    """
    conn = _conectar()
    try:
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """
            INSERT INTO registros_planta
                (timestamp, st_llenadora, st_etiq, st_palet,
                 pulmon_1, pulmon_2, pulmon_3,
                 cnt_llenadora, cnt_paletizadora)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                int(bool(st_llen)),
                int(bool(st_etiq)),
                int(bool(st_palet)),
                int(p1),
                int(p2),
                int(p3),
                int(cnt_llen),
                int(cnt_palet),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def reporte_produccion_dia(fecha: str | None = None) -> dict[str, Any]:
    """Resumen diario a partir del contador de llenadora."""
    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    conn = _conectar()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT cnt_llenadora, cnt_paletizadora, st_etiq, st_palet
            FROM registros_planta
            WHERE timestamp LIKE ?
            ORDER BY id ASC
            """,
            (f"{fecha}%",),
        )
        filas = c.fetchall()
    finally:
        conn.close()

    if not filas:
        return {
            "fecha": fecha,
            "total_lecturas": 0,
            "piezas_inicial": None,
            "piezas_final": None,
            "piezas_producidas": 0,
            "pallets_final": None,
        }

    piezas_inicial = int(filas[0][0] or 0)
    piezas_final = int(filas[-1][0] or 0)
    delta = piezas_final - piezas_inicial
    return {
        "fecha": fecha,
        "total_lecturas": len(filas),
        "piezas_inicial": piezas_inicial,
        "piezas_final": piezas_final,
        "piezas_producidas": delta if delta >= 0 else piezas_final,
        "pallets_final": int(filas[-1][1] or 0),
    }


def contar_registros() -> int:
    """Cuántas filas hay en registros_planta (útil para pruebas)."""
    conn = _conectar()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM registros_planta")
        return int(c.fetchone()[0])
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Base de datos: {DB_PATH}")
    init_db()
    guardar_lectura_completa(True, True, True, 20, 10, 5, 100, 2)
    guardar_lectura_completa(True, False, True, 25, 40, 5, 110, 2)
    print(f"Registros: {contar_registros()}")
    print("Reporte:", reporte_produccion_dia())
