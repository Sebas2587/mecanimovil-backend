# ⚡ Quick Start: Desarrollo Local

Guía rápida para empezar a desarrollar en 5 minutos.

---

## 🚀 Setup Inicial (Solo Primera Vez)

```bash
# 1. Clonar repositorio
git clone https://github.com/TU_USUARIO/mecanimovil-backend.git
cd mecanimovil-backend

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # macOS/Linux
# o venv\Scripts\activate  # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar .env
cp .env.example .env  # Si existe
# Editar .env con tus valores locales

# 5. Crear base de datos local
createdb mecanimovil_local

# 6. Ejecutar migraciones
python manage.py migrate

# 7. Crear superusuario (opcional)
python manage.py createsuperuser
```

---

## 💻 Trabajo Diario

```bash
# 1. Ir al proyecto
cd mecanimovil-backend

# 2. Activar entorno virtual
source venv/bin/activate

# 3. Actualizar código (si trabajas en equipo)
git pull origin main

# 4. Ejecutar servidor
python manage.py runserver

# Servidor en: http://localhost:8000
```

---

## ✏️ Hacer Cambios y Subir

```bash
# 1. Hacer cambios en el código
# ... editar archivos ...

# 2. Probar localmente
python manage.py runserver
# Probar en otra terminal: curl http://localhost:8000/api/hello/

# 3. Si modificaste modelos
python manage.py makemigrations
python manage.py migrate

# 4. Verificar cambios
git status
git diff

# 5. Commit y push
git add .
git commit -m "feat: Descripción de cambios"
git push origin main

# 6. Render despliega automáticamente
# Verificar en: https://dashboard.render.com
```

---

## ✅ Checklist Rápido

Antes de hacer commit:
- [ ] Probé localmente
- [ ] No hay errores de sintaxis
- [ ] No hay archivos sensibles (.env)
- [ ] Migraciones probadas (si aplica)

Después del deploy:
- [ ] Deploy completado en Render
- [ ] API responde en producción
- [ ] No hay errores en logs

---

## 🆘 Comandos Útiles

```bash
# Ver estado
git status

# Ver diferencias
git diff

# Deshacer cambios
git checkout -- archivo.py

# Ver logs de Django
python manage.py runserver --verbosity 2

# Django shell
python manage.py shell
```

---

## 📖 Guía Completa

Para más detalles, ver: [GUIA_DESARROLLO_LOCAL.md](GUIA_DESARROLLO_LOCAL.md)

---

**¡Listo para desarrollar!** 🎉
