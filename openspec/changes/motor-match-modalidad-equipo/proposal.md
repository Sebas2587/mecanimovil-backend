# motor-match-modalidad-equipo

## Why

El motor de match hoy ramifica por clase de entidad (`taller` vs `mecanico`). Con la
unificación por modalidad, una búsqueda "a domicilio" debe incluir talleres con
`modalidad_atencion in (a_domicilio, ambas)`. Además, un taller no debe aparecer para un
servicio si no tiene ningún mecánico habilitado con la especialidad requerida.

## What Changes

- `motor_match._queryset_ofertas_compatibles`: filtrar por modalidad solicitada.
- Excluir taller para un servicio si no existe `MiembroTaller(rol=mecanico, activo=True)`
  con la especialidad requerida (cuando el taller tiene equipo configurado).
- `_serialize_candidato`: reflejar `modalidad`/`a_domicilio` correctos.

## Requirements

- REQ-MATCH-MODALIDAD: la búsqueda por modalidad SHALL incluir talleres con modalidad compatible.
- REQ-MATCH-ESPECIALIDAD-EQUIPO: un taller con equipo SHALL aparecer solo si tiene mecánico activo con la especialidad.
- REQ-MATCH-FALLBACK: un taller sin equipo SHALL seguir el comportamiento previo.
- REQ-MATCH-DEDUPE: el candidato SHALL seguir siendo uno por proveedor (dedupe por usuario).
