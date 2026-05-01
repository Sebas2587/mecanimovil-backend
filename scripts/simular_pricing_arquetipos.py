"""
Simulación en consola de arquetipos vs precio bruto por crédito (sin tocar la BD).

  cd mecanimovil-backend && python scripts/simular_pricing_arquetipos.py --precio-bruto 520

Opcional: --posts-mes 12 --arquetipo medio  (sugiere créditos/mes de plan de referencia)
"""
import argparse
import os
import sys
from decimal import Decimal

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

import django  # noqa: E402

django.setup()

from mecanimovilapp.apps.suscripciones.pricing_arquetipos import (  # noqa: E402
    ARQUETIPOS_DEFAULT,
    arquetipos_por_id,
    filas_simulacion,
    creditos_mensuales_sugeridos_plan,
    precio_neto_credito_desde_bruto,
)
from mecanimovilapp.apps.suscripciones.mercado_pago_pricing import monto_bruto_para_neto  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--precio-bruto', type=float, required=True, help='Precio bruto por crédito (CLP, ej. lo que muestra la app)')
    p.add_argument('--posts-mes', type=int, default=0, help='Si >0, muestra créditos/mes de plan de referencia')
    p.add_argument('--arquetipo', type=str, default='medio', help='id de arquetipo para créditos/mes (basico|medio|alto|premium)')
    args = p.parse_args()

    pb = Decimal(str(args.precio_bruto))
    p_neto = precio_neto_credito_desde_bruto(pb)
    neto_ref_500_bruto = monto_bruto_para_neto(Decimal('500'))

    print(f'\nPrecio bruto/crédito: ${pb:,.2f}  →  neto aprox. por crédito (tras MP): ${p_neto:,.2f}')
    print(f'Referencia: neto $500/cr implica bruto ~ ${neto_ref_500_bruto:,.2f}\n')

    rows = filas_simulacion(pb, ARQUETIPOS_DEFAULT)
    print(f'{"ID":10} {"Ticket":>10} {"Obj%":>8} {"Cr":>4} {"Bruto post.":>14} {"Neto~ post.":>14} {"% ticket":>10}')
    for r in rows:
        print(
            f'{r["id"]:10} {int(r["ticket_clp"]):>10} '
            f'{float(r["fraccion_objetivo"]) * 100:>7.2f}% {r["creditos_sugeridos"]:>4} '
            f'{int(r["clp_bruto_postulacion"]):>14,} {int(r["clp_neto_postulacion_aprox"]):>14,} '
            f'{float(r["fraccion_ticket_bruta_efectiva"]) * 100:>9.2f}%'
        )

    if args.posts_mes > 0:
        by = arquetipos_por_id()
        aid = args.arquetipo
        if aid not in by:
            print(f'\nArquetipo desconocido: {aid}')
            return
        cm = creditos_mensuales_sugeridos_plan(args.posts_mes, pb, by[aid])
        print(f'\nPlan de referencia: {args.posts_mes} postulaciones/mes × arquetipo «{aid}» → ~{cm} créditos/mes\n')


if __name__ == '__main__':
    main()
