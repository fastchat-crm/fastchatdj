"""
Motor tarifario del cotizador médico.

Regla de negocio (correo MGA): la prima depende EXCLUSIVAMENTE de
edad + género + rango etario + plan + variante dental, consultados desde BD.
Para grupos (titular+1, familia) la prima total = suma de primas individuales.

No hay valores fijos en código: todo sale de las tablas `Tarifa` / `RangoEtario`.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Plan, Tarifa, RangoEtario, VigenciaTarifaria


class TarifaNoEncontrada(Exception):
    """No hay tarifa parametrizada para la combinación pedida."""


def vigencia_activa(empresa) -> VigenciaTarifaria | None:
    return (
        VigenciaTarifaria.objects
        .filter(empresa=empresa, activa=True, status=True)
        .order_by('-fecha_inicio', '-id')
        .first()
    )


def rango_para_edad(empresa, edad: int) -> RangoEtario | None:
    """Devuelve el RangoEtario que contiene la edad dada para esa empresa.

    Regla: cada rango (X-Y) cubre [X, Y) — límite superior EXCLUSIVO, para que las
    fronteras (ej. 45) caigan en el tramo superior (45-50) y no solapen con (40-45).
    El último tramo (mayor edad) es inclusivo en su límite superior (ej. 70-100 cubre 100).
    """
    rangos = list(
        RangoEtario.objects.filter(empresa=empresa, status=True).order_by('edad_min')
    )
    for rango in rangos:
        if rango.edad_min <= edad < rango.edad_max:
            return rango
    # Frontera superior del último tramo (edad == edad_max del rango más alto)
    if rangos and edad == rangos[-1].edad_max:
        return rangos[-1]
    return None


@dataclass
class PrimaIndividuo:
    edad: int
    genero: str
    rango_etiqueta: str
    prima: Decimal


@dataclass
class ResultadoCotizacion:
    plan: str
    variante_dental: str
    integrantes: list = field(default_factory=list)
    prima_total: Decimal = Decimal('0.00')

    def as_dict(self) -> dict:
        return {
            'plan': self.plan,
            'variante_dental': self.variante_dental,
            'prima_total': str(self.prima_total),
            'integrantes': [
                {
                    'edad': i.edad,
                    'genero': i.genero,
                    'rango': i.rango_etiqueta,
                    'prima': str(i.prima),
                }
                for i in self.integrantes
            ],
        }


def prima_individuo(plan: Plan, edad: int, genero: str, variante_dental: str,
                    vigencia: VigenciaTarifaria) -> PrimaIndividuo:
    """Prima mensual de un individuo. Lanza TarifaNoEncontrada si no está parametrizada."""
    genero = (genero or '').upper()[:1]
    rango = rango_para_edad(plan.empresa, edad)
    if rango is None:
        raise TarifaNoEncontrada(f'No hay rango etario para edad {edad}.')
    try:
        tarifa = Tarifa.objects.get(
            plan=plan, vigencia=vigencia, rango_etario=rango,
            genero=genero, variante_dental=variante_dental, status=True,
        )
    except Tarifa.DoesNotExist:
        raise TarifaNoEncontrada(
            f'Sin tarifa para {plan.nombre_comercial} · {rango.etiqueta} · '
            f'{genero} · {variante_dental}.'
        )
    return PrimaIndividuo(
        edad=edad, genero=genero, rango_etiqueta=rango.etiqueta, prima=tarifa.prima_mensual,
    )


def cotizar(plan: Plan, integrantes: list[dict], variante_dental: str = 'basico',
            vigencia: VigenciaTarifaria | None = None) -> ResultadoCotizacion:
    """Cotiza un plan para una lista de integrantes.

    integrantes: [{'edad': int, 'genero': 'M'|'F'}, ...]
       - "Solo titular": 1 integrante.
       - "Titular + 1": 2 integrantes.
       - "Familia": N integrantes.
    """
    if vigencia is None:
        vigencia = vigencia_activa(plan.empresa)
    if vigencia is None:
        raise TarifaNoEncontrada('No hay vigencia tarifaria activa para la empresa.')

    resultado = ResultadoCotizacion(
        plan=plan.nombre_comercial, variante_dental=variante_dental,
    )
    total = Decimal('0.00')
    for integrante in integrantes:
        pi = prima_individuo(
            plan, int(integrante['edad']), integrante.get('genero', 'M'),
            variante_dental, vigencia,
        )
        resultado.integrantes.append(pi)
        total += pi.prima
    resultado.prima_total = total
    return resultado


def cotizar_todos_los_planes(empresa, integrantes: list[dict],
                             variante_dental: str = 'basico') -> list[dict]:
    """Cotiza todos los planes activos de la empresa — para las tarjetas comparativas."""
    vigencia = vigencia_activa(empresa)
    salida = []
    for plan in Plan.objects.filter(empresa=empresa, status=True).order_by('orden', 'nombre_comercial'):
        try:
            salida.append(cotizar(plan, integrantes, variante_dental, vigencia).as_dict())
        except TarifaNoEncontrada as exc:
            salida.append({'plan': plan.nombre_comercial, 'error': str(exc)})
    return salida
