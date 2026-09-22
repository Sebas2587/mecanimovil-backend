"""
Ventanas de cache para reducir escrituras a BD y trabajo HTTP repetido
cuando muchos proveedores mantienen sesión activa (Render + Postgres).
"""
import threading
import time

from django.core.cache import cache

# POST /proveedores/conectar/: no repetir lógica completa si el cliente reintenta en poco tiempo.
CONECTAR_HTTP_THROTTLE_SEC = 90

# Heartbeats WebSocket: no escribir last_heartbeat en BD en cada mensaje (sigue el ping en vivo).
WS_HEARTBEAT_DB_WRITE_SEC = 50

# Un socket sin heartbeat durante esta ventana se considera muerto.
# 45s de intervalo del cliente × 2, con margen.
WS_SOCKET_TTL_SEC = 120

_local_sockets: dict[str, dict[str, float]] = {}
_local_lock = threading.Lock()


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


def ws_socket_set_key(tipo_proveedor: str, proveedor_pk: int) -> str:
    return f"ws:sockets:{tipo_proveedor}:{proveedor_pk}"


def _redis_client():
    client = getattr(cache, "client", None)
    if client is None or not hasattr(client, "get_client"):
        return None
    try:
        return client.get_client(write=True)
    except Exception:
        return None


def _socket_redis_key(tipo_proveedor: str, proveedor_pk: int) -> str:
    logical = ws_socket_set_key(tipo_proveedor, proveedor_pk)
    try:
        return cache.make_key(logical)
    except Exception:
        return logical


def _touch_local(tipo_proveedor: str, proveedor_pk: int, channel_name: str) -> int:
    key = ws_socket_set_key(tipo_proveedor, proveedor_pk)
    now = time.time()
    cutoff = now - WS_SOCKET_TTL_SEC
    with _local_lock:
        sockets = _local_sockets.setdefault(key, {})
        sockets[channel_name] = now
        stale = [channel for channel, seen in sockets.items() if seen < cutoff]
        for channel in stale:
            sockets.pop(channel, None)
        return len(sockets)


def _release_local(tipo_proveedor: str, proveedor_pk: int, channel_name: str) -> int:
    key = ws_socket_set_key(tipo_proveedor, proveedor_pk)
    now = time.time()
    cutoff = now - WS_SOCKET_TTL_SEC
    with _local_lock:
        sockets = _local_sockets.get(key)
        if not sockets:
            return 0
        sockets.pop(channel_name, None)
        stale = [channel for channel, seen in sockets.items() if seen < cutoff]
        for channel in stale:
            sockets.pop(channel, None)
        if not sockets:
            _local_sockets.pop(key, None)
            return 0
        return len(sockets)


def register_ws_socket(tipo_proveedor: str, proveedor_pk: int, channel_name: str) -> int:
    """
    Registra este socket como vivo. Devuelve cuántos sockets siguen abiertos
    para el mismo mecánico o taller.
    """
    client = _redis_client()
    if client is None:
        return _touch_local(tipo_proveedor, proveedor_pk, channel_name)
    key = _socket_redis_key(tipo_proveedor, proveedor_pk)
    now = time.time()
    try:
        pipe = client.pipeline()
        pipe.zadd(key, {channel_name: now})
        pipe.zremrangebyscore(key, 0, now - WS_SOCKET_TTL_SEC)
        pipe.expire(key, WS_SOCKET_TTL_SEC)
        pipe.zcard(key)
        result = pipe.execute()
        return int(result[-1] or 0)
    except Exception:
        return _touch_local(tipo_proveedor, proveedor_pk, channel_name)


def release_ws_socket(tipo_proveedor: str, proveedor_pk: int, channel_name: str) -> int:
    """
    Quita este socket. Devuelve cuántos siguen vivos.
    0 significa que este era el último: recién ahí el proveedor pasa a offline.
    """
    client = _redis_client()
    if client is None:
        return _release_local(tipo_proveedor, proveedor_pk, channel_name)
    key = _socket_redis_key(tipo_proveedor, proveedor_pk)
    now = time.time()
    try:
        pipe = client.pipeline()
        pipe.zrem(key, channel_name)
        pipe.zremrangebyscore(key, 0, now - WS_SOCKET_TTL_SEC)
        pipe.zcard(key)
        result = pipe.execute()
        remaining = int(result[-1] or 0)
        if remaining == 0:
            client.delete(key)
        return remaining
    except Exception:
        return _release_local(tipo_proveedor, proveedor_pk, channel_name)
