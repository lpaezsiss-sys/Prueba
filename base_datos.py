#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
base_datos.py
-------------
Persistencia SQLite de las lecturas del PLC (simulado o real).

Cada lectura guarda:
  - timestamp        -> cuándo se leyó
  - motor_encendido  -> estado del motor
  - contador_piezas  -> piezas acumuladas
  - alarma_activa    -> si había alarma

Este módulo NO habla Modbus: solo recibe valores ya leídos por el cliente
y los guarda. Así puedes reutilizarlo igual con el simulador o con el PLC Delta.

Uso típico (desde cliente_lectura.py o dashboard.py):

    from base_datos import init_db, guardar_lectura

    init_db()  # una vez al arrancar
    guardar_lectura(motor_encendido=True, contador_piezas=12, alarma_activa=False)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
# El archivo .db se crea en la misma carpeta del proyecto.
# (Más adelante puedes cambiarlo a una ruta absoluta si quieres.)
DB_NAME = "embalaje.db"
DB_PATH = Path(__file__).resolve().parent / DB_NAME


def _conectar() -> sqlite3.Connection:
    """Abre una conexión a SQLite (una por operación, patrón simple y seguro)."""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """
    Crea la tabla de registros si no existe.

    Llámalo una vez al iniciar el cliente o el dashboard.
    Es idempotente: si la tabla ya existe, no hace nada destructivo.
    """
    conn = _conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
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
        # Índice por fecha: acelera reportes del tipo "todo lo de hoy"
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_registros_timestamp
            ON registros_produccion (timestamp)
            """
        )
        conn.commit()
    finally:
        conn.close()


def guardar_lectura(
    motor_encendido: bool,
    contador_piezas: int,
    alarma_activa: bool,
) -> None:
    """
    Inserta una lectura del PLC en la base de datos.

    Parámetros:
      motor_encendido  -> True si el motor está ON
      contador_piezas  -> valor actual del contador Modbus
      alarma_activa    -> True si hay alarma activa
    """
    conn = _conectar()
    try:
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
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
    """
    Genera un resumen de producción para un día concreto.

    Args:
      fecha: cadena 'YYYY-MM-DD'. Si es None, usa el día de hoy.

    Returns:
      Diccionario con totales útiles para un cierre de jornada, por ejemplo:
        {
          "fecha": "2026-09-20",
          "total_lecturas": 120,
          "piezas_inicial": 0,
          "piezas_final": 45,
          "piezas_producidas": 45,
          "lecturas_con_alarma": 3,
          "lecturas_motor_on": 80,
        }
    """
    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    conn = _conectar()
    try:
        cursor = conn.cursor()
        # Todas las lecturas cuyo timestamp empieza por la fecha pedida
        cursor.execute(
            """
            SELECT contador_piezas, motor_encendido, alarma_activa
            FROM registros_produccion
            WHERE timestamp LIKE ?
            ORDER BY id ASC
            """,
            (f"{fecha}%",),
        )
        filas = cursor.fetchall()
    finally:
        conn.close()

    if not filas:
        return {
            "fecha": fecha,
            "total_lecturas": 0,
            "piezas_inicial": None,
            "piezas_final": None,
            "piezas_producidas": 0,
            "lecturas_con_alarma": 0,
            "lecturas_motor_on": 0,
        }

    piezas_inicial = int(filas[0][0])
    piezas_final = int(filas[-1][0])
    # Si el contador Modbus hace overflow (65535 -> 0), el delta puede ser negativo;
    # en ese caso informamos al menos el valor absoluto observado en el día.
    delta = piezas_final - piezas_inicial
    piezas_producidas = delta if delta >= 0 else piezas_final

    return {
        "fecha": fecha,
        "total_lecturas": len(filas),
        "piezas_inicial": piezas_inicial,
        "piezas_final": piezas_final,
        "piezas_producidas": piezas_producidas,
        "lecturas_con_alarma": sum(1 for f in filas if f[2]),
        "lecturas_motor_on": sum(1 for f in filas if f[1]),
    }


def contar_registros() -> int:
    """Devuelve cuántas filas hay en la tabla (útil para pruebas rápidas)."""
    conn = _conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM registros_produccion")
        return int(cursor.fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Prueba manual rápida:
#   python base_datos.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Base de datos: {DB_PATH}")
    init_db()
    print("Tabla registros_produccion lista.")

    guardar_lectura(True, 10, False)
    guardar_lectura(True, 11, False)
    guardar_lectura(False, 11, True)
    print(f"Registros totales: {contar_registros()}")

    resumen = reporte_produccion_dia()
    print("Reporte de hoy:")
    for clave, valor in resumen.items():
        print(f"  {clave}: {valor}")
