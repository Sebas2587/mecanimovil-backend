"""
Ventanas de cache para reducir escrituras a BD y trabajo HTTP repetido
cuando muchos proveedores mantienen sesión activa (Render + Postgres).
"""
from django.core.cache import cache

# POST /proveedores/conectar/: no repetir lógica completa si el cliente reintenta en poco tiempo.
CONECTAR_HTTP_THROTTLE_SEC = 90

# Heartbeats WebSocket: no escribir last_heartbeat en BD en cada mensaje (sigue el ping en vivo).
WS_HEARTBEAT_DB_WRITE_SEC = 50


def conectar_http_throttle_key(user_id: int) -> str:
    return f"api:proveedor_conectar:{user_id}"


def try_begin_conectar_http_window(user_id: int) -> bool:
    """
    True = esta petición debe ejecutar la actualización completa.
    False = responder 200 sin tocar BD (ventana aún activa).
    """
    return cache.add(conectar_http_throttle_key(user_id), 1, CONECTAR_HTTP_THROTTLE_SEC)


def clear_conectar_http_window(user_id: int) -> None:
    cache.delete(conectar_http_throttle_key(user_id))


def ws_heartbeat_db_key(tipo_proveedor: str, proveedor_pk: int) -> str:
    return f"ws:heartbeat_db:{tipo_proveedor}:{proveedor_pk}"


def reserve_ws_heartbeat_db_write(tipo_proveedor: str, proveedor_pk: int) -> bool:
    """
    True = esta llamada debe persistir last_heartbeat en BD.
    False = ventana reciente ya cubierta; omitir UPDATE (el WS sigue vivo).
    """
    key = ws_heartbeat_db_key(tipo_proveedor, proveedor_pk)
    if cache.get(key):
        return False
    cache.set(key, 1, WS_HEARTBEAT_DB_WRITE_SEC)
    return True
