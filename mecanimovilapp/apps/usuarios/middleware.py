import json
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token
from .models import Usuario

class TokenAuthMiddleware(BaseMiddleware):
    """
    Middleware personalizado para autenticación por token en WebSockets
    """
    
    async def __call__(self, scope, receive, send):
        path = scope.get('path', 'N/A')
        # Permitir conexiones anónimas solo para clientes
        if path.startswith('/ws/client_status/'):
            scope['user'] = AnonymousUser()
            return await super().__call__(scope, receive, send)
        # Para proveedores, exigir token
        token = None
        if 'query_string' in scope:
            query_string = scope['query_string'].decode()
            if query_string:
                params = {}
                for param in query_string.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                if 'token' in params:
                    token = params['token']
        if not token and 'headers' in scope:
            headers = dict(scope['headers'])
            for header_key in [b'authorization', b'Authorization', b'x-auth-token', b'X-Auth-Token']:
                if header_key in headers:
                    auth_header = headers[header_key].decode()
                    if auth_header.startswith('Token '):
                        token = auth_header.split('Token ')[1]
                        break
                    elif auth_header.startswith('Bearer '):
                        token = auth_header.split('Bearer ')[1]
                        break
                    else:
                        token = auth_header
                        break
        if token:
            user = await self.get_user_from_token(token)
            scope['user'] = user
        else:
            scope['user'] = AnonymousUser()
        return await super().__call__(scope, receive, send)
    
    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            token_obj = Token.objects.get(key=token)
            return token_obj.user
        except Token.DoesNotExist:
            return AnonymousUser() 