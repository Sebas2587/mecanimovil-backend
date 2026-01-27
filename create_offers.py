import os
import django
import random
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.usuarios.models import Usuario, Cliente
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor, DetalleServicioOferta

def create_test_offers():
    try:
        # 1. Get User/Client
        email = 'marthatest@gmail.com'
        user = Usuario.objects.get(email=email)
        cliente = Cliente.objects.get(usuario=user)
        print(f"Target Client: {cliente}")

        # 2. Get Active Request
        # Prioritize 'publicada', 'pendiente' states
        solicitud = SolicitudServicioPublica.objects.filter(
            cliente=cliente,
            estado__in=['publicada', 'pendiente']
        ).first()

        if not solicitud:
            print("No active public request found (state: publicada/pendiente).")
            return

        print(f"Found Request ID: {solicitud.id} - State: {solicitud.estado}")
        servicios = list(solicitud.servicios_solicitados.all())
        if not servicios:
            print("Request has no services linked.")
            return
        
        print(f"Request Services: {[s.nombre for s in servicios]}")

        # 3. Find 2 Providers
        # Exclude the client user if they happen to be a provider too
        providers = Usuario.objects.filter(
            Q(taller__isnull=False) | Q(mecanico_domicilio__isnull=False)
        ).exclude(id=user.id).distinct()[:5]

        # Use first 2 valid ones
        selected_providers = []
        for p in providers:
            # Check if they already have an offer for this request to avoid dupes?
            # Actually, user asked to create offers, so duplicate might be okay for testing or I should clean up previous ones.
            # Let's clean up previous active offers for this request from these providers to avoid clutter.
            if len(selected_providers) < 2:
                selected_providers.append(p)
        
        if len(selected_providers) < 2:
            print(f"Not enough providers found. Found: {len(selected_providers)}")
        
        print(f"Selected Providers: {[p.email for p in selected_providers]}")

        # 4. Create Offers
        for i, provider in enumerate(selected_providers):
            # Check provider type
            if hasattr(provider, 'taller') and provider.taller:
                tipo = 'taller'
            elif hasattr(provider, 'mecanico_domicilio') and provider.mecanico_domicilio:
                tipo = 'mecanico'
            else:
                continue # Should not happen due to filter

            # Price logic
            base_price = random.randint(30, 80) * 1000 # 30k to 80k
            
            # Create Offer
            oferta = OfertaProveedor.objects.create(
                solicitud=solicitud,
                proveedor=provider,
                tipo_proveedor=tipo,
                precio_total_ofrecido=base_price,
                fecha_disponible=timezone.now().date() + timedelta(days=i+1),
                hora_disponible=timezone.now().time().replace(hour=9+i, minute=0, second=0),
                estado='enviada',
                descripcion_oferta="Hola, puedo realizar este trabajo. Tengo disponibilidad y repuestos.",
                tiempo_estimado_total=timedelta(hours=2),
                incluye_repuestos=True,
                garantia_ofrecida="3 meses"
            )

            # Create Details
            details_count = len(servicios)
            price_per_service = base_price / details_count
            
            for servicio in servicios:
                DetalleServicioOferta.objects.create(
                    oferta=oferta,
                    servicio=servicio,
                    precio_servicio=price_per_service,
                    tiempo_estimado=timedelta(hours=1),
                    notas="Servicio estándar"
                )
            
            print(f"Created Offer {oferta.id} from {provider.email} for ${base_price}")
        
        # Update request status if needed
        if solicitud.estado == 'pendiente':
           solicitud.estado = 'publicada'
           solicitud.save()
           print("Updated request status to 'publicada'")

    except Usuario.DoesNotExist:
        print(f"User {email} not found.")
    except Exception as e:
        print(f"Error creating offers: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    create_test_offers()
