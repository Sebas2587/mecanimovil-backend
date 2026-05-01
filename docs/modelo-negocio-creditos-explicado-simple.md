# Créditos y planes en MecaniMovil (explicación simple)

Este texto es solo para entender el negocio. No hace falta saber de programación.

> Para una guía aún más accesible (postulación, arquetipos, porcentajes, Mercado Pago), ver [modelo-negocio-creditos-para-todos.md](modelo-negocio-creditos-para-todos.md).

## ¿Qué es un crédito?

Un **crédito** es como una moneda interna del taller. Cuando querés **postularte** a un trabajo que publicó un cliente, el sistema te pide **gastar algunos créditos**. Así nos aseguramos de que solo se postulen talleres que de verdad quieren ese trabajo.

Cada tipo de servicio puede costar **más o menos créditos**. Un lavado no es lo mismo que un mantenimiento grande: el que es más “caro” en valor suele pedir más créditos.

## Dos maneras de tener créditos

1. **Suscripción (plan mensual)**  
   Pagás una mensualidad y cada mes recibís una cantidad de créditos **mientras el pago esté bien** (Mercado Pago nos confirma el cobro). Es la forma más barata **por cada crédito**, si aprovechás el plan.

2. **Comprar créditos sueltos (recarga / top-up)**  
   Elegís cuántos créditos querés y pagás **precio por crédito**. Sirve cuando te faltan pocos o no querés plan. Ese precio por crédito suele ser **más alto** que el que “sale” dentro de un plan, porque el plan te da muchos créditos juntos.

## Los planes (idea general)

Tenemos **tres planes** con distinto precio mensual y distinta cantidad de créditos. El plan más caro trae **más créditos** al mes. En la app podés ver **cuánto te sale más o menos cada crédito** dentro de cada plan y compararlo con el precio de la recarga suelta.

Los números de “**cuántos trabajos al mes**” que ves en la app son **aproximados**: depende de cuántos créditos gasta cada trabajo (unos gastan 5, otros 7, otros 10, etc.). Sirven para orientarte, no como promesa exacta.

## Acumulación de créditos (fase 1)

Hoy, los créditos que te llegan **por la suscripción** se van sumando a tu saldo **mientras sigas pagando** y mientras no venza la regla de tiempo que tengamos para los créditos. En una fase siguiente podríamos poner un **tope máximo** de acumulación para evitar saldos enormes sin uso; si eso pasa, lo avisaremos con tiempo.

## Mercado Pago

Los pagos de **plan** y de **compra de créditos** pasan por **Mercado Pago**. Nosotros **no guardamos** la tarjeta del taller en nuestro servidor de la misma forma que MP: el cobro lo autoriza el proveedor en la app de Mercado Pago.

Si cambiamos precios o cantidades de créditos en los planes, **no borramos** los vínculos viejos de Mercado Pago en la base de datos: se actualizan los datos del plan **con cuidado** para que las suscripciones que ya existen sigan entendiendo a qué plan pertenecen.

## Resumen en una frase

**Los créditos son lo que gastás para postularte; el plan mensual suele ser la forma más conveniente por crédito; la recarga suelta es más flexible pero más cara por crédito; todo pago va por Mercado Pago.**
