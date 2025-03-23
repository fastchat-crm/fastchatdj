import enum

from django.http import HttpResponse


class ResponseFilePdfTypeFileEnum(enum.Enum):
    PDF = 'pdf'


class ResponseFilePdf:

    def __init__(self, file_name='archivo', content=''):
        self.__content = content
        self.__file_name = file_name
        self.__content_type = 'application/pdf'
        self.__type_file = ResponseFilePdfTypeFileEnum.PDF.value

    def get_content_type(self):
        return self.__content_type

    def get_file_name(self):
        return self.__file_name

    def get_content(self):
        return self.__content

    def get_type_file(self):
        return self.__type_file

    def get_response(self):
        response = self.__get_http_response()
        response['Content-Disposition'] = 'attachment; filename="{}.{}"'.format(
            self.get_file_name(),
            self.get_type_file()
        )

        return response

    def get_response_without_content_disposition(self):
        return self.__get_http_response()

    def __get_http_response(self):
        return HttpResponse(
            content=self.get_content(),
            content_type=self.get_content_type()
        )
