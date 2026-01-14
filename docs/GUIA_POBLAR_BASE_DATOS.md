# 📊 Guía Completa: Poblar Base de Datos para Producción

Guía paso a paso para poblar la base de datos de producción con todos los datos necesarios para que la aplicación funcione correctamente tanto para usuarios como para proveedores.

---

## 📋 Tabla de Contenidos

1. [Requisitos Previos](#1-requisitos-previos)
2. [Orden de Ejecución](#2-orden-de-ejecución)
3. [Paso 1: Migraciones](#3-paso-1-migraciones)
4. [Paso 2: Categorías de Servicios](#4-paso-2-categorías-de-servicios)
5. [Paso 3: Marcas y Modelos de Vehículos](#5-paso-3-marcas-y-modelos-de-vehículos)
6. [Paso 4: Repuestos](#6-paso-4-repuestos)
7. [Paso 5: Catálogo de Checklists](#7-paso-5-catálogo-de-checklists)
8. [Paso 6: Sistema de Créditos](#8-paso-6-sistema-de-créditos)
9. [Paso 7: Comunas de Chile](#9-paso-7-comunas-de-chile)
10. [Paso 8: Superusuario](#10-paso-8-superusuario)
11. [Paso 9: Verificación](#11-paso-9-verificación)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Requisitos Previos

### 1.1 Conectarse a Producción

Tienes dos opciones para ejecutar comandos en producción:

#### Opción A: Shell de Render (Recomendado)
1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Selecciona el servicio `mecanimovil-api`
3. Haz clic en **"Shell"** en el menú lateral
4. Se abrirá una terminal en el navegador

#### Opción B: SSH
```bash
ssh srv-XXXXX@ssh.oregon.render.com
cd /opt/render/project/src
```

### 1.2 Verificar que el Deploy Esté Completo

Antes de ejecutar comandos, asegúrate de que el último deploy esté completo:
- Ve a Render Dashboard → `mecanimovil-api` → **"Events"**
- Verifica que el último deploy esté en estado **"Live"** (verde)

---

## 2. Orden de Ejecución

**⚠️ IMPORTANTE:** Ejecuta los comandos en este orden específico, ya que algunos dependen de datos creados por comandos anteriores.

```
1. Migraciones
2. Categorías de Servicios
3. Marcas y Modelos de Vehículos
4. Repuestos
5. Catálogo de Checklists
6. Sistema de Créditos
7. Comunas de Chile
8. Superusuario
9. Verificación
```

---

## 3. Paso 1: Migraciones

**Objetivo:** Asegurar que todas las tablas de la base de datos estén creadas y actualizadas.

### Comando:
```bash
python manage.py migrate --noinput
```

### Qué hace:
- Crea todas las tablas necesarias en la base de datos
- Aplica todas las migraciones pendientes
- Configura índices y relaciones

### Verificación:
```bash
python manage.py showmigrations
```
Debe mostrar todas las migraciones con `[X]` (aplicadas).

### ⚠️ Nota:
Este comando normalmente se ejecuta automáticamente durante el deploy, pero es bueno verificarlo.

---

## 4. Paso 2: Categorías y Servicios

**Objetivo:** Poblar las categorías principales y los servicios asociados tanto para usuarios como para proveedores.

### Comando:
```bash
python manage.py populate_categorias_servicios
```

### Opciones disponibles:
- `--force`: Actualiza categorías y servicios existentes con nuevos datos
- `--clear`: Elimina todas las categorías y servicios antes de crear las nuevas (⚠️ usar con cuidado)

### Estructura que se crea:

#### Categorías Principales (5):
1. **🔍 Diagnóstico e Inspección** - Para saber qué tiene el auto
2. **🛠️ Mantención Preventiva y Motor** - Para cuidar la vida útil del auto
3. **🛑 Frenos y Seguridad** - Para seguridad crítica
4. **⚡ Electricidad y Luces** - Energía y visibilidad
5. **✨ Estética y Limpieza** - Cuidado visual

#### Servicios por Categoría:

**🔍 Diagnóstico e Inspección:**
- Diagnóstico mecánico
- Diagnóstico electromecánico
- Servicio escáner automotriz
- Revisión precompra
- Revisión técnica

**🛠️ Mantención Preventiva y Motor:**
- Cambio de aceite motor
- Cambio de filtro de aire
- Cambio de filtro habitáculo
- Cambio aceite motor y filtro
- Mantenimiento por kilometraje
- Cambio de bujías

**🛑 Frenos y Seguridad:**
- Cambio de pastillas de frenos
- Cambio de pastillas y discos de freno
- Cambio de pastillas de frenos y rectificado

**⚡ Electricidad y Luces:**
- Cambio de batería
- Cambio de ampolletas

**✨ Estética y Limpieza:**
- Lavado a domicilio

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio

# Verificar categorías principales (sin padre)
categorias_principales = CategoriaServicio.objects.filter(categoria_padre__isnull=True)
print(f"Total de categorías principales: {categorias_principales.count()}")
# Debe mostrar: Total de categorías principales: 5

# Verificar servicios
print(f"Total de servicios: {Servicio.objects.count()}")
# Debe mostrar: Total de servicios: 17

# Verificar asociaciones
for cat in categorias_principales:
    servicios_count = cat.servicios.count()
    print(f"{cat.nombre}: {servicios_count} servicios")
```

### O desde la API:
```bash
# Ver categorías principales
curl https://mecanimovil-api.onrender.com/api/servicios/categorias/principales/ | python -m json.tool

# Ver servicios
curl https://mecanimovil-api.onrender.com/api/servicios/servicios/ | python -m json.tool
```

---

## 5. Paso 3: Marcas y Modelos de Vehículos

**Objetivo:** Poblar las marcas y modelos de vehículos disponibles en Chile.

### Comando:
```bash
python manage.py load_chile_vehicles
```

### Qué hace:
- Crea marcas de vehículos comunes en Chile (Toyota, Chevrolet, Ford, etc.)
- Crea modelos asociados a cada marca
- Incluye años de producción para cada modelo

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo
print(f"Total de marcas: {MarcaVehiculo.objects.count()}")
print(f"Total de modelos: {Modelo.objects.count()}")
# Debe mostrar números significativos (ej: 20+ marcas, 100+ modelos)
```

### O desde la API:
```bash
curl https://mecanimovil-api.onrender.com/api/vehiculos/marcas/ | python -m json.tool
```

---

## 6. Paso 4: Repuestos

**Objetivo:** Poblar el catálogo de repuestos disponibles para los servicios.

### Comando:
```bash
python manage.py load_repuestos_data
```

### Qué hace:
- Crea repuestos comunes (aceites, filtros, pastillas de freno, etc.)
- Asocia repuestos a servicios específicos
- Define precios de referencia para cada repuesto

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.servicios.models import Repuesto
print(f"Total de repuestos: {Repuesto.objects.count()}")
# Debe mostrar un número significativo de repuestos
```

### O desde la API:
```bash
curl https://mecanimovil-api.onrender.com/api/servicios/repuestos/ | python -m json.tool
```

---

## 7. Paso 5: Catálogo de Checklists

**Objetivo:** Poblar el catálogo de items de checklist que los proveedores pueden usar.

### Comando:
```bash
python manage.py populate_checklist_catalog
```

### Qué hace:
- Crea items predefinidos para checklists de servicios
- Incluye categorías como: Información General, Datos del Vehículo, Sistema de Frenos, etc.
- Define tipos de preguntas (TEXT, NUMBER, BOOLEAN, etc.)

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.checklists.models import ChecklistItemCatalog
print(f"Total de items de checklist: {ChecklistItemCatalog.objects.count()}")
# Debe mostrar un número significativo de items
```

---

## 8. Paso 6: Sistema de Créditos

**Objetivo:** Inicializar el sistema de créditos y paquetes disponibles.

### Comando:
```bash
python manage.py init_sistema_creditos
```

### Qué hace:
- Crea los paquetes de créditos disponibles para compra
- Configura precios y cantidades de créditos
- Inicializa el sistema de suscripciones

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.suscripciones.models import PaqueteCreditos
print(f"Total de paquetes: {PaqueteCreditos.objects.count()}")
# Debe mostrar al menos algunos paquetes básicos
```

---

## 9. Paso 7: Comunas de Chile

**Objetivo:** Poblar las comunas de Chile para geolocalización y filtros de búsqueda.

### Comando:
```bash
python manage.py load_chilean_communes
```

### Qué hace:
- Crea todas las regiones de Chile
- Crea todas las comunas asociadas a cada región
- Incluye coordenadas geográficas para geolocalización

### Verificación:
```bash
python manage.py shell
```
```python
from mecanimovilapp.apps.usuarios.models import Region, Comuna
print(f"Total de regiones: {Region.objects.count()}")
print(f"Total de comunas: {Comuna.objects.count()}")
# Debe mostrar: 16 regiones, 346 comunas (aproximadamente)
```

---

## 10. Paso 8: Superusuario

**Objetivo:** Crear un superusuario para acceder al panel de administración de Django.

### Opción A: Usando Variables de Entorno (Recomendado)

1. **Configura variables de entorno en Render:**
   - Ve a Render Dashboard → `mecanimovil-api` → **"Environment"**
   - Agrega:
     - `DJANGO_SUPERUSER_USERNAME` = `admin`
     - `DJANGO_SUPERUSER_EMAIL` = `tu-email@ejemplo.com`
     - `DJANGO_SUPERUSER_PASSWORD` = `tu-contraseña-segura`

2. **Ejecuta el comando:**
   ```bash
   python manage.py crear_superusuario_produccion
   ```

### Opción B: Usando Shell Interactivo

```bash
python manage.py createsuperuser
```

Sigue las instrucciones:
- Username: `admin` (o el que prefieras)
- Email: `tu-email@ejemplo.com`
- Password: `[ingresa una contraseña segura]`

### Verificación:
1. Ve a: `https://mecanimovil-api.onrender.com/admin/`
2. Intenta hacer login con las credenciales creadas
3. Debes poder acceder al panel de administración

---

## 11. Paso 9: Verificación

**Objetivo:** Verificar que todos los datos se hayan creado correctamente.

### Script de Verificación Completo:

```bash
python manage.py shell
```

```python
# Verificar categorías principales y servicios
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio
categorias_principales = CategoriaServicio.objects.filter(categoria_padre__isnull=True)
print(f"✅ Categorías principales: {categorias_principales.count()}")
print(f"✅ Servicios: {Servicio.objects.count()}")

# Verificar marcas y modelos
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo
print(f"✅ Marcas de vehículos: {MarcaVehiculo.objects.count()}")
print(f"✅ Modelos de vehículos: {Modelo.objects.count()}")

# Verificar repuestos
from mecanimovilapp.apps.servicios.models import Repuesto
print(f"✅ Repuestos: {Repuesto.objects.count()}")

# Verificar checklists
from mecanimovilapp.apps.checklists.models import ChecklistItemCatalog
print(f"✅ Items de checklist: {ChecklistItemCatalog.objects.count()}")

# Verificar sistema de créditos
from mecanimovilapp.apps.suscripciones.models import PaqueteCreditos
print(f"✅ Paquetes de créditos: {PaqueteCreditos.objects.count()}")

# Verificar comunas
from mecanimovilapp.apps.usuarios.models import Region, Comuna
print(f"✅ Regiones: {Region.objects.count()}")
print(f"✅ Comunas: {Comuna.objects.count()}")

# Verificar superusuario
from django.contrib.auth import get_user_model
User = get_user_model()
superusers = User.objects.filter(is_superuser=True)
print(f"✅ Superusuarios: {superusers.count()}")
for su in superusers:
    print(f"   - {su.username} ({su.email})")

print("\n🎉 Verificación completada!")
```

### Verificación desde la API:

```bash
# Categorías de servicios
curl https://mecanimovil-api.onrender.com/api/servicios/categorias/ | python -m json.tool | head -20

# Marcas de vehículos
curl https://mecanimovil-api.onrender.com/api/vehiculos/marcas/ | python -m json.tool | head -20

# Repuestos
curl https://mecanimovil-api.onrender.com/api/servicios/repuestos/ | python -m json.tool | head -20
```

---

## 12. Troubleshooting

### Problema: "Command not found"

**Solución:**
- Verifica que el deploy esté completo
- Asegúrate de estar en el directorio correcto: `/opt/render/project/src`
- Usa `python3` en lugar de `python` si es necesario

### Problema: "No such table"

**Solución:**
```bash
python manage.py migrate --noinput
```

### Problema: "IntegrityError: duplicate key"

**Solución:**
- Esto significa que los datos ya existen
- Usa `--force` para actualizar datos existentes
- O verifica primero si los datos ya están creados

### Problema: "ModuleNotFoundError"

**Solución:**
- Verifica que el deploy esté completo
- Espera unos minutos y vuelve a intentar
- Revisa los logs del deploy en Render

### Problema: Comando no aparece en `python manage.py help`

**Solución:**
- Verifica que el archivo esté en la ubicación correcta
- Verifica que el deploy haya incluido el nuevo archivo
- Espera a que Render complete el deploy

---

## 📝 Checklist de Ejecución

Usa este checklist para asegurarte de que todo esté completo:

- [ ] **Paso 1:** Migraciones ejecutadas (`migrate`)
- [ ] **Paso 2:** Categorías de servicios creadas (`populate_categorias_servicios`)
- [ ] **Paso 3:** Marcas y modelos creados (`load_chile_vehicles`)
- [ ] **Paso 4:** Repuestos creados (`load_repuestos_data`)
- [ ] **Paso 5:** Catálogo de checklists creado (`populate_checklist_catalog`)
- [ ] **Paso 6:** Sistema de créditos inicializado (`init_sistema_creditos`)
- [ ] **Paso 7:** Comunas de Chile cargadas (`load_chilean_communes`)
- [ ] **Paso 8:** Superusuario creado (`createsuperuser` o `crear_superusuario_produccion`)
- [ ] **Paso 9:** Verificación completada (todos los datos existen)

---

## 🚀 Script de Ejecución Rápida

Si prefieres ejecutar todo de una vez, puedes crear un script:

```bash
#!/bin/bash
# Script para poblar la base de datos de producción

echo "🚀 Iniciando población de base de datos..."

echo "📊 Paso 1: Migraciones..."
python manage.py migrate --noinput

echo "📊 Paso 2: Categorías de servicios..."
python manage.py populate_categorias_servicios

echo "📊 Paso 3: Marcas y modelos de vehículos..."
python manage.py load_chile_vehicles

echo "📊 Paso 4: Repuestos..."
python manage.py load_repuestos_data

echo "📊 Paso 5: Catálogo de checklists..."
python manage.py populate_checklist_catalog

echo "📊 Paso 6: Sistema de créditos..."
python manage.py init_sistema_creditos

echo "📊 Paso 7: Comunas de Chile..."
python manage.py load_chilean_communes

echo "✅ Población de base de datos completada!"
echo "⚠️  No olvides crear el superusuario con: python manage.py createsuperuser"
```

**Nota:** Guarda este script como `populate_production.sh` y ejecútalo con `bash populate_production.sh`

---

## 📊 Resumen de Comandos

| Paso | Comando | Descripción |
|------|---------|-------------|
| 1 | `migrate --noinput` | Aplica migraciones |
| 2 | `populate_categorias_servicios` | Crea 17 categorías de servicios |
| 3 | `load_chile_vehicles` | Crea marcas y modelos de vehículos |
| 4 | `load_repuestos_data` | Crea catálogo de repuestos |
| 5 | `populate_checklist_catalog` | Crea items de checklist |
| 6 | `init_sistema_creditos` | Inicializa sistema de créditos |
| 7 | `load_chilean_communes` | Carga comunas de Chile |
| 8 | `createsuperuser` | Crea superusuario admin |

---

## ✅ Resultado Esperado

Después de completar todos los pasos, deberías tener:

- ✅ **5 categorías principales de servicios** con **17 servicios** asociados
- ✅ **20+ marcas de vehículos** y **100+ modelos**
- ✅ **Catálogo completo de repuestos** asociados a servicios
- ✅ **Items de checklist** predefinidos para proveedores
- ✅ **Sistema de créditos** configurado y funcionando
- ✅ **Todas las comunas de Chile** para geolocalización
- ✅ **Superusuario** para administración

---

## 🎯 Próximos Pasos

Una vez que la base de datos esté poblada:

1. **Verifica que las apps móviles puedan conectarse:**
   - App de usuarios debe poder ver categorías de servicios
   - App de proveedores debe poder seleccionar especialidades

2. **Prueba el flujo completo:**
   - Usuario crea solicitud de servicio
   - Proveedor ve la solicitud
   - Proveedor crea oferta
   - Usuario acepta oferta

3. **Monitorea los logs:**
   - Revisa que no haya errores en los logs de Render
   - Verifica que las APIs respondan correctamente

---

## 📞 Soporte

Si encuentras problemas:

1. Revisa los logs en Render Dashboard → `mecanimovil-api` → **"Logs"**
2. Ejecuta el script de verificación para identificar qué falta
3. Consulta la sección de Troubleshooting arriba

---

**¡Listo! Tu base de datos de producción está poblada y lista para usar.** 🎉
