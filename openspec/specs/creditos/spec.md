# creditos Specification

## Purpose
Sistema de créditos internos de Mecanimovil. Los proveedores consumen créditos
para acceder a solicitudes de usuarios o funciones premium de la plataforma.

## Requirements

### Requirement: Saldo de créditos del proveedor
Cada proveedor tiene un saldo de créditos que se recarga mediante pago.

#### Scenario: Consultar saldo
- GIVEN un proveedor autenticado
- WHEN hace GET /api/creditos/saldo/
- THEN recibe su saldo actual y el historial de movimientos

#### Scenario: Recargar créditos
- GIVEN un proveedor con saldo insuficiente
- WHEN compra un paquete de créditos mediante MercadoPago
- AND el pago es aprobado
- THEN su saldo se incrementa según el paquete adquirido
- AND se registra el movimiento con tipo=recarga

### Requirement: Consumo de créditos al acceder a solicitudes
El proveedor consume créditos cuando acepta o visualiza datos de contacto de una solicitud.

#### Scenario: Proveedor acepta solicitud con saldo suficiente
- GIVEN un proveedor con saldo >= costo de la acción
- WHEN acepta una solicitud
- THEN se descuenta el costo del saldo
- AND se registra el movimiento con tipo=consumo

#### Scenario: Proveedor sin saldo intenta aceptar solicitud
- GIVEN un proveedor con saldo=0
- WHEN intenta aceptar una solicitud
- THEN recibe status 402 con mensaje "Saldo insuficiente. Recarga tus créditos"
- AND no se descuenta nada
