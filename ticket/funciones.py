

def generate_code_ticket(empresa):
    """
    Genera un código de ticket único basado en las dos primeras letras de la empresa,
    seguido de -2 y un contador incremental.
    """
    from unidecode import unidecode
    from django.db.models import Max
    from .models import Ticket

    # Eliminar espacios y acentos de la empresa
    iniciales = unidecode(empresa.nombre.replace(" ", ""))[:2].upper()
    finales = unidecode(empresa.nombre.replace(" ", ""))[-2:].upper()

    # Obtener el contador incremental basado en los tickets existentes de la empresa
    ultimo_ticket = Ticket.objects.filter(empresa=empresa, status=True).aggregate(Max('numero_ticket'))['numero_ticket__max']
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
    from .models import Ticket
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
        usuarios_tickets = Ticket.objects.filter(asignadoa__in=usuarios).values('asignadoa').annotate(
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
