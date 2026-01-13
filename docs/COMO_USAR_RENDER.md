# 🎯 Guía para Empezar a Usar Render - MecaniMovil

Esta guía te ayudará a entender y usar tu deployment en Render paso a paso.

## 📍 Paso 1: Verificar que Todo Esté Desplegado

### 1.1 Acceder al Dashboard

1. Ve a [https://dashboard.render.com](https://dashboard.render.com)
2. Inicia sesión con tu cuenta

### 1.2 Ver tus Servicios

En el Dashboard verás una lista de servicios. Deberías ver:

- ✅ **mecanimovil-api** (Web Service) - Tu API principal
- ✅ **mecanimovil-celery-worker** (Background Worker) - Tareas asíncronas
- ✅ **mecanimovil-celery-beat** (Background Worker) - Tareas programadas
- ✅ **mecanimovil-db** (PostgreSQL Database) - Tu base de datos
- ✅ **mecanimovil-redis** (Redis) - Cache y mensajería

### 1.3 Verificar el Estado

Cada servicio tiene un indicador de estado:
- 🟢 **Live** = Funcionando correctamente
- 🟡 **Building** = Se está desplegando
- 🔴 **Failed** = Hay un error (revisa los logs)

**Si algún servicio está en "Failed":**
1. Haz clic en el servicio
2. Ve a la pestaña **"Logs"**
3. Revisa los errores al final del log

---

## 🔧 Paso 2: Configurar Variables de Entorno

Las variables de entorno son configuraciones secretas que tu aplicación necesita.

### 2.1 Acceder a las Variables

1. Haz clic en el servicio **mecanimovil-api**
2. En el menú lateral, ve a **"Environment"**
3. Verás una lista de variables ya configuradas (como `DATABASE_URL`, `REDIS_URL`)

### 2.2 Agregar Variables Necesarias

Haz clic en **"Add Environment Variable"** y agrega estas (una por una):

#### Variables de Mercado Pago:
```
Key: MERCADOPAGO_ACCESS_TOKEN
Value: APP_USR-tu-token-aqui
```

```
Key: MERCADOPAGO_MODE
Value: test
```
*(Cambia a `production` cuando estés listo para producción)*

```
Key: MERCADOPAGO_WEBHOOK_SECRET
Value: tu-webhook-secret-aqui
```

#### Variables de Email (opcional):
```
Key: EMAIL_HOST_USER
Value: tu-email@gmail.com
```

```
Key: EMAIL_HOST_PASSWORD
Value: tu-app-password
```

#### Variables para Superusuario (opcional):
```
Key: DJANGO_SUPERUSER_USERNAME
Value: admin
```

```
Key: DJANGO_SUPERUSER_EMAIL
Value: admin@mecanimovil.com
```

```
Key: DJANGO_SUPERUSER_PASSWORD
Value: tu-password-seguro-aqui
```

### 2.3 Guardar y Reiniciar

Después de agregar cada variable:
1. Haz clic en **"Save Changes"**
2. El servicio se reiniciará automáticamente

---

## 🌐 Paso 3: Obtener la URL de tu API

### 3.1 Encontrar la URL

1. Haz clic en el servicio **mecanimovil-api**
2. En la parte superior verás la URL, algo como:
   ```
   https://mecanimovil-api.onrender.com
   ```

### 3.2 Probar que Funciona

Abre esa URL en tu navegador. Deberías ver:
- Una página de error 404 (normal, significa que el servidor funciona)
- O una respuesta JSON si tienes un endpoint configurado

### 3.3 Probar un Endpoint

Si tienes un endpoint de prueba, prueba:
```
https://mecanimovil-api.onrender.com/api/hello/
```

---

## 📊 Paso 4: Ver los Logs

Los logs te muestran qué está pasando en tu aplicación.

### 4.1 Ver Logs en Tiempo Real

1. Haz clic en cualquier servicio
2. Ve a la pestaña **"Logs"**
3. Verás los logs en tiempo real

### 4.2 Buscar Errores

Si algo no funciona:
1. Ve a los logs
2. Busca líneas en rojo o que digan "ERROR"
3. Copia el mensaje de error para investigar

---

## 🔄 Paso 5: Hacer Cambios y Desplegar

### 5.1 Hacer Cambios en tu Código

1. Edita tu código localmente
2. Haz commit y push a GitHub:
   ```bash
   git add .
   git commit -m "Descripción de los cambios"
   git push
   ```

### 5.2 Render Despliega Automáticamente

Render detecta automáticamente cuando haces push a GitHub y:
1. Inicia un nuevo deploy
2. Ejecuta el `build.sh`
3. Reinicia los servicios

### 5.3 Ver el Progreso del Deploy

1. Ve al servicio **mecanimovil-api**
2. Verás un nuevo deploy en la sección **"Deploys"**
3. Haz clic en el deploy para ver el progreso
4. Espera hasta que diga **"Live"**

---

## 🗄️ Paso 6: Acceder a la Base de Datos

### 6.1 Ver la Información de Conexión

1. Haz clic en **mecanimovil-db**
2. Verás la información de conexión:
   - Host
   - Database
   - User
   - Password (haz clic en "Show" para verla)

### 6.2 Conectar con un Cliente SQL

Puedes usar herramientas como:
- **pgAdmin** (interfaz gráfica)
- **DBeaver** (interfaz gráfica)
- **psql** (línea de comandos)

**Ejemplo de conexión:**
```
Host: dpg-xxxxx-a.oregon-postgres.render.com
Port: 5432
Database: mecanimovil
User: mecanimovil
Password: [la que te muestra Render]
```

### 6.3 Usar el Shell de Render

1. En el servicio **mecanimovil-db**
2. Haz clic en **"Shell"**
3. Escribe comandos SQL directamente

---

## 🚨 Paso 7: Solucionar Problemas Comunes

### Problema: El servicio no inicia

**Solución:**
1. Ve a los logs del servicio
2. Busca el error
3. Revisa que todas las variables de entorno estén configuradas

### Problema: Error de migraciones

**Solución:**
1. Ve a los logs de **mecanimovil-api**
2. Busca errores relacionados con "migration"
3. Si hay errores, puede que necesites borrar la base de datos y recrearla

### Problema: Error 500 en la API

**Solución:**
1. Ve a los logs de **mecanimovil-api**
2. Busca el traceback del error
3. Revisa que todas las variables de entorno estén correctas

### Problema: El servicio se queda "Building"

**Solución:**
1. Espera unos minutos (el primer deploy puede tardar 10-15 minutos)
2. Si pasa mucho tiempo, cancela el deploy y vuelve a intentar
3. Revisa los logs para ver qué está fallando

---

## 📱 Paso 8: Conectar tu Frontend

### 8.1 Obtener la URL de la API

La URL de tu API es:
```
https://mecanimovil-api.onrender.com
```

### 8.2 Configurar CORS

Asegúrate de que en **mecanimovil-api** → **Environment** tengas:

```
Key: CORS_ALLOWED_ORIGINS
Value: https://tu-frontend.com,https://www.tu-frontend.com
```

*(Agrega todas las URLs donde esté tu frontend)*

### 8.3 Actualizar tu Frontend

En tu aplicación React Native o frontend, actualiza la URL base de la API:

```javascript
const API_URL = 'https://mecanimovil-api.onrender.com';
```

---

## 🔐 Paso 9: Seguridad Básica

### 9.1 No Compartir Variables de Entorno

- ❌ **NUNCA** subas variables de entorno a GitHub
- ✅ **SIEMPRE** úsalas en Render Dashboard

### 9.2 Cambiar a Producción

Cuando estés listo:
1. Cambia `MERCADOPAGO_MODE` de `test` a `production`
2. Usa tokens de producción de Mercado Pago
3. Configura `DEBUG=False` (ya está configurado)

---

## 📈 Paso 10: Monitorear tu Aplicación

### 10.1 Ver Métricas

En cada servicio puedes ver:
- **CPU Usage** - Uso de procesador
- **Memory Usage** - Uso de memoria
- **Request Count** - Número de peticiones

### 10.2 Configurar Alertas (Opcional)

1. Ve a **Settings** del servicio
2. Configura alertas por email si algo falla

---

## 🎓 Conceptos Importantes

### ¿Qué es un Blueprint?
Un Blueprint es un archivo (`render.yaml`) que define toda tu infraestructura. Render lo lee y crea todos los servicios automáticamente.

### ¿Qué es un Deploy?
Un deploy es cuando Render toma tu código nuevo y lo despliega. Cada vez que haces `git push`, Render hace un nuevo deploy automáticamente.

### ¿Qué son los Workers?
Los workers son servicios que ejecutan tareas en segundo plano:
- **celery-worker**: Procesa tareas asíncronas
- **celery-beat**: Ejecuta tareas programadas (como enviar emails diarios)

### ¿Qué es Redis?
Redis es una base de datos en memoria que se usa para:
- Cache (almacenar datos temporalmente)
- Mensajería entre servicios
- Cola de tareas de Celery

---

## ✅ Checklist de Inicio

- [ ] Todos los servicios están en estado "Live"
- [ ] Variables de entorno configuradas (Mercado Pago, Email, etc.)
- [ ] La URL de la API funciona
- [ ] Puedo ver los logs sin errores
- [ ] La base de datos está accesible
- [ ] El frontend está conectado a la API

---

## 🆘 ¿Necesitas Ayuda?

Si algo no funciona:
1. Revisa los logs del servicio que falla
2. Verifica que todas las variables de entorno estén configuradas
3. Asegúrate de que el código esté en GitHub y actualizado
4. Revisa la documentación de Render: https://render.com/docs

---

## 🎉 ¡Felicidades!

Ya tienes tu aplicación desplegada en Render. Cada vez que hagas cambios y hagas `git push`, Render los desplegará automáticamente.

**Próximos pasos:**
- Configura tu dominio personalizado (opcional)
- Configura alertas y monitoreo
- Optimiza los recursos según tu uso
