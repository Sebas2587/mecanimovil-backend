## MODIFIED Requirements

### Requirement: Sucursal según la dirección del taller

El sistema MUST elegir la sucursal cuya comuna aparece en la dirección configurada del taller: calle, número, comuna, ciudad y detalles de `TallerDireccion`, la dirección del usuario, y las direcciones guardadas de ese usuario. Si el texto nombra una comuna específica y también Santiago, MUST elegir la específica. Si varias sucursales comparten la comuna Santiago y ninguna comuna específica calza, MUST usar la primera sucursal de Santiago de la lista. MUST usar la primera sucursal que no es Concepción solo cuando no hay dirección configurada.

#### Scenario: John Kennedy 709, La Florida

- **WHEN** el taller tiene configurado John Kennedy 709 en La Florida
- **AND** la casa es Indra
- **THEN** la sucursal MUST ser Av. Vicuña Mackenna 8580, La Florida

#### Scenario: Solo Santiago no elige la última sucursal

- **GIVEN** la dirección configurada nombra Santiago y no nombra La Florida, Maipú ni Concepción
- **WHEN** se elige la sucursal de Indra
- **THEN** la sucursal MUST ser Lira 664, Santiago
- **AND** MUST NOT ser Avenida Brasil 28

#### Scenario: La dirección del taller gana a la oficina virtual

- **GIVEN** el usuario tiene una oficina virtual en Providencia que nombra Santiago
- **AND** otra dirección guardada del mismo usuario nombra La Florida
- **WHEN** se elige la sucursal de Indra
- **THEN** la sucursal MUST ser Av. Vicuña Mackenna 8580, La Florida
