#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
base_datos.py
-------------
Persistencia SQLite de lecturas de la planta completa (3 pulmones).

Tabla: registros_planta
  - estados de las 5 máquinas
  - fallas comandadas
  - contadores
  - niveles de pulmones (%)
  - velocidad BPH
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_NAME = "embalaje.db"
DB_PATH = Path(__file__).resolve().parent / DB_NAME


def _conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Crea la tabla de planta completa si no existe."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS registros_planta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                st_desp INTEGER NOT NULL,
                st_llen INTEGER NOT NULL,
                st_etiq INTEGER NOT NULL,
                st_encaj INTEGER NOT NULL,
                st_palet INTEGER NOT NULL,
                falla_etiq INTEGER NOT NULL,
                falla_palet INTEGER NOT NULL,
                cnt_desp INTEGER NOT NULL,
                cnt_llen INTEGER NOT NULL,
                cnt_palet INTEGER NOT NULL,
                pulmon_1 INTEGER NOT NULL,
                pulmon_2 INTEGER NOT NULL,
                pulmon_3 INTEGER NOT NULL,
                velocidad_bph INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_planta_timestamp
            ON registros_planta (timestamp)
            """
        )
        # Tabla legacy (pasos 1-4) se mantiene por compatibilidad si existiera
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS registros_produccion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                motor_encendido BOOLEAN NOT NULL,
                contador_piezas INTEGER NOT NULL,
                alarma_activa BOOLEAN NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def guardar_lectura_planta(
    st_desp: bool,
    st_llen: bool,
    st_etiq: bool,
    st_encaj: bool,
    st_palet: bool,
    falla_etiq: bool,
    falla_palet: bool,
    cnt_desp: int,
    cnt_llen: int,
    cnt_palet: int,
    pulmon_1: int,
    pulmon_2: int,
    pulmon_3: int,
    velocidad_bph: int,
) -> None:
    """Inserta una lectura completa de la planta."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO registros_planta (
                timestamp,
                st_desp, st_llen, st_etiq, st_encaj, st_palet,
                falla_etiq, falla_palet,
                cnt_desp, cnt_llen, cnt_palet,
                pulmon_1, pulmon_2, pulmon_3,
                velocidad_bph
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                int(bool(st_desp)),
                int(bool(st_llen)),
                int(bool(st_etiq)),
                int(bool(st_encaj)),
                int(bool(st_palet)),
                int(bool(falla_etiq)),
                int(bool(falla_palet)),
                int(cnt_desp),
                int(cnt_llen),
                int(cnt_palet),
                int(pulmon_1),
                int(pulmon_2),
                int(pulmon_3),
                int(velocidad_bph),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_lectura(motor_encendido: bool, contador_piezas: int, alarma_activa: bool) -> None:
    """
    Compatibilidad con el modelo simple (pasos 1-4).
    Prefiere guardar_lectura_planta() con el modelo de 3 pulmones.
    """
    conn = _conectar()
    try:
        cur = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO registros_produccion
                (timestamp, motor_encendido, contador_piezas, alarma_activa)
            VALUES (?, ?, ?, ?)
            """,
            (now, int(bool(motor_encendido)), int(contador_piezas), int(bool(alarma_activa))),
        )
        conn.commit()
    finally:
        conn.close()


def reporte_produccion_dia(fecha: str | None = None) -> dict[str, Any]:
    """Resumen diario a partir de registros_planta (contador llenadora)."""
    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT cnt_llen, cnt_palet, pulmon_2, velocidad_bph, falla_etiq, falla_palet
            FROM registros_planta
            WHERE timestamp LIKE ?
            ORDER BY id ASC
            """,
            (f"{fecha}%",),
        )
        filas = cur.fetchall()
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
            "lecturas_con_falla": 0,
        }

    piezas_inicial = int(filas[0][0])
    piezas_final = int(filas[-1][0])
    delta = piezas_final - piezas_inicial
    return {
        "fecha": fecha,
        "total_lecturas": len(filas),
        "piezas_inicial": piezas_inicial,
        "piezas_final": piezas_final,
        "piezas_producidas": delta if delta >= 0 else piezas_final,
        "pallets_final": int(filas[-1][1]),
        "lecturas_con_falla": sum(1 for f in filas if f[4] or f[5]),
    }


def contar_registros() -> int:
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM registros_planta")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Base de datos: {DB_PATH}")
    init_db()
    guardar_lectura_planta(
        True, True, True, True, True,
        False, False,
        10, 10, 1,
        20, 15, 5,
        2400,
    )
    print(f"Registros planta: {contar_registros()}")
    print("Reporte:", reporte_produccion_dia())
