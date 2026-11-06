# Fix: Validación de Balatas vs Pastillas de Freno

## Problema Reportado

El dueño del taller (Sebastián / MecaniMovil) reportó que el motor de cotización no es confiable: antes de mostrar una cotización, coloca lo que "cree" que es correcto sin consultar al taller. El taller confía en esas líneas y no puede haber margen de error.

**Caso concreto de falla:**
Se pidió cotizar "balatas traseras" (o "alatas traseras") para un Peugeot Boxer. La cotización etiquetó la línea como "balatas", pero el enlace del producto apuntaba a pastillas de freno ("pastillas de frenos"). En el lenguaje del taller chileno:
- **Balatas/zapatas**: zapatas de freno de tambor (drum shoes)
- **Pastillas**: pastillas de freno de disco (disc pads)

Son piezas completamente diferentes. Un título que "se ve relacionado" no es suficiente si el producto enlazado, la familia de pieza, la posición del eje o la versión del vehículo no coinciden.

## Causa Raíz

### 1. Mapeo de Categorías Incorrecto
En `busqueda_web_repuestos.py`, líneas 315-316:
```python
'balata': 'pastillas-de-freno',
'balatas': 'pastillas-de-freno',
```
Trataba balatas (tambor) como sinónimo de pastillas (disco).

### 2. Función de Detección Mezclada
La función `_es_pastillas_freno()` incluía tanto pastillas como balatas:
```python
def _es_pastillas_freno(nombre: str) -> bool:
    """Pastilla o balata. Un disco de freno no entra."""
    n = _norm(nombre)
    if 'freno' not in n and 'balata' not in n:
        return False
    return 'pastilla' in n or 'balata' in n
```

### 3. Falta de Validación de Tipo y Posición
No había validación que verificara:
- Tipo de freno coincide (pastillas vs balatas)
- Posición del eje coincide (delantero vs trasero)
- El producto enlazado es exactamente el que se pidió

## Solución Implementada

### 1. Separación de Categorías
**Archivo:** `busqueda_web_repuestos.py`
- Cambiado mapeo de balatas: `'balata': 'zapatas-freno'`
- Pastillas mantienen: `'pastilla': 'pastillas-de-freno'`

### 2. Funciones de Detección Separadas
**Archivo:** `busqueda_web_repuestos.py`

```python
def _es_pastillas_freno(nombre: str) -> bool:
    """Pastillas de freno (disco). Balatas/zapatas (tambor) NO entran aquí."""
    n = _norm(nombre)
    if 'freno' not in n and 'pastilla' not in n:
        return False
    return 'pastilla' in n

def _es_balatas_freno(nombre: str) -> bool:
    """Balatas/zapatas de freno (tambor). Pastillas (disco) NO entran aquí."""
    n = _norm(nombre)
    return 'balata' in n or 'zapata' in n
```

### 3. Validación de Tipo y Posición
**Archivo:** `busqueda_web_repuestos.py`

Nueva función `_validar_tipo_familia_freno(nombre_pedido, titulo_producto)`:
- Verifica que el tipo de freno coincida (pastillas vs balatas)
- Verifica que la posición coincida (delantero vs trasero)
- Detecta ambigüedad (se pide delantero pero el producto no especifica)
- Retorna `(es_valido: bool, motivo_rechazo: str)` en español

```python
def _posicion_freno(texto: str) -> str | None:
    """Extrae posición del freno: 'delantero', 'trasero' o None."""
    n = _norm(texto)
    if 'delanter' in n:
        return 'delantero'
    if 'traser' in n:
        return 'trasero'
    return None

def _validar_tipo_familia_freno(nombre_pedido: str, titulo_producto: str) -> tuple[bool, str]:
    """Valida que el tipo de freno (pastillas vs balatas) y posición coincidan."""
    # ... verifica tipo (pastillas vs balatas)
    # ... verifica posición (delantero vs trasero)
    # ... detecta ambigüedad
    return (es_valido, motivo_rechazo)
```

### 4. Integración en Flujo de Validación
**Archivo:** `busqueda_web_repuestos.py`

La validación se integró en `_motivo_calidad_pastilla()`:
```python
# CRÍTICO: Validar que tipo de freno (pastillas vs balatas) y posición coincidan
if _es_pastillas_freno(nombre) or _es_balatas_freno(nombre):
    es_valido, motivo = _validar_tipo_familia_freno(nombre, titulo_ficha)
    if not es_valido:
        return 'tipo_freno_incompatible'
```

### 5. Código de Rechazo y Mensaje
**Archivo:** `validar_linea_cotizacion.py`

