from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from django.utils.crypto import get_random_string

from rest_framework_simplejwt.views import TokenObtainPairView
from .models import CustomUser, Role
from .permissions import RolePermission, UserAccountPermission
from .recaptcha import verify_recaptcha
from .serializers import UserSerializer, RoleSerializer, MyTokenObtainPairSerializer


class RoleViewSet(viewsets.ModelViewSet):
    """CRUD sur les rôles : lecture pour tous les connectés, écriture réservée à l'administration."""
    queryset = Role.objects.all().order_by("libelle")
    serializer_class = RoleSerializer
    permission_classes = [RolePermission]


class UserViewSet(viewsets.ModelViewSet):
    """Gestion des comptes : réservée à l'administration (chacun peut lire sa propre fiche)."""
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer
    permission_classes = [UserAccountPermission]

    # Le modèle génère lui-même username et mot de passe (exposé une fois via `raw_password`).

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = get_random_string(8)
        user.set_password(new_password)
        user._raw_password = new_password
        user.save()
        return Response(
            {
                "username": user.username,
                "new_password": new_password,
            },
            status=status.HTTP_200_OK
        )


class MyTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = MyTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        verify_recaptcha(request)
        return super().post(request, *args, **kwargs)
