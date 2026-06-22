# taller-rendimiento-mecanicos

## Why

El taller debe controlar cuántos servicios se asignaron a cada mecánico y su rendimiento
(servicios completados), para distribución de carga y evaluación.

## What Changes

- Endpoint de rendimiento por mecánico: agregación sobre `SolicitudServicio` con
  `mecanico_asignado` (asignadas, en proceso, completadas) por rango de fechas.
- Sin contador denormalizado en v1 (agregación on-demand).

## Requirements

- REQ-KPI-POR-MECANICO: SHALL exponer, por mecánico, conteos de órdenes asignadas y completadas.
- REQ-KPI-SCOPE: SHALL limitarse a los mecánicos del taller del usuario autenticado.
