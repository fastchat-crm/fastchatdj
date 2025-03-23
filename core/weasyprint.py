import weasyprint
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import get_template
from .response_file_pdf import ResponseFilePdf
from .weasyprint_utils import WeasyprintUtil
from django.http import HttpResponse


class WeasyPrintPdf:
    def __init__(self, base_url='', template_name='', context=None, filename=None, stylesheets=None, attachment=True):
        self._template_name = template_name
        self._context = context or {}
        self._base_url = base_url
        self._stylesheets = stylesheets or []
        self.filename = filename
        self.disposition = 'attachment' if attachment else 'inline'

    def get_html_template(self):
        template = get_template(self._template_name)
        return template.render(self._context).encode(encoding="UTF-8")

    def get_base_url(self):
        return getattr(settings, 'WEASYPRINT_BASEURL', self._base_url)
        # return settings.STATIC_ROOT

    def get_url_fetcher(self):
        return WeasyprintUtil.django_url_fetcher

    def get_font_config(self):
        return weasyprint.text.fonts.FontConfiguration()

    def get_css(self, base_url, url_fetcher, font_config):
        css_sheets = [weasyprint.CSS(value, base_url=base_url, url_fetcher=url_fetcher, font_config=font_config)
                      for value in self._stylesheets]
        css_sheets.append(weasyprint.CSS(string=".italic2 { font-style: italic !important; }",
                                         font_config=font_config))
        return css_sheets

    def get_document(self):
        base_url = self.get_base_url()
        url_fetcher = self.get_url_fetcher()
        font_config = self.get_font_config()
        html = weasyprint.HTML(string=self.get_html_template(), base_url=base_url, url_fetcher=url_fetcher)
        css = self.get_css(base_url, url_fetcher, font_config)
        return html.render(stylesheets=css, font_config=font_config)

    @property
    def rendered_content(self):
        document = self.get_document()
        return document.write_pdf()

    def get_response(self):
        response = HttpResponse(self.rendered_content, content_type='application/pdf')
        response['Content-Disposition'] = f'{self.disposition}; filename="{self.filename}"'
        return response