# 🔍 Diagnosticar Errores 500 en Producción

## ⚠️ Problema: Errores 500 en Múltiples Endpoints

Si estás viendo errores `Server Error (500)` en el frontend, el problema está en el **backend**, no en la conexión.

---

## 🔧 Paso 1: Ver Logs del Servidor en Render

### Opción A: Dashboard de Render (Más Fácil)

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Selecciona el servicio **`mecanimovil-api`**
3. Haz clic en **"Logs"** (barra lateral izquierda)
4. Busca errores recientes (últimas 5-10 minutos)
5. **Copia el error completo** que aparezca

**Busca líneas que contengan:**
- ❌ `ERROR` o `Exception`
- ❌ `Traceback` o `Traceback (most recent call last)`
- ❌ `django.db.utils`
- ❌ `DoesNotExist` o `RelatedObjectDoesNotExist`
- ❌ `IntegrityError` o `DatabaseError`

### Opción B: Desde SSH (Si Necesitas Más Detalles)

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

# Navegar al proyecto
cd /opt/render/project/src

# Verificar que el servidor está corriendo
ps aux | grep daphne

# Ver errores recientes (esto muestra solo si hay archivos de log)
tail -n 200 /var/log/django.log 2>/dev/null || echo "Logs en stdout/stderr"
```

**Nota:** En Render, los logs generalmente se muestran en el Dashboard, no en archivos.

---

## 🔍 Paso 2: Verificar Estado del Servidor

### Verificar en Render Dashboard

1. Ve a `mecanimovil-api` → **"Metrics"** o **"Events"**
2. Verifica el estado:
   - 🟢 **Live** = Servidor funcionando
   - 🟡 **Building** = Se está desplegando
   - 🔴 **Failed** = Servidor caído

### Verificar Base de Datos

1. Ve a `mecanimovil-db` → **"Logs"**
2. Busca errores de conexión

---

## 🐛 Paso 3: Causas Comunes de Error 500

### 1. Error en el Código (Más Común)

**Síntoma:** Todos los endpoints devuelven 500

**Causa:** Un error en el código que se ejecuta en todas las peticiones (middleware, settings, etc.)

**Solución:** Revisa los logs para ver el `Traceback` exacto

### 2. Problema con Base de Datos

**Síntoma:** Errores con `DatabaseError`, `IntegrityError`, `DoesNotExist`

**Causa:** 
- Tabla corrupta
- Foreign key constraint violado
- Datos faltantes

**Solución:** Ejecuta desde SSH:

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src

# Verificar conexión a la base de datos
python3 manage.py check --database default

# Ver migraciones pendientes
python3 manage.py showmigrations

# Verificar estado de la base de datos
python3 manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('✅ Conexión OK')"
```

### 3. Memoria Agotada

**Síntoma:** Servidor se reinicia constantemente

**Causa:** El servidor se queda sin memoria

**Solución:** 
- Ve a `mecanimovil-api` → **"Settings"** → Aumenta **Memory**

### 4. Migraciones Pendientes

**Síntoma:** Errores con tablas que no existen

**Solución:**

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src

# Ver migraciones
python3 manage.py showmigrations

# Aplicar migraciones pendientes
python3 manage.py migrate
```

### 5. Variables de Entorno Faltantes

**Síntoma:** Errores con `KeyError` o `NoneType`

**Solución:**
1. Ve a `mecanimovil-api` → **"Environment"**
2. Verifica que todas las variables necesarias estén configuradas

---

## 🚨 Paso 4: Si Eliminaste Logs Recientemente

Si ejecutaste comandos para eliminar logs de `AuditAccesoCliente` y ahora hay errores 500:

### Verificar si Hay Problemas con Foreign Keys

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src

python3 manage.py shell << 'EOF'
from django.db import connection
from django.db.utils import IntegrityError

# Verificar integridad de AuditAccesoCliente
try:
    from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente
    total = AuditAccesoCliente.objects.count()
    print(f"✅ Total logs: {total}")
    
    # Intentar acceder a relaciones
    for audit in AuditAccesoCliente.objects.all()[:5]:
        try:
            solicitud = audit.solicitud_servicio
            usuario = audit.usuario_proveedor
            print(f"✅ Relaciones OK para audit {audit.id}")
        except Exception as e:
            print(f"❌ Error en audit {audit.id}: {e}")
except Exception as e:
    print(f"❌ Error verificando AuditAccesoCliente: {e}")
EOF
```

---

## 📋 Paso 5: Revisar Errores Específicos en Logs

Cuando veas los logs, busca estos patrones:

### Error de Importación
```
ModuleNotFoundError: No module named 'X'
```
**Solución:** Verifica que todas las dependencias estén en `requirements.txt`

### Error de Base de Datos
```
django.db.utils.OperationalError: could not connect to server
```
**Solución:** Verifica que `DATABASE_URL` esté configurada

### Error de Foreign Key
```
IntegrityError: insert or update on table violates foreign key constraint
```
**Solución:** Puede ser por datos eliminados recientemente. Revisa las relaciones.

### Error de Tabla No Existe
```
relation "nombre_tabla" does not exist
```
**Solución:** Ejecuta `python3 manage.py migrate`

---

## 🎯 Comando Rápido para Diagnóstico

Ejecuta esto desde SSH para obtener un diagnóstico completo:

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src

echo "🔍 Diagnóstico del Servidor"
echo "=========================="
echo ""

echo "1️⃣ Verificando conexión a BD..."
python3 manage.py check --database default 2>&1

echo ""
echo "2️⃣ Verificando migraciones..."
python3 manage.py showmigrations | grep "\[ \]"

echo ""
echo "3️⃣ Verificando servicios..."
ps aux | grep -E "daphne|gunicorn" | head -3

echo ""
echo "✅ Diagnóstico completado"
```

---

## 📞 Próximos Pasos

1. **Revisa los logs en Render Dashboard** (más importante)
2. **Copia el error completo** que aparezca
3. **Comparte el error** para que podamos identificar la causa exacta

**Los errores 500 siempre muestran un `Traceback` en los logs que indica exactamente qué línea de código está fallando.**
