#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
servidor_simulado.py
--------------------
Modelo industrial de línea COMPLETA con 3 pulmones de acumulación.

Flujo de planta:

  Despaletizador → [Pulmón 1] → Llenadora → [Pulmón 2] → Etiquetadora
       → Encajonadora → [Pulmón 3] → Paletizadora

Mapa Modbus TCP (zero_mode=True, puerto 5020):

  COILS
    0  st_desp      Despaletizador ON/OFF
    1  st_llen      Llenadora ON/OFF
    2  st_etiq      Etiquetadora ON/OFF
    3  st_encaj     Encajonadora ON/OFF
    4  st_palet     Paletizadora ON/OFF
   10  falla_etiq   comando HMI: 1 = falla etiquetadora
   11  falla_palet  comando HMI: 1 = falla paletizadora

  HOLDING REGISTERS
    0  cnt_desp     contador despaletizador
    1  cnt_llen     contador llenadora
    2  cnt_palet    contador paletizadora
   10  pulmon_1     nivel % 0-100 (pre-llenadora)
   11  pulmon_2     nivel % 0-100 (pre-etiquetadora)
   12  pulmon_3     nivel % 0-100 (pre-paletizadora)
   20  velocidad_bph  botellas/hora estimadas
"""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
HOST = "0.0.0.0"
PUERTO = 5020

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PLC_Planta_Completa")

# Coils iniciales: máquinas 0-4 en ON; fallas 10-11 en OFF
_coil_init = [0] * 32
_coil_init[0:5] = [1, 1, 1, 1, 1]
block_coils = ModbusSequentialDataBlock(0, _coil_init)

# Holding registers: pulmones iniciales + velocidad nominal
_hr_init = [0] * 32
_hr_init[10:13] = [20, 10, 5]  # P1, P2, P3 en %
_hr_init[20] = 2400
block_registers = ModbusSequentialDataBlock(0, _hr_init)

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 32),
    co=block_coils,
    hr=block_registers,
    ir=ModbusSequentialDataBlock(0, [0] * 32),
    zero_mode=True,
)
context = ModbusServerContext(slaves=store, single=True)


def _bit(v) -> int:
    return 1 if v else 0


def _u16(v: int) -> int:
    return int(v) & 0xFFFF


async def simular_balanceo_planta(contexto: ModbusServerContext) -> None:
    """Lógica de control en cascada y dinámica de acumulación (1 ciclo/s)."""
    logger.info(">>> Modelo de simulación de planta completa iniciado.")

    while True:
        await asyncio.sleep(1)
        slave = contexto[0]

        # Lectura de comandos de falla (los escribe el dashboard / HMI)
        coils = slave.getValues(1, 0, count=12)
        falla_etiq = bool(coils[10])
        falla_palet = bool(coils[11])

        regs = slave.getValues(3, 0, count=21)
        cnt_desp, cnt_llen, cnt_palet = int(regs[0]), int(regs[1]), int(regs[2])
        p1, p2, p3 = int(regs[10]), int(regs[11]), int(regs[12])

        # --- REGLA 1: estados deseados + fallas simuladas ---
        # Cada ciclo partimos de "quiero producir"; las fallas y los interlocks
        # pueden apagar máquinas. Así el interlock se recupera solo al bajar %.
        st_desp = True
        st_llen = True
        st_etiq = not falla_etiq
        st_encaj = True
        st_palet = not falla_palet

        # --- REGLA 2: Pulmón 2 (Post-Llenadora / Pre-Etiquetadora) ---
        if st_llen and not st_etiq:
            p2 = min(100, p2 + 10)
            if p2 >= 90:
                st_llen = False
                logger.warning(
                    "[PLC] Pulmón 2 ALTO (>=90%%) -> Paro preventivo de Llenadora"
                )
        elif st_etiq and p2 > 0:
            p2 = max(0, p2 - 15)

        # --- REGLA 3: Pulmón 1 (Pre-Llenadora) ---
        if st_desp and not st_llen:
            p1 = min(100, p1 + 8)
            if p1 >= 90:
                st_desp = False
                logger.warning(
                    "[PLC] Pulmón 1 ALTO (>=90%%) -> Paro preventivo de Despaletizador"
                )
        elif st_llen and p1 > 0:
            p1 = max(0, p1 - 5)

        # --- REGLA 4: Pulmón 3 (Pre-Paletizadora) ---
        if st_encaj and not st_palet:
            p3 = min(100, p3 + 12)
            if p3 >= 90:
                st_encaj = False
                logger.warning(
                    "[PLC] Pulmón 3 ALTO (>=90%%) -> Paro preventivo de Encajonadora"
                )
        elif st_palet and p3 > 0:
            p3 = max(0, p3 - 10)

        # --- REGLA 5: Conteo de producción ---
        if st_llen:
            cnt_llen = _u16(cnt_llen + 10)
            cnt_desp = _u16(cnt_desp + 10)
        if st_palet:
            cnt_palet = _u16(cnt_palet + 1)

        # --- REGLA 6: Velocidad BPH estimada ---
        if st_llen and st_etiq and st_palet:
            velocidad_bph = 2400
        elif st_llen and st_etiq:
            velocidad_bph = 1800
        elif st_llen:
            velocidad_bph = 900
        else:
            velocidad_bph = 0

        # Escritura al datastore Modbus
        slave.setValues(
            1,
            0,
            [
                _bit(st_desp),
                _bit(st_llen),
                _bit(st_etiq),
                _bit(st_encaj),
                _bit(st_palet),
            ],
        )
        slave.setValues(3, 0, [cnt_desp, cnt_llen, cnt_palet])
        slave.setValues(3, 10, [p1, p2, p3])
        slave.setValues(3, 20, [_u16(velocidad_bph)])

        logger.info(
            "D=%s L=%s E=%s C=%s P=%s | P1=%3d%% P2=%3d%% P3=%3d%% | "
            "Llen=%d Pal=%d | BPH=%d | fallas E=%s P=%s",
            "ON" if st_desp else "--",
            "ON" if st_llen else "--",
            "ON" if st_etiq else "--",
            "ON" if st_encaj else "--",
            "ON" if st_palet else "--",
            p1,
            p2,
            p3,
            cnt_llen,
            cnt_palet,
            velocidad_bph,
            falla_etiq,
            falla_palet,
        )


async def main() -> None:
    asyncio.create_task(simular_balanceo_planta(context))
    logger.info("=" * 64)
    logger.info("Servidor Modbus TCP — Planta completa (3 pulmones)")
    logger.info("Escuchando en %s:%s", HOST, PUERTO)
    logger.info("Coils 0-4 máquinas | 10-11 fallas | HR 0-2 cnt | 10-12 %% | 20 BPH")
    logger.info("Ctrl+C para detener.")
    logger.info("=" * 64)
    await StartAsyncTcpServer(context=context, address=(HOST, PUERTO))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServidor detenido.")
