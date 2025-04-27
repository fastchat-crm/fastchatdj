from django.db.models import Q

from autenticacion.models import Usuario
from ticket.models import EquipoAtencion, ProcesoAtencion


def generate_code_ticket(empresa):
    """
    Genera un código de ticket único basado en las dos primeras letras de la empresa,
    seguido de -2 y un contador incremental.
    """
    from unidecode import unidecode
    from django.db.models import Max
    from .models import TicketAtencion

    # Eliminar espacios y acentos de la empresa
    iniciales = unidecode(empresa.nombre.replace(" ", ""))[:2].upper()
    finales = unidecode(empresa.nombre.replace(" ", ""))[-2:].upper()

    # Obtener el contador incremental basado en los tickets existentes de la empresa
    ultimo_ticket = TicketAtencion.objects.filter(empresa=empresa, status=True).aggregate(Max('numero_ticket'))['numero_ticket__max']
    contador = (ultimo_ticket or 0) + 1

    # Formatear el código
    codigo_ticket = f"{iniciales}-{finales}-{contador:03d}"

    return codigo_ticket, contador

def get_user_attend(proceso):
    """
    Calcular a qué proceso y usuario pertenece el ticket. Si el proceso es automático,
    se asigna a un usuario aleatorio de los equipos que participan en el proceso, pero siempre y cuando
    ese usuario no tenga menos tickets asignados que los demás, es decir, asignar equitativamente los tickets
    que llegan a cada integrante de los equipos que conforman el proceso.
    """
    from django.db.models import Count
    from .models import TicketAtencion
    import random
    if not proceso.automatico:
        return None
    if proceso.automatico:
        equipos = proceso.equipos.all()
        usuarios = []

        # Obtener todos los integrantes de los equipos
        for equipo in equipos:
            usuarios.extend(equipo.integrantes.all())

        # Contar los tickets asignados a cada usuario
        usuarios_tickets = TicketAtencion.objects.filter(asignadoa__in=usuarios).values('asignadoa').annotate(
            ticket_count=Count('id')
        )

        # Crear un diccionario con los usuarios y su cantidad de tickets
        tickets_por_usuario = {usuario['asignadoa']: usuario['ticket_count'] for usuario in usuarios_tickets}

        # Agregar usuarios sin tickets al diccionario con un conteo de 0
        for usuario in usuarios:
            if usuario.id not in tickets_por_usuario:
                tickets_por_usuario[usuario.id] = 0

        # Obtener el usuario con menos tickets
        min_tickets = min(tickets_por_usuario.values())
        candidatos = [user_id for user_id, count in tickets_por_usuario.items() if count == min_tickets]

        # Seleccionar un usuario aleatorio entre los candidatos
        asignadoa = random.choice(candidatos)

        return asignadoa



def es_lider_equipo(usuario):
    return mis_equipos_lider(usuario).exists()

def mis_equipos_lider(usuario):
    return EquipoAtencion.objects.filter(lider=usuario, status=True)

def load_teams(usuario):
    mis_equipos = EquipoAtencion.objects.filter(Q(lider=usuario)|Q(integrantes=usuario), status=True).order_by('id').distinct('id')
    return mis_equipos

def load_integrantes(usuario):
    """
    Carga los integrantes de los equipos a los que pertenece el usuario.
    """
    integrantes = []  # Lista para acumular los integrantes
    equipos = mis_equipos_lider(usuario)
    for equipo in equipos:
        if not hasattr(equipo, 'integrantes'):
            continue
        integrantes.extend(equipo.integrantes.all())  # Agregar integrantes a la lista
    return list(set(integrantes))

def load_ids_empresas(usuario=None, equipos=None):
    if usuario:
        equipos = load_teams(usuario).values_list('id', flat=True)
    return ProcesoAtencion.objects.filter(equipos__id__in=equipos, status=True).order_by('id').distinct('id').values_list('empresa_id', flat=True)

def load_responsables():
    usuarios_id = EquipoAtencion.objects.filter(status=True, integrantes__isnull=False).values_list('integrantes__id', flat=True).distinct()
    return Usuario.objects.filter(id__in=usuarios_id)