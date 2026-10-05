# tableros-sigma

Tableros de control para gerentes de ventas (y, más adelante, vendedores) a partir de la
**API Sigma v10** (`sigma.sig2k.com`). Proyecto independiente del de las marcas que se leen por ODBC.

```
API Sigma ──(ETL, cron 06:00 y 16:00)──> data/silver/*.parquet ──> dashboards/ (Streamlit + login)
```

## Estructura

| Ruta | Qué hay |
|---|---|
| `src/sigma_conn/client.py` | Cliente **solo lectura** (bloquea `Import*`/`Modificacion*`), secuencial, reintenta 429 con `X-Retry-After-ms` |
| `src/sigma_conn/transform.py` | JSON -> tablas; normaliza typos de la API; venta neta, NC, anuladas |
| `src/sigma_conn/store.py` | Parquet/CSV con escritura atómica; hechos particionados por mes |
| `src/sigma_conn/etl.py` | Pipeline (dimensiones completas + ventana móvil de ventas) |
| `scripts/etl/run_etl.py` | CLI para cron |
| `scripts/etl/probe_pagination.py` | Prueba si la API respeta `page`/`pagesize` |
| `dashboards/` | (siguiente etapa) |
| `tests/` | Tests unitarios y de punta a punta |

## Puesta en marcha (VM `n8npeji`)

```bash
git clone <repo> && cd tableros-sigma
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # completar SIGMA_TOKEN; chmod 600 .env
python scripts/etl/probe_pagination.py          # 1) ¿funciona page/pagesize?
python scripts/etl/run_etl.py --desde 2026-04-01   # 2) carga inicial (6 meses)
python -m pytest                                # 3) tests
```

Cron (06:00 y 16:00, hora del servidor):

```cron
0 6 * * *  cd /opt/tableros-sigma && .venv/bin/python scripts/etl/run_etl.py >> logs/etl.log 2>&1
0 16 * * * cd /opt/tableros-sigma && .venv/bin/python scripts/etl/run_etl.py --solo ventas >> logs/etl.log 2>&1
```

**Rendimiento de la API:** la espera (429) se paga *después* de cada llamada y es proporcional a las filas
que devolvió (~12 s por cada 1.000), también entre corridas distintas. Por eso el ETL hace **una sola llamada
grande** por endpoint (`SIGMA_PAGE_SIZE=200000`, `SIGMA_CHUNK_DAYS=90`; la API corta respuestas de más de ~200 MB): la corrida diaria tarda segundos y la
carga de 6 meses (~157.000 ítems) son 2 llamadas, con una espera de ~15 min entre ambas. Correr el ETL varias veces seguidas SÍ espera (cooldown de la
corrida anterior); en producción (6:00 y 16:00) no.

Cada corrida escribe `data/_meta/last_run.json` (estado, filas, duración): el tablero puede
mostrar "actualizado a las HH:MM" y avisar si la última corrida falló. El ETL usa un lock
(`data/.etl.lock`) para no superponer corridas.

## Tablas (`data/silver/`)

| Tabla | Origen | Carga |
|---|---|---|
| `fact_ventas_item/AAAA-MM` | `ExportArticulosVendidos` + estado de `ExportFacturas` | ventana móvil (35 días) |
| `dim_factura/AAAA-MM` | `ExportFacturas` | ventana móvil |
| `dim_cliente`, `cliente_vendedor` | `ExportClientes` | completa |
| `dim_articulo` | `ExportArticulos` | completa |
| `dim_vendedor` | `ExportVendedores` | completa |
| `saldos` | `ExportClientesCtaCte` | completa (snapshot) |

## Reglas de negocio verificadas con datos reales

- `unidades` está en **unidades sueltas**. Bultos = `unidades / dim_articulo.unidades_por_bulto`.
- Las **notas de crédito** tienen `unidades` negativas (`es_nc = True`): sumar directo las resta.
- Los comprobantes **anulados** vienen incluidos en la API. Usar siempre
  `transform.ventas_validas(df)` (excluye `estado == "anulada"`).
- `importe_neto = unidades × precio × (1 − descuento%) × (1 − descuento_global%)`.
  Concilia con el subtotal de la factura en ~86% de los casos; **falta investigar el resto**.
- Hay días sin facturación (ej. 15/09/2026): no es un error de carga.

## Seguridad

- El token de `Api_Sigma` también permite **escribir** en el ERP. El cliente solo admite `Export*`,
  pero conviene pedir un token de solo lectura si SIGMA lo permite.
- `.env` y `data/` están en `.gitignore` (los datos incluyen clientes, CUIT y direcciones).
- Si un token se expone, regenerarlo en SIGMA (invalida el anterior).
- Si `conf_ApiSigma_Vendedores`/`Supervisores` están definidas para el token, la API **filtra en
  silencio** clientes y vendedores: verificar que `dim_vendedor` tenga todos.

## Pendiente

- [ ] Correr `probe_pagination.py` contra la API real.
- [ ] Probar la ruta Parquet (los tests corren con CSV; `pyarrow` va en `requirements.txt`).
- [ ] Definir con los gerentes los KPIs y cargar el Excel de objetivos (unidades).
- [ ] Pedidos (`ExportPedidos`): confirmar cómo traer los cumplidos/anulados antes de incluirlos.
- [ ] Dashboards Streamlit + login (gerentes ven todo; vendedores solo su `vendedor_id`).
