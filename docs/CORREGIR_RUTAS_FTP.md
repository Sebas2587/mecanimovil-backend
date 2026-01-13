# 🔧 Corregir Rutas FTP - Cuenta Restringida

## ❌ Problema Identificado

Los archivos se están subiendo a una ruta incorrecta:
```
public_html/mecanimovil.cl/mecanimovil-media/public_html/images/mecanimovil-app-media
```

Cuando debería ser:
```
public_html/mecanimovil.cl/mecanimovil-media/images/mecanimovil-app-media
```

**Causa:** La cuenta FTP está restringida a `public_html/mecanimovil.cl/mecanimovil-media/` y el código estaba intentando navegar a `public_html/` de nuevo, duplicando la ruta.

---

## ✅ Solución: Actualizar Variables de Entorno en Render

### Paso 1: Verificar el Directorio Raíz de la Cuenta FTP

La cuenta FTP `mecanimovil-media@mecanimovil.cl` está restringida a:
```
/public_html/mecanimovil.cl/mecanimovil-media/
```

Este es el directorio donde la cuenta FTP inicia cuando se conecta.

### Paso 2: Actualizar `CPANEL_FTP_ROOT` en Render

**Variable actual (INCORRECTA):**
```
CPANEL_FTP_ROOT=public_html/images/mecanimovil-app-media
```

**Variable nueva (CORRECTA):**
```
CPANEL_FTP_ROOT=images/mecanimovil-app-media
```

**Explicación:** Como la cuenta FTP ya está en `public_html/mecanimovil.cl/mecanimovil-media/`, solo necesitamos la ruta relativa desde ahí: `images/mecanimovil-app-media`.

### Paso 3: Verificar `CPANEL_MEDIA_URL`

Esta variable debe apuntar a la URL pública donde se servirán los archivos:

```
CPANEL_MEDIA_URL=https://www.mecanimovil.cl/images/mecanimovil-app-media/
```

**Nota:** Esta URL debe ser accesible desde el navegador. Verifica que el directorio `images/mecanimovil-app-media/` sea accesible vía HTTP en tu servidor.

---

## 📋 Pasos para Corregir en Render

1. **Ve a Render Dashboard** → Tu servicio (`mecanimovil-api`) → **Environment**

2. **Busca la variable `CPANEL_FTP_ROOT`**

3. **Cámbiala de:**
   ```
   public_html/images/mecanimovil-app-media
   ```
   
   **A:**
   ```
   images/mecanimovil-app-media
   ```

4. **Guarda los cambios**

5. **Render hará un redeploy automático**

---

## 🔍 Verificación

Después del cambio, los logs deberían mostrar:

```
🔍 [CPanelStorage._save] Directorio raíz de cuenta FTP: /public_html/mecanimovil.cl/mecanimovil-media
🔍 [CPanelStorage._save] Ruta ajustada (removido public_html/ porque ya estamos en public_html): images/mecanimovil-app-media/vehicle_xxx.jpg
✅ [CPanelStorage._save] Navegado a: images
✅ [CPanelStorage._save] Navegado a: mecanimovil-app-media
✅ [CPanelStorage._save] ARCHIVO SUBIDO EXITOSAMENTE
```

Y los archivos deberían estar en:
```
/public_html/mecanimovil.cl/mecanimovil-media/images/mecanimovil-app-media/vehicle_xxx.jpg
```

---

## 🌐 Verificar Accesibilidad HTTP

Después de corregir, verifica que las imágenes sean accesibles:

1. **Abre en el navegador:**
   ```
   https://www.mecanimovil.cl/images/mecanimovil-app-media/vehicle_xxx.jpg
   ```

2. **Si no carga**, verifica:
   - Que el directorio `images/mecanimovil-app-media/` tenga permisos `755`
   - Que el servidor web esté configurado para servir archivos desde ese directorio
   - Que no haya un `.htaccess` bloqueando el acceso

---

## 📝 Resumen de Variables de Entorno

Después de la corrección, las variables deben ser:

```
STORAGE_TYPE=cpanel
CPANEL_FTP_HOST=ftp.mecanimovil.cl
CPANEL_FTP_PORT=21
CPANEL_FTP_USER=mecanimovil-media@mecanimovil.cl
CPANEL_FTP_PASSWORD=[tu_contraseña]
CPANEL_FTP_ROOT=images/mecanimovil-app-media
CPANEL_MEDIA_URL=https://www.mecanimovil.cl/images/mecanimovil-app-media/
```

---

## ✅ Checklist

- [ ] `CPANEL_FTP_ROOT` actualizado a `images/mecanimovil-app-media` (sin `public_html/`)
- [ ] `CPANEL_MEDIA_URL` configurado correctamente
- [ ] Render redeployado después de los cambios
- [ ] Archivos se suben a la ruta correcta (verificar en cPanel)
- [ ] Imágenes accesibles vía HTTP (verificar en navegador)

---

¡Listo! Después de actualizar `CPANEL_FTP_ROOT` en Render, los archivos se subirán a la ruta correcta.
