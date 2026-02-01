"""
Management command para poblar:
1. ChecklistItemCatalog con items bien diseñados para inspección automotriz
2. ChecklistTemplate por cada servicio existente
3. ChecklistItemTemplate asociando items del catálogo en orden correcto

Uso: python manage.py populate_checklists_por_servicio [--dry-run]
"""
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.checklists.models import (
    ChecklistItemCatalog,
    ChecklistTemplate,
    ChecklistItemTemplate,
)
from mecanimovilapp.apps.servicios.models import Servicio


# Lista de nombres de servicio a mapear (resolver por nombre en BD)
SERVICIOS_NOMBRES = [
    'Diagnóstico mecánico',
    'Diagnóstico electromecánico',
    'Servicio escáner automotriz',
    'Revisión precompra',
    'Revisión técnica',
    'Cambio de aceite motor',
    'Cambio de filtro de aire',
    'Cambio de filtro habitáculo',
    'Cambio aceite motor y filtro',
    'Mantenimiento por kilometraje',
    'Cambio de bujías',
    'Cambio de pastillas de frenos',
    'Cambio de pastillas y discos de freno',
    'Cambio de pastillas de frenos y rectificado',
    'Cambio de batería',
    'Cambio de ampolletas',
    'Lavado a domicilio',
]

