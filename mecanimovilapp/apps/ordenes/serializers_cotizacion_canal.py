"""Serializers cotización canal."""
from __future__ import annotations

from rest_framework import serializers

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CotizacionCanalPlantilla
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
    MAX_ITEMS_POR_REQUEST,
)


class AlternativaRepuestoSerializer(serializers.Serializer):
    etiqueta = serializers.ChoiceField(
        choices=('economica', 'equivalente', 'premium'),
        required=False,
        default='equivalente',
    )
    nombre = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    marca_repuesto = serializers.CharField(required=False, allow_blank=True, default='')
    especificacion = serializers.CharField(required=False, allow_blank=True, default='')
    precio_clp = serializers.IntegerField(required=False, min_value=0, default=0)
    proveedor_nombre = serializers.CharField(required=False, allow_blank=True, default='')
    url_producto = serializers.CharField(required=False, allow_blank=True, default='')


class FuenteRepuestoSerializer(serializers.Serializer):
    """Trazabilidad del precio (solo app taller; nunca viaja al link público)."""

    fuente = serializers.CharField(required=False, allow_blank=True, default='')
    tienda = serializers.CharField(required=False, allow_blank=True, default='')
    dominio = serializers.CharField(required=False, allow_blank=True, default='')
    precio_clp = serializers.IntegerField(required=False, min_value=0, default=0)
    url = serializers.CharField(required=False, allow_blank=True, default='')
    nombre = serializers.CharField(required=False, allow_blank=True, default='')


class OpcionRepuestoSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, default='')
    nombre = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    marca_repuesto = serializers.CharField(required=False, allow_blank=True, default='')
    especificacion = serializers.CharField(required=False, allow_blank=True, default='')
    calidad = serializers.CharField(required=False, allow_blank=True, default='')
    precio_clp = serializers.IntegerField(required=False, min_value=0, default=0)
    precio_min_clp = serializers.IntegerField(required=False, min_value=0)
    precio_max_clp = serializers.IntegerField(required=False, min_value=0)
    fuente = serializers.CharField(required=False, allow_blank=True, default='')
    tienda = serializers.CharField(required=False, allow_blank=True, default='')
    dominio = serializers.CharField(required=False, allow_blank=True, default='')
    url = serializers.CharField(required=False, allow_blank=True, default='')
    es_proveedor_taller = serializers.BooleanField(required=False, default=False)
    proveedor_id = serializers.IntegerField(required=False, allow_null=True)
    imagen_url = serializers.CharField(required=False, allow_blank=True, default='')
    certeza = serializers.CharField(required=False, allow_blank=True, default='')
    compatibilidad = serializers.CharField(required=False, allow_blank=True, default='')
    confianza = serializers.FloatField(required=False)
    posicion_relativa = serializers.CharField(required=False, allow_blank=True, default='')


class RepuestoCotizacionSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    nombre = serializers.CharField(max_length=200)
    cantidad = serializers.IntegerField(min_value=1, default=1)
    precio_unitario_clp = serializers.IntegerField(min_value=0, default=0, allow_null=True)
    precio_referencia_ia = serializers.IntegerField(required=False, min_value=0)
    precio_iva_incluido = serializers.BooleanField(required=False, default=True)
    fuente_marketplace = serializers.CharField(required=False, allow_blank=True, default='')
    fuente_repuesto = serializers.CharField(required=False, allow_blank=True, default='')
    marca_repuesto = serializers.CharField(required=False, allow_blank=True, default='')
    tienda_ml = serializers.CharField(required=False, allow_blank=True, default='')
    proveedor_nombre = serializers.CharField(required=False, allow_blank=True, default='')
    url_producto = serializers.CharField(required=False, allow_blank=True, default='')
    url_referencia = serializers.CharField(required=False, allow_blank=True, default='')
    tienda_referencia = serializers.CharField(required=False, allow_blank=True, default='')
    precio_verificado_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    casa_sugerida = serializers.CharField(required=False, allow_blank=True, default='')
    precio_verificado_en_casa = serializers.BooleanField(required=False, default=False)
    nota_referencia = serializers.CharField(required=False, allow_blank=True, default='')
    costo_unitario_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    costo_estimado_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    costo_registrado_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    costo_origen = serializers.CharField(required=False, allow_blank=True, default='')
    precio_cobrado_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    margen_clp = serializers.IntegerField(required=False, allow_null=True)
    margen_pct = serializers.FloatField(required=False, allow_null=True)
    validacion_estado = serializers.CharField(required=False, allow_blank=True, default='')
    validacion_motivo = serializers.CharField(required=False, allow_blank=True, default='')
    alertas = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    nombre_producto = serializers.CharField(required=False, allow_blank=True, default='')
    precio_estimado = serializers.BooleanField(required=False, default=True)
    precio_referencia_mercado = serializers.BooleanField(required=False, default=False)
    comentario = serializers.CharField(required=False, allow_blank=True, default='')
    # Campos de selección inteligente de casa (PR #7)
    casa_repuesto_nombre = serializers.CharField(required=False, allow_blank=True, default='')
    motivo_seleccion = serializers.CharField(required=False, allow_blank=True, default='')
    alternativas_descartadas = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )
    consolidacion_aplicada = serializers.BooleanField(required=False, default=False)
    precio_a_consultar = serializers.BooleanField(required=False, default=False)
    casa_sucursal = serializers.CharField(required=False, allow_blank=True, default='')
    casa_telefono = serializers.CharField(required=False, allow_blank=True, default='')
    referencia_tienda = serializers.CharField(required=False, allow_blank=True, default='')
    precio_referencia_clp = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    certeza = serializers.ChoiceField(
        choices=('confirmado', 'asumido', 'referencial', 'sin_precio'),
        required=False,
        allow_blank=True,
        default='',
    )
    precio_min_clp = serializers.IntegerField(required=False, min_value=0)
    precio_max_clp = serializers.IntegerField(required=False, min_value=0)
    fuentes_n = serializers.IntegerField(required=False, min_value=0)
    precio_capturado_en = serializers.CharField(required=False, allow_blank=True, default='')
    proveedor_id = serializers.IntegerField(required=False, allow_null=True)
    precio_marketplace_clp = serializers.IntegerField(required=False, min_value=0)
    factor_mercado = serializers.FloatField(required=False)
    categoria = serializers.CharField(required=False, allow_blank=True, default='')
    especificacion = serializers.CharField(required=False, allow_blank=True, default='')
    especificacion_pendiente = serializers.BooleanField(required=False, default=False)
    familia_sensible = serializers.CharField(required=False, allow_blank=True, default='')
    codigo_parte = serializers.CharField(required=False, allow_blank=True, default='')
    compatibilidad = serializers.CharField(required=False, allow_blank=True, default='')
    motivo_sin_precio = serializers.CharField(required=False, allow_blank=True, default='')
    alternativas = AlternativaRepuestoSerializer(many=True, required=False)
    fuentes_detalle = FuenteRepuestoSerializer(many=True, required=False)
    calidad = serializers.CharField(required=False, allow_blank=True, default='')
    calidad_pendiente = serializers.BooleanField(required=False, default=False)
    pais_origen = serializers.CharField(required=False, allow_blank=True, default='', max_length=40)
    seleccion_cliente = serializers.BooleanField(required=False, default=False)
    seleccion_cliente_en = serializers.CharField(required=False, allow_blank=True, default='')
    imagen_url = serializers.CharField(required=False, allow_blank=True, default='')
    opciones = OpcionRepuestoSerializer(many=True, required=False)
    
    # NUEVOS CAMPOS: Selección inteligente de casas de repuestos
    casa_repuesto_nombre = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Nombre de la casa de repuestos elegida'
    )
    motivo_seleccion = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Explicación de por qué se eligió esta casa'
    )
    alternativas_descartadas = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Otras opciones consideradas y razón de descarte'
    )
    consolidacion_aplicada = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Si este repuesto fue consolidado con otros en la misma casa'
    )


def _monto_guardado(valor):
    if valor is None or valor == '':
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def _costo_guardado_linea(rep: dict) -> dict:
    """Costo que el taller ya persistió, antes de que la validación de ficha lo pise."""
    return {
        'costo_registrado_clp': _monto_guardado(rep.get('costo_registrado_clp')),
        'costo_estimado_clp': _monto_guardado(rep.get('costo_estimado_clp')),
        'costo_unitario_clp': _monto_guardado(rep.get('costo_unitario_clp')),
        'costo_origen': str(rep.get('costo_origen') or ''),
    }


