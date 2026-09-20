# Simulador de línea de embalaje (Modbus TCP)

Proyecto de aprendizaje para preparar la automatización de una PYME con un
**PLC Delta** (DVP14SS2 / DVP12SE11R). Por ahora **no hay hardware físico**:
simulamos el PLC con un servidor Modbus TCP en Python.

## Estado del proyecto

| Paso | Componente              | Archivo                 | Estado        |
|------|-------------------------|-------------------------|---------------|
| 1    | Servidor Modbus TCP     | `servidor_simulado.py`  | **Listo**     |
| 2    | Cliente de lectura      | `cliente_lectura.py`    | **Listo**     |
| 3    | Dashboard web           | `dashboard.py`          | **Listo**     |
| 4    | Persistencia SQLite     | `base_datos.py`         | **Listo**     |

---

## Paso 1 — Servidor Modbus simulado

### ¿Qué hace?

Actúa como si fuera el PLC de la línea de embalaje:

- Expone bits y registros por **Modbus TCP**
- Simula producción de piezas mientras el motor está ON
- Activa una alarma si el motor lleva más de **10 segundos** apagado
- Responde a pulsaciones de arranque / paro escritas por un cliente Modbus

### Mapa de variables (guarda este mapa: lo usará el cliente y el PLC real)

| Variable           | Tipo Modbus         | Dirección | Descripción                                      |
|--------------------|---------------------|-----------|--------------------------------------------------|
| `motor_encendido`  | Coil (bit)          | 0         | Estado del motor (1=ON, 0=OFF)                   |
| `alarma_activa`    | Coil (bit)          | 1         | Alarma por paro prolongado                       |
| `boton_arranque`   | Coil (bit)          | 2         | Escribir `1` para arrancar (se resetea solo)     |
| `boton_paro`       | Coil (bit)          | 3         | Escribir `1` para parar (se resetea solo)        |
| `contador_piezas`  | Holding Register    | 0         | Piezas producidas (sube cada 2–3 s con motor ON) |

### Requisitos

- Python 3.10+ (probado con 3.12)
- Sistema: Windows, macOS o Linux (este entorno de desarrollo es Linux)

### Instalación (una sola vez)

```bash
cd <carpeta-del-proyecto>
python -m venv .venv

# Windows:
.venv\Scripts\activate

# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Ejecutar el servidor

```bash
python servidor_simulado.py
```

Deberías ver algo como:

```text
Servidor Modbus TCP SIMULADO (línea de embalaje)
Escuchando en 0.0.0.0:5020  (unit/slave id = 1)
ESTADO | motor=OFF | alarma=NO | piezas=    0 | ...
```

Tras ~10 segundos con el motor apagado:

```text
!!! ALARMA: motor apagado durante 10.x s
ESTADO | motor=OFF | alarma=SI | piezas=    0 | ...
```

### Datos de conexión (para el futuro cliente / PLC)

| Parámetro     | Valor (simulador) | Valor típico PLC Delta |
|---------------|-------------------|------------------------|
| Protocolo     | Modbus TCP        | Modbus TCP (o RTU)     |
| IP            | `127.0.0.1`       | IP del PLC en la red   |
| Puerto        | `5020`            | `502`                  |
| Unit / Slave  | `1`               | `1` (configurable)     |

> **Nota:** usamos el puerto **5020** porque el 502 oficial en muchos sistemas
> requiere permisos de administrador. Cuando conectes al PLC real, cambiarás
> solo IP y puerto en el cliente.

### Cómo probar el arranque/paro sin el cliente todavía

Con el servidor en marcha, en **otra terminal** (misma carpeta / venv):

```bash
python -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('127.0.0.1', port=5020)
assert c.connect()
# Arrancar motor (escribir coil 2 = 1)
c.write_coil(2, True, slave=1)
import time; time.sleep(1)
r = c.read_coils(0, 4, slave=1)
h = c.read_holding_registers(0, 1, slave=1)
print('coils motor,alarma,arr,paro =', r.bits[:4])
print('contador =', h.registers[0])
c.close()
"
```

Deberías ver `motor=True` y la alarma en `False`. En la consola del servidor
aparecerá `>>> ARRANQUE recibido` y luego `Pieza producida...`.

Para parar:

```bash
python -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('127.0.0.1', port=5020)
c.connect()
c.write_coil(3, True, slave=1)  # boton_paro
c.close()
"
```

### Detener el servidor

En la terminal del servidor: `Ctrl+C`.

---

## Paso 2 — Cliente de lectura (`cliente_lectura.py`)

Lee el PLC/simulador cada 1 s, imprime en consola y guarda en SQLite.

### Orden de arranque

```bash
# Terminal 1 — servidor simulado
python servidor_simulado.py

# Terminal 2 — cliente
python cliente_lectura.py
```

Salida esperada:

```text
TIMESTAMP            | MOTOR    | ALARMA   | PIEZAS
-------------------------------------------------------
2026-09-20 13:30:01  | OFF      | ALERTA   | 2
```

### Cambio para PLC Delta real

En `cliente_lectura.py` solo modifica:

```python
PLC_IP = "192.168.1.XX"  # IP del PLC
PLC_PORT = 502           # Puerto Modbus TCP del Delta
SLAVE_ID = 1             # Si tu PLC usa otro unit id
```

El resto de la lógica (lectura, print, `guardar_lectura`) no se reescribe.

Detener el cliente: `Ctrl+C`.

---

## Paso 3 — Dashboard web (`dashboard.py`)

Panel Streamlit en tiempo real: motor, piezas, alarma, botonera HMI y gráfica.

### Orden de arranque (3 terminales)

```bash
# Terminal 1 — PLC simulado
python servidor_simulado.py

# Terminal 2 — cliente que llena embalaje.db
python cliente_lectura.py

# Terminal 3 — dashboard
streamlit run dashboard.py --server.port 8501
```

Abre el navegador en `http://localhost:8501`.

- **ARRANCAR / PARAR** escriben coils 2 / 3 por Modbus TCP
- Los indicadores leen el último registro de `embalaje.db` (por eso hace falta el cliente)
- Auto-actualización cada ~1.5 s

Para PLC Delta real: cambia `PLC_IP` / `PLC_PORT` al inicio de `dashboard.py`.

---

## Paso 4 — Persistencia SQLite (`base_datos.py`)

Guarda cada lectura (timestamp, motor, contador, alarma) en `embalaje.db`.
No habla Modbus: solo recibe valores ya leídos. El futuro cliente lo usará así:

```python
from base_datos import init_db, guardar_lectura, reporte_produccion_dia

init_db()
guardar_lectura(motor_encendido=True, contador_piezas=12, alarma_activa=False)
print(reporte_produccion_dia())  # resumen del día
```

Prueba aislada (sin servidor):

```bash
python base_datos.py
```

Se crea `embalaje.db` en la carpeta del proyecto (está en `.gitignore`).

---

## Proyecto completo

Con los 4 archivos listos, el flujo local es:

`servidor_simulado.py` → `cliente_lectura.py` → `embalaje.db` → `dashboard.py`

Cuando tengas el PLC Delta, apaga el servidor simulado y apunta cliente + dashboard
a la IP/puerto reales.
