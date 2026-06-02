# oferta-multimarca-por-marca Specification

## Purpose
Precios diferenciados por marca para proveedores multimarca, con precio base opcional, sin alterar el flujo de especialistas.

## Requirements

### REQ-MM-COBERTURA
`tipo_cobertura_marca=multimarca` SHALL mantener al proveedor visible para vehículos de cualquier marca en discovery, comparador y `proveedores_filtrados`.

### REQ-MM-PRECIO-MARCA
Un proveedor multimarca verificado MAY publicar varias `OfertaServicio` del mismo `servicio` con distintas `marca_vehiculo_seleccionada`.

### REQ-MM-PRECIO-BASE
Una oferta con `marca_vehiculo_seleccionada=null` SHALL interpretarse como precio base para marcas sin oferta específica.

### REQ-RESOLUCION-MARCA
WHEN el cliente consulta con marca de vehículo X, THEN el sistema SHALL usar la oferta con `marca_vehiculo_seleccionada_id=X` si existe; ELSE la oferta genérica del mismo proveedor y servicio; ELSE no ofertar ese servicio para ese proveedor.

#### Scenario: Toyota específico y base genérico
- GIVEN taller multimarca con cambio de aceite genérico $40.000 y cambio de aceite Toyota $45.000
- WHEN el vehículo del cliente es Toyota
- THEN el comparador y la ficha SHALL mostrar $45.000

#### Scenario: Solo precio base
- GIVEN taller multimarca con cambio de aceite solo genérico $40.000
- WHEN el vehículo es BMW
- THEN el cliente SHALL ver $40.000

### REQ-ESP-SIN-CAMBIO
WHEN `tipo_cobertura_marca=especialista`, THEN `mis_marcas` SHALL devolver solo `marcas_atendidas` y la validación de onboarding SHALL no cambiar.

### REQ-PROV-UX
La app proveedor SHALL ofrecer tabs «Precio base» y «Por marca» al publicar servicios si el proveedor es multimarca.

### REQ-CLI-PERFIL
La ficha del proveedor en usuarios SHALL resolver precios con el vehículo activo del cliente cuando exista; sin vehículo, agrupar por servicio mostrando «Desde $X» si hay varios precios.

## Archivos

| Repo | Archivo |
|------|---------|
| Backend | `apps/servicios/oferta_resolucion.py`, `views.py`, `panel_servicios_utils.py` |
| Backend | `apps/ordenes/services/agendamiento_ia/motor_match.py` |
| Prov | `crear-servicio.tsx`, `catalogo-servicios-marcas.tsx`, `mis-servicios.tsx` |
| Usuarios | `utils/ofertaResolucionMarca.js`, `servicioVehiculoCompat.js`, `providers.js` |