def _restaurar_costo_taller(rep: dict, guardado: dict) -> None:
    """La validación de ficha copia el precio cobrado al costo cuando no hay tienda.

    Si la línea no traía costo, ese valor no es un costo. Si lo traía, se conserva.
    """
    tiene = any(guardado.get(clave) for clave in (
        'costo_registrado_clp', 'costo_estimado_clp', 'costo_unitario_clp',
    ))
    if not tiene:
        if not rep.get('precio_verificado_clp'):
            rep['costo_unitario_clp'] = None
        return
    for clave in ('costo_registrado_clp', 'costo_estimado_clp', 'costo_unitario_clp'):
        if guardado.get(clave):
            rep[clave] = guardado[clave]
    if guardado.get('costo_origen'):
        rep['costo_origen'] = guardado['costo_origen']


class CotizacionCanalSerializer(serializers.ModelSerializer):
    repuestos = RepuestoCotizacionSerializer(many=True, required=False)
    share_url = serializers.SerializerMethodField()
    canal = serializers.SerializerMethodField()
    cliente_display = serializers.SerializerMethodField()
    cita_personal_id = serializers.SerializerMethodField()
    cita_ultima_id = serializers.SerializerMethodField()
    cita_ultima_estado = serializers.SerializerMethodField()
    listo_para_enviar = serializers.SerializerMethodField()
    pendientes_revision = serializers.SerializerMethodField()
    cotizacion_original_id = serializers.IntegerField(read_only=True, allow_null=True)
    cita_origen_id = serializers.IntegerField(read_only=True, allow_null=True)
    tiene_horario_agendado = serializers.SerializerMethodField()
    fecha_agendada = serializers.SerializerMethodField()
    hora_agendada = serializers.SerializerMethodField()
    permite_edicion_completa = serializers.SerializerMethodField()
    descuento_etiqueta = serializers.SerializerMethodField()
    servicio_principal_nombre = serializers.SerializerMethodField()
    mano_obra_lineas = serializers.SerializerMethodField()
    entrega_via = serializers.SerializerMethodField()
    entrega_pendiente_compartir = serializers.SerializerMethodField()
    emision_pendiente = serializers.SerializerMethodField()
    tipo_documento = serializers.SerializerMethodField()
    tipo_documento_emitido = serializers.SerializerMethodField()
    repuestos_confirmados = serializers.SerializerMethodField()
    repuestos_total = serializers.SerializerMethodField()
    puede_enviar_firme = serializers.SerializerMethodField()
    lineas_pendientes_precio = serializers.SerializerMethodField()
    total_min_clp = serializers.SerializerMethodField()
    total_max_clp = serializers.SerializerMethodField()
    ejecucion_adicional = serializers.CharField(read_only=True)
    fecha_propuesta = serializers.DateField(read_only=True, allow_null=True)
    hora_propuesta = serializers.TimeField(read_only=True, allow_null=True, format='%H:%M')

    def _metadata_agente(self, obj) -> dict:
        meta = obj.metadata if isinstance(getattr(obj, 'metadata', None), dict) else {}
        return meta

    def get_listo_para_enviar(self, obj) -> bool:
        return bool(self._metadata_agente(obj).get('listo_para_enviar'))

    def get_pendientes_revision(self, obj) -> list[str]:
        raw = self._metadata_agente(obj).get('pendientes_revision') or []
        return [str(p) for p in raw if p]

    def get_share_url(self, obj) -> str | None:
        if obj.url_publica:
            return obj.url_publica
        if obj.token:
            from mecanimovilapp.apps.ordenes.services.cotizacion_publica import construir_url_publica_cotizacion
            return construir_url_publica_cotizacion(obj.token)
        return None

    def get_canal(self, obj) -> str:
        if obj.es_libre or obj.conversation_id is None:
            return 'directo'
        channel = (getattr(obj.conversation, 'source_channel', None) or 'APP').lower()
        if channel in ('whatsapp', 'instagram', 'messenger'):
            return channel
        return 'canal'

    def get_cliente_display(self, obj) -> str:
        if (obj.cliente_nombre or '').strip():
            return obj.cliente_nombre.strip()
        conv = obj.conversation
        if conv is not None:
            ext = getattr(conv, 'external_contact', None)
            name = getattr(ext, 'display_name', None) if ext else None
            if name:
                return str(name)
        parts = [obj.vehiculo_marca, obj.vehiculo_modelo]
        joined = ' '.join(p for p in parts if p).strip()
        return joined or 'Cliente'

    def _cita_activa(self, obj):
        if obj.es_cotizacion_adicional and obj.cita_origen_id:
            return None
        cache = self.context.setdefault('_cita_obj_by_cotizacion', {})
        if obj.pk in cache:
            return cache[obj.pk]
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import cita_activa_de_cotizacion
        cita = cita_activa_de_cotizacion(obj)
        cache[obj.pk] = cita
        return cita

    def get_cita_personal_id(self, obj) -> int | None:
        if obj.es_cotizacion_adicional and obj.cita_origen_id:
            return obj.cita_origen_id
        cita = self._cita_activa(obj)
        return getattr(cita, 'id', None) if cita is not None else None

    def _cita_cerrada(self, obj):
        """Última visita ya entregada, cuando ya no queda una cita activa."""
        if obj.es_cotizacion_adicional and obj.cita_origen_id:
            return None
        if self._cita_activa(obj) is not None:
            return None
        cache = self.context.setdefault('_cita_cerrada_by_cotizacion', {})
        if obj.pk in cache:
            return cache[obj.pk]
        cita = (
            obj.citas_generadas.filter(estado='cerrada')
            .order_by('-cerrada_en', '-fecha_creacion')
            .first()
        )
        cache[obj.pk] = cita
        return cita

    def get_cita_ultima_id(self, obj) -> int | None:
        activa = self._cita_activa(obj)
        if activa is not None:
            return getattr(activa, 'id', None)
        cerrada = self._cita_cerrada(obj)
        return getattr(cerrada, 'id', None) if cerrada is not None else None

    def get_cita_ultima_estado(self, obj) -> str:
        if self._cita_activa(obj) is not None:
            return 'activa'
        if self._cita_cerrada(obj) is not None:
            return 'cerrada'
        return ''

    def get_tiene_horario_agendado(self, obj) -> bool:
        cita = self._cita_activa(obj)
        if cita is None:
            return False
        if getattr(cita, 'horario_por_confirmar', False):
            return False
        return bool(getattr(cita, 'fecha_servicio', None) and getattr(cita, 'hora_servicio', None))

    def get_fecha_agendada(self, obj) -> str:
        cita = self._cita_activa(obj)
        if cita is None or getattr(cita, 'horario_por_confirmar', False) or not cita.fecha_servicio:
            return ''
        return cita.fecha_servicio.isoformat()

    def get_hora_agendada(self, obj) -> str:
        cita = self._cita_activa(obj)
        if cita is None or getattr(cita, 'horario_por_confirmar', False) or not cita.hora_servicio:
            return ''
        return cita.hora_servicio.strftime('%H:%M')

    def get_permite_edicion_completa(self, obj) -> bool:
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            cotizacion_permite_edicion_completa,
        )
        return cotizacion_permite_edicion_completa(obj)

    def get_descuento_etiqueta(self, obj) -> str:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            etiqueta_descuento,
        )
        return etiqueta_descuento(
            descuento_tipo=obj.descuento_tipo or '',
            descuento_alcance=obj.descuento_alcance or 'mano_obra',
            descuento_valor=obj.descuento_valor or 0,
            descuento_clp=int(obj.descuento_clp or 0),
        )

    def get_mano_obra_lineas(self, obj) -> list[dict]:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            resolver_mano_obra_lineas,
        )
        return resolver_mano_obra_lineas(obj)

    def get_entrega_via(self, obj) -> str | None:
        via = str(self._metadata_agente(obj).get('entrega_canal') or '').strip()
        if via:
            return via
        if obj.estado in ('enviada', 'aceptada', 'rechazada', 'expirada') and (
            obj.es_libre or obj.conversation_id is None
        ):
            return 'link_publico'
        return None

    def get_entrega_pendiente_compartir(self, obj) -> bool:
        if obj.estado != 'enviada' or obj.visto_en:
            return False
        via = self.get_entrega_via(obj)
        return via in ('link_publico', 'whatsapp_template')

    def get_emision_pendiente(self, obj) -> bool:
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import emision_pendiente
        return emision_pendiente(obj)

    def get_tipo_documento(self, obj) -> str:
        val = str(getattr(obj, 'tipo_documento', '') or '').strip()
        if val in ('estimacion', 'cotizacion'):
            return val
        return 'estimacion' if obj.estado == 'borrador' else 'cotizacion'

    def get_tipo_documento_emitido(self, obj) -> str:
        return str(getattr(obj, 'tipo_documento_emitido', '') or '').strip()

    def _repuestos_list(self, obj) -> list:
        raw = obj.repuestos if isinstance(getattr(obj, 'repuestos', None), list) else []
        return [r for r in raw if isinstance(r, dict)]

    def get_repuestos_total(self, obj) -> int:
        return len(self._repuestos_list(obj))

    def get_repuestos_confirmados(self, obj) -> int:
        return sum(
            1
            for r in self._repuestos_list(obj)
            if str(r.get('certeza') or '') in ('confirmado', 'asumido')
        )

    def get_lineas_pendientes_precio(self, obj) -> list[dict]:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
            CERTEZA_ASUMIDO,
            CERTEZA_CONFIRMADO,
            backfill_certeza,
        )

        out: list[dict] = []
        for r in self._repuestos_list(obj):
            certeza = backfill_certeza(r)
            if certeza in (CERTEZA_CONFIRMADO, CERTEZA_ASUMIDO):
                continue
            out.append({
                'id': str(r.get('id') or ''),
                'nombre': str(r.get('nombre') or ''),
                'certeza': certeza,
                'especificacion_pendiente': bool(r.get('especificacion_pendiente')),
            })
        return out

    def get_puede_enviar_firme(self, obj) -> bool:
        return not self.get_lineas_pendientes_precio(obj)

    def get_total_min_clp(self, obj) -> int:
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            _banda_totales_publica,
        )

        return _banda_totales_publica(obj)[0]

    def get_total_max_clp(self, obj) -> int:
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            _banda_totales_publica,
        )

        return _banda_totales_publica(obj)[1]

    def get_servicio_principal_nombre(self, obj) -> str | None:
        if not obj.es_cotizacion_adicional:
            return None
        orig = obj.cotizacion_original
        if orig is not None and (orig.servicio_nombre or '').strip():
            return orig.servicio_nombre.strip()
        cita = obj.cita_origen
        det = getattr(cita, 'detalle', None) if cita is not None else None
        if det is not None and (det.servicio_nombre or '').strip():
            return det.servicio_nombre.strip()
        return None

    def update(self, instance, validated_data):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            congelar_costo,
        )

        nuevos = validated_data.get('repuestos')
        if isinstance(nuevos, list):
            previos = {
                str(rep.get('id') or ''): rep
                for rep in (instance.repuestos or [])
                if isinstance(rep, dict) and rep.get('id')
            }
            for rep in nuevos:
                if not isinstance(rep, dict):
                    continue
                if rep.get('costo_unitario_clp'):
                    continue
                previo = previos.get(str(rep.get('id') or ''))
                if previo:
                    congelar_costo(previo)
                    if previo.get('costo_unitario_clp'):
                        rep['costo_unitario_clp'] = previo['costo_unitario_clp']
                else:
                    congelar_costo(rep)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key in ('mano_obra_clp', 'costo_repuestos_clp', 'total_clp', 'descuento_clp'):
            if data.get(key) is not None:
                data[key] = int(data[key])
        if data.get('descuento_valor') is not None:
            try:
                val = float(data['descuento_valor'])
            except (TypeError, ValueError):
                val = 0.0
            data['descuento_valor'] = int(val) if val == int(val) else val
        for key in ('total_min_clp', 'total_max_clp'):
            if data.get(key) is not None:
                data[key] = int(data[key])
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
            contexto_nota_cotizacion,
            economia_cotizacion,
            economia_repuesto,
            sanear_notas_linea,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.validar_linea_cotizacion import (
            validar_repuesto,
        )

        nota_kw = contexto_nota_cotizacion(instance)
        saneados = []
        for rep in data.get('repuestos') or []:
            if not isinstance(rep, dict):
                saneados.append(rep)
                continue
            costo_guardado = _costo_guardado_linea(rep)
            rep = sanear_notas_linea(rep, **nota_kw)
            rep.update(validar_repuesto(rep, **{
                'marca': nota_kw.get('marca') or '',
                'modelo': nota_kw.get('modelo') or '',
                'anio': nota_kw.get('anio'),
                'tipo_motor': nota_kw.get('tipo_motor') or '',
                'cilindraje': nota_kw.get('cilindraje') or '',
            }))
            _restaurar_costo_taller(rep, costo_guardado)
            rep.update(economia_repuesto(rep))
            saneados.append(rep)
            if rep.get('precio_unitario_clp') is not None:
                rep['precio_unitario_clp'] = int(rep['precio_unitario_clp'])
            ref = rep.get('precio_referencia_ia')
            if ref is not None:
                rep['precio_referencia_ia'] = int(ref)
            for extra in ('precio_min_clp', 'precio_max_clp', 'precio_marketplace_clp', 'fuentes_n'):
                if rep.get(extra) is not None:
                    try:
                        rep[extra] = int(rep[extra])
                    except (TypeError, ValueError):
                        pass
        data['repuestos'] = saneados
        data.update(economia_cotizacion(saneados))
        data['alertas_validacion'] = [
            {
                'repuesto': rep.get('nombre') or '',
                'estado': rep.get('validacion_estado') or '',
                'motivo': rep.get('validacion_motivo') or '',
                'alertas': list(rep.get('alertas') or []),
            }
            for rep in saneados
            if isinstance(rep, dict) and (
                (rep.get('validacion_estado') or 'ok') != 'ok' or rep.get('alertas')
            )
        ]
        for lin in data.get('mano_obra_lineas') or []:
            if isinstance(lin, dict) and lin.get('monto_clp') is not None:
                lin['monto_clp'] = int(lin['monto_clp'] or 0)
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            etiqueta_descuento,
            resolver_obligacion_cotizacion,
            totales_desde_lineas_respuesta,
        )

        canon = totales_desde_lineas_respuesta(
            data.get('repuestos') or [],
            data.get('mano_obra_lineas') or [],
            descuento_tipo=data.get('descuento_tipo') or '',
            descuento_alcance=data.get('descuento_alcance') or 'mano_obra',
            descuento_valor=data.get('descuento_valor') or 0,
            total_persistido=data.get('total_clp'),
        )
        data.update(canon)
        data['descuento_etiqueta'] = etiqueta_descuento(
            descuento_tipo=data.get('descuento_tipo') or '',
            descuento_alcance=data.get('descuento_alcance') or 'mano_obra',
            descuento_valor=data.get('descuento_valor') or 0,
            descuento_clp=int(canon.get('descuento_clp') or 0),
        )
        obligacion = resolver_obligacion_cotizacion(instance)
        data['obligacion_clp'] = obligacion['obligacion_clp']
        data['obligacion_conocida'] = obligacion['obligacion_conocida']
        data['obligacion_fuente'] = obligacion['obligacion_fuente']
        data['obligacion_faltantes'] = obligacion['obligacion_faltantes']
        return data

    class Meta:
        model = CotizacionCanal
        fields = (
            'id',
            'conversation',
            'es_libre',
            'cliente_nombre',
            'cliente_telefono',
            'cliente_display',
            'canal',
            'cita_personal_id',
            'cita_ultima_id',
            'cita_ultima_estado',
            'cita_origen_id',
            'tiene_horario_agendado',
            'fecha_agendada',
            'hora_agendada',
            'permite_edicion_completa',
            'token',
            'numero_publico',
            'url_publica',
            'share_url',
            'visto_en',
            'estado',
            'modalidad',
            'direccion_servicio',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_anio',
            'vehiculo_patente',
            'vehiculo_cilindraje',
            'vehiculo_vin',
            'tipo_motor',
            'tipo_motor_label',
            'aviso_motor',
            'servicio_nombre',
            'descripcion_problema',
            'repuestos',
            'mano_obra_lineas',
            'mano_obra_clp',
            'tipo_documento',
            'tipo_documento_emitido',
            'repuestos_confirmados',
            'repuestos_total',
            'puede_enviar_firme',
            'lineas_pendientes_precio',
            'total_min_clp',
            'total_max_clp',
            'entrega_via',
            'entrega_pendiente_compartir',
            'emision_pendiente',
            'costo_repuestos_clp',
            'descuento_tipo',
            'descuento_alcance',
            'descuento_valor',
            'descuento_clp',
            'descuento_etiqueta',
            'total_clp',
            'duracion_minutos_estimada',
            'advertencias',
            'notas_internas',
            'politicas_cotizacion',
            'dias_validez',
            'fecha_expiracion_publica',
            'metadata',
            'listo_para_enviar',
            'pendientes_revision',
            'cotizacion_original_id',
            'es_cotizacion_adicional',
            'motivo_servicio_adicional',
            'servicio_principal_nombre',
            'ejecucion_adicional',
            'fecha_propuesta',
            'hora_propuesta',
            'message_envio',
            'enviada_en',
            'aceptada_en',
            'rechazada_en',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = (
            'id',
            'conversation',
            'es_libre',
            'cliente_display',
            'canal',
            'cita_personal_id',
            'cita_ultima_id',
            'cita_ultima_estado',
            'cita_origen_id',
            'tiene_horario_agendado',
            'fecha_agendada',
            'hora_agendada',
            'permite_edicion_completa',
            'mano_obra_lineas',
            'tipo_documento',
            'tipo_documento_emitido',
            'repuestos_confirmados',
            'repuestos_total',
            'puede_enviar_firme',
            'lineas_pendientes_precio',
            'total_min_clp',
            'total_max_clp',
            'entrega_via',
            'entrega_pendiente_compartir',
            'emision_pendiente',
            'token',
            'numero_publico',
            'url_publica',
            'share_url',
            'visto_en',
            'fecha_expiracion_publica',
            'estado',
            'listo_para_enviar',
            'pendientes_revision',
            'cotizacion_original_id',
            'es_cotizacion_adicional',
            'motivo_servicio_adicional',
            'servicio_principal_nombre',
            'ejecucion_adicional',
            'fecha_propuesta',
            'hora_propuesta',
            'costo_repuestos_clp',
            'descuento_clp',
            'descuento_etiqueta',
            'total_clp',
            'message_envio',
            'enviada_en',
            'aceptada_en',
            'rechazada_en',
            'creado_en',
            'actualizado_en',
        )


class GenerarCotizacionIaSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    cliente_nombre = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    cliente_telefono = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    servicio_nombre = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    descripcion_problema = serializers.CharField(required=False, allow_blank=True, default='')
    modalidad = serializers.ChoiceField(choices=('taller', 'domicilio'), default='taller')
    direccion_servicio = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
    )
    vehiculo = serializers.DictField(required=False, default=dict)
    plantilla_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        conversation_id = attrs.get('conversation_id')
        if conversation_id is None:
            nombre = (attrs.get('cliente_nombre') or '').strip()
            if not nombre:
                raise serializers.ValidationError(
                    {'cliente_nombre': 'Indica el nombre del cliente para cotización libre.'},
                )
        if attrs.get('modalidad') == 'domicilio' and not (attrs.get('direccion_servicio') or '').strip():
            raise serializers.ValidationError(
                {'direccion_servicio': 'Indica la dirección para servicio a domicilio.'},
            )
        if attrs.get('plantilla_id'):
            return attrs
        if not (attrs.get('servicio_nombre') or '').strip():
            raise serializers.ValidationError(
                {'servicio_nombre': 'Indica el servicio a cotizar.'},
            )
        v = attrs.get('vehiculo') or {}
        marca = str(v.get('marca') or '').strip()
        modelo = str(v.get('modelo') or '').strip()
        patente = str(v.get('patente') or '').strip()
        if not marca and not modelo and not patente:
            raise serializers.ValidationError(
                {'vehiculo': 'Indica patente o marca y modelo del vehículo.'},
            )
        if (not marca or not modelo) and not patente:
            raise serializers.ValidationError(
                {'vehiculo': 'Marca y modelo son necesarios para estimar repuestos.'},
            )
        return attrs


