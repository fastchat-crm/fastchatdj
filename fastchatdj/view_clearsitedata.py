from django.http import JsonResponse

def clearSiteDataView(request):
    if request.method == 'POST':
        response = JsonResponse({})
        response['Clear-Site-Data'] = '"cache", "storage"'
        return response