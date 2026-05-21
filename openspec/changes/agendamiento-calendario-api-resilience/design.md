# Diseño — API disponibilidad con duración

## Servicio `disponibilidad_proveedor.py`

### `duracion_rango_oferta(oferta)`
Orden de precedencia:
1. `duracion_maxima_minutos` / `duracion_minima_minutos`
2. `duracion_estimada` (TimeField → minutos desde medianoche)
3. `servicio.duracion_estimada_base` (DurationField → `total_seconds // 60`)
4. Default 60 minutos

### `disponibilidad_con_duracion(...)`
1. Busca `HorarioProveedor` activo para `dia_semana` del proveedor.
2. Sin horario → `proveedor_disponible: false`, slots vacíos.
3. Carga oferta filtrada por taller/mecánico del path.
4. Calcula intervalos ocupados del día, ventanas libres, slots cada 15 min.
5. Si fecha es hoy, filtra slots pasados.
6. Devuelve slots vía `_slots_json_safe`.

### `dias_con_slots`
Itera días llamando `disponibilidad_con_duracion`; captura excepciones por día (log + skip).

## Vistas (`views.py`)

Ambos viewsets exponen las mismas acciones. En error no controlado en `disponibilidad_con_duracion`:
- Log `logger.exception`
- Response 200 con payload vacío y `tipo_proveedor` / `proveedor_id`

## Pruebas manuales

```http
GET /api/usuarios/mecanicos-domicilio/{mecanico_id}/horarios_semanales/
GET /api/usuarios/mecanicos-domicilio/{mecanico_id}/dias_disponibles_agenda/?oferta_servicio_id={oferta_id}
GET /api/usuarios/mecanicos-domicilio/{mecanico_id}/disponibilidad_con_duracion/?fecha=2026-05-27&oferta_servicio_id={oferta_id}
```

Esperado: status 200; si hay horario y ventanas, `slots_disponibles.length > 0`.
