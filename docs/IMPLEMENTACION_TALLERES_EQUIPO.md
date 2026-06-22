# Talleres con equipo, modalidad y asignación automática — Proceso de implementación

Documento del trabajo realizado para unificar proveedores por modalidad de
atención, introducir el equipo de taller (`MiembroTaller`), la asignación
automática de mecánico y el match por modalidad, junto con la verificación
contra la base de datos de Render y los Pull Requests asociados.

## 1. Alcance entregado

| Repo | Rama | PR |
|------|------|----|
| `mecanimovil-backend` | `feat/talleres-equipo-modalidad` | [#3](https://github.com/Sebas2587/mecanimovil-backend/pull/3) |
| `mecanimovil-prov` | `feat/taller-equipo-modalidad-ui` | [#3](https://github.com/Sebas2587/mecanimovil-prov/pull/3) |
| `mecanimovil-usuarios` | `feat/proveedor-modalidad-discovery` | [#2](https://github.com/Sebas2587/mecanimovil-usuarios/pull/2) |

### Backend
- **Modelo unificado**: `Taller.modalidad_atencion` (`en_taller` / `a_domicilio` / `ambas`) y `radio_cobertura`. Estrategia *strangler*: `MecanicoDomicilio` se mantiene como legacy.
- **Equipo de taller** (`MiembroTaller`): roles `mandante` / `supervisor` / `mecanico`, especialidades (M2M con `CategoriaServicio`), `modalidad_tecnico`, `activo`. Constraints: máx. 1 mandante y 1 supervisor por taller.
- **FKs nuevas**: `HorarioProveedor.miembro_taller`, `SolicitudServicio.mecanico_asignado`, `CitaAgendaPersonal.miembro_taller`, `MechanicServiceArea.taller` (XOR con `mechanic`).
- **Disponibilidad por unión**: la disponibilidad pública se calcula como unión de ventanas libres por mecánico apto (filtrando especialidad y modalidad). *Fallback* al horario a nivel taller cuando no hay equipo (sin regresión).
- **Asignación automática** (`services/asignacion_mecanico.py`): selecciona un mecánico apto, libre en el slot y con menor carga; integrada en los 4 puntos de creación de `SolicitudServicio`.
- **Motor de match**: filtra por modalidad solicitada y excluye talleres sin mecánico apto activo; expone la modalidad en el candidato.
- **API de equipo**: CRUD de `MiembroTaller`, `habilitar`/`deshabilitar`, horarios por mecánico y KPIs de rendimiento.

### App proveedores (`mecanimovil-prov`)
- Onboarding por modalidad, pantalla **Gestión de Equipo**, agenda/horarios por mecánico, calendario filtrable por mecánico, selector de mecánico en cita personal y KPIs por mecánico.
- Incluye módulos de soporte (`components/forms/*`, `utils/citaPersonalHorario`, `utils/fechaLocal`, `utils/parseMontoDecimal`, `components/solicitudes/CatalogoFechaHoraPickers`) de los que dependen las pantallas, porque los cambios estaban entrelazados en los mismos archivos.

### App usuarios (`mecanimovil-usuarios`)
- Badges de modalidad en la lista y el detalle de proveedor, y propagación de `modalidad_atencion` en el agendamiento asistido.

## 2. Verificación contra la base de datos de Render

No se creó una base de datos de test desechable como verificación final: se
verificó **contra el estado real de la base de datos de Render** (Postgres 15,
`mecanimovil-db`, `dpg-d5iia824d50c739ofub0-a`) usando consultas de **solo
lectura** vía MCP, y luego una **simulación local** del estado de Render.

### Hallazgo crítico (bug de deploy) y corrección
La base de datos de Render tenía aplicadas migraciones `0014_*` "fantasma"
(registradas en `django_migrations` pero **sin archivo en el repo**) que ya
habían **renombrado índices**:

| Índice (nombre actual en Render) | Nombre antiguo (ya no existe) |
|---|---|
| `usuarios_we_usuario_3ebe70_idx` | `usuarios_we_usuario_activo_idx` |
| `ordenes_pat_fragmen_5a63a6_idx` | `ordenes_pat_fragmen_idx` |
| `ordenes_pat_confirm_e32a22_idx` | `ordenes_pat_confirm_idx` |

Las migraciones nuevas autogeneradas (`usuarios/0015`, `ordenes/0015`)
**volvían a renombrar** esos índices desde sus nombres antiguos, lo que habría
**roto el deploy** (`RenameIndex` sobre un índice inexistente).

**Solución**: se reemplazaron los `RenameIndex` por
`SeparateDatabaseAndState` con `RunSQL` idempotente
(`ALTER INDEX IF EXISTS ... RENAME TO ...`). Así:
- En bases nuevas: el índice antiguo existe → se renombra.
- En Render: el índice antiguo ya no existe → es no-op, sin fallar.
- El estado de Django queda consistente (`makemigrations --check` sin cambios).

Además, se corrigió un orden de operaciones en `usuarios/0015`: el `AddField`
de `HorarioProveedor.miembro_taller` debía ir **antes** de las constraints que
lo referencian.

### Data migration
`usuarios/0016_data_mandante_por_taller.py` crea un `MiembroTaller(rol='mandante')`
por cada `Taller` con usuario. Es **idempotente** (no duplica). Datos reales en
Render al momento de la verificación: **2 talleres, ambos con usuario → 2
mandantes, 0 con usuario nulo**.

### Simulación local del estado de Render
1. Migrar una BD limpia hasta el estado pre-feature (índices con nombre antiguo).
2. Renombrar los índices a los nombres nuevos (replicando las migraciones fantasma de Render).
3. Aplicar las migraciones nuevas → **aplican OK** (los renames son no-op).
4. `makemigrations --check` para `usuarios` y `ordenes` → **sin cambios**.

> Nota: no se realizó un `pg_dump` completo de Render a una BD local porque el
> MCP no expone credenciales y el `.env` local solo tiene un placeholder. La
> verificación se hizo con consultas de solo lectura sobre Render + simulación
> local del mismo estado, que reproduce exactamente el modo de fallo.

## 3. Pruebas
- 14 tests nuevos (`test_asignacion_mecanico`, `test_motor_match_modalidad`, `test_disponibilidad_union`): asignación, match por modalidad, disponibilidad-unión y no-regresión para talleres sin equipo. **Todos OK** en BD limpia.
- Migraciones aplican sobre estado tipo-Render y `makemigrations --check` sin cambios.

## 4. Pendientes / seguimiento (completados 2026-06-22)

### Merge y deploy en Render
- PRs mergeados a `main`:
  - Backend [#3](https://github.com/Sebas2587/mecanimovil-backend/pull/3) → commit `c311480`
  - Prov [#3](https://github.com/Sebas2587/mecanimovil-prov/pull/3) → commit `2319ecb` (+ fix TS `3347747`)
  - Usuarios [#2](https://github.com/Sebas2587/mecanimovil-usuarios/pull/2) → commit `fb716f5`
- Deploy `mecanimovil-api` en Render: **live** (`dep-d8s9srq8qa3s73af05i0`, ~2 min).
- Health check: `GET /api/hello/` → **200**.

### Migraciones en producción (Render)
Todas aplicadas OK durante el build (`build.sh` → `python manage.py migrate --noinput`):

| Migración | Resultado |
|-----------|-----------|
| `usuarios.0015_miembrotaller_and_more` | OK |
| `ordenes.0015_remove_citaagendapersonal_cita_xor_proveedor_and_more` | OK |
| `ordenes.0016_citaagendapersonal_miembro_taller_and_more` | OK |
| `usuarios.0016_data_mandante_por_taller` | OK |

Los `RenameIndex` idempotentes no fallaron (índices ya renombrados en Render).

### Data migration verificada en Render
| Taller | Mandante creado | `modalidad_atencion` |
|--------|-----------------|----------------------|
| TECNI-CARS D&L SPA (id 5) | TECNI-CARS D&L SPA (id 1) | `en_taller` |
| matias toledo (id 11) | matias toledo (id 2) | `en_taller` |

Total: **2 talleres → 2 mandantes** (idempotente, sin duplicados).

### API verificada
- `GET /api/usuarios/taller/equipo/` sin token → **401** (endpoint registrado, requiere auth como se espera).

### Verificación de apps
- **Usuarios**: smoke test de `providerModalidad.js` — badges y filtro por modalidad OK.
- **Prov**: archivos de la funcionalidad sin errores TS; fix menor en `tipo-cuenta.tsx` (callback `onConfirm`) pusheado a `main`.
- **Expo prov**: Metro levanta con las rutas nuevas (`gestion-equipo` incluida en el stack).

### Checklist visual (manual en dispositivo)
- [ ] Prov: Inicio → tarjeta **Equipo** → CRUD mecánicos / toggle activo.
- [ ] Prov: **Configuración de horarios** → selector de mecánico.
- [ ] Prov: **Calendario** → filtro por mecánico.
- [ ] Prov: **Agendar cita personal** → selector de mecánico.
- [ ] Prov: **Rendimiento** → tabla por mecánico.
- [ ] Usuarios: badges "En taller" / "A domicilio" en lista y detalle de proveedor.

### Nota opcional (no ejecutada)
Separar el refactor de formularios/cita-personal del PR de prov queda como mejora futura; no bloquea la funcionalidad desplegada.
