# deploy-render Specification

## Purpose
Configuración y operación del deploy en Render: Web Service (Django), Celery Worker,
Redis y PostgreSQL. Define cómo se despliega, qué variables de entorno son necesarias
y cómo se diagnostican problemas en producción.

## Requirements

### Requirement: Servicios en Render
El backend corre en 3 servicios en Render coordinados mediante render.yaml.

#### Scenario: Deploy exitoso del Web Service
- GIVEN un push a la rama main con build que pasa
- WHEN Render ejecuta el deploy
- THEN gunicorn arranca en el puerto definido por $PORT
- AND /api/health/ responde 200 en menos de 30 segundos

#### Scenario: Celery Worker activo
- GIVEN el Web Service corriendo correctamente
- WHEN el Celery Worker arranca
- THEN se conecta a Redis y procesa tareas en la cola default
- AND las tareas de notificaciones push se ejecutan en menos de 10 segundos

### Requirement: Variable AGENDAMIENTO_IA_ASISTIDO en API
El Web Service `mecanimovil-api` expone el asistente de agendamiento cuando la variable está activa.

#### Scenario: API en Render con asistente habilitado
- GIVEN `AGENDAMIENTO_IA_ASISTIDO=True` en el servicio web (definido en render.yaml)
- WHEN un cliente autenticado llama POST `/api/ordenes/asistente-agendamiento/analizar-necesidad/`
- THEN la respuesta es 200 con servicios sugeridos (no 403)

### Requirement: Variables de entorno críticas
El sistema no debe arrancar sin las variables mínimas requeridas.

#### Scenario: Variable faltante al startup
- GIVEN que SECRET_KEY, DATABASE_URL o REDIS_URL no están definidas
- WHEN Django intenta arrancar
- THEN el proceso falla con mensaje explícito indicando la variable faltante
- AND Render marca el deploy como fallido

### Requirement: Migraciones automáticas en deploy
Las migraciones de Django se corren automáticamente antes de iniciar el servidor.

#### Scenario: Migración exitosa
- GIVEN migraciones pendientes al desplegar
- WHEN Render ejecuta el start command
- THEN python manage.py migrate corre antes de gunicorn
- AND las migraciones se aplican sin errores

#### Scenario: Migración con conflicto
- GIVEN migraciones en conflicto (ej. dos migraciones con mismo número)
- WHEN se intenta migrar
- THEN el comando falla
- AND gunicorn no arranca (Render marca deploy como fallido)
