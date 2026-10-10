"""
Contrôle d'accès global aux comptes « portail » (étudiants et formateurs).

Avant ce middleware, n'importe quel compte connecté — y compris un étudiant — pouvait
appeler toutes les routes de l'API d'administration (liste des étudiants avec leurs mots
de passe initiaux, salaires, modification des notes, des paiements, etc.), car la quasi
totalité des vues n'exigeait que `IsAuthenticated`.

Les comptes portail ne peuvent désormais appeler que les routes listées ci-dessous, qui
correspondent exactement à ce qu'utilisent les portails étudiant et formateur du frontend.
Les autres comptes (personnel, administration) conservent leur fonctionnement actuel.
"""
import re

from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .permissions import is_admin_user

SAFE = ("GET", "HEAD", "OPTIONS")
ALL = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE")

# Routes de référence en lecture seule, utiles à tous les portails.
_REFERENTIEL = [
    (SAFE, r"^/api/v2/(annees-academiques|configuration-etablissement|filieres|specialites|cycles|levels|niveaux|classes|semestres|parametres-globaux)(/|$)"),
    (SAFE, r"^/api/v2/epreuves/"),  # filtrées (est_partage) pour les étudiants dans la vue
    (SAFE, r"^/api/auth/roles/$"),
    (SAFE, r"^/api/auth/\d+/$"),  # la vue n'autorise que sa propre fiche
    (SAFE, r"^/api/formateurs/cours-etudiants/$"),
]

PORTAL_RULES = {
    "etudiant": _REFERENTIEL + [
        (SAFE, r"^/api/etudiants/me/"),
        (SAFE, r"^/api/etudiants/portal/"),
        (SAFE, r"^/api/emploi-du-temps/me/$"),
        (SAFE, r"^/api/emploi-du-temps-documents/me/$"),
        (SAFE, r"^/api/paiements/me/$"),
        (SAFE, r"^/api/notes/me/$"),
        (SAFE, r"^/api/notes/\d+/(details|releve-notes)/$"),  # la vue vérifie qu'il s'agit de l'étudiant connecté
        (SAFE, r"^/api/assiduite/$"),  # la vue ne renvoie que ses propres enregistrements
    ],
    "formateur": _REFERENTIEL + [
        (ALL, r"^/api/formateurs/portal/"),
        (ALL, r"^/api/formateurs/cours-documents/"),  # la vue limite aux documents du formateur
        (SAFE, r"^/api/emploi-du-temps-documents/formateur/$"),
        (ALL, r"^/api/vacations/(coordonnateur|pointages)/"),  # réservé aux coordonnateurs par la vue
        (SAFE, r"^/api/vacations/mes-heures/"),
    ],
}
_COMPILED = {k: [(m, re.compile(p)) for m, p in rules] for k, rules in PORTAL_RULES.items()}


def portal_type(user):
    """'etudiant' / 'formateur' pour un compte portail, None pour le personnel et l'administration."""
    if not user or not getattr(user, "is_authenticated", False) or is_admin_user(user):
        return None
    role = getattr(user, "role", "")
    if role == "etudiant":
        return "etudiant"
    if role == "formateur":
        return "formateur"
    return None


def jwt_user(request):
    """Utilisateur du jeton JWT (le middleware d'auth Django ne connaît que la session)."""
    if hasattr(request, "_jwt_user"):
        return request._jwt_user
    user = None
    try:
        result = JWTAuthentication().authenticate(request)
        if result:
            user = result[0]
    except (InvalidToken, TokenError):
        user = None
    except Exception:
        user = None
    request._jwt_user = user
    return user


def is_portal_request_allowed(kind, method, path):
    return any(method in methods and pattern.search(path) for methods, pattern in _COMPILED.get(kind, []))


class PortalAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/") and not path.startswith("/api/auth/login") and not path.startswith("/api/auth/token/"):
            kind = portal_type(jwt_user(request))
            if kind and not is_portal_request_allowed(kind, request.method, path):
                return JsonResponse(
                    {"detail": "Accès refusé : cette ressource est réservée au personnel de l'établissement."},
                    status=403,
                )
        return self.get_response(request)
