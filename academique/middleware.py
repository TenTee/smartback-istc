import contextvars
from django.http import JsonResponse

# Variable globale pour stocker l'année académique courante pour le thread/contexte actuel
_current_academic_year_id = contextvars.ContextVar('current_academic_year_id', default=None)

class AcademicYearMiddleware:
    """
    Middleware qui capture le header 'X-Academic-Year' et le stocke 
    dans un ContextVar pour qu'il soit accessible partout dans le code.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        academic_year_id = request.headers.get('X-Academic-Year')
        
        # Stockage de l'ID
        token = _current_academic_year_id.set(academic_year_id)
        
        try:
            response = self.get_response(request)
        finally:
            # Nettoyage après la réponse
            _current_academic_year_id.reset(token)
            
        return response


class ArchiveAcademicYearMiddleware:
    """
    Bloque l'accès aux utilisateurs non superuser lorsque l'année académique
    sélectionnée n'est pas active.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        academic_year_id = request.headers.get('X-Academic-Year')
        if academic_year_id:
            try:
                year_id = int(academic_year_id)
            except (TypeError, ValueError):
                year_id = None

            if year_id is not None:
                from .models import AnneeAcademique

                try:
                    year = AnneeAcademique.objects.get(pk=year_id)
                except AnneeAcademique.DoesNotExist:
                    return JsonResponse(
                        {'detail': 'Année académique introuvable.'},
                        status=404,
                    )

                if not year.est_active and request.user.is_authenticated and not request.user.is_superuser:
                    return JsonResponse(
                        {
                            'detail': "L'année académique sélectionnée est archivée. Seul le super-admin peut y accéder."
                        },
                        status=403,
                    )

        return self.get_response(request)

def get_current_academic_year_id():
    val = _current_academic_year_id.get()
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
