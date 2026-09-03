from rest_framework.permissions import BasePermission, SAFE_METHODS


def get_role_access_level(user, permission_name):
    """Renvoie le niveau d'accès d'un rôle pour un module donné."""
    if not user or not getattr(user, 'is_authenticated', False):
        return 'none'

    if getattr(user, 'is_superuser', False):
        return 'ecriture'

    if getattr(user, 'role', '') in ('admin', 'superadmin'):
        return 'ecriture'

    try:
        from users.models import Role
        role_obj = Role.objects.get(code=user.role)
        value = getattr(role_obj, permission_name, 'none')
        return value or 'none'
    except Role.DoesNotExist:
        return 'none'


def user_has_write_access(user, permission_name):
    return get_role_access_level(user, permission_name) == 'ecriture'


def user_has_read_access(user, permission_name):
    return get_role_access_level(user, permission_name) in ('lecture', 'ecriture')


class HasRolePermission(BasePermission):
    """
    Permission personnalisée qui vérifie le rôle de l'utilisateur.
    Si SAFE_METHODS (GET, HEAD, OPTIONS) -> exige 'lecture' ou 'ecriture'.
    Sinon (POST, PUT, PATCH, DELETE) -> exige 'ecriture'.
    """

    required_permission = None
    required_access = None  # Si None, calculé automatiquement selon HTTP method

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or getattr(request.user, 'role', '') in ('admin', 'superadmin'):
            return True

        if hasattr(view, 'required_roles'):
            return request.user.role in view.required_roles

        permission_name = getattr(view, 'required_permission', self.required_permission)
        if permission_name:
            level = get_role_access_level(request.user, permission_name)
            req_access = getattr(view, 'required_access', self.required_access)
            if req_access == 'ecriture':
                return level == 'ecriture'
            elif req_access == 'lecture':
                return level in ('lecture', 'ecriture')
            
            # Automatique selon la méthode HTTP
            if request.method in SAFE_METHODS:
                return level in ('lecture', 'ecriture')
            return level == 'ecriture'

        return request.user.is_active