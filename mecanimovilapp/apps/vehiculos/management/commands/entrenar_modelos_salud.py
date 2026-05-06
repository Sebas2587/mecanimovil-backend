"""
Management command: entrena modelos scikit-learn por componente.

Lee EventoSaludVehiculo (eventos SERVICIO_REALIZADO + NIVEL_CRITICO),
agrupa por slug de componente, entrena un Random Forest Regressor que
predice km_desde_ultimo_servicio en función de marca, modelo, año, motor
y kilometraje. Guarda los modelos como joblib en MEDIA_ROOT/ml_models/.

Uso:
    python manage.py entrenar_modelos_salud           # entrena todos
    python manage.py entrenar_modelos_salud --slug aceite-motor

Diseño:
- Si un componente tiene < 30 eventos, no se entrena (insuficiente data).
- Encoders (LabelEncoder) se persisten dentro del bundle joblib.
- Métrica: MAE (Mean Absolute Error) para reporte por consola.
- Idempotente: re-entrenar reemplaza el modelo previo.
"""
import os
import logging
from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)

ML_MODEL_DIR = os.path.join(getattr(settings, 'MEDIA_ROOT', '/tmp'), 'ml_models')
ML_TRAINING_THRESHOLD = 30


class Command(BaseCommand):
    help = 'Entrena modelos scikit-learn predictivos para cada componente de salud'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug', type=str, default=None,
            help='Slug específico para entrenar; sin él entrena todos los componentes.',
        )
        parser.add_argument(
            '--min-samples', type=int, default=ML_TRAINING_THRESHOLD,
            help=f'Mínimo de muestras para entrenar (default {ML_TRAINING_THRESHOLD}).',
        )

    def handle(self, *args, **options):
        from mecanimovilapp.apps.vehiculos.models_health import (
            ComponenteSalud, EventoSaludVehiculo,
        )

        os.makedirs(ML_MODEL_DIR, exist_ok=True)

        try:
            import numpy as np
            import joblib
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.linear_model import LinearRegression  # noqa: F401
            from sklearn.tree import DecisionTreeClassifier    # noqa: F401
            from sklearn.preprocessing import LabelEncoder
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import mean_absolute_error
        except ImportError as e:
            self.stdout.write(self.style.ERROR(
                f'Faltan dependencias ML: {e}. Instala scikit-learn, numpy, joblib.'
            ))
            return

        slug_filter = options.get('slug')
        min_samples = options['min_samples']

        if slug_filter:
            componentes = ComponenteSalud.objects.filter(slug=slug_filter)
        else:
            componentes = ComponenteSalud.objects.all()

        total_entrenados = 0
        total_omitidos = 0

        for comp in componentes:
            qs = EventoSaludVehiculo.objects.filter(
                componente=comp,
                tipo_evento__in=['SERVICIO_REALIZADO', 'NIVEL_CRITICO'],
                km_desde_ultimo_servicio__isnull=False,
                km_desde_ultimo_servicio__gt=0,
            ).values(
                'marca', 'modelo', 'year', 'tipo_motor',
                'kilometraje', 'salud_porcentaje', 'km_desde_ultimo_servicio',
            )
            data = list(qs)
            n = len(data)

            if n < min_samples:
                self.stdout.write(self.style.WARNING(
                    f'  {comp.slug}: {n}/{min_samples} eventos — skip.'
                ))
                total_omitidos += 1
                continue

            # Preparar datos
            marcas = [d['marca'] or '' for d in data]
            modelos = [d['modelo'] or '' for d in data]
            motores = [d['tipo_motor'] or 'GASOLINA' for d in data]

            enc_marca = LabelEncoder().fit(marcas)
            enc_modelo = LabelEncoder().fit(modelos)
            enc_motor = LabelEncoder().fit(motores)

            X = []
            y = []
            for d in data:
                X.append([
                    int(enc_marca.transform([d['marca'] or ''])[0]),
                    int(enc_modelo.transform([d['modelo'] or ''])[0]),
                    int(enc_motor.transform([d['tipo_motor'] or 'GASOLINA'])[0]),
                    int(d['year'] or 2020),
                    int(d['kilometraje'] or 0),
                    float(d['salud_porcentaje'] or 100),
                ])
                y.append(int(d['km_desde_ultimo_servicio']))

            X = np.array(X)
            y = np.array(y)

            # Split 80/20 si hay suficientes muestras
            if n >= 50:
                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42,
                )
            else:
                X_train, y_train = X, y
                X_test, y_test = X, y

            # Random Forest: robusto, maneja categóricas codificadas y valores no lineales
            rf = RandomForestRegressor(
                n_estimators=80, max_depth=12,
                min_samples_leaf=2, n_jobs=-1, random_state=42,
            )
            rf.fit(X_train, y_train)
            y_pred = rf.predict(X_test)
            mae = mean_absolute_error(y_test, y_pred)

            bundle = {
                'regressor':  rf,
                'encoders':   {
                    'marca':      enc_marca,
                    'modelo':     enc_modelo,
                    'tipo_motor': enc_motor,
                },
                'features':   ['marca', 'modelo', 'tipo_motor', 'year', 'kilometraje', 'salud_inicial'],
                'n_samples':  n,
                'mae_km':     float(mae),
                'algoritmo':  'RandomForestRegressor',
            }
            path = os.path.join(ML_MODEL_DIR, f'{comp.slug}.joblib')
            joblib.dump(bundle, path)
            total_entrenados += 1

            self.stdout.write(self.style.SUCCESS(
                f'  ✅ {comp.slug}: n={n}  MAE={mae:.0f} km  → {path}'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'\nResumen: {total_entrenados} entrenados / {total_omitidos} omitidos.'
        ))
