#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cliente_lectura.py
------------------
Cliente Modbus TCP: lectura periódica + logging en consola + persistencia SQLite.

Este script es el "puente" entre el PLC (simulado o real) y el resto del sistema
(base de datos, y más adelante el dashboard).

IMPORTANTE para el PLC Delta físico:
  Solo debes cambiar PLC_IP y PLC_PORT (y SLAVE_ID si aplica).
  La lógica de lectura / impresión / guardado NO cambia.
"""

from __future__ import annotations

import time

from pymodbus.client import ModbusTcpClient

from base_datos import init_db, guardar_lectura

# ==============================================================================
# CONFIGURACIÓN DE CONEXIÓN
# Para conectar con el PLC Delta real en el futuro, cambia estas variables:
# ==============================================================================
PLC_IP = "127.0.0.1"  # IP del PLC (o del simulador en tu PC)
PLC_PORT = 5020       # 5020 = simulador | 502 = típico PLC Delta real
SLAVE_ID = 1          # Unit / Slave ID Modbus (en Delta suele ser 1)

# Mapa de direcciones (debe coincidir con servidor_simulado.py / PLC)
ADDR_MOTOR = 0
ADDR_ALARMA = 1
# Coils 2 y 3 son botones (arranque/paro); aquí solo leemos estado de proceso
ADDR_CONTADOR = 0

INTERVALO_LECTURA_S = 1.0  # Periodo de muestreo (segundos)

# Inicializar base de datos (crea la tabla si no existe)
init_db()


def leer_plc() -> None:
    """
    Conecta por Modbus TCP, lee variables cada segundo e imprime + guarda.
    """
    # Instancia del cliente Modbus TCP (misma clase sirve para simulador y PLC real)
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

    print(f"[CLIENTE] Conectando a PLC en {PLC_IP}:{PLC_PORT}...")
    if not client.connect():
        print("[CLIENTE] Error: No se pudo establecer conexión con el PLC/Simulador.")
        print("[CLIENTE] ¿Está corriendo 'python servidor_simulado.py' en otra terminal?")
        return

    print("[CLIENTE] Conexión establecida. Iniciando lectura continua (Ctrl+C para detener)...\n")
    print(f"{'TIMESTAMP':<20} | {'MOTOR':<8} | {'ALARMA':<8} | {'PIEZAS':<8}")
    print("-" * 55)

    try:
        while True:
            # 1) Leer coils 0..3 (fx=01): motor, alarma, arranque, paro
            res_coils = client.read_coils(address=0, count=4, slave=SLAVE_ID)

            # 2) Leer holding register 0 (fx=03): contador_piezas
            res_registers = client.read_holding_registers(
                address=ADDR_CONTADOR, count=1, slave=SLAVE_ID
            )

            if not res_coils.isError() and not res_registers.isError():
                motor_encendido = bool(res_coils.bits[ADDR_MOTOR])
                alarma_activa = bool(res_coils.bits[ADDR_ALARMA])
                contador_piezas = int(res_registers.registers[0])

                # Estado visual en consola
                str_motor = "ON" if motor_encendido else "OFF"
                str_alarma = "ALERTA" if alarma_activa else "OK"
                ts = time.strftime("%Y-%m-%d %H:%M:%S")

                print(f"{ts:<20} | {str_motor:<8} | {str_alarma:<8} | {contador_piezas:<8}")

                # Persistencia en SQLite (módulo base_datos.py)
                guardar_lectura(motor_encendido, contador_piezas, alarma_activa)
            else:
                print("[CLIENTE] Error al leer registros Modbus.")

            time.sleep(INTERVALO_LECTURA_S)

    except KeyboardInterrupt:
        print("\n[CLIENTE] Lectura detenida por el usuario.")
    finally:
        client.close()
        print("[CLIENTE] Conexión cerrada.")


if __name__ == "__main__":
    leer_plc()
