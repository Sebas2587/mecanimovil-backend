"""API de caja del taller. No envía nada hacia afuera."""
from __future__ import annotations

from datetime import date

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.services.caja_taller import (
    CajaError,
    ancla_asignada,
    consultar_periodo,
    monto_entero_clp,
    movimiento_response,
    registrar_costo,
    registrar_manual,
    resolver_ancla,
)
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


def _error(exc: CajaError) -> Response:
    return Response({'code': exc.code, 'detail': exc.detail}, status=exc.status)


def _contexto(request):
    taller, miembro, rol = resolver_contexto_taller(request.user)
    if taller is None:
        return None, None, None
    return taller, miembro, rol


class CajaPeriodoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def get(self, request):
        taller, miembro, rol = _contexto(request)
        if taller is None:
            return Response({'detail': 'Taller no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            desde = date.fromisoformat(request.query_params.get('desde') or '')
            hasta = date.fromisoformat(request.query_params.get('hasta') or '')
        except ValueError:
            return Response(
                {'code': 'periodo_invalido', 'detail': 'Usa desde y hasta como YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data = consultar_periodo(
                taller=taller,
                desde=desde,
                hasta=hasta,
                granularidad=(request.query_params.get('granularidad') or 'dia'),
                page=int(request.query_params.get('page') or 1),
                page_size=int(request.query_params.get('page_size') or 50),
                casos_page=int(request.query_params.get('casos_page') or 1),
                miembro=miembro,
                rol=rol,
                ancla_tipo=request.query_params.get('ancla_tipo') or None,
                ancla_id=request.query_params.get('ancla_id') or None,
            )
        except CajaError as exc:
            return _error(exc)
        except ValueError:
            return Response(
                {'code': 'parametro_invalido', 'detail': 'Revisa page y page_size.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(data)


class CajaCobroManualView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def post(self, request):
        taller, miembro, rol = _contexto(request)
        if taller is None:
            return Response({'detail': 'Taller no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if rol == 'mecanico':
            return Response(
                {'code': 'sin_permiso', 'detail': 'Un mecánico no registra cobros.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        cuerpo = request.data if isinstance(request.data, dict) else {}
        ancla_tipo = str(cuerpo.get('ancla_tipo') or '')
        ancla_id = str(cuerpo.get('ancla_id') or '')
        try:
            resolver_ancla(taller, ancla_tipo, ancla_id)
            if rol == 'mecanico' and not ancla_asignada(miembro, ancla_tipo, ancla_id):
                raise CajaError('ancla_ajena', 'El caso no pertenece a este taller.', status=404)
            mov, creado = registrar_manual(
                taller=taller,
                usuario=request.user,
                ancla_tipo=ancla_tipo,
                ancla_id=ancla_id,
                tipo=str(cuerpo.get('tipo') or 'entrada'),
                monto_clp=monto_entero_clp(cuerpo.get('monto_clp')),
                fecha_valor=cuerpo.get('fecha_efectiva'),
                idempotency_key=request.headers.get('Idempotency-Key', ''),
                componente=str(cuerpo.get('componente') or 'total'),
                movimiento_origen_id=cuerpo.get('movimiento_origen_id'),
                motivo=str(cuerpo.get('motivo') or ''),
                confirmar_sobrepago=bool(cuerpo.get('confirmar_sobrepago')),
            )
        except CajaError as exc:
            return _error(exc)
        codigo = status.HTTP_201_CREATED if creado else status.HTTP_200_OK
        return Response(movimiento_response(mov, creado=creado), status=codigo)


class CajaCostoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def post(self, request):
        taller, _miembro, rol = _contexto(request)
        if taller is None:
            return Response({'detail': 'Taller no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if rol not in {'mandante', 'supervisor'}:
            return Response(
                {'code': 'sin_permiso', 'detail': 'Solo el taller registra costos.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        cuerpo = request.data if isinstance(request.data, dict) else {}
        try:
            costo = registrar_costo(
                taller=taller,
                usuario=request.user,
                ancla_tipo=str(cuerpo.get('ancla_tipo') or ''),
                ancla_id=str(cuerpo.get('ancla_id') or ''),
                componente=str(cuerpo.get('componente') or ''),
                tipo=str(cuerpo.get('tipo') or ''),
                monto_clp=monto_entero_clp(cuerpo.get('monto_clp'), permitir_cero=True),
                nota=str(cuerpo.get('nota') or ''),
            )
        except CajaError as exc:
            return _error(exc)
        return Response(
            {
                'id': str(costo.id),
                'ancla_tipo': costo.ancla_tipo,
                'ancla_id': costo.ancla_id,
                'componente': costo.componente,
                'tipo': costo.tipo,
                'monto_clp': int(costo.monto_clp),
                'moneda': costo.moneda,
                'vigente': costo.vigente,
            },
            status=status.HTTP_201_CREATED,
        )
