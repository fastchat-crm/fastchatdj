def create_authgroup(sender, instance, created, **kwargs):
    from seguridad.models import GroupModulo
    if not GroupModulo.objects.filter(group_id=instance.pk).exists():
        GroupModulo.objects.create(group_id=instance.pk)