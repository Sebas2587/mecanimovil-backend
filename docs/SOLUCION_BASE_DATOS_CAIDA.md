# 🔧 Solución: Base de Datos Caída en Render

## ❌ Error Observado

```
django.db.utils.OperationalError: connection to server at "dpg-d5iia824d50c739ofub0-a" (10.230.119.40), port 5432 failed: Connection refused
	Is the server running on that host and accepting TCP/IP connections?
```

**Este error indica que la base de datos PostgreSQL NO está disponible.**

---

## 🔍 Causas Comunes

### 1. Base de Datos en Plan Gratuito (Más Común)

**Render suspende automáticamente las bases de datos en plan gratuito** después de inactividad. Cuando hay actividad, se reactiva, pero puede tardar unos segundos.

**Síntomas:**
- Errores intermitentes de "Connection refused"
- El servicio funciona después de unos minutos
- Sucede especialmente después de periodos de inactividad

**Solución:** 
- Considera actualizar a un plan pago si necesitas disponibilidad 24/7
- O espera ~30-60 segundos después de la primera petición para que se reactive

### 2. Reinicio Manual o Automático

Render puede reiniciar la base de datos por:
- Actualizaciones de seguridad
- Mantenimiento programado
- Problemas de recursos

**Solución:** Espera 1-2 minutos para que se reactive

### 3. Problemas de Memoria/Recursos

Si la base de datos se queda sin recursos, Render puede reiniciarla.

**Solución:**
- Ve a `mecanimovil-db` → **"Metrics"** 
- Verifica uso de memoria/CPU
- Considera aumentar el plan si es necesario

### 4. Cambio de IP Interna

Render puede cambiar la IP interna de la base de datos durante un reinicio.

**Solución:** 
- El `DATABASE_URL` se actualiza automáticamente
- A veces el API necesita reiniciarse para detectar el cambio

---

## ✅ Soluciones Inmediatas

### Opción 1: Reiniciar el Servicio API

1. Ve a Render Dashboard → `mecanimovil-api`
2. Haz clic en **"Manual Deploy"** → **"Restart"**
3. Esto forzará que el API reconecte con la base de datos

### Opción 2: Verificar Estado de la Base de Datos

1. Ve a Render Dashboard → `mecanimovil-db`
2. Verifica el estado:
   - 🟢 **Available** = Base de datos funcionando
   - 🟡 **Starting** = Se está iniciando (espera 30-60 segundos)
   - 🔴 **Failed** = Hay un problema (revisa logs)

### Opción 3: Verificar Logs de la Base de Datos

1. Ve a `mecanimovil-db` → **"Logs"**
2. Busca errores recientes

### Opción 4: Reiniciar la Base de Datos (Si es Necesario)

**⚠️ ADVERTENCIA: Solo hazlo si es absolutamente necesario**

1. Ve a `mecanimovil-db` → **"Settings"**
2. Haz clic en **"Restart"**
3. Espera 2-3 minutos a que se reactive

---

## 🔄 Prevención Futura

### 1. Mantener la Base de Datos Activa (Plan Gratuito)

Si estás en plan gratuito, puedes usar un "keep-alive" para evitar suspensiones:

```bash
# Crear un cron job que haga ping cada 5 minutos
# O usar un servicio externo como cron-job.org
```

### 2. Actualizar a Plan Pago

Las bases de datos en plan pago no se suspenden automáticamente.

### 3. Monitoreo

Render envía emails cuando hay problemas con servicios. Verifica tu email registrado.

---

## 📊 Verificación Rápida

Ejecuta esto para verificar el estado actual:

```bash
# En Render Dashboard:
# 1. Ve a mecanimovil-db → "Status"
# 2. Debe decir "Available" (verde)
# 3. Ve a mecanimovil-api → "Logs"
# 4. Busca errores recientes de "Connection refused"
```

---

## 🎯 Para tu Caso Específico

**Según los logs:**
- ❌ **02:28:02** - Base de datos caída (Connection refused)
- ✅ **02:28:14** - Base de datos reactivada (errores desaparecen)

**Conclusión:** La base de datos se reactivó automáticamente después de ~12 segundos. Esto es normal en planes gratuitos.

**Recomendación:**
1. Si es plan gratuito → Es normal, espera unos segundos tras la primera petición
2. Si necesitas disponibilidad constante → Considera actualizar a plan pago
3. Si el problema persiste → Revisa los logs de `mecanimovil-db` en Render Dashboard

---

## 📞 Próximos Pasos

1. **Verifica el estado actual** de `mecanimovil-db` en Render Dashboard
2. **Si está "Available"** → El problema ya se resolvió (se reactivó automáticamente)
3. **Si el problema persiste** → Comparte los logs de `mecanimovil-db`

**Nota:** El frontend NO tiene la culpa. El problema es que la base de datos estaba temporalmente no disponible.
