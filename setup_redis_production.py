#!/usr/bin/env python
"""
Script para configurar Redis y Django Channels para producción
"""

import os
import sys
import subprocess
import django
import redis

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings_production')
django.setup()

def check_redis_connection():
    """Verificar conexión a Redis"""
    print("🔍 Verificando conexión a Redis...")
    
    try:
        # Obtener configuración de Redis desde settings
        from django.conf import settings
        
        redis_host = getattr(settings, 'REDIS_HOST', 'localhost')
        redis_port = getattr(settings, 'REDIS_PORT', 6379)
        redis_db = getattr(settings, 'REDIS_DB', 0)
        redis_password = getattr(settings, 'REDIS_PASSWORD', None)
        
        print(f"📡 Configuración Redis: {redis_host}:{redis_port}/{redis_db}")
        
        # Crear conexión a Redis
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            decode_responses=True
        )
        
        # Probar conexión
        r.ping()
        print("✅ Conexión a Redis exitosa")
        
        # Probar operaciones básicas
        r.set('test_key', 'test_value')
        value = r.get('test_key')
        r.delete('test_key')
        
        if value == 'test_value':
            print("✅ Operaciones básicas de Redis funcionando")
            return True
        else:
            print("❌ Error en operaciones básicas de Redis")
            return False
            
    except Exception as e:
        print(f"❌ Error conectando a Redis: {e}")
        return False

def test_channels_configuration():
    """Probar configuración de Django Channels"""
    print("🔍 Verificando configuración de Django Channels...")
    
    try:
        from channels.layers import get_channel_layer
        from channels.testing import WebsocketCommunicator
        
        channel_layer = get_channel_layer()
        print("✅ Channel layer configurado correctamente")
        
        # Probar envío de mensaje
        channel_layer.group_add("test_group", "test_channel")
        channel_layer.group_send("test_group", {
            "type": "test.message",
            "text": "test"
        })
        
        print("✅ Operaciones de channel layer funcionando")
        return True
        
    except Exception as e:
        print(f"❌ Error en configuración de Channels: {e}")
        return False

def test_websocket_consumers():
    """Probar consumers de WebSocket"""
    print("🔍 Verificando consumers de WebSocket...")
    
    try:
        from mecanimovilapp.apps.usuarios.consumers import ConnectionConsumer, ClientConsumer
        
        print("✅ Consumers importados correctamente")
        
        # Verificar que los consumers tienen los métodos necesarios
        required_methods = ['connect', 'disconnect', 'receive']
        
        for consumer_class in [ConnectionConsumer, ClientConsumer]:
            for method in required_methods:
                if not hasattr(consumer_class, method):
                    print(f"❌ Consumer {consumer_class.__name__} no tiene método {method}")
                    return False
        
        print("✅ Todos los consumers tienen los métodos necesarios")
        return True
        
    except Exception as e:
        print(f"❌ Error verificando consumers: {e}")
        return False

def test_connection_status_model():
    """Probar modelo ConnectionStatus"""
    print("🔍 Verificando modelo ConnectionStatus...")
    
    try:
        from mecanimovilapp.apps.usuarios.models import ConnectionStatus
        
        # Verificar que el modelo se puede crear
        connection = ConnectionStatus()
        print("✅ Modelo ConnectionStatus se puede instanciar")
        
        # Verificar propiedades
        if hasattr(connection, 'tipo_proveedor'):
            print("✅ Propiedad tipo_proveedor disponible")
        else:
            print("❌ Propiedad tipo_proveedor no encontrada")
            return False
            
        if hasattr(connection, 'nombre_proveedor'):
            print("✅ Propiedad nombre_proveedor disponible")
        else:
            print("❌ Propiedad nombre_proveedor no encontrada")
            return False
        
        print("✅ Modelo ConnectionStatus verificado correctamente")
        return True
        
    except Exception as e:
        print(f"❌ Error verificando modelo ConnectionStatus: {e}")
        return False

def run_cleanup_commands():
    """Ejecutar comandos de limpieza"""
    print("🧹 Ejecutando comandos de limpieza...")
    
    try:
        # Limpiar conexiones antiguas
        subprocess.check_call([sys.executable, 'manage.py', 'cleanup_websockets', '--force'])
        print("✅ Comando cleanup_websockets ejecutado")
        
        # Limpiar estados de conexión
        subprocess.check_call([sys.executable, 'manage.py', 'cleanup_connections', '--minutes', '10'])
        print("✅ Comando cleanup_connections ejecutado")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error ejecutando comandos de limpieza: {e}")
        return False

def create_redis_config():
    """Crear archivo de configuración de Redis"""
    print("📝 Creando configuración de Redis...")
    
    redis_config = """
# Configuración de Redis para Mecanimovil
# Archivo: /etc/redis/mecanimovil.conf

# Configuración básica
port 6379
bind 127.0.0.1
timeout 0
tcp-keepalive 300

# Configuración de memoria
maxmemory 256mb
maxmemory-policy allkeys-lru

# Configuración de persistencia
save 900 1
save 300 10
save 60 10000

# Configuración de logging
loglevel notice
logfile /var/log/redis/redis-server.log

# Configuración de seguridad
requirepass tu_password_aqui

# Configuración de clientes
maxclients 10000

# Configuración de replicación (si se usa)
# slaveof <masterip> <masterport>
# masterauth <master-password>
"""
    
    try:
        with open('redis_mecanimovil.conf', 'w') as f:
            f.write(redis_config)
        print("✅ Archivo de configuración de Redis creado: redis_mecanimovil.conf")
        print("💡 Copia este archivo a /etc/redis/mecanimovil.conf en tu servidor")
        return True
    except Exception as e:
        print(f"❌ Error creando configuración de Redis: {e}")
        return False

def main():
    """Función principal"""
    print("🚀 Configurando Redis y Django Channels para producción...")
    
    # Verificar conexión a Redis
    if not check_redis_connection():
        print("❌ Error en conexión a Redis")
        return
    
    # Verificar configuración de Channels
    if not test_channels_configuration():
        print("❌ Error en configuración de Channels")
        return
    
    # Verificar consumers de WebSocket
    if not test_websocket_consumers():
        print("❌ Error en consumers de WebSocket")
        return
    
    # Verificar modelo ConnectionStatus
    if not test_connection_status_model():
        print("❌ Error en modelo ConnectionStatus")
        return
    
    # Ejecutar comandos de limpieza
    if not run_cleanup_commands():
        print("❌ Error ejecutando comandos de limpieza")
        return
    
    # Crear configuración de Redis
    create_redis_config()
    
    print("✅ Configuración de Redis y Django Channels completada exitosamente")
    print("\n📋 Próximos pasos para producción:")
    print("1. Instalar Redis en el servidor:")
    print("   sudo apt-get install redis-server")
    print("2. Configurar Redis con el archivo generado")
    print("3. Ejecutar el servidor con Daphne:")
    print("   daphne -b 0.0.0.0 -p 8000 mecanimovilapp.asgi:application")
    print("4. Configurar un proxy reverso (nginx) para WebSockets")
    print("5. Configurar variables de entorno para producción")

if __name__ == "__main__":
    main() 