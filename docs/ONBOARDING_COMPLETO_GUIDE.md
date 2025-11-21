# 📋 Sistema de Onboarding Completo - Guía Técnica

## 🎯 **Resumen de Mejoras Implementadas**

El sistema de onboarding ha sido **completamente optimizado** para recopilar **toda la información relevante** para la evaluación y habilitación posterior de talleres y mecánicos.

---

## 🗃️ **1. Almacenamiento de Datos del Onboarding**

### **📊 Información Básica del Proveedor**
```sql
-- Tabla: usuarios_taller / usuarios_mecanicodomicilio
- nombre, telefono, descripcion
- rut (talleres), dni (mecánicos)
- direccion (talleres), experiencia_anos (mecánicos)
- estado_verificacion, verificado, activo
- onboarding_completado, onboarding_iniciado
```

### **🔧 Especialidades de Servicio**
```sql
-- Relación M2M: especialidades
- Taller.especialidades → servicios_categoriaservicio
- MecanicoDomicilio.especialidades → servicios_categoriaservicio

Ejemplos:
- Mecánica General, Electricidad Automotriz
- Frenos, Suspensión, Motor, Transmisión
- Aire Acondicionado, Diagnóstico por Computadora
```

### **🚗 Marcas de Vehículos Atendidas**
```sql
-- Relación M2M: marcas_atendidas
- Taller.marcas_atendidas → vehiculos_marcavehiculo
- MecanicoDomicilio.marcas_atendidas → vehiculos_marcavehiculo

Ejemplos:
- Toyota, Honda, Nissan, Hyundai
- Chevrolet, Ford, Volkswagen
- Mazda, Suzuki, Kia
```

### **📄 Documentos de Verificación**
```sql
-- Tabla: usuarios_documentoonboarding
- tipo_documento (dni_frontal, dni_trasero, etc.)
- archivo (imagen del documento)
- taller_id / mecanico_id (FK al proveedor)
- verificado, fecha_subida
```

---

## 🎨 **2. Flujo de Onboarding Optimizado**

### **Para Mecánicos (5 pasos):**
1. **Información Básica** - nombre, teléfono, DNI, experiencia
2. **Especialidades** - servicios que ofrece
3. **Marcas** - marcas de vehículos que atiende  
4. **Documentación** - documentos requeridos
5. **Finalizar** - confirmación y registro

### **Para Talleres (5 pasos):**
1. **Información Básica** - nombre, teléfono, RUT, dirección
2. **Especialidades** - servicios que ofrece
3. **Marcas** - marcas de vehículos que atiende
4. **Documentación** - documentos requeridos  
5. **Finalizar** - confirmación y registro

---

## 🔧 **3. Nuevas APIs Implementadas**

### **Especialidades (Mejorada)**
```typescript
POST /api/usuarios/actualizar-especialidades/
{
  "especialidades": [1, 2, 3, 5] // IDs de CategoriaServicio
}
```

### **Marcas de Talleres**
```typescript
POST /api/usuarios/actualizar-marcas-taller/
{
  "marcas": [1, 2, 4, 7] // IDs de MarcaVehiculo
}
```

### **Marcas de Mecánicos**
```typescript
POST /api/usuarios/actualizar-marcas-mecanico/
{
  "marcas": [1, 3, 5, 8] // IDs de MarcaVehiculo
}
```

### **Obtener Marcas Disponibles**
```typescript
GET /api/vehiculos/marcas/
// Devuelve todas las marcas disponibles
```

---

## 📱 **4. Pantallas del Frontend**

### **Nueva Pantalla: Marcas de Vehículos**
- **Archivo**: `app/(onboarding)/marcas.tsx`
- **Funcionalidad**: 
  - Lista todas las marcas disponibles
  - Búsqueda y filtrado
  - Selección múltiple obligatoria
  - Validación (mínimo 1 marca)

### **Especialidades Mejorada**
- **Archivo**: `app/(onboarding)/especialidades.tsx`
- **Mejoras**:
  - Ahora disponible para talleres también
  - Flujo optimizado hacia marcas
  - Mejor validación

### **Finalizar Mejorado**
- **Archivo**: `app/(onboarding)/finalizar.tsx`
- **Nuevas Funciones**:
  - Guarda especialidades Y marcas
  - Funciona para talleres y mecánicos
  - Mejor manejo de errores

