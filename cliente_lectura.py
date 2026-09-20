#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cliente_lectura.py
------------------
Cliente Modbus TCP: captura periódica de la planta completa (3 pulmones).

Lee estados clave + pulmones + contadores, guarda en embalaje_completo.db
e imprime un resumen en consola.

Para el PLC Delta real: cambia solo PLC_IP / PLC_PORT / SLAVE_ID.
"""

from __future__ import annotations

import time

from pymodbus.client import ModbusTcpClient

from base_datos import init_db, guardar_lectura_completa

# ------------------------------------------------------------------------------
# CONFIGURACIÓN DE CONEXIÓN
# Simulador: 127.0.0.1:5020 | PLC Delta típico: <IP_PLC>:502
# ------------------------------------------------------------------------------
PLC_IP = "127.0.0.1"
PLC_PORT = 5020
SLAVE_ID = 1

init_db()


def ciclo_lectura() -> None:
    """Conecta al PLC/simulador y registra lecturas cada 1 segundo."""
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    if not client.connect():
        print("[ERROR] No se pudo conectar al PLC.")
        print("[ERROR] ¿Está corriendo 'python servidor_simulado.py'?")
        return

    print(f"[CLIENTE] Capturando datos de planta completa en {PLC_IP}:{PLC_PORT}...")
    print("[CLIENTE] Ctrl+C para detener.\n")

    try:
        while True:
            # Coils 0..4: estados de las 5 máquinas
            res_coils = client.read_coils(address=0, count=5, slave=SLAVE_ID)
            # HR 0..12: contadores (0-2) + pulmones (10-12)
            res_regs = client.read_holding_registers(address=0, count=13, slave=SLAVE_ID)

            if not res_coils.isError() and not res_regs.isError():
                coils = res_coils.bits
                regs = res_regs.registers

                # Desempaquetado (mapa alineado con servidor_simulado.py)
                st_llen = bool(coils[1])   # Llenadora
                st_etiq = bool(coils[2])   # Etiquetadora
                st_palet = bool(coils[4])  # Paletizadora
                p1, p2, p3 = int(regs[10]), int(regs[11]), int(regs[12])
                cnt_llen = int(regs[1])    # Contador llenadora
                cnt_palet = int(regs[2])   # Contador paletizadora / cajas

                guardar_lectura_completa(
                    st_llen, st_etiq, st_palet, p1, p2, p3, cnt_llen, cnt_palet
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"Llenadora: {'ON' if st_llen else 'OFF'} | "
                    f"Pulmón 2: {p2}% | "
                    f"Cajas: {cnt_palet}"
                )
            else:
                print("[CLIENTE] Error al leer registros Modbus.")

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[CLIENTE] Lectura detenida por el usuario.")
    finally:
        client.close()
        print("[CLIENTE] Conexión cerrada.")


if __name__ == "__main__":
    ciclo_lectura()
