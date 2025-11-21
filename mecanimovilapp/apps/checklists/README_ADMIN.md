# 🔧 Admin de Checklists - Guía de Uso

## 📋 Resumen

El admin de checklists permite gestionar de forma intuitiva el sistema de checklists para MecaniMóvil. Está organizado en una estructura de **catálogo → templates → instancias**.

## 🎯 Flujo de Trabajo

### 1. **Items del Catálogo** (Base del Sistema)
- **URL**: `/admin/checklists/checklistitemcatalog/`
- **Propósito**: Crear elementos reutilizables que se pueden usar en cualquier checklist
- **Categorías principales**:
  - 📋 Información General
  - 🚗 Datos del Vehículo  
  - 📦 Inventario del Vehículo
  - 🔧 Servicios Aplicados
  - ⚡ Sistema Eléctrico
  - 🚨 Sistema de Frenos
  - 📝 Observaciones del Técnico
  - ✍️ Firmas de Conformidad

### 2. **Templates de Checklist** (Configuración por Servicio)
- **URL**: `/admin/checklists/checklisttemplate/`
- **Propósito**: Crear plantillas específicas asignando items del catálogo a servicios
- **Proceso**:
  1. Crear nuevo template
  2. Asignar a un servicio específico
  3. Agregar items del catálogo usando el inline
  4. Configurar orden y obligatoriedad

### 3. **Instancias de Checklist** (Ejecución en Tiempo Real)
- **URL**: `/admin/checklists/checklistinstance/`
- **Propósito**: Ver y monitorear checklists ejecutados por técnicos
- **Solo lectura**: Las instancias se crean automáticamente desde la app móvil

## 🔧 Características del Admin

### **Items del Catálogo - Funcionalidades**

#### **Tipos de Pregunta Disponibles**
- **TEXT**: Texto libre
- **NUMBER**: Entrada numérica
- **BOOLEAN**: Sí/No
- **SELECT**: Selección única de opciones
- **MULTISELECT**: Selección múltiple
- **PHOTO**: Captura de fotografías
- **SIGNATURE**: Firma digital
- **DATETIME**: Fecha y hora
- **KILOMETER_INPUT**: Entrada de kilometraje
- **FUEL_GAUGE**: Medidor de combustible
- **VEHICLE_DIAGRAM**: Diagrama de vehículo
- **SERVICE_SELECTION**: Selección de servicios

#### **Campo Opciones de Selección**
Para los tipos SELECT y MULTISELECT:
```
Excelente
Bueno
Regular
Malo
Crítico
```
- Una opción por línea
- Se convierte automáticamente a formato JSON
- Solo aplica para tipos de selección

#### **Acciones Masivas**
- ⭐ Marcar/desmarcar como uso frecuente
- ✅ Activar/desactivar items
- 📊 Ver estadísticas de uso

### **Templates de Checklist - Funcionalidades**

#### **Asignación de Items**
- Inline completamente simplificado
- Solo 2 campos esenciales:
  - **Orden visual**: Secuencia de aparición en el checklist (1, 2, 3...)
  - **Item del catálogo**: Selección del elemento base (con información completa)
- Items ordenados por uso frecuente para facilitar selección
- Representación informativa: `[Tipo] Nombre (Categoría)`
- **Filosofía**: Toda la información (descripción, placeholder, obligatoriedad) viene del catálogo
- **Sin sobrescrituras**: No se permite modificar propiedades del item por template

#### **Información Visual**
- Total de items en el template
- Número de items de uso frecuente  
- Estado del servicio asignado
- Información de creación

## 📊 Dashboard y Monitoreo

### **Lista de Items del Catálogo**
- Vista filtrable por categoría, tipo, estado
- Búsqueda por nombre y descripción
- Indicador de uso en templates
- Ordenamiento inteligente (frecuentes primero)

### **Lista de Templates**
- Vista por servicio asignado
- Información de items incluidos
- Estado de activación
- Acciones rápidas de edición

### **Lista de Instancias**
- Vista de checklists ejecutados
- Barra de progreso visual
- Información de la orden asociada
- Estados: Pendiente, En Progreso, Completado

## 🚀 Casos de Uso Comunes

### **Crear un Nuevo Tipo de Checklist**

1. **Crear Items del Catálogo**:
   ```
   Admin → Items del catálogo → Agregar
   - Nombre: "Verificación de Frenos"
   - Categoría: "Sistema de Frenos"
   - Tipo: "BRAKE_CHECK"
   - Pregunta: "¿Cuál es el estado de los frenos?"
   ```

2. **Crear Template**:
   ```
   Admin → Templates → Agregar
   - Nombre: "Checklist Mantenimiento General"
   - Servicio: "Mantenimiento Preventivo"
   - Agregar items usando el inline
   ```

3. **Configurar Orden**:
   ```
   En el inline:
   - Orden 1: Identificación del Técnico
   - Orden 2: Fecha y Hora
   - Orden 3: Kilometraje
   - ...
   ```

### **Modificar Items Existentes**

1. **Editar Item del Catálogo**:
   - Cambiar opciones de selección
   - Actualizar texto de pregunta
   - Modificar configuración de fotos

2. **Los cambios se reflejan automáticamente** en todos los templates que usen ese item

### **Gestionar Templates por Servicio**

1. **Buscar por servicio**: Usar filtros en la lista
2. **Duplicar template**: Crear nuevo basado en existente
3. **Activar/desactivar**: Control de disponibilidad

## 🔍 Tips y Mejores Prácticas

### **Organización de Items**
- Usar nombres descriptivos y únicos
- Marcar como "uso frecuente" los items más comunes
- Organizar por categorías lógicas
- Mantener descripciones claras y útiles

### **Configuración de Templates**
- Un template por tipo de servicio
- Orden lógico de items (general → específico → firmas)
- Configurar obligatoriedad según importancia
- Usar descripciones personalizadas cuando sea necesario

### **Mantenimiento**
- Revisar periódicamente items sin uso
- Actualizar opciones de selección según feedback
- Monitorear instancias completadas para mejoras

## 🎯 URLs de Acceso Rápido

```bash
# Admin Principal
http://localhost:8000/admin/

# Items del Catálogo
http://localhost:8000/admin/checklists/checklistitemcatalog/

# Templates de Checklist  
http://localhost:8000/admin/checklists/checklisttemplate/

# Instancias Ejecutadas
http://localhost:8000/admin/checklists/checklistinstance/

# Respuestas Individuales
http://localhost:8000/admin/checklists/checklistitemresponse/

# Fotos de Checklist
http://localhost:8000/admin/checklists/checklistphoto/
```

## ✅ Estado del Sistema

- ✅ **Admin completamente funcional**
- ✅ **19 items predefinidos en el catálogo**
- ✅ **Formularios intuitivos con widgets personalizados**
- ✅ **APIs REST integradas para la app móvil**
- ✅ **Sin errores de configuración**

El sistema está listo para crear templates de checklist y ser utilizado por la aplicación móvil de proveedores. 