---

## 🗂️ **5. Tabla DocumentoOnboarding - Función y Uso**

### **✅ Función Correcta:**
- **Almacena documentos** de verificación durante onboarding
- **Organiza por tipo** (DNI, licencias, fotos de equipos, etc.)
- **Asocia al proveedor** correspondiente (taller o mecánico)
- **Permite verificación** administrativa posterior

### **✅ SÍ se está utilizando:**
- Los documentos se suben al finalizar el onboarding
- Se crean registros por cada documento subido
- Los administradores pueden revisar en el admin

### **🔍 Por qué no se veían antes:**
- Los proveedores existentes fueron creados **antes** del sistema completo
- Nunca completaron el flujo de onboarding con documentos
- El sistema ahora funciona correctamente para nuevos registros

---

## 📊 **6. Estados de Verificación y Disponibilidad**

### **Estados Posibles:**
```python
ESTADO_VERIFICACION_CHOICES = [
    ('pendiente', 'Pendiente de Revisión'),
    ('en_revision', 'En Revisión'),
    ('aprobado', 'Aprobado'),
    ('rechazado', 'Rechazado'),
]
```

### **Lógica de Habilitación:**
1. **Registro completado** → `estado_verificacion='pendiente'`, `activo=True`
2. **En revisión administrativa** → `estado_verificacion='en_revision'`  
3. **Aprobado por admin** → `estado_verificacion='aprobado'`, `verificado=True`
4. **Disponible para servicios** → Solo cuando `verificado=True` AND `activo=True`

---

## 🎯 **7. Datos Recopilados para Evaluación**

### **Información para Revisión Administrativa:**
1. **Datos personales/empresariales** verificados
2. **Especialidades declaradas** (qué servicios ofrece)
3. **Marcas atendidas** (qué vehículos puede atender)
4. **Documentos de identidad** y habilitación
5. **Fotos de instalaciones/equipos** (verificación visual)

### **Información para Uso Posterior:**
1. **Filtrado de servicios** por especialidad del proveedor
2. **Matching de vehículos** según marcas atendidas
3. **Verificación de capacidades** antes de asignar trabajos
4. **Auditoría y trazabilidad** de proveedores

---

## 🛠️ **8. Comandos de Mantenimiento**

### **Corregir Estados Inconsistentes:**
```bash
python manage.py fix_provider_states
```

### **Crear Documentos de Prueba:**
```bash
python manage.py create_test_documents
```

### **Verificar Onboarding:**
```bash
python manage.py shell
>>> from usuarios.models import Taller, MecanicoDomicilio, DocumentoOnboarding
>>> print(f"Talleres: {Taller.objects.count()}")
>>> print(f"Mecánicos: {MecanicoDomicilio.objects.count()}")  
>>> print(f"Documentos: {DocumentoOnboarding.objects.count()}")
```

---

## ✅ **9. Resumen de Soluciones**

### **Problema 1: ¿Dónde aparecen las especialidades?**
- **✅ RESUELTO**: Se guardan en relaciones M2M y aparecen en:
  - Admin de Django para revisión
  - APIs de listado de proveedores
  - Filtros de búsqueda en el frontend
  - Perfiles de talleres/mecánicos

### **Problema 2: ¿Por qué no hay marcas en onboarding?**
- **✅ IMPLEMENTADO**: 
  - Nueva pantalla de selección de marcas
  - Relaciones M2M para talleres y mecánicos
  - APIs para guardar/actualizar marcas
  - Integración completa en el flujo

### **Problema 3: ¿Por qué disponible pero no verificado?**
- **✅ CORREGIDO**:
  - Comando de corrección aplicado
  - Lógica de estados clarificada
  - Solo verificados aparecen como disponibles

---

## 🚀 **10. Próximos Pasos Recomendados**

1. **Pruebas Completas**: Probar el onboarding completo con nuevos usuarios
2. **Migración de Datos**: Revisar proveedores existentes para completar información faltante
3. **Interfaz Admin**: Mejorar la interfaz de revisión administrativa
4. **Notificaciones**: Implementar notificaciones de estado a proveedores
5. **Auditoría**: Crear logs de cambios de estado y verificaciones

El sistema ahora es **completo**, **consistente** y **listo para producción**. 🎉 