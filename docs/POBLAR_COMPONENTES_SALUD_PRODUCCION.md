# Poblar Componentes de Salud en Producción

## Problema

Las métricas de salud de vehículos aparecen en **0%** y no se muestran estados de componentes porque:

1. **No existen `ComponenteSaludConfig` activos** en la base de datos de producción
2. El sistema necesita estas configuraciones para calcular la salud de los componentes (Aceite Motor, Filtros, Bujías, etc.)
3. Sin configuraciones, no se pueden crear `ComponenteSaludVehiculo` ni calcular métricas

## Solución

Ejecutar el comando de management que crea las configuraciones iniciales de componentes de salud.

> **IMPORTANTE:** El sistema ahora diferencia entre vehículos **Gasolina** y **Diésel**, creando componentes específicos para cada tipo de motor.

---

## Pasos para Ejecutar en Producción

### Opción 1: Usando Render Shell (Recomendado)

1. **Acceder a Render Shell:**
   - Ve a tu dashboard de Render: https://dashboard.render.com
   - Selecciona el servicio `mecanimovil-api`
   - Haz clic en **"Shell"** en el menú lateral
   - Se abrirá una terminal en el navegador

2. **Ejecutar el comando:**
   ```bash
   python manage.py populate_health_components
   ```

3. **Verificar la salida:**
   Deberías ver algo como:
   ```
   Iniciando población de componentes de salud...
   
   ✓ Creado: Aceite Motor
   ✓ Creado: Filtro de Aire
   ✓ Creado: Filtro de Aceite
   ✓ Creado: Batería
   ✓ Creado: Neumáticos
   ✓ Creado: Pastillas de Freno
   ✓ Creado: Discos de Freno
   ✓ Creado: Amortiguadores
   ✓ Creado: Líquido de Frenos
   ✓ Creado: Refrigerante
   ✓ Creado: Bujías (Solo Gasolina)
   ✓ Creado: Filtro de Bencina (Solo Gasolina)
   ✓ Creado: Correa de Distribución (Solo Gasolina)
   ✓ Creado: Bujías Incandescentes (Solo Diésel)
   ✓ Creado: Filtro de Petróleo (Solo Diésel)
   ✓ Creado: Correa de Distribución (Solo Diésel)
   ✓ Creado: Filtro de Partículas (DPF) (Solo Diésel)
   ✓ Creado: Inyectores Diésel (Solo Diésel)
   ✓ Creado: Válvula EGR (Solo Diésel)
   
   ============================================================
   ✅ Proceso completado: 19 creados, 0 actualizados
   
   📊 Resumen:
      - Componentes comunes (todos): 10
      - Componentes solo Gasolina:   3
      - Componentes solo Diésel:     6
      - Total:                       19
   ```

### Opción 2: Usando Django Management Command desde Local

Si tienes acceso SSH o puedes conectarte directamente:

```bash
# Conectarte al servidor de producción (ajusta según tu configuración)
ssh usuario@servidor

# O si usas Render CLI
render shell mecanimovil-api

# Ejecutar el comando
cd /path/to/mecanimovil-backend
python manage.py populate_health_components
```

---

## Componentes que se Crean

El comando crea **19 componentes de salud** diferenciados por tipo de motor:

### Componentes Comunes (Todos los motores) - 10 componentes

| Componente | Intervalo de Cambio |
|------------|---------------------|
| Aceite Motor | 10,000 km |
| Filtro de Aire | 15,000 km |
| Filtro de Aceite | 10,000 km |
| Batería | 48 meses |
| Neumáticos | 40,000 km |
| Pastillas de Freno | 35,000 km |
| Discos de Freno | 70,000 km |
| Amortiguadores | 80,000 km |
| Líquido de Frenos | 30,000 km o 24 meses |
| Refrigerante | 40,000 km o 24 meses |

### Componentes Solo Gasolina - 3 componentes

| Componente | Intervalo de Cambio | Descripción |
|------------|---------------------|-------------|
| Bujías | 30,000 km | Bujías de encendido estándar |
| Filtro de Bencina | 40,000 km | Filtro de combustible gasolina |
| Correa de Distribución | 100,000 km | Correa del motor a gasolina |

### Componentes Solo Diésel - 6 componentes

| Componente | Intervalo de Cambio | Descripción |
|------------|---------------------|-------------|
| Bujías Incandescentes | 100,000 km | Calentadores/Precalentadores - duran más que bujías normales |
| Filtro de Petróleo | 20,000 km | Filtro de combustible diésel - cambio más frecuente |
| Correa de Distribución | 120,000 km | Correa del motor diésel - intervalo mayor |
| Filtro de Partículas (DPF) | 150,000 km | Componente exclusivo de diésel moderno |
| Inyectores Diésel | 200,000 km | Sistema de inyección diésel |
| Válvula EGR | 80,000 km | Recirculación de gases de escape |

