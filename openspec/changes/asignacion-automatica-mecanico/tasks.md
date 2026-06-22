# Tasks: asignacion-automatica-mecanico

## Backend
- [ ] `services/asignacion_mecanico.py`
- [ ] Integrar en `CarritoAgendamientoViewSet.confirmar`
- [ ] Integrar en `AgendamientoViewSet.confirmar_agendamiento`
- [ ] Integrar en `pagar_solicitud_adjudicada`
- [ ] Integrar en lazy creation `ProveedorOrdenesViewSet.activas`

## Verificación
- [ ] Asigna mecánico apto y libre
- [ ] Balanceo entre 2 mecánicos aptos
- [ ] Sin candidato → mecanico_asignado null sin romper la orden
