# 🔐 Acceder al Admin de Django en Producción (Render)

Guía completa para acceder al panel de administración de Django en producción.

---

## 📍 URL del Admin

El admin está disponible en:
```
https://mecanimovil-api.onrender.com/admin/
```

---

## 👤 Paso 1: Crear Superusuario

Necesitas crear un superusuario para acceder al admin. Tienes varias opciones:

### Opción A: Usando Shell de Render (Recomendado)

1. **Ve a Render Dashboard → `mecanimovil-api` → "Shell"**
2. **Ejecuta el comando:**
   ```bash
   python manage.py createsuperuser
   ```
3. **Sigue las instrucciones:**
   ```
   Username: admin
   Email: tu-email@ejemplo.com
   Password: [ingresa una contraseña segura]
   Password (again): [confirma la contraseña]
   ```

**⚠️ Nota:** Si el Shell no está disponible en tu plan, usa la Opción B.

---

### Opción B: Usando Script de Management

Crea un script de management para crear el superusuario desde variables de entorno.

1. **Crea el script:**
   ```bash
   cd mecanimovil-backend
   touch mecanimovilapp/apps/usuarios/management/commands/crear_superusuario_produccion.py
   ```

2. **Agrega este código al archivo:**
   ```python
   from django.core.management.base import BaseCommand
   from mecanimovilapp.apps.usuarios.models import Usuario
   
   class Command(BaseCommand):
       help = 'Crea un superusuario desde variables de entorno'
       
       def handle(self, *args, **options):
           username = os.environ.get('ADMIN_USERNAME', 'admin')
           email = os.environ.get('ADMIN_EMAIL', 'admin@mecanimovil.com')
           password = os.environ.get('ADMIN_PASSWORD')
           
           if not password:
               self.stdout.write(self.style.ERROR('❌ ADMIN_PASSWORD no está configurada'))
               return
           
           if Usuario.objects.filter(username=username).exists():
               self.stdout.write(self.style.WARNING(f'⚠️  Usuario {username} ya existe'))
               return
           
           Usuario.objects.create_superuser(
               username=username,
               email=email,
               password=password
           )
           self.stdout.write(self.style.SUCCESS(f'✅ Superusuario {username} creado exitosamente'))
   ```

3. **Agrega el import de `os` al inicio:**
   ```python
   import os
   ```

4. **Configura variables de entorno en Render:**
   - Ve a `mecanimovil-api` → Environment
   - Agrega:
     - `ADMIN_USERNAME` = `admin`
     - `ADMIN_EMAIL` = `tu-email@ejemplo.com`
     - `ADMIN_PASSWORD` = `tu-contraseña-segura`

5. **Ejecuta el comando desde Shell de Render:**
   ```bash
   python manage.py crear_superusuario_produccion
   ```

---

### Opción C: Usando Django Shell (Si Shell está disponible)

1. **Ve a Render Dashboard → `mecanimovil-api` → "Shell"**
2. **Ejecuta:**
   ```bash
   python manage.py shell
   ```
3. **En el shell de Python, ejecuta:**
   ```python
   from mecanimovilapp.apps.usuarios.models import Usuario
   Usuario.objects.create_superuser(
       username='admin',
       email='tu-email@ejemplo.com',
       password='tu-contraseña-segura'
   )
   ```

---

## 🌐 Paso 2: Acceder al Admin

1. **Abre tu navegador**
2. **Ve a:**
   ```
   https://mecanimovil-api.onrender.com/admin/
   ```
3. **Ingresa tus credenciales:**
   - Username: El que configuraste
   - Password: La contraseña que configuraste

---

## 🔒 Seguridad

### ⚠️ Importante: Proteger el Admin en Producción

El admin de Django es sensible. Considera:

1. **Usar contraseñas seguras:**
   - Mínimo 12 caracteres
   - Combinar mayúsculas, minúsculas, números y símbolos
   - No usar contraseñas comunes