> **Nota:** El sistema selecciona automáticamente los componentes según el tipo de motor registrado en el vehículo.

---

## Después de Ejecutar el Comando

### 1. Verificar que se Crearon

Puedes verificar en el Django Admin:
- URL: `https://mecanimovil-api.onrender.com/admin/vehiculos/componentesaludconfig/`
- Deberías ver los 12 componentes listados

### 2. Recalcular Salud de Vehículos Existentes

Una vez creados los componentes, necesitas recalcular la salud de los vehículos que ya existen:

**Opción A: Desde la App (Automático)**
- Al abrir la pantalla de salud de un vehículo, el sistema detectará que no hay estado y lo calculará automáticamente
- Esto puede tardar unos segundos la primera vez

**Opción B: Forzar Cálculo desde API**

Puedes hacer una petición GET a:
```
GET https://mecanimovil-api.onrender.com/api/vehiculos/health/vehicle/{vehicle_id}/
```

Esto iniciará el cálculo automáticamente si no existe.

**Opción C: Usando Django Shell (Avanzado)**

```bash
# En Render Shell
python manage.py shell

# En el shell de Python
from mecanimovilapp.apps.vehiculos.tasks import calcular_estado_salud_interno
from mecanimovilapp.apps.vehiculos.models import Vehiculo

# Recalcular todos los vehículos
for vehiculo in Vehiculo.objects.all():
    print(f"Calculando salud para vehículo {vehiculo.id}...")
    calcular_estado_salud_interno(vehiculo.id)
    print(f"✅ Completado")
```

### 3. Verificar que Funciona

1. **Abre la app móvil**
2. **Ve a "Mis Vehículos"**
3. **Selecciona un vehículo**
4. **Abre la pantalla de "Salud del Vehículo"**
5. **Deberías ver:**
   - Porcentaje de salud general (inicialmente 100% si es un vehículo nuevo)
   - Lista de componentes con sus estados
   - Métricas de componentes óptimos, en atención, urgentes, críticos

---

## Notas Importantes

### Sobre las Métricas Iniciales

- **Vehículos nuevos sin servicios:** Inicialmente mostrarán **100% de salud** en todos los componentes
- **La salud se degrada** según:
  - Kilometraje del vehículo
  - Tiempo desde el último servicio
  - Edad del vehículo
  - Servicios completados

### Sobre Celery

- El cálculo de salud puede ejecutarse de forma **asíncrona** usando Celery
- Si Celery no está disponible, se calcula **sincrónicamente** (puede tardar 1-2 segundos)
- Verifica que `mecanimovil-celery-worker` esté corriendo en Render

### Sobre el Cache

- Los datos de salud se guardan en **Redis** para respuesta rápida
- Si cambias configuraciones, el cache se invalida automáticamente
- Puedes forzar recálculo desde la app usando el botón de "Actualizar"

---

## Troubleshooting

### Problema: "No se crean los componentes"

**Solución:**
- Verifica que tienes permisos de superusuario o staff
- Revisa los logs en Render para ver errores
- Asegúrate de estar en el directorio correcto del proyecto

### Problema: "Las métricas siguen en 0 después de crear componentes"

**Solución:**
1. Verifica que los componentes estén **activos** (`activo=True`) en el admin
2. Fuerza el recálculo de salud desde la app (botón "Actualizar")
3. Verifica que Celery esté funcionando si usas cálculo asíncrono
4. Revisa los logs de la API para ver si hay errores en el cálculo

### Problema: "No aparecen componentes en la app"

**Solución:**
- Verifica que el endpoint `/api/vehiculos/health/vehicle/{id}/` esté respondiendo
- Revisa la consola del navegador/app para ver errores de red
- Asegúrate de que el vehículo pertenezca al usuario autenticado

---

## Comandos Útiles

```bash
# Ver componentes creados
python manage.py shell
>>> from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig
>>> ComponenteSaludConfig.objects.filter(activo=True).count()
# Debería mostrar 12

# Ver estados de salud de vehículos
>>> from mecanimovilapp.apps.vehiculos.models_health import EstadoSaludVehiculo
>>> EstadoSaludVehiculo.objects.count()
# Debería mostrar el número de vehículos con salud calculada

# Recalcular salud de un vehículo específico
>>> from mecanimovilapp.apps.vehiculos.tasks import calcular_estado_salud_interno
>>> calcular_estado_salud_interno(1)  # Reemplaza 1 con el ID del vehículo
```

---

## Referencias

- **Comando:** `mecanimovilapp/apps/vehiculos/management/commands/populate_health_components.py`
- **Modelos:** `mecanimovilapp/apps/vehiculos/models_health.py`
- **Tareas Celery:** `mecanimovilapp/apps/vehiculos/tasks.py`
- **API Endpoint:** `/api/vehiculos/health/vehicle/{id}/`
