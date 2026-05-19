# Propuesta: Fase 6 — Integración aprendizaje + salud en confirmación

## Why
El motor semántico y los patrones aprendidos deben alimentarse con decisiones reales del usuario (confirmar candidato / crear solicitud), incluyendo métricas de salud cruzadas con el texto.

## What Changes
- Cliente envía `metadata_ia_entrada` al confirmar catálogo (análisis + componentes de salud, sin texto efímero extra).
- Comando `alimentar_patrones_necesidad` para bootstrap desde solicitudes históricas.
- Admin de patrones aprendidos para operaciones.

## Non-goals
- Reentrenar modelos externos.
- Persistir consultas `analizar-necesidad` en vivo.
