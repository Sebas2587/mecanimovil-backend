# Configuración de Celery para Producción

## 📋 Tabla de Contenidos

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Arquitectura de Colas](#arquitectura-de-colas)
3. [Parámetros de Configuración](#parámetros-de-configuración)
4. [Recomendaciones por Recursos del Servidor](#recomendaciones-por-recursos-del-servidor)
5. [Configuración de Workers](#configuración-de-workers)
6. [Guía de Deployment](#guía-de-deployment)
7. [Monitoreo y Troubleshooting](#monitoreo-y-troubleshooting)
8. [Ajustes según Carga](#ajustes-según-carga)

---

## Resumen Ejecutivo

Esta configuración de Celery está optimizada para **prevenir sobrecarga de memoria** mediante:

- ✅ **Colas separadas** para tareas pesadas y ligeras
- ✅ **Límites de workers** y memoria por proceso
- ✅ **Prefetch limit** para evitar acumulación de tareas en memoria
- ✅ **Timeouts** para evitar tareas infinitas
- ✅ **Reinicio automático** de workers para prevenir memory leaks

### Configuración Actual

| Cola | Workers | Concurrency | Prefetch | Max Memory | Max Tasks |
|------|---------|-------------|----------|------------|-----------|
| `default` | 1 | 4 | 4 | 512 MB | 100 |
| `heavy` | 1 | 2 | 2 | 512 MB | 50 |

---

## Arquitectura de Colas

### Cola `default` - Tareas Ligeras

**Propósito**: Procesar tareas rápidas que no consumen mucha memoria

**Tareas asignadas**:
- `calcular_salud_vehiculo_async` - Calcula salud de un vehículo individual
- `actualizar_salud_desde_checklist` - Actualiza salud desde un checklist

**Configuración recomendada**:
- **Concurrency**: 4 procesos worker
- **Prefetch**: 4 tareas por worker
- **Max Memory**: 512 MB por worker
- **Max Tasks**: 100 tareas antes de reiniciar

### Cola `heavy` - Tareas Pesadas

**Propósito**: Procesar tareas que requieren más recursos y tiempo

**Tareas asignadas**:
- `procesar_checklists_historicos_batch` - Procesa múltiples vehículos
- `procesar_checklists_historicos_vehiculo` - Procesa checklists históricos de un vehículo
- `recalcular_salud_vehiculos_batch` - Recalcula salud de múltiples vehículos

**Configuración recomendada**:
- **Concurrency**: 2 procesos worker
- **Prefetch**: 2 tareas por worker
- **Max Memory**: 512 MB por worker
- **Max Tasks**: 50 tareas antes de reiniciar
- **Timeouts**: 15 min (soft), 20 min (hard)

---

## Parámetros de Configuración

### 1. Worker Prefetch Multiplier

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.worker_prefetch_multiplier = 4
```

**Descripción**: Número de tareas que cada worker "pre-fetcha" de la cola antes de procesarlas.

**Efecto**:
- **Valor alto (8+)**: Más tareas en memoria, menor latencia, mayor consumo de memoria
- **Valor bajo (1-2)**: Menos tareas en memoria, mayor latencia, menor consumo de memoria

**Recomendación**:
- **Cola `default`**: 4-8
- **Cola `heavy`**: 1-2

### 2. Worker Max Tasks Per Child

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.worker_max_tasks_per_child = 100
```

**Descripción**: Número de tareas que un worker procesa antes de reiniciarse automáticamente.

**Propósito**: Prevenir memory leaks acumulativos. Después de N tareas, el worker se reinicia limpiando memoria.

**Recomendación**:
- **Cola `default`**: 100-200 tareas
- **Cola `heavy`**: 50-100 tareas (reinicia más frecuentemente debido a mayor consumo)

### 3. Worker Max Memory Per Child

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.worker_max_memory_per_child = 512000  # 512 MB en KB
```

**Descripción**: Límite de memoria (en KB) que un worker puede consumir antes de reiniciarse.

**Propósito**: Prevenir que un worker consuma toda la memoria del servidor.

**Cálculo**:
- **Memoria total del servidor**: Ej. 8 GB = 8,388,608 KB
- **Memoria para OS y otros servicios**: ~2 GB = 2,097,152 KB
- **Memoria disponible**: 6 GB = 6,291,456 KB
- **Para 6 workers (4 default + 2 heavy)**: 6,291,456 / 6 = ~1,048,576 KB (1 GB) por worker
- **Configuración conservadora**: 512 MB (512,000 KB) por worker

**Ajuste según servidor**:
- **Servidor con 2 GB RAM**: 128 MB por worker
- **Servidor con 4 GB RAM**: 256 MB por worker
- **Servidor con 8 GB RAM**: 512 MB por worker
- **Servidor con 16+ GB RAM**: 1 GB por worker

### 4. Task Time Limits

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.task_soft_time_limit = 300  # 5 minutos
app.conf.task_time_limit = 600       # 10 minutos
```

**Descripción**:
- **Soft Time Limit**: Lanza excepción `SoftTimeLimitExceeded` pero permite cleanup
- **Hard Time Limit**: Mata el proceso worker si excede el tiempo

**Recomendación**:
- **Tareas ligeras**: 5 min (soft), 10 min (hard)
- **Tareas pesadas**: 15 min (soft), 20 min (hard) - configurado en decoradores

### 5. Task Acknowledge Late

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.task_acks_late = True
```

**Descripción**: El worker solo confirma (ACK) la tarea cuando termina de procesarla, no cuando la recibe.

**Ventaja**: Si el worker muere durante el procesamiento, la tarea se reintenta automáticamente.

**Desventaja**: Si el worker muere frecuentemente, puede haber tareas duplicadas.

### 6. Task Reject On Worker Lost

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.task_reject_on_worker_lost = True
```

**Descripción**: Si el worker muere, rechaza la tarea y la devuelve a la cola para reintentar.

**Propósito**: Garantizar que las tareas se completen incluso si un worker falla.

### 7. Result Expiration

**Archivo**: `mecanimovilapp/celery.py`

```python
app.conf.result_expires = 3600  # 1 hora
```

**Descripción**: Tiempo en segundos antes de que los resultados de tareas expiren en Redis.

**Propósito**: Limpiar automáticamente resultados antiguos para liberar memoria en Redis.

---

## Recomendaciones por Recursos del Servidor

### Servidor Pequeño (2-4 GB RAM, 2-4 CPUs)

**Configuración recomendada**:

```bash
# Worker default
--concurrency=2 --prefetch-multiplier=2 --max-memory-per-child=256000

# Worker heavy
--concurrency=1 --prefetch-multiplier=1 --max-memory-per-child=256000
```

**Total workers**: 3 (2 + 1)  
**Memoria total**: ~768 MB (256 MB × 3)  
**CPU uso**: 75% (3 workers de 4 CPUs)

### Servidor Mediano (4-8 GB RAM, 4-8 CPUs)

**Configuración actual (recomendada)**:

```bash
# Worker default
--concurrency=4 --prefetch-multiplier=4 --max-memory-per-child=512000

# Worker heavy
--concurrency=2 --prefetch-multiplier=2 --max-memory-per-child=512000
```

**Total workers**: 6 (4 + 2)  
**Memoria total**: ~3 GB (512 MB × 6)  
**CPU uso**: 75% (6 workers de 8 CPUs)

### Servidor Grande (16+ GB RAM, 8+ CPUs)

**Configuración recomendada**:

```bash
# Worker default
--concurrency=6 --prefetch-multiplier=6 --max-memory-per-child=1048576

# Worker heavy
--concurrency=3 --prefetch-multiplier=2 --max-memory-per-child=1048576
```

**Total workers**: 9 (6 + 3)  
**Memoria total**: ~9 GB (1 GB × 9)  
**CPU uso**: 75% (9 workers de 12 CPUs)

---

## Configuración de Workers

### Desarrollo

**Archivo**: `scripts/start_celery_dev.sh`

El script inicia automáticamente dos workers:

1. **Worker para cola `default`**:
   ```bash
   celery -A mecanimovilapp worker \
       --queues=default \
       --concurrency=4 \
       --max-tasks-per-child=100 \
       --max-memory-per-child=512000 \
       --prefetch-multiplier=4 \
       --hostname=worker-default@%h
   ```

2. **Worker para cola `heavy`**:
   ```bash
   celery -A mecanimovilapp worker \
       --queues=heavy \
       --concurrency=2 \
       --max-tasks-per-child=50 \
       --max-memory-per-child=512000 \
       --prefetch-multiplier=2 \
       --hostname=worker-heavy@%h
   ```

### Producción (Supervisor)

**Archivo**: `scripts/deploy_production.sh`

Supervisor gestiona automáticamente los workers:

```ini
[program:mecanimovil_celery_default]
command=/var/www/mecanimovil/venv/bin/celery -A mecanimovilapp worker \
    --loglevel=info \
    --queues=default \
    --concurrency=4 \
    --max-tasks-per-child=100 \
    --max-memory-per-child=512000 \
    --prefetch-multiplier=4 \
    --hostname=worker-default@%h

[program:mecanimovil_celery_heavy]
command=/var/www/mecanimovil/venv/bin/celery -A mecanimovilapp worker \
    --loglevel=info \
    --queues=heavy \
    --concurrency=2 \
    --max-tasks-per-child=50 \
    --max-memory-per-child=512000 \
    --prefetch-multiplier=2 \
    --hostname=worker-heavy@%h
```

**Comandos Supervisor**:

```bash
# Ver estado de workers
supervisorctl status

# Reiniciar un worker específico
supervisorctl restart mecanimovil_celery_default
supervisorctl restart mecanimovil_celery_heavy

# Reiniciar todos los workers
supervisorctl restart all

# Ver logs en tiempo real
tail -f /var/log/mecanimovil/celery_default.log
tail -f /var/log/mecanimovil/celery_heavy.log
```

---

## Guía de Deployment

### 1. Verificar Configuración Actual

```bash
cd /var/www/mecanimovil/backend
source venv/bin/activate

# Verificar configuración de Celery
python -c "from mecanimovilapp.celery import app; print(app.conf)"

# Verificar colas configuradas
python -c "from mecanimovilapp.celery import app; print(app.conf.task_routes)"
```

### 2. Actualizar Supervisor (si ya está en producción)

```bash
# Editar configuración de Supervisor
sudo nano /etc/supervisor/conf.d/mecanimovil.conf

# Recargar configuración
sudo supervisorctl reread
sudo supervisorctl update

# Reiniciar workers
sudo supervisorctl restart mecanimovil_celery_default
sudo supervisorctl restart mecanimovil_celery_heavy
```

### 3. Verificar que los Workers Estén Corriendo

```bash
# Ver procesos de Celery
ps aux | grep celery

# Verificar workers conectados
celery -A mecanimovilapp inspect active --destination=worker-default@$(hostname)
celery -A mecanimovilapp inspect active --destination=worker-heavy@$(hostname)

# Ver estadísticas
celery -A mecanimovilapp inspect stats
```

### 4. Verificar Colas en Redis

```bash
# Conectar a Redis
redis-cli

# Ver colas disponibles
KEYS celery*

# Ver tamaño de colas
LLEN celery
LLEN heavy
LLEN default

# Monitorear colas en tiempo real
redis-cli --stat
```

---

## Monitoreo y Troubleshooting

### Comandos de Monitoreo

#### Ver Tareas Activas

```bash
celery -A mecanimovilapp inspect active
```

#### Ver Estadísticas de Workers

```bash
celery -A mecanimovilapp inspect stats
```

Salida ejemplo:
```json
{
    "worker-default@hostname": {
        "total": {
            "tasks.succeeded": 1250,
            "tasks.failed": 5,
            "tasks.retried": 12
        },
        "pool": {
            "max-concurrency": 4,
            "processes": [1234, 1235, 1236, 1237],
            "max-tasks-per-child": 100
        }
    }
}
```

#### Ver Tareas Reservadas (en cola)

```bash
celery -A mecanimovilapp inspect reserved
```

#### Ver Colas y sus Tamaños

```bash
celery -A mecanimovilapp inspect active_queues
```

#### Ver Logs de Workers

```bash
# Desarrollo
tail -f /path/to/celery.log

# Producción
sudo tail -f /var/log/mecanimovil/celery_default.log
sudo tail -f /var/log/mecanimovil/celery_heavy.log
```

### Troubleshooting Común

#### Problema: Workers se quedan sin memoria

**Síntomas**:
- Workers reiniciándose frecuentemente
- Memoria del servidor al 100%
- Tareas fallando con `MemoryError`

**Solución**:
1. Reducir `max-memory-per-child`:
   ```bash
   --max-memory-per-child=256000  # De 512 MB a 256 MB
   ```
2. Reducir `concurrency`:
   ```bash
   --concurrency=2  # De 4 a 2
   ```
3. Reducir `prefetch-multiplier`:
   ```bash
   --prefetch-multiplier=2  # De 4 a 2
   ```

#### Problema: Tareas se acumulan en cola

**Síntomas**:
- Cola creciendo sin procesar
- Workers procesando lentamente
- Muchas tareas en estado "reserved"

**Solución**:
1. Aumentar `concurrency`:
   ```bash
   --concurrency=6  # De 4 a 6
   ```
2. Verificar que los workers estén corriendo:
   ```bash
   supervisorctl status
   ```
3. Verificar que no haya errores en logs:
   ```bash
   tail -f /var/log/mecanimovil/celery_default.log | grep ERROR
   ```

#### Problema: Tareas fallan frecuentemente

**Síntomas**:
- Muchas tareas en estado "failed"
- Errores en logs
- Tareas reintentándose continuamente

**Solución**:
1. Revisar logs de errores:
   ```bash
   grep ERROR /var/log/mecanimovil/celery_default.log
   ```
2. Verificar conexión a base de datos
3. Verificar recursos del servidor (memoria, CPU, disco)
4. Ajustar timeouts si las tareas son muy largas:
   ```python
   @shared_task(time_limit=1200, soft_time_limit=900)  # 20 min / 15 min
   ```

#### Problema: Workers no procesan tareas de cola `heavy`

**Síntomas**:
- Tareas en cola `heavy` no se procesan
- Solo procesa tareas de cola `default`

**Solución**:
1. Verificar que el worker `heavy` esté corriendo:
   ```bash
   supervisorctl status mecanimovil_celery_heavy
   ```
2. Verificar que el worker esté suscrito a la cola `heavy`:
   ```bash
   celery -A mecanimovilapp inspect active_queues --destination=worker-heavy@$(hostname)
   ```
3. Reiniciar el worker:
   ```bash
   supervisorctl restart mecanimovil_celery_heavy
   ```

### Monitoreo de Recursos

#### Memoria

```bash
# Ver uso de memoria por proceso Celery
ps aux | grep celery | awk '{print $2, $4, $11}' | sort -k2 -nr

# Monitorear memoria en tiempo real
watch -n 1 'ps aux | grep "[c]elery" | awk "{sum+=\$4} END {print sum\"%\"}"'
```

#### CPU

```bash
# Ver uso de CPU por proceso Celery
top -p $(pgrep -d',' -f celery)

# Monitorear CPU en tiempo real
htop -p $(pgrep -d',' -f celery)
```

#### Colas de Redis

```bash
# Ver tamaño de colas
redis-cli <<EOF
LLEN celery
LLEN heavy
LLEN default
EOF
```

---

## Ajustes según Carga

### Carga Alta de Tareas Ligeras

**Síntomas**: Cola `default` creciendo rápidamente, tareas ligeras en espera

**Ajustes**:
```bash
# Aumentar workers de cola default
--concurrency=6  # De 4 a 6
--prefetch-multiplier=6  # De 4 a 6
```

### Carga Alta de Tareas Pesadas

**Síntomas**: Cola `heavy` creciendo, tareas pesadas tardan mucho

**Ajustes**:
```bash
# Aumentar workers de cola heavy (con precaución por memoria)
--concurrency=3  # De 2 a 3 (solo si hay memoria disponible)
--prefetch-multiplier=2  # Mantener bajo
```

### Carga Mixta Alta

**Síntomas**: Ambas colas creciendo, sistema lento

**Ajustes**:
1. Escalar horizontalmente: agregar más workers en otro servidor
2. Optimizar tareas pesadas: dividirlas en tareas más pequeñas
3. Aumentar recursos del servidor (RAM, CPU)

### Carga Baja

**Síntomas**: Workers inactivos la mayor parte del tiempo

**Ajustes**:
```bash
# Reducir workers para ahorrar recursos
--concurrency=2  # De 4 a 2 (cola default)
--concurrency=1  # De 2 a 1 (cola heavy)
```

---

## Configuración en Variables de Entorno (Opcional)

Para mayor flexibilidad, puedes mover algunos parámetros a variables de entorno:

**Archivo**: `.env`

```bash
# Celery Workers
CELERY_WORKER_DEFAULT_CONCURRENCY=4
CELERY_WORKER_HEAVY_CONCURRENCY=2
CELERY_WORKER_MAX_MEMORY_MB=512
CELERY_WORKER_PREFETCH_DEFAULT=4
CELERY_WORKER_PREFETCH_HEAVY=2
```

**Archivo**: `mecanimovilapp/settings.py`

```python
import os

CELERY_WORKER_DEFAULT_CONCURRENCY = int(os.environ.get('CELERY_WORKER_DEFAULT_CONCURRENCY', 4))
CELERY_WORKER_HEAVY_CONCURRENCY = int(os.environ.get('CELERY_WORKER_HEAVY_CONCURRENCY', 2))
CELERY_WORKER_MAX_MEMORY_KB = int(os.environ.get('CELERY_WORKER_MAX_MEMORY_MB', 512)) * 1024
```

---

## Checklist de Deployment

- [ ] Verificar que Redis esté corriendo y accesible
- [ ] Verificar que la configuración de `celery.py` esté correcta
- [ ] Verificar que `settings_production.py` tenga los parámetros optimizados
- [ ] Configurar Supervisor con workers separados
- [ ] Verificar que ambos workers (default y heavy) estén corriendo
- [ ] Verificar que las colas estén configuradas correctamente en Redis
- [ ] Probar ejecutar una tarea ligera y una pesada
- [ ] Monitorear uso de memoria y CPU después del deployment
- [ ] Configurar alertas si workers fallan o memoria excede umbrales

---

## Referencias

- [Celery Best Practices](https://docs.celeryproject.org/en/stable/userguide/optimizing.html)
- [Celery Configuration](https://docs.celeryproject.org/en/stable/userguide/configuration.html)
- [Celery Monitoring](https://docs.celeryproject.org/en/stable/userguide/monitoring.html)

---

**Última actualización**: 2025-01-XX  
**Mantenido por**: Equipo Mecanimovil