2. **Limitar acceso por IP (Opcional):**
   - Puedes configurar un middleware para restringir acceso al admin por IP
   - O usar un servicio como Cloudflare para proteger el endpoint

3. **Usar HTTPS:**
   - Render ya proporciona HTTPS automáticamente
   - Asegúrate de que `ALLOWED_HOSTS` esté configurado correctamente

4. **Cambiar la URL del admin (Opcional):**
   - Puedes cambiar `/admin/` por algo menos obvio como `/administracion-secreta/`
   - Esto requiere modificar `urls.py`

---

## 🛠️ Cambiar Contraseña del Superusuario

Si necesitas cambiar la contraseña:

### Opción 1: Desde Shell de Render

```bash
python manage.py changepassword admin
```

### Opción 2: Desde Django Shell

```bash
python manage.py shell
```

```python
from mecanimovilapp.apps.usuarios.models import Usuario
user = Usuario.objects.get(username='admin')
user.set_password('nueva-contraseña-segura')
user.save()
```

---

## 📋 Verificar que el Admin Funciona

1. **Verifica que la URL responde:**
   ```bash
   curl https://mecanimovil-api.onrender.com/admin/
   ```
   Deberías ver HTML del login (no un error 404)

2. **Intenta acceder desde el navegador:**
   - Deberías ver la pantalla de login
   - No deberías ver errores de servidor

3. **Verifica los logs:**
   - Ve a Render Dashboard → `mecanimovil-api` → Logs
   - Busca errores relacionados con el admin

---

## 🚨 Troubleshooting

### Problema: No puedo acceder al admin (404)

**Solución:**
1. Verifica que la URL sea correcta: `https://mecanimovil-api.onrender.com/admin/`
2. Verifica que el servicio esté "Live" en Render
3. Revisa los logs del servicio para ver errores

### Problema: Error "CSRF verification failed"

**Solución:**
1. Asegúrate de usar HTTPS (no HTTP)
2. Limpia las cookies del navegador
3. Intenta en modo incógnito

### Problema: No puedo crear superusuario desde Shell

**Solución:**
1. Verifica que el Shell esté disponible en tu plan
2. Si no está disponible, usa la Opción B (script de management)
3. Verifica que las variables de entorno estén configuradas

### Problema: Olvidé la contraseña del admin

**Solución:**
1. Usa el comando `changepassword` desde Shell
2. O crea un nuevo superusuario con otro username
3. O resetea desde Django shell (ver arriba)

---

## 📝 Resumen Rápido

```bash
# 1. Crear superusuario (desde Shell de Render)
python manage.py createsuperuser

# 2. Acceder al admin
# URL: https://mecanimovil-api.onrender.com/admin/

# 3. Cambiar contraseña (si es necesario)
python manage.py changepassword admin
```

---

## 🔗 URLs Importantes

| Recurso | URL |
|---------|-----|
| **Admin Login** | `https://mecanimovil-api.onrender.com/admin/` |
| **API Base** | `https://mecanimovil-api.onrender.com/api/` |
| **Health Check** | `https://mecanimovil-api.onrender.com/api/hello/` |

---

## ✅ Checklist

- [ ] Superusuario creado
- [ ] Puedo acceder a `/admin/` desde el navegador
- [ ] Puedo hacer login con las credenciales
- [ ] Veo el panel de administración
- [ ] Puedo ver los modelos registrados en el admin
- [ ] Contraseña es segura

---

## 🎯 Próximos Pasos

Después de acceder al admin, puedes:

1. **Gestionar usuarios:**
   - Ver, editar, crear usuarios
   - Cambiar permisos
   - Verificar proveedores

2. **Gestionar servicios:**
   - Ver solicitudes de servicio
   - Gestionar ofertas
   - Ver chats

3. **Gestionar órdenes:**
   - Ver carritos
   - Gestionar pagos
   - Ver historial

4. **Gestionar suscripciones:**
   - Ver paquetes de créditos
   - Gestionar compras
   - Ver consumos

---

**¡Listo! Ya puedes acceder al admin de Django en producción.** 🎉
