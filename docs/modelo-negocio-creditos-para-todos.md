# Cómo funciona MecaniMóvil: créditos, planes y pagos (versión simple)

Este texto es para **cualquier persona** que quiera entender el negocio sin saber de programación ni de contabilidad avanzada.

---

## ¿Qué es un crédito?

Un **crédito** es una unidad que usa el **taller o mecánico** cuando quiere **postularse** a un trabajo que publicó un cliente. No es plata que el cliente paga al taller por el arreglo: es lo que el taller “gasta” en la plataforma para **competir por esa oportunidad**.

- Si no tiene créditos, no puede postular (según las reglas de la app).
- Si tiene créditos, puede postular mientras le alcance el saldo.

---

## ¿De dónde salen los créditos?

Hay **dos maneras** principales:

1. **Plan mensual (suscripción)**  
   El taller paga una **mensualidad** y recibe una cantidad de créditos **cada mes**, cuando el pago queda bien confirmado (Mercado Pago).

2. **Comprar créditos sueltos (Tienda)**  
   El taller compra la cantidad que necesita y paga **por cada crédito**. Suele ser un poco **más caro por crédito** que meterlos en un plan, porque el plan trae muchos créditos juntos.

---

## ¿Qué tiene que ver el “valor de un servicio en el mercado”?

En la vida real, un trabajo puede valer **muy distinto** según el tipo de servicio (un diagnóstico liviano no es lo mismo que un trabajo grande).

Por eso usamos **arquetipos**: ejemplos de “cuánto podría valer” un tipo de trabajo en el mercado (en pesos chilenos). Sobre ese número definimos una **fracción pequeña** (un porcentaje) que representa **cuánto queremos que “pese” en créditos el hecho de postular** a ese tipo de trabajo.

- No es “nos llevamos ese porcentaje de la factura del taller”.
- Sí es: “que **postular** a un trabajo de ese tamaño tenga un costo en créditos **proporcional** a ese ticket de referencia”.

Los servicios reales del sistema se agrupan en **niveles** (liviano, medio, alto, premium) y cada nivel tiene una referencia de ticket y un porcentaje ajustado.

---

## ¿Cómo se consumen los créditos?

Cuando el taller **postula** a un trabajo, el sistema **descuenta** una cantidad de créditos según el **tipo de servicio** de esa publicación.

- Un servicio “liviano” suele gastar **menos** créditos por postulación.
- Un servicio “más caro o complejo” suele gastar **más** créditos por postulación.

Así evitamos que postular a trabajos de alto valor cueste lo mismo que postular a algo muy chico.

---

## ¿Qué es Mercado Pago y qué son los “impuestos” de MP?

Los pagos (plan o compra de créditos) pasan por **Mercado Pago**. MP cobra una **comisión** sobre el cobro y además puede haber **IVA** asociado a esa comisión (según las reglas vigentes).

Eso significa que, si nosotros queremos que **en la cuenta quede una cantidad “neta”** clara después de MP, el precio que mostramos al usuario tiene que ser un poco **más alto (bruto)**, para que al descontar MP quede cerca del **neto** que buscamos.

En el sistema técnico eso está en el módulo `mercado_pago_pricing` y en los scripts que actualizan precios.

---

## ¿Qué son los planes de suscripción en una frase?

Son **paquetes mensuales**: pagás una cuota y recibís muchos créditos juntos. Sirve para talleres que postulan seguido y quieren pagar **menos por crédito** que comprando de a poco.

Los montos del plan también se plantean en **neto deseado** y se guardan en sistema como **bruto** para MP, igual que con los créditos sueltos.

---

## Resumen en pocas líneas

- **Crédito** = permiso para **postular** (competir por un trabajo).
- **Más servicio “grande”** → normalmente **más créditos** por postulación.
- **Plan** = muchos créditos al mes, suele convenir si postulás mucho.
- **Tienda** = comprás pocos créditos cuando te faltan.
- **Mercado Pago** cobra comisión + IVA sobre comisión → los precios públicos son **brutos** para que el **neto** quede alineado con lo que queremos.

Si necesitás cambiar el negocio (porcentajes, tickets de referencia o cuántos créditos trae un plan), lo hacemos ajustando los **arquetipos**, el **objetivo neto por crédito** y los **planes** en el script de actualización y volviendo a ejecutarlo en el servidor, con cuidado de alinear también lo que haya en Mercado Pago para suscripciones recurrentes.