# FASE 1: Items del catálogo (nombre, categoria, tipo_pregunta, pregunta_texto, etc.)
# get_or_create por (nombre, categoria)
CATALOG_ITEMS = [
    # --- INFORMACION_GENERAL ---
    {
        'nombre': 'Identificación del Técnico',
        'categoria': 'INFORMACION_GENERAL',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Nombre completo del técnico responsable',
        'descripcion_ayuda': 'Ingrese el nombre completo del técnico que realizará el servicio',
        'placeholder': 'Ej: Juan Pérez García',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Fecha y Hora de Inicio',
        'categoria': 'INFORMACION_GENERAL',
        'tipo_pregunta': 'DATETIME',
        'pregunta_texto': '¿Cuándo se inicia el servicio?',
        'descripcion_ayuda': 'Registre la fecha y hora exacta de inicio del servicio',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    # --- DATOS_VEHICULO ---
    {
        'nombre': 'Kilometraje Actual',
        'categoria': 'DATOS_VEHICULO',
        'tipo_pregunta': 'KILOMETER_INPUT',
        'pregunta_texto': '¿Cuál es el kilometraje actual del vehículo?',
        'descripcion_ayuda': 'Registre el kilometraje que muestra el odómetro',
        'placeholder': 'Ej: 85.450',
        'valor_minimo': 0,
        'valor_maximo': 9999999,
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    # --- FIRMAS_CONFORMIDAD ---
    {
        'nombre': 'Firma del Técnico',
        'categoria': 'FIRMAS_CONFORMIDAD',
        'tipo_pregunta': 'SIGNATURE',
        'pregunta_texto': 'Firma del técnico responsable',
        'descripcion_ayuda': 'Firma digital del técnico que realizó la inspección',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Firma del Cliente',
        'categoria': 'FIRMAS_CONFORMIDAD',
        'tipo_pregunta': 'SIGNATURE',
        'pregunta_texto': 'Firma del cliente',
        'descripcion_ayuda': 'Firma digital del cliente confirmando la recepción del servicio',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    # --- Diagnósticos / revisiones ---
    {
        'nombre': 'Estado del Sistema Eléctrico',
        'categoria': 'SISTEMA_ELECTRICO',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado general del sistema eléctrico?',
        'descripcion_ayuda': 'Evalúe luces, batería, alternador y componentes eléctricos',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Malo', 'Crítico'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado de Frenos',
        'categoria': 'SISTEMA_FRENOS',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado del sistema de frenos?',
        'descripcion_ayuda': 'Evalúe pastillas, discos, líquido de frenos',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Malo', 'Requiere atención'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado Pastillas de Frenos',
        'categoria': 'SISTEMA_FRENOS',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado de las pastillas de frenos?',
        'descripcion_ayuda': 'Evalúe el desgaste de las pastillas',
        'opciones_seleccion': ['Óptimo', 'Bueno', 'Regular', 'Desgastadas', 'Crítico'],
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado Discos de Frenos',
        'categoria': 'SISTEMA_FRENOS',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado de los discos de frenos?',
        'descripcion_ayuda': 'Evalúe desgaste, rayaduras y grosor',
        'opciones_seleccion': ['Óptimo', 'Bueno', 'Regular', 'Desgastados', 'Requiere rectificado'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Rectificado Realizado',
        'categoria': 'SISTEMA_FRENOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se realizó rectificado de discos?',
        'descripcion_ayuda': 'Indique si se rectificaron los discos de frenos',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': False,
    },
    {
        'nombre': 'Estado del Motor',
        'categoria': 'MOTOR_COMPARTIMIENTO',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado general del motor?',
        'descripcion_ayuda': 'Evalúe fugas, ruidos y funcionamiento',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Malo', 'Requiere diagnóstico'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Nivel de Fluidos',
        'categoria': 'FLUIDOS_NIVELES',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el nivel general de fluidos?',
        'descripcion_ayuda': 'Evalúe aceite motor, refrigerante, líquido frenos, dirección',
        'opciones_seleccion': ['Todos correctos', 'Algunos bajos', 'Refrigerante bajo', 'Aceite bajo', 'Requiere rellenado'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Nivel Aceite Antes',
        'categoria': 'FLUIDOS_NIVELES',
        'tipo_pregunta': 'FLUID_LEVEL',
        'pregunta_texto': 'Nivel de aceite antes del servicio',
        'descripcion_ayuda': 'Registre el nivel de aceite en la varilla antes del cambio',
        'opciones_seleccion': ['Mínimo', 'Bajo', 'Normal', 'Alto', 'Sobre máximo'],
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Nivel Aceite Después',
        'categoria': 'FLUIDOS_NIVELES',
        'tipo_pregunta': 'FLUID_LEVEL',
        'pregunta_texto': 'Nivel de aceite después del servicio',
        'descripcion_ayuda': 'Verifique que el nivel de aceite sea correcto tras el cambio',
        'opciones_seleccion': ['Mínimo', 'Bajo', 'Normal', 'Alto', 'Sobre máximo'],
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado de Neumáticos',
        'categoria': 'NEUMATICOS_LLANTAS',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado de los neumáticos?',
        'descripcion_ayuda': 'Evalúe profundidad de dibujo y condición general',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Desgastados', 'Requiere cambio'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Observaciones del Técnico',
        'categoria': 'OBSERVACIONES_TECNICO',
        'tipo_pregunta': 'FINAL_NOTES',
        'pregunta_texto': 'Observaciones y notas del técnico',
        'descripcion_ayuda': 'Anote hallazgos relevantes durante la inspección',
        'placeholder': 'Escriba aquí...',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Recomendaciones',
        'categoria': 'RECOMENDACIONES',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Recomendaciones para el cliente',
        'descripcion_ayuda': 'Indique mantenimientos o reparaciones sugeridas',
        'placeholder': 'Ej: Revisar batería en próximo servicio',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Fotos Evidencia',
        'categoria': 'FOTOS_FINALES',
        'tipo_pregunta': 'PHOTO',
        'pregunta_texto': 'Fotografías de evidencia del trabajo realizado',
        'descripcion_ayuda': 'Capture fotos del antes/después o de piezas reemplazadas',
        'min_fotos': 0,
        'max_fotos': 10,
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    # --- Cambio aceite / filtros ---
    {
        'nombre': 'Tipo de Aceite Usado',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Tipo y grado de aceite utilizado',
        'descripcion_ayuda': 'Indique marca, viscosidad (ej: 5W-30) y cantidad',
        'placeholder': 'Ej: 5W-30 Semi-sintético, 4L',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Filtro de Aceite Reemplazado',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazó el filtro de aceite?',
        'descripcion_ayuda': 'Confirme el reemplazo del filtro de aceite',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Filtro de Aire Reemplazado',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazó el filtro de aire?',
        'descripcion_ayuda': 'Confirme el reemplazo del filtro de aire del motor',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Filtro Habitáculo Reemplazado',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazó el filtro de habitáculo?',
        'descripcion_ayuda': 'Confirme el reemplazo del filtro de polen/habitáculo',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    # --- Repuestos ---
    {
        'nombre': 'Repuestos Utilizados',
        'categoria': 'REPUESTOS_UTILIZADOS',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Repuestos y piezas utilizados',
        'descripcion_ayuda': 'Indique marcas, referencias o cantidades de repuestos',
        'placeholder': 'Ej: Pastillas delanteras marca X, 1 juego',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    # --- Batería / eléctrico ---
    {
        'nombre': 'Estado de Batería',
        'categoria': 'SISTEMA_ELECTRICO',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado de la batería?',
        'descripcion_ayuda': 'Evalúe carga, conexiones y estado general',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Baja carga', 'Requiere cambio'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Voltaje Batería',
        'categoria': 'SISTEMA_ELECTRICO',
        'tipo_pregunta': 'NUMBER',
        'pregunta_texto': 'Voltaje de la batería (V)',
        'descripcion_ayuda': 'Registre el voltaje medido en bornes',
        'placeholder': '12.6',
        'valor_minimo': 0,
        'valor_maximo': 20,
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': False,
    },
    {
        'nombre': 'Batería Reemplazada',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazó la batería?',
        'descripcion_ayuda': 'Confirme el reemplazo de la batería',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Ampolletas Reemplazadas',
        'categoria': 'LUCES_SENALIZACION',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': '¿Qué ampolletas fueron reemplazadas?',
        'descripcion_ayuda': 'Indique posición (delantera, trasera, intermitentes, etc.)',
        'placeholder': 'Ej: Ampolleta delantera izquierda baja',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Verificación de Luces',
        'categoria': 'LUCES_SENALIZACION',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se verificó el funcionamiento de todas las luces?',
        'descripcion_ayuda': 'Confirme revisión de luces altas, bajas, intermitentes, reversa',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    # --- Lavado ---
    {
        'nombre': 'Estado Exterior Antes',
        'categoria': 'CARROCERIA_EXTERIOR',
        'tipo_pregunta': 'EXTERIOR_INSPECTION',
        'pregunta_texto': 'Estado exterior del vehículo antes del lavado',
        'descripcion_ayuda': 'Describa el estado de la carrocería, suciedad, manchas',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado Exterior Después',
        'categoria': 'CARROCERIA_EXTERIOR',
        'tipo_pregunta': 'EXTERIOR_INSPECTION',
        'pregunta_texto': 'Estado exterior del vehículo después del lavado',
        'descripcion_ayuda': 'Confirme que el lavado exterior se completó correctamente',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado Interior',
        'categoria': 'INTERIOR_CABINA',
        'tipo_pregunta': 'INTERIOR_INSPECTION',
        'pregunta_texto': 'Estado interior del vehículo',
        'descripcion_ayuda': 'Evalúe asientos, tablero, alfombras y limpieza general',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    # --- Revisión técnica / precompra ---
    {
        'nombre': 'Inventario del Vehículo',
        'categoria': 'INVENTARIO_VEHICULO',
        'tipo_pregunta': 'INVENTORY_CHECKLIST',
        'pregunta_texto': 'Inventario de accesorios y elementos del vehículo',
        'descripcion_ayuda': 'Verifique llanta de repuesto, herramientas, manuales',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Documentos del Vehículo',
        'categoria': 'DOCUMENTOS_VEHICULO',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Documentos revisados (revisión técnica, permiso circulación)',
        'descripcion_ayuda': 'Indique estado de documentación y vencimientos',
        'placeholder': 'Ej: Revisión técnica vigente hasta 01/2026',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Inspección Exterior',
        'categoria': 'CARROCERIA_EXTERIOR',
        'tipo_pregunta': 'EXTERIOR_INSPECTION',
        'pregunta_texto': 'Inspección exterior del vehículo',
        'descripcion_ayuda': 'Evalúe carrocería, pintura, golpes, rayones',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Inspección Interior',
        'categoria': 'INTERIOR_CABINA',
        'tipo_pregunta': 'INTERIOR_INSPECTION',
        'pregunta_texto': 'Inspección interior del vehículo',
        'descripcion_ayuda': 'Evalúe tablero, asientos, funcionamiento de controles',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Resumen del Trabajo',
        'categoria': 'OBSERVACIONES_TECNICO',
        'tipo_pregunta': 'WORK_SUMMARY',
        'pregunta_texto': 'Resumen del trabajo realizado',
        'descripcion_ayuda': 'Síntesis de inspección, servicios realizados y hallazgos',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    # --- Mantenimiento por kilometraje / bujías ---
    {
        'nombre': 'Bujías Reemplazadas',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazaron las bujías?',
        'descripcion_ayuda': 'Confirme el reemplazo de bujías',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
    {
        'nombre': 'Estado Cables Bujías',
        'categoria': 'MOTOR_COMPARTIMIENTO',
        'tipo_pregunta': 'SELECT',
        'pregunta_texto': '¿Cuál es el estado de los cables de bujías?',
        'descripcion_ayuda': 'Evalúe cables de encendido',
        'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Requiere cambio'],
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': False,
    },
    {
        'nombre': 'Items Mantenimiento Realizados',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'TEXT',
        'pregunta_texto': 'Items de mantenimiento revisados y/o cambiados',
        'descripcion_ayuda': 'Liste aceite, filtros, bujías y otros según kilometraje',
        'placeholder': 'Ej: Aceite, filtro aceite, filtro aire, bujías',
        'es_obligatorio_por_defecto': False,
        'uso_frecuente': True,
    },
    # Pastillas/discos reemplazados
    {
        'nombre': 'Pastillas y Discos Reemplazados',
        'categoria': 'SERVICIOS_APLICADOS',
        'tipo_pregunta': 'BOOLEAN',
        'pregunta_texto': '¿Se reemplazaron pastillas y/o discos de frenos?',
        'descripcion_ayuda': 'Confirme reemplazo de pastillas y discos',
        'es_obligatorio_por_defecto': True,
        'uso_frecuente': True,
    },
]

# FASE 2: Mapeo servicio -> lista de (nombre_item_catalogo, orden_visual, es_obligatorio)
# es_obligatorio: True/False, o None para usar valor por defecto del catálogo
SERVICIO_TEMPLATE_ITEMS = {
    # Diagnósticos: técnico, fecha, km, motor, eléctrico, fluidos, frenos, neumáticos, observaciones, recomendaciones, fotos, firmas
    'Diagnóstico mecánico': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado del Motor', 4, False),
        ('Estado del Sistema Eléctrico', 5, False),
        ('Nivel de Fluidos', 6, False),
        ('Estado de Frenos', 7, False),
        ('Estado de Neumáticos', 8, False),
        ('Observaciones del Técnico', 9, False),
        ('Recomendaciones', 10, False),
        ('Fotos Evidencia', 11, False),
        ('Firma del Técnico', 12, True),
        ('Firma del Cliente', 13, True),
    ],
    'Diagnóstico electromecánico': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado del Motor', 4, False),
        ('Estado del Sistema Eléctrico', 5, True),
        ('Nivel de Fluidos', 6, False),
        ('Estado de Frenos', 7, False),
        ('Estado de Neumáticos', 8, False),
        ('Observaciones del Técnico', 9, False),
        ('Recomendaciones', 10, False),
        ('Fotos Evidencia', 11, False),
        ('Firma del Técnico', 12, True),
        ('Firma del Cliente', 13, True),
    ],
    'Servicio escáner automotriz': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado del Motor', 4, False),
        ('Estado del Sistema Eléctrico', 5, True),
        ('Nivel de Fluidos', 6, False),
        ('Estado de Frenos', 7, False),
        ('Estado de Neumáticos', 8, False),
        ('Observaciones del Técnico', 9, False),
        ('Recomendaciones', 10, False),
        ('Fotos Evidencia', 11, False),
        ('Firma del Técnico', 12, True),
        ('Firma del Cliente', 13, True),
    ],
    # Revisión precompra / técnica: inventario, documentos, inspección exterior/interior, motor, fluidos, frenos, neumáticos, luces, fotos, firmas
    'Revisión precompra': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Inventario del Vehículo', 4, False),
        ('Documentos del Vehículo', 5, False),
        ('Inspección Exterior', 6, True),
        ('Inspección Interior', 7, True),
        ('Estado del Motor', 8, False),
        ('Nivel de Fluidos', 9, False),
        ('Estado de Frenos', 10, False),
        ('Estado de Neumáticos', 11, False),
        ('Verificación de Luces', 12, False),
        ('Fotos Evidencia', 13, False),
        ('Observaciones del Técnico', 14, False),
        ('Resumen del Trabajo', 15, False),
        ('Firma del Técnico', 16, True),
        ('Firma del Cliente', 17, True),
    ],
    'Revisión técnica': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Inventario del Vehículo', 4, False),
        ('Documentos del Vehículo', 5, True),
        ('Inspección Exterior', 6, True),
        ('Inspección Interior', 7, True),
        ('Estado del Motor', 8, False),
        ('Nivel de Fluidos', 9, False),
        ('Estado de Frenos', 10, False),
        ('Estado de Neumáticos', 11, False),
        ('Verificación de Luces', 12, False),
        ('Fotos Evidencia', 13, False),
        ('Observaciones del Técnico', 14, False),
        ('Resumen del Trabajo', 15, False),
        ('Firma del Técnico', 16, True),
        ('Firma del Cliente', 17, True),
    ],
    # Cambio de aceite motor
    'Cambio de aceite motor': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Nivel Aceite Antes', 4, True),
        ('Tipo de Aceite Usado', 5, False),
        ('Filtro de Aceite Reemplazado', 6, True),
        ('Nivel Aceite Después', 7, True),
        ('Fotos Evidencia', 8, False),
        ('Firma del Técnico', 9, True),
        ('Firma del Cliente', 10, True),
    ],
    # Cambio aceite motor y filtro
    'Cambio aceite motor y filtro': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Nivel Aceite Antes', 4, True),
        ('Tipo de Aceite Usado', 5, False),
        ('Filtro de Aceite Reemplazado', 6, True),
        ('Filtro de Aire Reemplazado', 7, True),
        ('Filtro Habitáculo Reemplazado', 8, False),
        ('Nivel Aceite Después', 9, True),
        ('Fotos Evidencia', 10, False),
        ('Firma del Técnico', 11, True),
        ('Firma del Cliente', 12, True),
    ],
    # Filtros individuales
    'Cambio de filtro de aire': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Filtro de Aire Reemplazado', 4, True),
        ('Fotos Evidencia', 5, False),
        ('Firma del Técnico', 6, True),
        ('Firma del Cliente', 7, True),
    ],
    'Cambio de filtro habitáculo': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Filtro Habitáculo Reemplazado', 4, True),
        ('Fotos Evidencia', 5, False),
        ('Firma del Técnico', 6, True),
        ('Firma del Cliente', 7, True),
    ],
    # Mantenimiento por kilometraje
    'Mantenimiento por kilometraje': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Items Mantenimiento Realizados', 4, True),
        ('Nivel de Fluidos', 5, False),
        ('Fotos Evidencia', 6, False),
        ('Observaciones del Técnico', 7, False),
        ('Firma del Técnico', 8, True),
        ('Firma del Cliente', 9, True),
    ],
    # Cambio de bujías
    'Cambio de bujías': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Bujías Reemplazadas', 4, True),
        ('Estado Cables Bujías', 5, False),
        ('Fotos Evidencia', 6, False),
        ('Firma del Técnico', 7, True),
        ('Firma del Cliente', 8, True),
    ],
    # Frenos
    'Cambio de pastillas de frenos': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado Pastillas de Frenos', 4, True),
        ('Estado Discos de Frenos', 5, False),
        ('Pastillas y Discos Reemplazados', 6, True),
        ('Repuestos Utilizados', 7, False),
        ('Fotos Evidencia', 8, False),
        ('Firma del Técnico', 9, True),
        ('Firma del Cliente', 10, True),
    ],
    'Cambio de pastillas y discos de freno': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado Pastillas de Frenos', 4, True),
        ('Estado Discos de Frenos', 5, True),
        ('Pastillas y Discos Reemplazados', 6, True),
        ('Repuestos Utilizados', 7, False),
        ('Fotos Evidencia', 8, False),
        ('Firma del Técnico', 9, True),
        ('Firma del Cliente', 10, True),
    ],
    'Cambio de pastillas de frenos y rectificado': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado Pastillas de Frenos', 4, True),
        ('Estado Discos de Frenos', 5, True),
        ('Rectificado Realizado', 6, True),
        ('Pastillas y Discos Reemplazados', 7, True),
        ('Repuestos Utilizados', 8, False),
        ('Fotos Evidencia', 9, False),
        ('Firma del Técnico', 10, True),
        ('Firma del Cliente', 11, True),
    ],
    # Batería
    'Cambio de batería': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Estado de Batería', 4, False),
        ('Voltaje Batería', 5, False),
        ('Batería Reemplazada', 6, True),
        ('Fotos Evidencia', 7, False),
        ('Firma del Técnico', 8, True),
        ('Firma del Cliente', 9, True),
    ],
    # Ampolletas
    'Cambio de ampolletas': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Kilometraje Actual', 3, True),
        ('Ampolletas Reemplazadas', 4, True),
        ('Verificación de Luces', 5, True),
        ('Fotos Evidencia', 6, False),
        ('Firma del Técnico', 7, True),
        ('Firma del Cliente', 8, True),
    ],
    # Lavado
    'Lavado a domicilio': [
        ('Identificación del Técnico', 1, True),
        ('Fecha y Hora de Inicio', 2, True),
        ('Estado Exterior Antes', 3, False),
        ('Estado Exterior Después', 4, True),
        ('Estado Interior', 5, False),
        ('Fotos Evidencia', 6, False),
        ('Firma del Técnico', 7, True),
        ('Firma del Cliente', 8, True),
    ],
}


