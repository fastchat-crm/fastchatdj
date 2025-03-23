from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML
from django.conf import settings
from io import BytesIO

from core.weasyprint import WeasyPrintPdf
from fastchatdj.settings import URL_GENERAL
from seguridad.models import Configuracion


class WeasyPrintConfig:
    BASE_DIR = settings.MEDIA_ROOT


def render_pdf_view(html_string):
    try:
        return HTML(string=html_string).write_pdf()
    except Exception as e:
        print(f"Error al generar PDF: {e}")
        return None


def renderweasypdf(request, context, template_name, pdf_name="document.pdf"):
    if not isinstance(context, dict) or not isinstance(template_name, str) or not isinstance(pdf_name, str):
        return HttpResponse("Invalid parameters", status=400)
    pdf_generator = WeasyPrintPdf(
        base_url=request.build_absolute_uri(),
        template_name=template_name,
        context=context,
        filename=pdf_name,
        stylesheets=[],
        attachment=False
    )
    return pdf_generator.get_response()


def downweasypdf(request, context, template_name, pdf_name="document.pdf"):
    if not isinstance(context, dict) or not isinstance(template_name, str) or not isinstance(pdf_name, str):
        return HttpResponse("Invalid parameters", status=400)
    confi_ = Configuracion.get_instancia()
    pdf_generator = WeasyPrintPdf(
        base_url=request.build_absolute_uri(),
        template_name=template_name,
        context=context,
        filename=pdf_name,
        stylesheets=[],
        attachment=True  # Change this to True
    )
    return pdf_generator.get_response()


def generateweasypdf(request, context, template_name, pdf_name="document.pdf"):
    if not isinstance(context, dict) or not isinstance(template_name, str) or not isinstance(pdf_name, str):
        return None
    confi_ = Configuracion.get_instancia()
    pdf_generator = WeasyPrintPdf(
        base_url=request.build_absolute_uri(),
        template_name=template_name,
        context=context,
        filename=pdf_name,
        stylesheets=[],
        attachment=False
    )
    pdf_content = pdf_generator.rendered_content
    pdf_file = BytesIO(pdf_content)
    return pdf_file
