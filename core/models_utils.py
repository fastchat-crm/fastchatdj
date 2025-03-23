import datetime
import os
import unicodedata
from django.core.files.storage import default_storage
from django.utils.deconstruct import deconstructible
from django.utils.encoding import force_str


@deconstructible
class UserUploadToPath(object):
    """
    Funciona sólo si el modelo tiene un campo user (ForeignKey de auth.User)
    """
    def __init__(self, upload_to, funcUser=None):
        self.upload_to = upload_to
        self.funcUser = funcUser

    def __call__(self, instance, filename):
        return self.generate_filename(instance, filename)

    def get_directory_name(self):
        return os.path.normpath(force_str(datetime.datetime.now().strftime(force_str(self.upload_to))))

    def get_filename(self, filename):
        from django.utils.text import slugify
        filename = default_storage.get_valid_name(os.path.basename(filename))
        filename = force_str(filename)
        filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
        extension = os.path.splitext(filename)[1][1:]
        file_name = os.path.splitext(filename)[0]
        return os.path.normpath("%s%s.%s" % (slugify(file_name), datetime.datetime.now().strftime('%d_%m_%Y_%H_%M_%S_%f'), extension.lower()))

    def generate_filename(self, instance, filename):
        from django.utils.text import slugify
        if self.funcUser:
            user = self.funcUser(instance)
        else:
            user = instance.user
        return os.path.join(self.upload_to, str(user.id), slugify(user.username)+"_"+self.get_filename(filename))


@deconstructible
class FileNameUploadToPath(object):
    """
    Funciona sólo si el modelo tiene un campo user (ForeignKey de auth.User)
    """
    def __init__(self, upload_to, nombreArchivo, campos_concatenar=[]):
        self.upload_to = upload_to
        self.nombreArchivo = nombreArchivo
        self.campos_concatenar = campos_concatenar

    def __call__(self, instance, filename):
        return self.generate_filename(instance, filename)

    def get_directory_name(self):
        return os.path.normpath(force_str(datetime.datetime.now().strftime(force_str(self.upload_to))))

    def get_filename(self, instance, filename):
        from django.utils.text import slugify
        filename = default_storage.get_valid_name(os.path.basename(filename))
        filename = force_str(filename)
        filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
        extension = os.path.splitext(filename)[1][1:]
        from core.funciones_adicionales import customgetattr
        concatenar = ""
        for x in self.campos_concatenar:
            concatenar += str(customgetattr(instance, x) or "") + " "
        return os.path.normpath("%s-%s.%s" % (slugify(self.nombreArchivo + concatenar).upper(), datetime.datetime.now().strftime('%d-%m-%Y-%H-%M-%S-%f'), extension.lower()))

    def generate_filename(self, instance, filename):
        return os.path.join(self.upload_to, self.get_filename(instance, filename))