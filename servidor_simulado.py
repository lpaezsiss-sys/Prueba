#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
servidor_simulado.py
--------------------
Servidor Modbus TCP que SIMULA un PLC Delta de una línea de embalaje.

NO hay hardware físico: este script actúa como si fuera el PLC.
Más adelante, cuando tengas el PLC Delta real, el CLIENTE solo cambiará
IP/puerto; este servidor ya no será necesario.

Mapa de variables (igual que documentamos para el PLC real):

  COILS (bits, función Modbus 01 lectura / 05 escritura):
    Dirección 0 -> motor_encendido   (bool)  estado del motor
    Dirección 1 -> alarma_activa     (bool)  alarma de paro prolongado
    Dirección 2 -> boton_arranque    (bool)  pulso de arranque (escritura)
    Dirección 3 -> boton_paro        (bool)  pulso de paro (escritura)

  HOLDING REGISTERS (enteros 16-bit, función 03 lectura / 06 escritura):
    Dirección 0 -> contador_piezas   (int)   piezas producidas

Lógica de simulación:
  - Si se escribe boton_arranque=1 -> motor ON, se limpia alarma, se resetea el botón
  - Si se escribe boton_paro=1     -> motor OFF, se resetea el botón
  - Con motor ON, contador_piezas sube cada 2-3 segundos
  - Si el motor está OFF más de 10 segundos seguidos -> alarma_activa=1

Puerto por defecto: 5020 (el 502 oficial suele pedir permisos de administrador).
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartTcpServer

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL SERVIDOR (cámbiala si lo necesitas)
# ---------------------------------------------------------------------------
HOST = "0.0.0.0"   # Escucha en todas las interfaces de red locales
PUERTO = 5020      # Puerto Modbus TCP del simulador (NO uses 502 sin permisos)
UNIT_ID = 1        # ID de esclavo Modbus (en Delta suele ser 1)

# Direcciones de coils (bits)
ADDR_MOTOR = 0
ADDR_ALARMA = 1
ADDR_BOTON_ARRANQUE = 2
ADDR_BOTON_PARO = 3

# Direcciones de holding registers
ADDR_CONTADOR = 0

# Tiempos de la simulación (segundos)
TIEMPO_ALARMA_PARO = 10.0          # Segundos con motor OFF para activar alarma
INTERVALO_PRODUCCION_MIN = 2.0     # Mínimo entre piezas
INTERVALO_PRODUCCION_MAX = 3.0     # Máximo entre piezas
INTERVALO_LOGICA = 0.2             # Cada cuánto revisamos botones / alarma
INTERVALO_ESTADO_CONSOLA = 2.0     # Cada cuánto imprimimos estado en consola

# Códigos de función Modbus usados internamente por pymodbus al leer/escribir
# el datastore (no los envías tú a mano; son constantes de la librería):
FC_COILS = 1              # Lectura/escritura de coils (bits)
FC_HOLDING_REGISTERS = 3  # Lectura/escritura de holding registers


# ---------------------------------------------------------------------------
# LOGGING: mensajes claros en español para ir siguiendo qué hace el servidor
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("servidor_simulado")


def crear_contexto_modbus() -> ModbusServerContext:
    """
    Crea el "mapa de memoria" del PLC simulado.

    Imagina esto como las tablas internas del PLC:
      - co = coils (bits de salida / flags)
      - di = discrete inputs (bits de entrada, no usados aquí)
      - hr = holding registers (registros de 16 bits)
      - ir = input registers (no usados aquí)

    zero_mode=True hace que la dirección 0 del cliente coincida con la
    dirección 0 interna (más intuitivo para aprender).
    """
    # Bloques de 100 direcciones inicializadas a 0 (apagado / cero)
    slave = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [0] * 100),
        co=ModbusSequentialDataBlock(0, [0] * 100),
        hr=ModbusSequentialDataBlock(0, [0] * 100),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
        zero_mode=True,
    )
    # single=True: un solo dispositivo (unit id se ignora / se acepta cualquiera)
    return ModbusServerContext(slaves=slave, single=True)


def leer_coil(context: ModbusServerContext, address: int) -> bool:
    """Lee un bit (coil) del datastore y lo devuelve como True/False."""
    valores = context[UNIT_ID].getValues(FC_COILS, address, count=1)
    return bool(valores[0])


def escribir_coil(context: ModbusServerContext, address: int, valor: bool) -> None:
    """Escribe un bit (coil) en el datastore (0 o 1)."""
    context[UNIT_ID].setValues(FC_COILS, address, [1 if valor else 0])


def leer_registro(context: ModbusServerContext, address: int) -> int:
    """Lee un holding register (entero 0..65535)."""
    valores = context[UNIT_ID].getValues(FC_HOLDING_REGISTERS, address, count=1)
    return int(valores[0])


def escribir_registro(context: ModbusServerContext, address: int, valor: int) -> None:
    """Escribe un holding register (se limita a 16 bits sin signo)."""
    context[UNIT_ID].setValues(FC_HOLDING_REGISTERS, address, [int(valor) & 0xFFFF])


