from django.core.management.base import BaseCommand
from mecanimovilapp.apps.usuarios.models import ChileanCommune


class Command(BaseCommand):
    help = 'Cargar las comunas chilenas en la base de datos'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Cargando comunas chilenas...'))
        
        # Datos de comunas chilenas por región
        comunas_data = [
            # Región de Arica y Parinacota (XV)
            {'code': '15101', 'name': 'Arica', 'region_code': '15', 'region_name': 'Arica y Parinacota', 'province_name': 'Arica'},
            {'code': '15102', 'name': 'Camarones', 'region_code': '15', 'region_name': 'Arica y Parinacota', 'province_name': 'Arica'},
            {'code': '15201', 'name': 'Putre', 'region_code': '15', 'region_name': 'Arica y Parinacota', 'province_name': 'Parinacota'},
            {'code': '15202', 'name': 'General Lagos', 'region_code': '15', 'region_name': 'Arica y Parinacota', 'province_name': 'Parinacota'},
            
            # Región de Tarapacá (I)
            {'code': '01101', 'name': 'Iquique', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Iquique'},
            {'code': '01107', 'name': 'Alto Hospicio', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Iquique'},
            {'code': '01401', 'name': 'Pozo Almonte', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Tamarugal'},
            {'code': '01402', 'name': 'Camiña', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Tamarugal'},
            {'code': '01403', 'name': 'Colchane', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Tamarugal'},
            {'code': '01404', 'name': 'Huara', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Tamarugal'},
            {'code': '01405', 'name': 'Pica', 'region_code': '01', 'region_name': 'Tarapacá', 'province_name': 'Tamarugal'},
            
            # Región de Antofagasta (II)
            {'code': '02101', 'name': 'Antofagasta', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Antofagasta'},
            {'code': '02102', 'name': 'Mejillones', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Antofagasta'},
            {'code': '02103', 'name': 'Sierra Gorda', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Antofagasta'},
            {'code': '02104', 'name': 'Taltal', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Antofagasta'},
            {'code': '02201', 'name': 'Calama', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'El Loa'},
            {'code': '02202', 'name': 'Ollagüe', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'El Loa'},
            {'code': '02203', 'name': 'San Pedro de Atacama', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'El Loa'},
            {'code': '02301', 'name': 'Tocopilla', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Tocopilla'},
            {'code': '02302', 'name': 'María Elena', 'region_code': '02', 'region_name': 'Antofagasta', 'province_name': 'Tocopilla'},
            
            # Región de Atacama (III)
            {'code': '03101', 'name': 'Copiapó', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Copiapó'},
            {'code': '03102', 'name': 'Caldera', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Copiapó'},
            {'code': '03103', 'name': 'Tierra Amarilla', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Copiapó'},
            {'code': '03201', 'name': 'Chañaral', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Chañaral'},
            {'code': '03202', 'name': 'Diego de Almagro', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Chañaral'},
            {'code': '03301', 'name': 'Vallenar', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Huasco'},
            {'code': '03302', 'name': 'Alto del Carmen', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Huasco'},
            {'code': '03303', 'name': 'Freirina', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Huasco'},
            {'code': '03304', 'name': 'Huasco', 'region_code': '03', 'region_name': 'Atacama', 'province_name': 'Huasco'},
            
            # Región de Coquimbo (IV)
            {'code': '04101', 'name': 'La Serena', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04102', 'name': 'Coquimbo', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04103', 'name': 'Andacollo', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04104', 'name': 'La Higuera', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04105', 'name': 'Paiguano', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04106', 'name': 'Vicuña', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Elqui'},
            {'code': '04201', 'name': 'Illapel', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Choapa'},
            {'code': '04202', 'name': 'Canela', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Choapa'},
            {'code': '04203', 'name': 'Los Vilos', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Choapa'},
            {'code': '04204', 'name': 'Salamanca', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Choapa'},
            {'code': '04301', 'name': 'Ovalle', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Limarí'},
            {'code': '04302', 'name': 'Combarbalá', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Limarí'},
            {'code': '04303', 'name': 'Monte Patria', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Limarí'},
            {'code': '04304', 'name': 'Punitaqui', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Limarí'},
            {'code': '04305', 'name': 'Río Hurtado', 'region_code': '04', 'region_name': 'Coquimbo', 'province_name': 'Limarí'},
            
            # Región de Valparaíso (V)
            {'code': '05101', 'name': 'Valparaíso', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05102', 'name': 'Casablanca', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05103', 'name': 'Concón', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05104', 'name': 'Juan Fernández', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05105', 'name': 'Puchuncaví', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05107', 'name': 'Quintero', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05109', 'name': 'Viña del Mar', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Valparaíso'},
            {'code': '05201', 'name': 'Isla de Pascua', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Isla de Pascua'},
            {'code': '05301', 'name': 'Los Andes', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Los Andes'},
            {'code': '05302', 'name': 'Calle Larga', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Los Andes'},
            {'code': '05303', 'name': 'Rinconada', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Los Andes'},
            {'code': '05304', 'name': 'San Esteban', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Los Andes'},
            {'code': '05401', 'name': 'La Ligua', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Petorca'},
            {'code': '05402', 'name': 'Cabildo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Petorca'},
            {'code': '05403', 'name': 'Papudo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Petorca'},
            {'code': '05404', 'name': 'Petorca', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Petorca'},
            {'code': '05405', 'name': 'Zapallar', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Petorca'},
            {'code': '05501', 'name': 'Quillota', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Quillota'},
            {'code': '05502', 'name': 'Calera', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Quillota'},
            {'code': '05503', 'name': 'Hijuelas', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Quillota'},
            {'code': '05504', 'name': 'La Cruz', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Quillota'},
            {'code': '05506', 'name': 'Nogales', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'Quillota'},
            {'code': '05601', 'name': 'San Antonio', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05602', 'name': 'Algarrobo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05603', 'name': 'Cartagena', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05604', 'name': 'El Quisco', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05605', 'name': 'El Tabo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05606', 'name': 'Santo Domingo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Antonio'},
            {'code': '05701', 'name': 'San Felipe', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            {'code': '05702', 'name': 'Catemu', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            {'code': '05703', 'name': 'Llaillay', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            {'code': '05704', 'name': 'Panquehue', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            {'code': '05705', 'name': 'Putaendo', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            {'code': '05706', 'name': 'Santa María', 'region_code': '05', 'region_name': 'Valparaíso', 'province_name': 'San Felipe de Aconcagua'},
            
            # Región Metropolitana de Santiago (RM)
            {'code': '13101', 'name': 'Santiago', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13102', 'name': 'Cerrillos', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13103', 'name': 'Cerro Navia', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13104', 'name': 'Conchalí', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13105', 'name': 'El Bosque', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13106', 'name': 'Estación Central', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13107', 'name': 'Huechuraba', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13108', 'name': 'Independencia', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13109', 'name': 'La Cisterna', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13110', 'name': 'La Florida', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13111', 'name': 'La Granja', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13112', 'name': 'La Pintana', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13113', 'name': 'La Reina', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13114', 'name': 'Las Condes', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13115', 'name': 'Lo Barnechea', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13116', 'name': 'Lo Espejo', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13117', 'name': 'Lo Prado', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13118', 'name': 'Macul', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13119', 'name': 'Maipú', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13120', 'name': 'Ñuñoa', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13121', 'name': 'Pedro Aguirre Cerda', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13122', 'name': 'Peñalolén', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13123', 'name': 'Providencia', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13124', 'name': 'Pudahuel', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13125', 'name': 'Quilicura', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13126', 'name': 'Quinta Normal', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13127', 'name': 'Recoleta', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13128', 'name': 'Renca', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13129', 'name': 'San Joaquín', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13130', 'name': 'San Miguel', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13131', 'name': 'San Ramón', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13132', 'name': 'Vitacura', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Santiago'},
            {'code': '13201', 'name': 'Puente Alto', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Cordillera'},
            {'code': '13202', 'name': 'Pirque', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Cordillera'},
            {'code': '13203', 'name': 'San José de Maipo', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Cordillera'},
            {'code': '13301', 'name': 'Colina', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Chacabuco'},
            {'code': '13302', 'name': 'Lampa', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Chacabuco'},
            {'code': '13303', 'name': 'Tiltil', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Chacabuco'},
            {'code': '13401', 'name': 'San Bernardo', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Maipo'},
            {'code': '13402', 'name': 'Buin', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Maipo'},
            {'code': '13403', 'name': 'Calera de Tango', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Maipo'},
            {'code': '13404', 'name': 'Paine', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Maipo'},
            {'code': '13501', 'name': 'Melipilla', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Melipilla'},
            {'code': '13502', 'name': 'Alhué', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Melipilla'},
            {'code': '13503', 'name': 'Curacaví', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Melipilla'},
            {'code': '13504', 'name': 'María Pinto', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Melipilla'},
            {'code': '13505', 'name': 'San Pedro', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Melipilla'},
            {'code': '13601', 'name': 'Talagante', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Talagante'},
            {'code': '13602', 'name': 'El Monte', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Talagante'},
            {'code': '13603', 'name': 'Isla de Maipo', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Talagante'},
            {'code': '13604', 'name': 'Padre Hurtado', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Talagante'},
            {'code': '13605', 'name': 'Peñaflor', 'region_code': '13', 'region_name': 'Metropolitana de Santiago', 'province_name': 'Talagante'},
            
            # Más regiones principales...
            # Región del Libertador General Bernardo O'Higgins (VI) - Solo principales
            {'code': '06101', 'name': 'Rancagua', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06102', 'name': 'Codegua', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06103', 'name': 'Coinco', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06104', 'name': 'Coltauco', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06105', 'name': 'Doñihue', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06106', 'name': 'Graneros', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06107', 'name': 'Las Cabras', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06108', 'name': 'Machalí', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06109', 'name': 'Malloa', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06110', 'name': 'Mostazal', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06111', 'name': 'Olivar', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06112', 'name': 'Peumo', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06113', 'name': 'Pichidegua', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06114', 'name': 'Quinta de Tilcoco', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06115', 'name': 'Rengo', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06116', 'name': 'Requínoa', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            {'code': '06117', 'name': 'San Vicente', 'region_code': '06', 'region_name': "Libertador Gral. Bernardo O'Higgins", 'province_name': 'Cachapoal'},
            
            # Región del Maule (VII) - Solo principales 
            {'code': '07101', 'name': 'Talca', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07102', 'name': 'Constitución', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07103', 'name': 'Curepto', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07104', 'name': 'Empedrado', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07105', 'name': 'Maule', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07106', 'name': 'Pelarco', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07107', 'name': 'Pencahue', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07108', 'name': 'Río Claro', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07109', 'name': 'San Clemente', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            {'code': '07110', 'name': 'San Rafael', 'region_code': '07', 'region_name': 'Maule', 'province_name': 'Talca'},
            
            # Región del Biobío (VIII) - Solo principales
            {'code': '08101', 'name': 'Concepción', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08102', 'name': 'Coronel', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08103', 'name': 'Chiguayante', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08104', 'name': 'Florida', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08105', 'name': 'Hualqui', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08106', 'name': 'Lota', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08107', 'name': 'Penco', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08108', 'name': 'San Pedro de la Paz', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08109', 'name': 'Santa Juana', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08110', 'name': 'Talcahuano', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08111', 'name': 'Tomé', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            {'code': '08112', 'name': 'Hualpén', 'region_code': '08', 'region_name': 'Biobío', 'province_name': 'Concepción'},
            
            # Región de La Araucanía (IX) - Solo principales
            {'code': '09101', 'name': 'Temuco', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09102', 'name': 'Carahue', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09103', 'name': 'Cunco', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09104', 'name': 'Curarrehue', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09105', 'name': 'Freire', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09106', 'name': 'Galvarino', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09107', 'name': 'Gorbea', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09108', 'name': 'Lautaro', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09109', 'name': 'Loncoche', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09110', 'name': 'Melipeuco', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09111', 'name': 'Nueva Imperial', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09112', 'name': 'Padre las Casas', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09113', 'name': 'Perquenco', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09114', 'name': 'Pitrufquén', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09115', 'name': 'Pucón', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09116', 'name': 'Saavedra', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09117', 'name': 'Teodoro Schmidt', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09118', 'name': 'Toltén', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09119', 'name': 'Vilcún', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09120', 'name': 'Villarrica', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            {'code': '09121', 'name': 'Cholchol', 'region_code': '09', 'region_name': 'La Araucanía', 'province_name': 'Cautín'},
            
            # Región de Los Ríos (XIV) - Solo principales
            {'code': '14101', 'name': 'Valdivia', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14102', 'name': 'Corral', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14103', 'name': 'Lanco', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14104', 'name': 'Los Lagos', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14105', 'name': 'Máfil', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14106', 'name': 'Mariquina', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14107', 'name': 'Paillaco', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            {'code': '14108', 'name': 'Panguipulli', 'region_code': '14', 'region_name': 'Los Ríos', 'province_name': 'Valdivia'},
            
            # Región de Los Lagos (X) - Solo principales
            {'code': '10101', 'name': 'Puerto Montt', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10102', 'name': 'Calbuco', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10103', 'name': 'Cochamó', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10104', 'name': 'Fresia', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10105', 'name': 'Frutillar', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10106', 'name': 'Los Muermos', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10107', 'name': 'Llanquihue', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10108', 'name': 'Maullín', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            {'code': '10109', 'name': 'Puerto Varas', 'region_code': '10', 'region_name': 'Los Lagos', 'province_name': 'Llanquihue'},
            
            # Región Aysén del General Carlos Ibáñez del Campo (XI) - Solo principales
            {'code': '11101', 'name': 'Coihaique', 'region_code': '11', 'region_name': 'Aysén del General Carlos Ibáñez del Campo', 'province_name': 'Coihaique'},
            {'code': '11102', 'name': 'Lago Verde', 'region_code': '11', 'region_name': 'Aysén del General Carlos Ibáñez del Campo', 'province_name': 'Coihaique'},
            
            # Región de Magallanes y de la Antártica Chilena (XII) - Solo principales
            {'code': '12101', 'name': 'Punta Arenas', 'region_code': '12', 'region_name': 'Magallanes y de la Antártica Chilena', 'province_name': 'Magallanes'},
            {'code': '12102', 'name': 'Laguna Blanca', 'region_code': '12', 'region_name': 'Magallanes y de la Antártica Chilena', 'province_name': 'Magallanes'},
            {'code': '12103', 'name': 'Río Verde', 'region_code': '12', 'region_name': 'Magallanes y de la Antártica Chilena', 'province_name': 'Magallanes'},
            {'code': '12104', 'name': 'San Gregorio', 'region_code': '12', 'region_name': 'Magallanes y de la Antártica Chilena', 'province_name': 'Magallanes'},
        ]
        
        # Cargar comunas
        created_count = 0
        updated_count = 0
        
        for data in comunas_data:
            commune, created = ChileanCommune.objects.get_or_create(
                code=data['code'],
                defaults=data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f"✅ Creada: {commune.name} ({commune.region_name})")
            else:
                # Actualizar datos si ya existe
                for key, value in data.items():
                    setattr(commune, key, value)
                commune.save()
                updated_count += 1
                self.stdout.write(f"🔄 Actualizada: {commune.name} ({commune.region_name})")
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Proceso completado!\n'
                f'   📊 Comunas creadas: {created_count}\n'
                f'   🔄 Comunas actualizadas: {updated_count}\n'
                f'   📈 Total comunas en BD: {ChileanCommune.objects.count()}'
            )
        ) 