class ServicioCatalogoAdicionalSerializer(serializers.Serializer):
    oferta_servicio_id = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1, default=1, required=False)


class CrearCotizacionAdicionalSerializer(serializers.Serializer):
    cita_id = serializers.IntegerField(min_value=1)
    cotizacion_original_id = serializers.IntegerField(min_value=1)
    motivo_servicio_adicional = serializers.CharField(max_length=2000)
    modo = serializers.ChoiceField(choices=('catalogo', 'ia'), default='catalogo')
    servicios_catalogo = ServicioCatalogoAdicionalSerializer(many=True, required=False)
    servicio_nombre = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    descripcion_problema = serializers.CharField(required=False, allow_blank=True, default='')
    ejecucion_adicional = serializers.ChoiceField(
        choices=('misma_visita', 'nueva_fecha'),
        required=False,
        default='misma_visita',
    )
    fecha_propuesta = serializers.DateField(required=False, allow_null=True)
    hora_propuesta = serializers.TimeField(required=False, allow_null=True)

    def validate(self, attrs):
        modo = attrs.get('modo') or 'catalogo'
        motivo = (attrs.get('motivo_servicio_adicional') or '').strip()
        if not motivo:
            raise serializers.ValidationError(
                {'motivo_servicio_adicional': 'Indica el motivo del servicio adicional.'},
            )
        if modo == 'catalogo':
            servicios = attrs.get('servicios_catalogo') or []
            if not servicios:
                raise serializers.ValidationError(
                    {'servicios_catalogo': 'Selecciona al menos un servicio del catálogo.'},
                )
        else:
            if not (attrs.get('servicio_nombre') or '').strip():
                raise serializers.ValidationError(
                    {'servicio_nombre': 'Indica el servicio a cotizar con IA.'},
                )
        return attrs