def bucle_simulacion(context: ModbusServerContext, stop_event: threading.Event) -> None:
    """
    Hilo en segundo plano que comporta el PLC de forma autónoma:
    botones, producción de piezas y alarma por paro prolongado.
    """
    log.info("Lógica de simulación iniciada.")

    # Instantes de control interno (no son registros Modbus)
    motor_apagado_desde: float | None = time.monotonic()  # Arranca con motor OFF
    proxima_pieza_en: float = 0.0
    ultimo_log_consola: float = 0.0

    while not stop_event.is_set():
        ahora = time.monotonic()

        # --- 1) Leer botones de arranque / paro (escritos por un cliente Modbus) ---
        boton_arranque = leer_coil(context, ADDR_BOTON_ARRANQUE)
        boton_paro = leer_coil(context, ADDR_BOTON_PARO)
        motor = leer_coil(context, ADDR_MOTOR)

        # Pulso de ARRANQUE: enciende motor, limpia alarma y resetea el botón
        if boton_arranque:
            escribir_coil(context, ADDR_MOTOR, True)
            escribir_coil(context, ADDR_ALARMA, False)
            escribir_coil(context, ADDR_BOTON_ARRANQUE, False)
            motor = True
            motor_apagado_desde = None
            # Programa la primera pieza dentro de 2-3 s
            proxima_pieza_en = ahora + random.uniform(
                INTERVALO_PRODUCCION_MIN, INTERVALO_PRODUCCION_MAX
            )
            log.info(">>> ARRANQUE recibido: motor ON, alarma reseteada.")

        # Pulso de PARO: apaga motor y resetea el botón
        if boton_paro:
            escribir_coil(context, ADDR_MOTOR, False)
            escribir_coil(context, ADDR_BOTON_PARO, False)
            motor = False
            motor_apagado_desde = ahora
            log.info(">>> PARO recibido: motor OFF.")

        # --- 2) Producción: incrementar contador si el motor está ON ---
        if motor:
            # Si por algún motivo no había temporizador, lo creamos
            if proxima_pieza_en <= 0:
                proxima_pieza_en = ahora + random.uniform(
                    INTERVALO_PRODUCCION_MIN, INTERVALO_PRODUCCION_MAX
                )
            if ahora >= proxima_pieza_en:
                piezas = leer_registro(context, ADDR_CONTADOR) + 1
                # Si supera 65535 (límite de un registro de 16 bits), vuelve a 0
                if piezas > 65535:
                    piezas = 0
                escribir_registro(context, ADDR_CONTADOR, piezas)
                proxima_pieza_en = ahora + random.uniform(
                    INTERVALO_PRODUCCION_MIN, INTERVALO_PRODUCCION_MAX
                )
                log.info("Pieza producida. contador_piezas = %s", piezas)
        else:
            proxima_pieza_en = 0.0
            # --- 3) Alarma por paro prolongado (> 10 s con motor OFF) ---
            if motor_apagado_desde is None:
                motor_apagado_desde = ahora
            segundos_apagado = ahora - motor_apagado_desde
            if segundos_apagado >= TIEMPO_ALARMA_PARO and not leer_coil(
                context, ADDR_ALARMA
            ):
                escribir_coil(context, ADDR_ALARMA, True)
                log.warning(
                    "!!! ALARMA: motor apagado durante %.1f s", segundos_apagado
                )

        # --- 4) Estado periódico en consola (para verificar sin cliente aún) ---
        if ahora - ultimo_log_consola >= INTERVALO_ESTADO_CONSOLA:
            ultimo_log_consola = ahora
            estado = (
                f"motor={'ON' if leer_coil(context, ADDR_MOTOR) else 'OFF':<3} | "
                f"alarma={'SI' if leer_coil(context, ADDR_ALARMA) else 'NO':<2} | "
                f"piezas={leer_registro(context, ADDR_CONTADOR):5d} | "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )
            log.info("ESTADO | %s", estado)

        stop_event.wait(INTERVALO_LOGICA)

    log.info("Lógica de simulación detenida.")


def main() -> None:
    """Punto de entrada: prepara datastore, lanza lógica y abre el puerto TCP."""
    context = crear_contexto_modbus()

    # Estado inicial: todo en cero (motor OFF, sin alarma, contador 0)
    escribir_coil(context, ADDR_MOTOR, False)
    escribir_coil(context, ADDR_ALARMA, False)
    escribir_coil(context, ADDR_BOTON_ARRANQUE, False)
    escribir_coil(context, ADDR_BOTON_PARO, False)
    escribir_registro(context, ADDR_CONTADOR, 0)

    stop_event = threading.Event()
    hilo = threading.Thread(
        target=bucle_simulacion,
        args=(context, stop_event),
        name="logica-embalaje",
        daemon=True,  # Se cierra automáticamente al terminar el proceso principal
    )
    hilo.start()

    log.info("=" * 60)
    log.info("Servidor Modbus TCP SIMULADO (línea de embalaje)")
    log.info("Escuchando en %s:%s  (unit/slave id = %s)", HOST, PUERTO, UNIT_ID)
    log.info("Coils: motor=0  alarma=1  arranque=2  paro=3")
    log.info("Holding register: contador_piezas=0")
    log.info("Motor OFF > %.0f s => alarma automática", TIEMPO_ALARMA_PARO)
    log.info("Ctrl+C para detener.")
    log.info("=" * 60)

    try:
        # Bloquea aquí sirviendo peticiones Modbus TCP
        StartTcpServer(
            context=context,
            address=(HOST, PUERTO),
        )
    except KeyboardInterrupt:
        log.info("Interrupción recibida. Cerrando...")
    finally:
        stop_event.set()
        hilo.join(timeout=2.0)
        log.info("Servidor detenido.")


if __name__ == "__main__":
    main()
