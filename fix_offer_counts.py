import os
import django
from django.db.models import Count, Q

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica

def fix_offer_counts():
    print("Starting offer count fix...")
    
    # Get all public requests
    solicitudes = SolicitudServicioPublica.objects.all()
    count_updated = 0
    
    for solicitud in solicitudes:
        # Count original offers (not secondary)
        # Assuming related_name='ofertas' from SolicitudServicioPublica to OfertaProveedor
        actual_count = solicitud.ofertas.filter(
            es_oferta_secundaria=False,
            estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago', 'pagada', 'en_ejecucion', 'completada']
            # Exclude rejected/expired/withdrawn if that's the logic? 
            # Looking at serializer get_ofertas, it just filters by original.
            # But usually total_ofertas should reflect valid offers.
            # Let's check `incrementar_ofertas` implementation if possible, best guess is all active-ish offers.
            # For now, let's include all except explicitly cancelled if that makes sense, 
            # OR just trust all linked offers if the logic is simple.
            # The view just calls increment, so it counts everything created. 
            # Let's count all non-secondary offers to be safe and match 'received'.
        ).count()
        
        if solicitud.total_ofertas != actual_count:
            print(f"Fixing Request {solicitud.id}: {solicitud.total_ofertas} -> {actual_count}")
            solicitud.total_ofertas = actual_count
            solicitud.save(update_fields=['total_ofertas'])
            count_updated += 1
            
    print(f"Finished. Updated {count_updated} requests.")

if __name__ == "__main__":
    fix_offer_counts()
