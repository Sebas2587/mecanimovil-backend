# 📁 Crear Directorio mecanimovil-app-media en cPanel

## ❌ Problema

Los logs muestran:
```
⚠️ [CPanelStorage] No se pudo crear directorio images/mecanimovil-app-media: 550 Can't create directory: No such file or directory
```

**Causa:** El directorio `mecanimovil-app-media` no existe en el servidor FTP y la cuenta FTP no tiene permisos para crearlo automáticamente.

---

## ✅ Solución: Crear el Directorio Manualmente

### Paso 1: Acceder a cPanel

1. Inicia sesión en tu cPanel
2. Ve a **"Administrador de Archivos"** o **"File Manager"**

### Paso 2: Navegar al Directorio Correcto

1. En el File Manager, navega a:
   ```
   public_html/images/
   ```

2. Si el directorio `images/` no existe, créalo primero:
   - Haz clic derecho en `public_html/`
   - Selecciona **"Create Folder"** o **"Nueva Carpeta"**
   - Nombre: `images`
   - Permisos: `755`

### Paso 3: Crear el Directorio mecanimovil-app-media

1. Dentro de `public_html/images/`, crea el directorio:
   - Haz clic derecho en `images/`
   - Selecciona **"Create Folder"** o **"Nueva Carpeta"**
   - Nombre: `mecanimovil-app-media`
   - Permisos: `755`

### Paso 4: Verificar Permisos

1. Haz clic derecho en `mecanimovil-app-media`
2. Selecciona **"Change Permissions"** o **"Cambiar Permisos"**
3. Asegúrate de que tenga:
   - **Owner (Propietario)**: `7` (Read, Write, Execute)
   - **Group (Grupo)**: `5` (Read, Execute)
   - **Public (Público)**: `5` (Read, Execute)
   - **Total**: `755`

### Paso 5: Verificar Estructura Final

La estructura debe quedar así:
```
public_html/
  └── images/
      └── mecanimovil-app-media/
```

---

## 🔍 Verificar desde FTP

Después de crear el directorio, puedes verificar desde tu terminal local:

```bash
# Conectarte vía FTP
ftp ftp.mecanimovil.cl

# Ingresar credenciales
# Usuario: mecanimovil-media@mecanimovil.cl
# Contraseña: [tu contraseña]

# Navegar y verificar
cd public_html
cd images
cd mecanimovil-app-media
pwd  # Debería mostrar: /public_html/images/mecanimovil-app-media
ls   # Debería estar vacío (o mostrar archivos si ya hay)
```

---

## 🚨 Si No Puedes Crear el Directorio

### Opción 1: Verificar Permisos de la Cuenta FTP

1. Ve a cPanel → **"Cuentas FTP"** o **"FTP Accounts"**
2. Busca la cuenta `mecanimovil-media@mecanimovil.cl`
3. Verifica que el **"Directorio"** sea:
   ```
   /public_html/images
   ```
   O al menos:
   ```
   /public_html
   ```

4. Si el directorio está restringido a otro lugar, edítalo para que apunte a `/public_html` o `/public_html/images`

### Opción 2: Usar el Usuario Principal de cPanel

Si la cuenta FTP restringida no puede crear directorios:

1. Usa el usuario principal de cPanel (el que usas para iniciar sesión)
2. Crea el directorio manualmente desde File Manager
3. Asegúrate de que la cuenta FTP `mecanimovil-media@mecanimovil.cl` tenga acceso de lectura/escritura

### Opción 3: Crear desde SSH (si tienes acceso)

Si tienes acceso SSH a tu servidor:

```bash
ssh usuario@tudominio.com

# Crear directorios
mkdir -p ~/public_html/images/mecanimovil-app-media

# Ajustar permisos
chmod 755 ~/public_html/images
chmod 755 ~/public_html/images/mecanimovil-app-media
```

---

## ✅ Verificación Final

Después de crear el directorio, prueba subir una imagen desde la app. Los logs deberían mostrar:

```
✅ [CPanelStorage._save] Navegado a: images
✅ [CPanelStorage._save] Navegado a: mecanimovil-app-media
✅ [CPanelStorage._save] ARCHIVO SUBIDO EXITOSAMENTE
```

---

## 📋 Checklist

- [ ] Directorio `public_html/images/` existe
- [ ] Directorio `public_html/images/mecanimovil-app-media/` existe
- [ ] Permisos del directorio son `755`
- [ ] La cuenta FTP puede escribir en el directorio
- [ ] Verificado desde File Manager que el directorio existe
- [ ] Probado subir una imagen desde la app

---

## 🔗 Referencias

- [Guía de Configuración de cPanel](./CONFIGURACION_CPANEL.md)
- [Verificar Configuración](./VERIFICAR_CONFIGURACION_CPANEL.md)
