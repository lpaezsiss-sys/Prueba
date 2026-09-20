#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cliente_lectura.py
------------------
Cliente Modbus TCP para la planta completa (3 pulmones).

Lee cada 1 s estados, pulmones, contadores y BPH; imprime en consola
y guarda en SQLite.

Para el PLC Delta real: cambia solo PLC_IP / PLC_PORT / SLAVE_ID.
"""

from __future__ import annotations

import time

from pymodbus.client import ModbusTcpClient

from base_datos import init_db, guardar_lectura_completa

# ==============================================================================
# CONFIGURACIÓN DE CONEXIÓN (cambia esto para el PLC Delta físico)
# ==============================================================================
PLC_IP = "127.0.0.1"
PLC_PORT = 5020  # 5020 simulador | 502 PLC Delta típico
SLAVE_ID = 1
INTERVALO_LECTURA_S = 1.0

init_db()


def _on_off(v: bool) -> str:
    return "ON" if v else "--"


def leer_plc() -> None:
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

    print(f"[CLIENTE] Conectando a planta en {PLC_IP}:{PLC_PORT}...")
    if not client.connect():
        print("[CLIENTE] Error: no hay conexión. ¿Corriste servidor_simulado.py?")
        return

    print("[CLIENTE] Conexión OK. Lectura continua (Ctrl+C para detener).\n")
    print(
        f"{'TIMESTAMP':<19} | {'D':^3} {'L':^3} {'E':^3} {'C':^3} {'P':^3} | "
        f"{'P1%':>4} {'P2%':>4} {'P3%':>4} | {'LLEN':>6} {'PAL':>5} | {'BPH':>5}"
    )
    print("-" * 78)

    try:
        while True:
            res_coils = client.read_coils(address=0, count=12, slave=SLAVE_ID)
            res_regs = client.read_holding_registers(address=0, count=21, slave=SLAVE_ID)

            if res_coils.isError() or res_regs.isError():
                print("[CLIENTE] Error al leer Modbus.")
            else:
                bits = res_coils.bits
                regs = res_regs.registers

                st_desp = bool(bits[0])
                st_llen = bool(bits[1])
                st_etiq = bool(bits[2])
                st_encaj = bool(bits[3])
                st_palet = bool(bits[4])
                falla_etiq = bool(bits[10])
                falla_palet = bool(bits[11])

                cnt_desp = int(regs[0])
                cnt_llen = int(regs[1])
                cnt_palet = int(regs[2])
                p1, p2, p3 = int(regs[10]), int(regs[11]), int(regs[12])
                bph = int(regs[20])

                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                print(
                    f"{ts:<19} | "
                    f"{_on_off(st_desp):^3} {_on_off(st_llen):^3} {_on_off(st_etiq):^3} "
                    f"{_on_off(st_encaj):^3} {_on_off(st_palet):^3} | "
                    f"{p1:>4} {p2:>4} {p3:>4} | {cnt_llen:>6} {cnt_palet:>5} | {bph:>5}"
                )

                # Persistencia (esquema embalaje_completo.db)
                guardar_lectura_completa(
                    st_llen,
                    st_etiq,
                    st_palet,
                    p1,
                    p2,
                    p3,
                    cnt_llen,
                    cnt_palet,
                )

            time.sleep(INTERVALO_LECTURA_S)

    except KeyboardInterrupt:
        print("\n[CLIENTE] Lectura detenida.")
    finally:
        client.close()
        print("[CLIENTE] Conexión cerrada.")


if __name__ == "__main__":
    leer_plc()