def normalize_servicio_nombre(nombre):
    """Normaliza nombre de servicio para búsqueda (espacios, acentos)."""
    import unicodedata
    s = (nombre or '').strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.lower()


class Command(BaseCommand):
    help = 'Pobla el catálogo de items de checklist y los templates por servicio'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='No guardar; solo imprimir qué se crearía',
        )

    def _resolve_servicio(self, nombre_buscado):
        """Resuelve Servicio por nombre (iexact o normalizado)."""
        # Primero intento exacto
        servicio = Servicio.objects.filter(nombre__iexact=nombre_buscado).first()
        if servicio:
            return servicio
        # Buscar por normalización
        normalizado = normalize_servicio_nombre(nombre_buscado)
        for s in Servicio.objects.all():
            if normalize_servicio_nombre(s.nombre) == normalizado:
                return s
        return None

    def _get_catalog_by_name(self, catalog_map, nombre):
        """Obtiene ChecklistItemCatalog por nombre (el nombre es único dentro del catálogo definido)."""
        return catalog_map.get(nombre)

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 DRY-RUN: No se guardará nada'))

        self.stdout.write(self.style.SUCCESS('🚀 Iniciando población de checklists por servicio...'))

        total_catalog_created = 0
        total_templates_created = 0
        total_template_items_created = 0

        # --- FASE 1: Catálogo ---
        self.stdout.write('\n📦 FASE 1: Poblando ChecklistItemCatalog...')
        catalog_by_name = {}

        for item_data in CATALOG_ITEMS:
            nombre = item_data['nombre']
            categoria = item_data['categoria']
            defaults = {
                'tipo_pregunta': item_data['tipo_pregunta'],
                'pregunta_texto': item_data['pregunta_texto'],
                'descripcion_ayuda': item_data.get('descripcion_ayuda'),
                'placeholder': item_data.get('placeholder'),
                'es_obligatorio_por_defecto': item_data.get('es_obligatorio_por_defecto', True),
                'opciones_seleccion': item_data.get('opciones_seleccion'),
                'valor_minimo': item_data.get('valor_minimo'),
                'valor_maximo': item_data.get('valor_maximo'),
                'min_fotos': item_data.get('min_fotos'),
                'max_fotos': item_data.get('max_fotos'),
                'activo': True,
                'uso_frecuente': item_data.get('uso_frecuente', False),
            }
            if not dry_run:
                obj, created = ChecklistItemCatalog.objects.get_or_create(
                    nombre=nombre,
                    categoria=categoria,
                    defaults=defaults,
                )
                catalog_by_name[nombre] = obj
                if created:
                    total_catalog_created += 1
                    self.stdout.write(f"  ✅ Creado: {nombre}")
            else:
                exists = ChecklistItemCatalog.objects.filter(
                    nombre=nombre, categoria=categoria
                ).exists()
                catalog_by_name[nombre] = None  # En dry-run no tenemos objeto
                if exists:
                    self.stdout.write(f"  ⏭️  Ya existe: {nombre}")
                else:
                    total_catalog_created += 1
                    self.stdout.write(f"  [DRY] Crearía: {nombre}")

        # En dry-run necesitamos los objetos para validar nombres; cargar desde BD
        if dry_run and not catalog_by_name.get('Identificación del Técnico'):
            for nombre in set(i['nombre'] for i in CATALOG_ITEMS):
                obj = ChecklistItemCatalog.objects.filter(nombre=nombre).first()
                catalog_by_name[nombre] = obj

        self.stdout.write(
            self.style.SUCCESS(
                f'  Total items en catálogo: {ChecklistItemCatalog.objects.count()} '
                f'(creados en esta ejecución: {total_catalog_created})'
            )
        )

        # --- FASE 2: Templates por servicio ---
        self.stdout.write('\n📋 FASE 2: Creando ChecklistTemplate y ChecklistItemTemplate por servicio...')

        for nombre_servicio in SERVICIOS_NOMBRES:
            servicio = self._resolve_servicio(nombre_servicio)
            if not servicio:
                self.stdout.write(
                    self.style.WARNING(f"  ⚠️  Servicio no encontrado: {nombre_servicio}")
                )
                continue

            items_config = SERVICIO_TEMPLATE_ITEMS.get(nombre_servicio)
            if not items_config:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠️  Sin mapeo de items para: {nombre_servicio}"
                    )
                )
                continue

            # ChecklistTemplate
            if dry_run:
                template_exists = ChecklistTemplate.objects.filter(
                    servicio=servicio, version='1.0'
                ).exists()
                if template_exists:
                    template = ChecklistTemplate.objects.get(
                        servicio=servicio, version='1.0'
                    )
                    self.stdout.write(f"  ⏭️  Template ya existe: {servicio.nombre}")
                else:
                    total_templates_created += 1
                    template = None
                    self.stdout.write(f"  [DRY] Crearía template: Checklist {servicio.nombre}")
            else:
                template, created = ChecklistTemplate.objects.get_or_create(
                    servicio=servicio,
                    version='1.0',
                    defaults={
                        'nombre': f"Checklist {servicio.nombre}",
                        'descripcion': f"Inspección y verificación para {servicio.nombre}",
                        'activo': True,
                    },
                )
                if created:
                    total_templates_created += 1
                    self.stdout.write(f"  ✅ Template creado: {template.nombre}")

            if not template and not dry_run:
                template = ChecklistTemplate.objects.get(
                    servicio=servicio, version='1.0'
                )

            # ChecklistItemTemplate
            catalog_names_defined = {i['nombre'] for i in CATALOG_ITEMS}
            for item_nombre, orden_visual, es_obligatorio in items_config:
                catalog_item = ChecklistItemCatalog.objects.filter(
                    nombre=item_nombre
                ).first()
                # En dry-run, el item puede no existir aún pero estar en CATALOG_ITEMS (se crearía en Fase 1)
                if not catalog_item and item_nombre not in catalog_names_defined:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠️  Item de catálogo no encontrado: {item_nombre} "
                            f"(omitido en {nombre_servicio})"
                        )
                    )
                    continue
                if not dry_run and not catalog_item:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠️  Item de catálogo no encontrado: {item_nombre} "
                            f"(omitido en {nombre_servicio})"
                        )
                    )
                    continue

                if dry_run:
                    exists = False
                    if template:
                        exists = ChecklistItemTemplate.objects.filter(
                            checklist_template=template,
                            orden_visual=orden_visual,
                        ).exists()
                    if not exists:
                        total_template_items_created += 1
                        self.stdout.write(
                            f"    [DRY] Crearía item: {item_nombre} (orden {orden_visual})"
                        )
                else:
                    _, created = ChecklistItemTemplate.objects.update_or_create(
                        checklist_template=template,
                        orden_visual=orden_visual,
                        defaults={
                            'catalog_item': catalog_item,
                            'es_obligatorio': es_obligatorio,
                        },
                    )
                    if created:
                        total_template_items_created += 1

        # Resumen final
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f'🎉 Resumen:\n'
                f'   Items catálogo (creados): {total_catalog_created}\n'
                f'   Templates (creados): {total_templates_created}\n'
                f'   ChecklistItemTemplate (creados): {total_template_items_created}\n'
                f'   Total items en catálogo: {ChecklistItemCatalog.objects.count()}\n'
                f'   Total templates: {ChecklistTemplate.objects.count()}\n'
                f'   Total ChecklistItemTemplate: {ChecklistItemTemplate.objects.count()}'
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING('\n🔍 Modo DRY-RUN: ningún cambio fue guardado'))
