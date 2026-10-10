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
    sélectionnée (en-tête X-Academic-Year) n'est pas active.

    Correctif : l'ancienne version lisait `request.user`, qui à ce stade ne connaît que
    l'authentification par session ; avec les jetons JWT de l'API il était toujours anonyme,
    donc la protection ne s'appliquait jamais. Une année inconnue est désormais ignorée
    (au lieu d'un 404 sur toutes les requêtes), et la liste des années reste accessible
    pour que le frontend puisse corriger une sélection périmée.
    """

    EXEMPT_PREFIXES = ("/api/auth/", "/api/v2/annees-academiques/", "/api/v2/configuration-etablissement/", "/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        academic_year_id = request.headers.get('X-Academic-Year')

        if not academic_year_id or request.path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)

        try:
            year_id = int(academic_year_id)
        except (TypeError, ValueError):
            return self.get_response(request)

        from users.middleware import jwt_user
        user = jwt_user(request)
        if not user or user.is_superuser:
            return self.get_response(request)

        from .models import AnneeAcademique

        year = AnneeAcademique.objects.filter(pk=year_id).only("est_active").first()
        if year is not None and not year.est_active:
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
