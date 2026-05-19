"""
API del asistente de agendamiento IA (consultas stateless + confirmación bajo flag).
"""
import logging

from django.conf import settings
from rest_framework import permissions, status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.decorators import action
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicioPublica
from mecanimovilapp.apps.ordenes.serializers import (
    OfertaProveedorSerializer,
    SolicitudServicioPublicaSerializer,
)
from mecanimovilapp.apps.ordenes.services.agendamiento_ia import (
    ConfirmacionCatalogoError,
    analizar_necesidad,
    confirmar_candidato,
    listar_candidatos_proveedor,
)
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_operacion import (
    obtener_resumen_operacion_agendamiento_ia,
)

logger = logging.getLogger(__name__)


def _flag_habilitado() -> bool:
    return bool(getattr(settings, 'AGENDAMIENTO_IA_ASISTIDO', False))


def _parse_int_list(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return [int(value)]
    except (TypeError, ValueError):
        return []


class AsistenteAgendamientoViewSet(viewsets.ViewSet):
    """
    Endpoints del asistente. Las acciones de consulta no persisten el texto enviado.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _check_flag(self):
        if not _flag_habilitado():
            return Response(
                {
                    'error': 'Funcionalidad no habilitada',
                    'codigo': 'agendamiento_ia_deshabilitado',
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    @action(detail=False, methods=['post'], url_path='analizar-necesidad')
    def analizar_necesidad_action(self, request):
        denied = self._check_flag()
        if denied:
            return denied

        data = request.data or {}
        texto = (data.get('texto') or '').strip()
        vehiculo_id = data.get('vehiculo_id')
        if vehiculo_id is not None:
            try:
                vehiculo_id = int(vehiculo_id)
            except (TypeError, ValueError):
                return Response(
                    {'error': 'vehiculo_id inválido'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        componentes_salud = data.get('componentes_salud')
        if componentes_salud is not None and not isinstance(componentes_salud, list):
            componentes_salud = []

        origen = (data.get('origen') or 'texto').strip()[:32]

        if not texto and not componentes_salud:
            return Response(
                {'error': 'Proporciona texto o señales de salud del vehículo'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resultado = analizar_necesidad(
                texto=texto,
                vehiculo_id=vehiculo_id,
                componentes_salud=componentes_salud,
                origen=origen,
            )
            return Response(resultado)
        except Exception:
            logger.exception('Error en analizar-necesidad (sin texto usuario en log)')
            return Response(
                {'error': 'No se pudo analizar la necesidad'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['get'], url_path='candidatos-proveedor')
    def candidatos_proveedor_action(self, request):
        denied = self._check_flag()
        if denied:
            return denied

        qp = request.query_params
        try:
            vehiculo_id = int(qp.get('vehiculo_id', ''))
        except (TypeError, ValueError):
            return Response(
                {'error': 'vehiculo_id es obligatorio'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        servicio_ids = _parse_int_list(qp.getlist('servicio_ids[]') or qp.getlist('servicio_ids'))
        if not servicio_ids:
            raw = qp.get('servicio_ids')
            if raw:
                servicio_ids = _parse_int_list(str(raw).split(','))

        if not servicio_ids:
            return Response(
                {'error': 'servicio_ids es obligatorio'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requiere_repuestos = qp.get('requiere_repuestos', 'true').lower() in (
            '1',
            'true',
            'yes',
            'si',
        )
        comunas = qp.getlist('comunas_extraidas[]') or qp.getlist('comunas_extraidas')

        try:
            lat = float(qp['lat']) if qp.get('lat') else None
            lng = float(qp['lng']) if qp.get('lng') else None
        except (TypeError, ValueError):
            lat, lng = None, None

        try:
            direccion_texto = (qp.get('direccion_texto') or qp.get('direccion_servicio_texto') or '').strip()

            resultado = listar_candidatos_proveedor(
                vehiculo_id=vehiculo_id,
                servicio_ids=servicio_ids,
                requiere_repuestos=requiere_repuestos,
                comunas_extraidas=comunas,
                direccion_texto=direccion_texto or None,
                lat=lat,
                lng=lng,
            )
            if resultado.get('error') == 'vehiculo_no_encontrado':
                return Response(
                    {'error': 'Vehículo no encontrado'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(resultado)
        except Exception:
            logger.exception('Error en candidatos-proveedor')
            return Response(
                {'error': 'No se pudieron obtener candidatos'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=['get'],
        url_path='resumen-operacion',
        permission_classes=[IsAdminUser],
    )
    def resumen_operacion_action(self, request):
        """Métricas del asistente IA para staff (sin PII)."""
        denied = self._check_flag()
        if denied:
            return denied
        try:
            return Response(obtener_resumen_operacion_agendamiento_ia())
        except Exception:
            logger.exception('Error en resumen-operacion agendamiento IA')
            return Response(
                {'error': 'No se pudo obtener el resumen operativo'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'], url_path='confirmar-candidato')
    def confirmar_candidato_action(self, request):
        denied = self._check_flag()
        if denied:
            return denied

        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo clientes pueden confirmar candidatos'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            resultado = confirmar_candidato(request.user.cliente, request.data or {})
            solicitud = SolicitudServicioPublica.objects.get(pk=resultado['solicitud_id'])
            oferta = OfertaProveedor.objects.get(pk=resultado['oferta_id'])
            ctx = {'request': request}
            return Response(
                {
                    **resultado,
                    'solicitud': SolicitudServicioPublicaSerializer(solicitud, context=ctx).data,
                    'oferta': OfertaProveedorSerializer(oferta, context=ctx).data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ConfirmacionCatalogoError as e:
            return Response(
                {'error': str(e), 'codigo': e.code},
                status=e.status_code,
            )
        except Exception:
            logger.exception('Error en confirmar-candidato')
            return Response(
                {'error': 'No se pudo confirmar el candidato'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
