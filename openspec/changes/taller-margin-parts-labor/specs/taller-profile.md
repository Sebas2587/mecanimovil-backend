# Taller Profile API

## ADDED Requirements

### REQ-MARGIN-001: Taller margin field
The `Taller` model **SHALL** include a `margen_ganancia_pct` field:
- Type: `DecimalField(max_digits=5, decimal_places=2)`
- Nullable: `True` (null means no configured margin)
- Validators: `MinValueValidator(0)`, `MaxValueValidator(999.99)`
- Help text: "Margen de ganancia sobre costo de repuestos (porcentaje). Ejemplo: 30 significa vender a costo × 1.30"

#### Scenario: Workshop owner reads their margin
**Given** a taller with `margen_ganancia_pct = 30.00`  
**When** GET `/usuarios/estado-proveedor/` or actualizar_propio  
**Then** response **SHALL** include `margen_ganancia_pct: 30.00`

#### Scenario: Workshop owner updates margin
**Given** an authenticated taller owner  
**When** PATCH actualizar_propio with `{"margen_ganancia_pct": 25.5}`  
**Then** taller.margen_ganancia_pct **SHALL** be `25.50`

#### Scenario: Null margin stays null
**Given** a taller with `margen_ganancia_pct = null`  
**When** quote engine runs  
**Then** it **SHALL NOT** invent a default margin (0% or 30%)

### REQ-MARGIN-002: Serializer exposure
The taller profile serializers used by workshop app **SHALL** include `margen_ganancia_pct` as a read-write field.

The taller public serializer (customer-facing) **SHALL NOT** include `margen_ganancia_pct`.
