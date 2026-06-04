# Comparador: respeto catálogo repuestos en motor_match

## Problema
Con `requiere_repuestos=false`, el pool excluía proveedores que solo publican con repuestos.
El match y las cards no reflejaban la configuración real por servicio.

## Solución
- Incluir todas las ofertas con precio publicado (MO, con repuestos o ambas).
- Precio/desglose efectivo por servicio; repuestos obligatorios si el catálogo no tiene solo MO.
- Scoring sin excluir proveedores con repuestos cuando el cliente pidió solo MO.

## Spec
`specs/asistente-agendamiento/spec.md`