- Agregado `'tipo_freno_incompatible'` al conjunto `_INCOMPATIBLE`
- Mensaje en español: `'El tipo de freno no coincide (pastillas vs balatas, o posición delantero/trasero).'`

### 6. Familias Sensibles
**Archivo:** `familias_sensibles.py`

Separadas las familias:
```python
'pastilla_freno': {
    'keywords': ('pastilla', 'pastillas'),
    'excluye': ('balata', 'zapata'),
},
'balata_freno': {
    'keywords': ('balata', 'balatas', 'zapata', 'zapatas'),
    'excluye': ('pastilla',),
},
```

## Tests Añadidos

**Archivo:** `test_validar_tipo_freno.py` (NUEVO)

Suite completa de tests:
1. **test_balatas_no_es_pastillas**: Verifica separación de detección
2. **test_validar_tipo_familia_freno_pastillas_vs_balatas**: Rechazo de tipo incorrecto
3. **test_validar_tipo_familia_freno_posicion_correcta**: Acepta cuando coincide
4. **test_validar_tipo_familia_freno_posicion_incorrecta**: Rechaza posición incorrecta
5. **test_validar_tipo_familia_freno_posicion_ambigua**: Rechaza ambigüedad
6. **test_posicion_freno_extraccion**: Extracción de posición
7. **test_motivo_calidad_pastilla_rechaza_tipo_incompatible**: Rechazo en flujo
8. **test_motivo_calidad_pastilla_acepta_tipo_correcto**: Acepta cuando correcto
9. **test_validar_repuesto_rechaza_tipo_incompatible**: Validación end-to-end rechazo
10. **test_validar_repuesto_acepta_tipo_compatible**: Validación end-to-end acepta

**Caso de regresión específico:**
```python
def test_validar_repuesto_rechaza_tipo_incompatible(self):
    """Caso reportado: balatas traseras -> pastillas de freno debe rechazarse."""
    rep = {
        'nombre': 'balatas traseras',
        'fuentes_detalle': [{
            'url': 'https://repuestoschile.cl/pastillas-peugeot-boxer',
            'nombre': 'Pastillas de freno Peugeot Boxer',
            'precio_clp': 35000,
        }],
    }
    resultado = validar_repuesto(rep, marca='Peugeot', modelo='Boxer', ...)
    self.assertEqual(resultado['validacion_estado'], 'sin_referencia_valida')
```

## Cambios en el Contrato de API

**No hay cambios en el contrato de API existente.**

### Comportamiento Anterior
Una línea de cotización podía mostrar un producto incompatible con `validacion_estado='ok'`.

### Comportamiento Nuevo
Una línea con tipo de freno incompatible ahora:
- `validacion_estado`: `'sin_referencia_valida'`
- `validacion_motivo`: Mensaje en español explicando el problema (ej: "El tipo de freno no coincide (pastillas vs balatas, o posición delantero/trasero).")
- El frontend puede mostrar este `validacion_motivo` al taller

### Nuevos Campos Estructurados (Propuesta Futura)
Para que el frontend pueda mostrar alertas específicas:
```python
{
    'validacion_estado': 'requiere_revision',  # o 'sin_referencia_valida'
    'validacion_motivo': 'El enlace apunta a pastillas, no a balatas traseras',
    'validacion_detalles': {
        'tipo_conflicto': 'tipo_freno',
        'tipo_pedido': 'balatas',
        'tipo_producto': 'pastillas',
        'posicion_pedido': 'trasero',
        'posicion_producto': None,
    }
}
```
*Nota: Los campos estructurados en `validacion_detalles` no están implementados aún. Actualmente solo se usa `validacion_motivo` en string.*

## Cómo Verificar

### 1. Tests Automatizados
```bash
python manage.py test mecanimovilapp.apps.ordenes.tests.test_validar_tipo_freno --verbosity=2
```

Todos los tests deben pasar (10 tests).

### 2. Test Manual - Caso de Regresión
**Entrada:**
- Vehículo: Peugeot Boxer 2015, Diesel 2.2
- Pedido: "balatas traseras"
- Candidato encontrado: URL que apunta a "Pastillas de freno Peugeot Boxer"

**Comportamiento esperado:**
- La validación debe rechazar el candidato
- `validacion_estado`: `'sin_referencia_valida'`
- `validacion_motivo` debe contener mensaje sobre incompatibilidad de tipo

### 3. Test Manual - Caso Correcto
**Entrada:**
- Vehículo: Peugeot Boxer 2015, Diesel 2.2
- Pedido: "balatas traseras"
- Candidato encontrado: URL que apunta a "Balatas de freno traseras Peugeot Boxer"

