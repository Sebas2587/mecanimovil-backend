# 🧹 Limpiar Logs de la Base de Datos en Render

## 📋 Opciones para Limpiar Logs

### Opción 1: Usando Django Shell (Recomendado) ⭐

**Conéctate por SSH a Render y ejecuta:**

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

# Navegar al directorio del proyecto
cd /opt/render/project/src

# Ejecutar Django shell con comando de limpieza
python3 manage.py shell << 'EOF'
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente

# Ver cuántos logs hay
total = AuditAccesoCliente.objects.count()
print(f"📊 Total de logs de auditoría: {total}")

# Limpiar logs más antiguos de 90 días
dias_antiguos = 90
fecha_limite = timezone.now() - timedelta(days=dias_antiguos)
logs_antiguos = AuditAccesoCliente.objects.filter(fecha_acceso__lt=fecha_limite)

cantidad = logs_antiguos.count()
print(f"🗑️  Logs a eliminar (más de {dias_antiguos} días): {cantidad}")

# Eliminar (descomenta la siguiente línea para ejecutar realmente)
logs_antiguos.delete()

print("✅ Comando completado (en modo dry-run)")
EOF
```

**Para eliminar realmente, descomenta la línea `logs_antiguos.delete()`**

---

### Opción 2: Comando SQL Directo (Rápido)

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

# Navegar al directorio del proyecto
cd /opt/render/project/src

# Conectar a la base de datos PostgreSQL (usando variables de entorno)
python3 manage.py dbshell << 'EOF'
-- Ver cuántos logs hay
SELECT COUNT(*) FROM ordenes_auditaccesocliente;

-- Ver logs más antiguos de 90 días
SELECT COUNT(*) FROM ordenes_auditaccesocliente 
WHERE fecha_acceso < NOW() - INTERVAL '90 days';

-- Eliminar logs más antiguos de 90 días (DESCOMENTA PARA EJECUTAR)
-- DELETE FROM ordenes_auditaccesocliente 
-- WHERE fecha_acceso < NOW() - INTERVAL '90 days';

-- Salir
\q
EOF
```

---

### Opción 3: Limpiar TODOS los Logs (⚠️ Cuidado)

**Solo si estás seguro de eliminar TODOS los logs:**

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

cd /opt/render/project/src

python3 manage.py shell << 'EOF'
from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente

total = AuditAccesoCliente.objects.count()
print(f"📊 Total de logs: {total}")

# DESCOMENTA LA SIGUIENTE LÍNEA PARA ELIMINAR TODOS
AuditAccesoCliente.objects.all().delete()

print("✅ Completado (en modo dry-run)")
EOF
```

---

### Opción 4: Crear un Management Command Personalizado

Si quieres automatizar la limpieza, crea un comando de management:

**Archivo:** `mecanimovilapp/apps/ordenes/management/commands/limpiar_logs_auditoria.py`

```python
"""
Comando para limpiar logs antiguos de auditoría
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente


class Command(BaseCommand):
    help = 'Limpiar logs de auditoría más antiguos de X días'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias',
            type=int,
            default=90,
            help='Eliminar logs más antiguos de X días (default: 90)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar cuántos logs se eliminarían sin eliminar realmente'
        )

    def handle(self, *args, **options):
        dias = options['dias']
        dry_run = options['dry_run']
        
        fecha_limite = timezone.now() - timedelta(days=dias)
        logs_antiguos = AuditAccesoCliente.objects.filter(
            fecha_acceso__lt=fecha_limite
        )
        
        cantidad = logs_antiguos.count()
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN: Se eliminarían {cantidad} logs de auditoría '
                    f'(más antiguos de {dias} días)'
                )
            )
        else:
            eliminados, _ = logs_antiguos.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Eliminados {eliminados} logs de auditoría '
                    f'(más antiguos de {dias} días)'
                )
            )
```

**Uso del comando:**

```bash
# Ver cuántos se eliminarían (sin eliminar)
python3 manage.py limpiar_logs_auditoria --dias 90 --dry-run

# Eliminar logs más antiguos de 90 días
python3 manage.py limpiar_logs_auditoria --dias 90

# Eliminar logs más antiguos de 30 días
python3 manage.py limpiar_logs_auditoria --dias 30
```

---

## 🎯 Comandos Rápidos para Render

### Ver estadísticas de logs:

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src
python3 manage.py shell -c "from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente; print(f'Total logs: {AuditAccesoCliente.objects.count()}')"
```

### Limpiar logs de más de 90 días:

```bash
ssh srv-abc123@ssh.oregon.render.com
cd /opt/render/project/src
python3 manage.py shell -c "from django.utils import timezone; from datetime import timedelta; from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente; fecha = timezone.now() - timedelta(days=90); eliminados, _ = AuditAccesoCliente.objects.filter(fecha_acceso__lt=fecha).delete(); print(f'Eliminados: {eliminados}')"
```

---

## ⚠️ Consideraciones Importantes

1. **Backup**: Antes de eliminar logs en producción, considera hacer un backup:
   ```bash
   python3 manage.py dumpdata ordenes.AuditAccesoCliente > logs_auditoria_backup_$(date +%Y%m%d).json
   ```

2. **Retención**: Define una política de retención (ej: 90 días) y documenta por qué.

3. **Compliance**: Si hay requisitos legales de retención de auditorías, NO elimines logs antiguos.

4. **Performance**: Los logs antiguos pueden afectar el rendimiento si son muchos. Considera crear índices.

---

## 📊 Verificar Otras Tablas de Logs

Si hay otras tablas con logs (como `ChecklistAuditLog`):

```bash
python3 manage.py dbshell << 'EOF'
-- Listar todas las tablas que contienen "log" o "audit"
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND (table_name LIKE '%log%' OR table_name LIKE '%audit%');
EOF
```
