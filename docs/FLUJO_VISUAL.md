# 📊 Flujo Visual: Desarrollo Local → Producción

Diagrama visual del flujo completo de trabajo.

---

## 🔄 Flujo Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONFIGURACIÓN INICIAL                        │
│                    (Solo una vez)                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  1. Clonar repositorio              │
        │     git clone ...                   │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  2. Crear entorno virtual           │
        │     python -m venv venv            │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  3. Instalar dependencias           │
        │     pip install -r requirements.txt │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  4. Configurar .env                  │
        │     (variables locales)             │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  5. Configurar base de datos        │
        │     createdb + migrate              │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │        ✅ LISTO PARA DESARROLLAR    │
        └─────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DIARIO DE TRABAJO                      │
└─────────────────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  Iniciar día    │
    └─────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  cd mecanimovil-backend              │
    │  source venv/bin/activate           │
    │  git pull origin main                │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  HACER CAMBIOS                      │
    │  - Editar archivos                  │
    │  - Agregar funcionalidades          │
    │  - Corregir bugs                    │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  PROBAR LOCALMENTE                  │
    │  python manage.py runserver         │
    │  curl http://localhost:8000/api/... │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  ¿Funciona bien?                     │
    └─────────────────────────────────────┘
            │
        ┌───┴───┐
        │       │
       SÍ      NO
        │       │
        │       └───► Corregir y probar de nuevo
        │
        ▼
    ┌─────────────────────────────────────┐
    │  PREPARAR PARA SUBIR                │
    │  - git status (verificar cambios)   │
    │  - git diff (revisar diferencias)   │
    │  - Verificar .env NO está incluido │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  COMMIT Y PUSH                      │
    │  git add .                           │
    │  git commit -m "feat: ..."          │
    │  git push origin main                │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  RENDER DETECTA CAMBIOS             │
    │  (Automáticamente)                  │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  DEPLOY EN RENDER                    │
    │  - Build                             │
    │  - Migrations                        │
    │  - Deploy                            │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  VERIFICAR EN PRODUCCIÓN             │
    │  - Render Dashboard                 │
    │  - Logs                              │
    │  - Probar API                        │
    └─────────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────┐
    │  ¿Todo funciona?                    │
    └─────────────────────────────────────┘
            │
        ┌───┴───┐
        │       │
       SÍ      NO
        │       │
        │       └───► Revisar logs y corregir
        │
        ▼
    ┌─────────────────────────────────────┐
    │        ✅ DEPLOY EXITOSO             │
    └─────────────────────────────────────┘
```

---

## 📁 Estructura de Archivos

```
mecanimovil-backend/
│
├── 📁 mecanimovilapp/          # Código principal
│   ├── 📁 apps/                # Apps Django
│   │   ├── usuarios/
│   │   ├── servicios/
│   │   └── ...
│   ├── settings.py             # Settings desarrollo
│   └── settings_production.py # Settings producción
│
├── 📁 docs/                    # Documentación
│   ├── GUIA_DESARROLLO_LOCAL.md
│   └── ...
│
├── 📁 scripts/                 # Scripts útiles
│   └── verificar_produccion_completo.sh
│
├── 📄 requirements.txt         # Dependencias Python
├── 📄 render.yaml              # Configuración Render
├── 📄 .env                     # Variables locales (NO en Git)
├── 📄 .env.example             # Plantilla de .env
└── 📄 .gitignore               # Archivos ignorados por Git
```

---

## 🔐 Variables de Entorno

### Local (.env) - NO se sube a Git

```bash
DEBUG=True
SECRET_KEY=local-secret-key
DATABASE_URL=postgresql://localhost/mecanimovil_local
REDIS_URL=redis://localhost:6379/0
```

### Producción (Render Dashboard) - Configurar manualmente

```
DEBUG=False
SECRET_KEY=[generado automáticamente]
DATABASE_URL=[de mecanimovil-db]
REDIS_URL=[de mecanimovil-redis]
```

---

## 🚦 Estados del Código

```
┌─────────────┐
│  Working    │  ← Tu editor (cambios sin guardar)
│  Directory  │
└──────┬──────┘
       │ git add
       ▼
┌─────────────┐
│  Staging    │  ← Cambios preparados para commit
│   Area      │
└──────┬──────┘
       │ git commit
       ▼
┌─────────────┐
│   Local     │  ← Commits locales
│ Repository  │
└──────┬──────┘
       │ git push
       ▼
┌─────────────┐
│  Remote     │  ← GitHub (código en la nube)
│ Repository  │
└──────┬──────┘
       │ Auto-deploy
       ▼
┌─────────────┐
│   Render    │  ← Producción (Render)
│  Production │
└─────────────┘
```

---

## ⚠️ Zonas de Peligro

### ❌ NO Hacer

```
❌ Subir .env a Git
❌ Subir secrets/passwords
❌ Commit sin probar
❌ Push a main sin verificar
❌ Modificar settings_production.py directamente
❌ Hacer cambios en producción sin probar localmente
```

### ✅ SI Hacer

```
✅ Probar localmente primero
✅ Usar ramas para features grandes
✅ Commit con mensajes descriptivos
✅ Verificar cambios antes de push
✅ Revisar logs después del deploy
✅ Hacer backup antes de cambios grandes
```

---

## 🎯 Casos de Uso Comunes

### Caso 1: Agregar Nuevo Endpoint

```
1. Editar views.py o urls.py
2. Probar localmente: python manage.py runserver
3. Test: curl http://localhost:8000/api/nuevo-endpoint/
4. git add . && git commit -m "feat: Agregar endpoint X"
5. git push origin main
6. Verificar en producción
```

### Caso 2: Modificar Modelo (Base de Datos)

```
1. Editar models.py
2. Crear migraciones: python manage.py makemigrations
3. Aplicar localmente: python manage.py migrate
4. Probar que funciona
5. git add */migrations/ models.py
6. git commit -m "feat: Agregar campo X a modelo Y"
7. git push origin main
8. Render aplicará migraciones automáticamente
```

### Caso 3: Agregar Nueva Dependencia

```
1. Instalar localmente: pip install nueva-dependencia
2. Agregar a requirements.txt
3. Probar que funciona
4. git add requirements.txt
5. git commit -m "feat: Agregar dependencia X"
6. git push origin main
7. Render instalará en el próximo deploy
```

---

## 📊 Timeline Típico

```
Tiempo    Acción
─────────────────────────────────────────
00:00     Iniciar desarrollo
          cd proyecto && source venv/bin/activate

00:05     Hacer cambios
          Editar archivos...

00:30     Probar localmente
          python manage.py runserver

00:35     Verificar que funciona
          curl http://localhost:8000/api/...

00:40     Commit y push
          git add . && git commit && git push

00:45     Render detecta cambios
          (Automático)

01:00     Deploy completado
          (2-5 minutos de build)

01:05     Verificar en producción
          curl https://mecanimovil-api.onrender.com/api/...
```

---

## 🔗 Enlaces Rápidos

- **Guía Completa:** [GUIA_DESARROLLO_LOCAL.md](GUIA_DESARROLLO_LOCAL.md)
- **Quick Start:** [QUICK_START_DEVELOPMENT.md](QUICK_START_DEVELOPMENT.md)
- **Flujo Detallado:** [FLUJO_DESARROLLO_PRODUCCION.md](FLUJO_DESARROLLO_PRODUCCION.md)

---

**¡Visualiza el flujo y trabaja con confianza!** 🎉