**Comportamiento esperado:**
- La validación debe aceptar el candidato
- `validacion_estado`: `'ok'`
- `precio_verificado_clp` > 0

### 4. Test Manual - Pastillas
**Entrada:**
- Vehículo: Fiat Bravo 2012, T-Jet 1.4
- Pedido: "pastillas delanteras"
- Candidato encontrado: URL que apunta a "Pastillas de freno delanteras Fiat Bravo 1.4"

**Comportamiento esperado:**
- La validación debe aceptar el candidato
- `validacion_estado`: `'ok'`

## Impacto en Producción

### Cotizaciones Existentes
- ✅ No se mutan cotizaciones guardadas
- ✅ No se borran datos existentes
- ✅ No se reenvían cotizaciones a clientes

### Comportamiento de Búsqueda
- ✅ Búsquedas de "balatas" ahora mapean a "zapatas-freno" (categoría correcta)
- ✅ Búsquedas de "pastillas" siguen mapeando a "pastillas-de-freno"
- ✅ La validación rechaza enlaces con tipo incorrecto

### Feedback al Taller
Cuando hay incompatibilidad:
- El sistema **no** muestra la línea como "segura"
- El `validacion_estado` indica que requiere revisión
- El `validacion_motivo` explica el problema en español
- El taller puede decidir si aceptar o buscar otro producto

### Flujo Completo
1. Se solicita "balatas traseras Peugeot Boxer"
2. Se busca en web (ahora categoría "zapatas-freno")
3. Candidato encontrado: "Pastillas de freno Peugeot Boxer"
4. Validación detecta tipo incompatible
5. Candidato rechazado con motivo `'tipo_freno_incompatible'`
6. Si no hay otro candidato válido:
   - `validacion_estado`: `'sin_referencia_valida'`
   - `validacion_motivo`: "El tipo de freno no coincide..."
7. El taller ve que la línea necesita revisión y busca manualmente

## Archivos Modificados

1. `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/busqueda_web_repuestos.py`
   - Mapeo de categorías (líneas 313-316)
   - Funciones de detección separadas (líneas ~3055-3110)
   - Validación de tipo y posición (nuevas funciones)
   - Integración en `_motivo_calidad_pastilla`

2. `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/validar_linea_cotizacion.py`
   - Código de rechazo `'tipo_freno_incompatible'`
   - Mensaje de error en español
   - Importación de nuevas funciones

3. `mecanimovilapp/apps/ordenes/services/asistente_cotizacion/familias_sensibles.py`
   - Familia `'pastilla_freno'` separada
   - Familia `'balata_freno'` nueva
   - Exclusión mutua entre ambas

4. `mecanimovilapp/apps/ordenes/tests/test_validar_tipo_freno.py` (NUEVO)
   - Suite completa de tests
   - Caso de regresión del bug reportado

## Próximos Pasos (Opcional)

### Frontend
Actualizar la UI para mostrar alertas específicas cuando:
- `validacion_estado === 'sin_referencia_valida'`
- `validacion_motivo` contiene texto sobre incompatibilidad

Ejemplo de mensaje UI:
```
⚠️ No se encontró una referencia válida para "balatas traseras"
El enlace disponible apunta a pastillas (disco), no a balatas (tambor).
Por favor, verifica manualmente el precio antes de enviar al cliente.
```

### Campos Estructurados (Futuro)
Si el frontend necesita lógica específica por tipo de error, agregar:
```python
'validacion_detalles': {
    'tipo_conflicto': 'tipo_freno' | 'posicion' | 'ambiguo',
    'tipo_pedido': 'balatas' | 'pastillas',
    'tipo_producto': 'balatas' | 'pastillas' | None,
    'posicion_pedido': 'delantero' | 'trasero' | None,
    'posicion_producto': 'delantero' | 'trasero' | None,
}
```

## Resumen

**Antes:**
- Balatas y pastillas tratadas como sinónimos ❌
- Enlaces incorrectos marcados como válidos ❌
- Taller no confiaba en el motor de cotización ❌

**Después:**
- Balatas y pastillas son familias separadas ✅
- Validación de tipo y posición de freno ✅
- Enlaces incompatibles son rechazados ✅
- Feedback en español sobre por qué se rechazó ✅
- Taller puede confiar en líneas marcadas como `'ok'` ✅

**Principio aplicado:**
> No mostrar una pieza como correcta si el nombre mostrado, el producto enlazado, la familia de pieza, el eje (delantero/trasero) o el vehículo (marca/modelo/versión/año) no coinciden.
