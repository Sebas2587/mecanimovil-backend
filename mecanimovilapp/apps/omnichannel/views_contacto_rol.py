"""Fijar rol de un contacto que no es casa de repuestos."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from mecanimovilapp.apps.omnichannel.models import ExternalContact

_ROLES_DESDE_CHAT = {
    ExternalContact.ROL_SOLO_CONSULTA,
    ExternalContact.ROL_OTRO,
    ExternalContact.ROL_SIN_CLASIFICAR,
}


class ContactoRolView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, contact_id):
        rol = str(request.data.get('rol') or '').strip()
        if rol not in _ROLES_DESDE_CHAT:
            return Response(
                {'detail': 'Desde el chat se puede marcar solo consulta, otro, o quitar la marca.'},
                status=400,
            )
        contact = ExternalContact.objects.filter(
            pk=contact_id,
            connection__usuario=request.user,
        ).first()
        if contact is None:
            return Response({'detail': 'Contacto no encontrado.'}, status=404)
        if contact.rol == ExternalContact.ROL_CASA_REPUESTOS and contact.rol_manual:
            return Response(
                {'detail': 'Este número es una casa de repuestos. Quítala desde Casas de repuestos.'},
                status=400,
            )
        contact.rol = rol
        contact.rol_manual = rol != ExternalContact.ROL_SIN_CLASIFICAR
        contact.rol_sugerido = ''
        contact.save(update_fields=['rol', 'rol_manual', 'rol_sugerido', 'updated_at'])
        return Response({'id': str(contact.id), 'rol': contact.rol, 'rol_sugerido': contact.rol_sugerido})
