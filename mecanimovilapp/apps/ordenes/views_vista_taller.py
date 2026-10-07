"""Limpieza de listas del taller. No toca chats ni aprendizaje."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CotizacionCanal,
    OfertaProveedor,
    SolicitudServicio,
    VistaTallerOculta,
)
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.services.vista_taller import AMBITOS, limpiar_vista, ocultar_cita, ocultar_cotizacion, ocultar_oferta, ocultar_orden
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


class VistaTallerLimpiarView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def post(self, request):
        taller, _miembro, rol = resolver_contexto_taller(request.user)
        if taller is None or rol == 'mecanico':
            return Response({'detail': 'Solo el taller puede limpiar sus listas.'}, status=status.HTTP_403_FORBIDDEN)
        ambito = str(request.data.get('ambito') or '').strip()
        if ambito not in AMBITOS:
            return Response({'ambito': 'Indica qué lista quieres limpiar.'}, status=status.HTTP_400_BAD_REQUEST)
        ocultos = limpiar_vista(taller, ambito)
        return Response({'ocultos': ocultos, 'ambito': ambito})


class VistaTallerOcultarView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def post(self, request):
        taller, _miembro, rol = resolver_contexto_taller(request.user)
        if taller is None or rol == 'mecanico':
            return Response({'detail': 'Solo el taller puede quitar fichas de sus listas.'}, status=status.HTTP_403_FORBIDDEN)
        tipo = str(request.data.get('tipo') or '').strip()
        objeto_id = request.data.get('id')
        if objeto_id in (None, ''):
            return Response({'id': 'Falta la ficha.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            if tipo == VistaTallerOculta.TIPO_COTIZACION:
                cotizacion = CotizacionCanal.objects.get(pk=int(objeto_id), taller=taller)
                ocultos = ocultar_cotizacion(taller, cotizacion)
            elif tipo == VistaTallerOculta.TIPO_CITA:
                cita = CitaAgendaPersonal.objects.get(pk=int(objeto_id), taller=taller)
                ocultos = ocultar_cita(taller, cita)
            elif tipo == VistaTallerOculta.TIPO_ORDEN:
                orden = SolicitudServicio.objects.get(pk=int(objeto_id), taller=taller)
                ocultos = ocultar_orden(taller, orden)
            elif tipo == VistaTallerOculta.TIPO_OFERTA:
                oferta = OfertaProveedor.objects.get(pk=objeto_id, proveedor_id=taller.usuario_id)
                ocultos = ocultar_oferta(taller, oferta)
            else:
                return Response({'tipo': 'Tipo de ficha no reconocido.'}, status=status.HTTP_400_BAD_REQUEST)
        except (CotizacionCanal.DoesNotExist, CitaAgendaPersonal.DoesNotExist, SolicitudServicio.DoesNotExist, OfertaProveedor.DoesNotExist):
            return Response({'detail': 'No encontramos esa ficha.'}, status=status.HTTP_404_NOT_FOUND)
        except (TypeError, ValueError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'ocultos': ocultos})
