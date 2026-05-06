# pagos-mercadopago Specification

## Purpose
Procesar cobros a usuarios y pagos a proveedores mediante MercadoPago.
Incluye configuración de credenciales por proveedor, webhook de eventos y split de pagos.

## Requirements

### Requirement: Configuración de cuenta MercadoPago del proveedor
Cada proveedor conecta su cuenta MercadoPago para recibir pagos.

#### Scenario: Proveedor conecta cuenta MP
- GIVEN un proveedor autenticado
- WHEN hace POST /api/pagos/configurar-mp/ con access_token de MercadoPago
- THEN se almacenan las credenciales encriptadas del proveedor
- AND se valida que el token sea válido contra la API de MP

#### Scenario: Token de MP inválido
- GIVEN credenciales inválidas de MercadoPago
- WHEN el proveedor intenta configurar su cuenta
- THEN recibe status 400 con mensaje de error de validación

### Requirement: Cobro al usuario al completar orden
Al completar una orden, se inicia el cobro al usuario mediante MP.

#### Scenario: Pago procesado correctamente
- GIVEN una orden completada con monto definido
- WHEN se ejecuta el Celery task de cobro
- THEN se crea un Payment Intent en MercadoPago
- AND se registra la transacción en la base de datos con estado=pendiente

#### Scenario: Webhook de pago aprobado
- GIVEN MP envía evento payment.updated con status=approved
- WHEN llega el POST al webhook /api/pagos/webhook/
- THEN la transacción se actualiza a estado=aprobado
- AND se transfiere el monto neto al proveedor (descontando comisión de plataforma)
- AND se registra el ingreso en el historial del proveedor

#### Scenario: Pago rechazado por MP
- GIVEN MP envía evento con status=rejected
- WHEN llega el POST al webhook
- THEN la transacción se marca como rechazada
- AND se notifica al usuario para reintentar con otro método de pago

### Requirement: Comisión de plataforma
Mecanimovil retiene un porcentaje configurable de cada pago.

#### Scenario: Cálculo de comisión
- GIVEN un pago aprobado de $1000 con comisión=10%
- WHEN se procesa la distribución
- THEN el proveedor recibe $900
- AND Mecanimovil registra $100 como ingreso de comisión
