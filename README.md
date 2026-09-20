# Simulador de línea de embalaje (Modbus TCP)

Modelo industrial de **planta completa con 3 pulmones de acumulación**, sin
hardware físico. Prepara el salto a un PLC Delta (DVP14SS2 / DVP12SE11R).

## Flujo de planta

```text
Despaletizador → [Pulmón 1] → Llenadora → [Pulmón 2] → Etiquetadora
     → Encajonadora → [Pulmón 3] → Paletizadora
```

## Archivos

| Archivo | Rol |
|---------|-----|
| `servidor_simulado.py` | PLC virtual + lógica de balanceo / interlocks |
| `cliente_lectura.py` | Lectura 1 s + consola + SQLite |
| `base_datos.py` | Persistencia (`embalaje_completo.db` / `registros_planta`) |
| `dashboard.py` | HMI SCADA Streamlit (mímico ISA-101, gauges, fallas) |
| `generar_informe_pdf.py` | Informe técnico PDF (métricas DB + Ladder Delta) |

## Mapa Modbus

### Coils

| Dir | Nombre | Descripción |
|-----|--------|-------------|
| 0 | `st_desp` | Despaletizador ON/OFF |
| 1 | `st_llen` | Llenadora |
| 2 | `st_etiq` | Etiquetadora |
| 3 | `st_encaj` | Encajonadora |
| 4 | `st_palet` | Paletizadora |
| 10 | `falla_etiq` | Comando HMI: falla etiquetadora |
| 11 | `falla_palet` | Comando HMI: falla paletizadora |

### Holding registers

| Dir | Nombre | Descripción |
|-----|--------|-------------|
| 0 | `cnt_desp` | Contador despaletizador |
| 1 | `cnt_llen` | Contador llenadora |
| 2 | `cnt_palet` | Contador palets |
| 10 | `pulmon_1` | Nivel % pre-llenadora |
| 11 | `pulmon_2` | Nivel % pre-etiquetadora |
| 12 | `pulmon_3` | Nivel % pre-paletizadora |
| 20 | `velocidad_bph` | Botellas/hora estimadas |

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Arranque (3 terminales)

```bash
# T1 — PLC simulado (:5020)
python servidor_simulado.py

# T2 — logger + SQLite
python cliente_lectura.py

# T3 — dashboard (:8501)
streamlit run dashboard.py --server.port 8501
```

Abre `http://localhost:8501`.

### Experimento recomendado

1. En el dashboard (sidebar), pulsa **Simular Paro por Cambio de Rollo en Etiquetadora**
2. Observa cómo **Pulmón 2** sube y la **Llenadora** se para al llegar a ≥85–90%
3. Luego **Pulmón 1** satura y frena el **Despaletizador**
4. Pulsa **Restablecer Planta** y mira cómo se vacían los pulmones

### Informe técnico PDF

Con datos en `embalaje_completo.db`:

```bash
python generar_informe_pdf.py
```

Genera `Informe_Tecnico_SCADA_PLC_Delta.pdf` (métricas SCADA, mapa M/D Delta y rungs Ladder).

## PLC Delta real

En `cliente_lectura.py` y `dashboard.py` cambia solo:

```python
PLC_IP = "192.168.1.XX"
PLC_PORT = 502
SLAVE_ID = 1
```

## Lógica de interlocks (resumen)

- Falla etiquetadora → Etiquetadora OFF → Pulmón 2 carga → ≥90% para Llenadora
- Llenadora OFF → Pulmón 1 carga → ≥90% para Despaletizador
- Falla paletizadora → Pulmón 3 carga → ≥90% para Encajonadora
- Al recuperar la falla, los pulmones se vacían y las máquinas vuelven ON
