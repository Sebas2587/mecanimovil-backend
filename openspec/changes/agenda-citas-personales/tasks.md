# Tasks: agenda-citas-personales

## Backend
- [x] Modelos `CitaAgendaPersonal` + `CitaAgendaPersonalDetalle`
- [x] Migración `0014_cita_agenda_personal`
- [x] Servicio dominio `services/cita_agenda_personal.py`
- [x] Integración `intervalos_ocupados_dia`
- [x] ViewSet CRUD + cerrar/cancelar/validar-slot
- [x] `ProveedorAgendaViewSet` feed unificado
- [x] Tests `test_cita_agenda_personal.py`
- [ ] Ejecutar tests en CI/local con PostGIS + GDAL

## App proveedores
- [x] `agendaProveedorService.ts`
- [x] Calendario unificado + badges + FAB
- [x] `agendar-cita-personal.tsx`
- [x] `cita-agenda-personal/[id].tsx`
- [x] Tab Órdenes completadas/rechazadas

## Verificación supervisor
- [ ] Cita activa bloquea slot usuarios
- [ ] Cerrar → completadas, cancelar → rechazadas
- [ ] DELETE solo cancelada (409 en otros)
- [ ] Sin checklist/créditos en flujo personal