class CotizacionCanalPlantillaSerializer(serializers.ModelSerializer):
    vehiculo_marca = serializers.SerializerMethodField()
    vehiculo_modelo = serializers.SerializerMethodField()
    vehiculo_cilindraje = serializers.SerializerMethodField()
    aprendizaje_auto = serializers.SerializerMethodField()
    servicio_nombre = serializers.SerializerMethodField()

    class Meta:
        model = CotizacionCanalPlantilla
        fields = (
            'id',
            'titulo',
            'snapshot',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_cilindraje',
            'aprendizaje_auto',
            'servicio_nombre',
            'uso_count',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = ('id', 'uso_count', 'creado_en', 'actualizado_en')

    def _snap(self, obj) -> dict:
        return obj.snapshot or {}

    def get_vehiculo_marca(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_marca') or '')

    def get_vehiculo_modelo(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_modelo') or '')

    def get_vehiculo_cilindraje(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_cilindraje') or '')

    def get_aprendizaje_auto(self, obj) -> bool:
        snap = self._snap(obj)
        return bool(snap.get('aprendizaje_auto')) or (obj.titulo or '').startswith('Auto:')

    def get_servicio_nombre(self, obj) -> str:
        snap = self._snap(obj)
        serv = str(snap.get('servicio_nombre') or '').strip()
        if serv:
            return serv
        titulo = obj.titulo or ''
        if titulo.startswith('Auto:') and '—' in titulo:
            return titulo.split('—', 1)[1].strip()
        return titulo


class GuardarPlantillaCotizacionSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=255)
    cotizacion_id = serializers.IntegerField(required=False, allow_null=True)
    snapshot = serializers.DictField(required=False)


class CotizarItemsIaSerializer(serializers.Serializer):
    """Ítems a agregar y cotizar con IA sobre un borrador existente."""

    nombres = serializers.ListField(
        child=serializers.CharField(max_length=200, allow_blank=False),
        required=False,
        allow_empty=True,
        max_length=MAX_ITEMS_POR_REQUEST,
    )
    repuestos = RepuestoCotizacionSerializer(many=True, required=False)
    repuesto_ids = serializers.ListField(
        child=serializers.CharField(max_length=64, allow_blank=False),
        required=False,
        allow_empty=True,
        max_length=MAX_ITEMS_POR_REQUEST,
    )

    def validate_nombres(self, value):
        limpios = []
        for raw in value or []:
            nombre = ' '.join(str(raw or '').split()).strip()
            if nombre:
                limpios.append(nombre[:200])
        return limpios[:MAX_ITEMS_POR_REQUEST]
