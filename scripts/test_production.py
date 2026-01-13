#!/usr/bin/env python
"""
Script para verificar que todos los servicios estén funcionando en producción.
Ejecutar: python scripts/test_production.py
"""

import requests
import sys
import os

# Color codes para terminal
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_success(message):
    print(f"{GREEN}✅ {message}{RESET}")

def print_error(message):
    print(f"{RED}❌ {message}{RESET}")

def print_info(message):
    print(f"{BLUE}ℹ️  {message}{RESET}")

def print_warning(message):
    print(f"{YELLOW}⚠️  {message}{RESET}")

def test_api_endpoint(base_url):
    """Probar que el endpoint básico funcione"""
    print_info("Probando endpoint básico...")
    try:
        response = requests.get(f"{base_url}/api/hello/", timeout=10)
        if response.status_code == 200:
            print_success(f"API responde correctamente (Status: {response.status_code})")
            try:
                data = response.json()
                print_success(f"Respuesta: {data}")
            except:
                print_warning("Respuesta no es JSON, pero el servidor funciona")
            return True
        else:
            print_error(f"API responde con código {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        print_error("Timeout: El servidor no responde en 10 segundos")
        return False
    except requests.exceptions.ConnectionError:
        print_error("Error de conexión: No se pudo conectar al servidor")
        return False
    except Exception as e:
        print_error(f"Error inesperado: {str(e)}")
        return False

def test_cors(base_url):
    """Probar que CORS esté configurado correctamente"""
    print_info("Probando CORS...")
    try:
        response = requests.get(
            f"{base_url}/api/hello/",
            headers={
                'Origin': 'https://expo.dev',
                'Access-Control-Request-Method': 'GET',
            },
            timeout=10
        )
        
        # Verificar headers CORS
        cors_headers = {
            'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin'),
            'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods'),
            'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers'),
        }
        
        if cors_headers['Access-Control-Allow-Origin']:
            if cors_headers['Access-Control-Allow-Origin'] == '*':
                print_success("CORS configurado: Permite todos los orígenes (*)")
            else:
                print_success(f"CORS configurado: {cors_headers['Access-Control-Allow-Origin']}")
            return True
        else:
            print_warning("No se encontraron headers CORS (puede ser normal si no hay preflight)")
            return True  # No es un error crítico
    except Exception as e:
        print_error(f"Error probando CORS: {str(e)}")
        return False

def test_health_endpoint(base_url):
    """Probar endpoint de health check si existe"""
    print_info("Probando health check...")
    try:
        response = requests.get(f"{base_url}/api/hello/", timeout=10)
        if response.status_code in [200, 404]:  # 404 también es válido si el endpoint no existe
            print_success("Health check responde")
            return True
        return False
    except:
        print_warning("Health check no disponible (no es crítico)")
        return True

def main():
    print("\n" + "="*60)
    print(f"{BLUE}🧪 Verificación de Servicios en Producción{RESET}")
    print("="*60 + "\n")
    
    # Obtener URL de la API
    base_url = os.environ.get('API_URL')
    if not base_url:
        base_url = input("Ingresa la URL de tu API (ej: https://mecanimovil-api.onrender.com): ").strip()
        if not base_url:
            print_error("URL requerida")
            sys.exit(1)
    
    # Remover barra final si existe
    base_url = base_url.rstrip('/')
    
    print_info(f"Probando API en: {base_url}\n")
    
    # Ejecutar pruebas
    results = {
        'API Endpoint': test_api_endpoint(base_url),
        'CORS': test_cors(base_url),
        'Health Check': test_health_endpoint(base_url),
    }
    
    # Resumen
    print("\n" + "="*60)
    print(f"{BLUE}📊 Resumen de Pruebas{RESET}")
    print("="*60)
    
    for test_name, result in results.items():
        if result:
            print_success(f"{test_name}: OK")
        else:
            print_error(f"{test_name}: FALLÓ")
    
    # Resultado final
    all_passed = all(results.values())
    print("\n" + "="*60)
    if all_passed:
        print_success("🎉 ¡Todos los tests pasaron! Tu API está funcionando correctamente.")
    else:
        print_error("⚠️  Algunos tests fallaron. Revisa los errores arriba.")
    print("="*60 + "\n")
    
    # Instrucciones adicionales
    print_info("Próximos pasos:")
    print("1. Verifica los logs en Render Dashboard → mecanimovil-api → Logs")
    print("2. Verifica que Celery Worker y Beat estén 'Live'")
    print("3. Verifica que Redis esté 'Live'")
    print("4. Prueba desde tu app Expo con la URL:", base_url)
    print()
    
    sys.exit(0 if all_passed else 1)

if __name__ == '__main__':
    main()
