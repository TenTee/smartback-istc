from rest_framework import viewsets, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from .models import EmploiDuTemps, Salle, EmploiDuTempsDocument
from .serializers import EmploiDuTempsSerializer, SalleSerializer, EmploiDuTempsDocumentSerializer
from users.permissions import user_has_write_access, user_has_read_access
from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS


class EmploiDuTempsDocumentPermission(BasePermission):
    """
    - Actions portail (`me`, `formateur`) : tout utilisateur authentifié.
    - Lecture globale (list/retrieve) : accès 'lecture' ou 'ecriture' en pédagogie.
    - Écriture (create/update/delete) : accès 'ecriture' en pédagogie.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(view, "action", None) in ("me", "for_formateur"):
            return True
        if request.method in SAFE_METHODS:
            return user_has_read_access(user, "can_manage_pedagogie")
        return user_has_write_access(user, "can_manage_pedagogie")

class SalleViewSet(viewsets.ModelViewSet):
    queryset = Salle.objects.all()
    serializer_class = SalleSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nom", "description"]
    ordering_fields = ["nom"]

class EmploiDuTempsViewSet(viewsets.ModelViewSet):
    queryset = EmploiDuTemps.objects.all()
    serializer_class = EmploiDuTempsSerializer

    # 🔎 Ajout de filtres et recherche
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["jour", "filiere", "niveau", "classe", "formateur", "module", "salle"]
    search_fields = ["salle__nom", "filiere__nom", "formateur__nom", "module__nom"]
    ordering_fields = ["heure_debut", "heure_fin"]

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        """Récupère l'emploi du temps de l'étudiant connecté."""
        etudiant = getattr(request.user, 'etudiant_profile', None)
        if not etudiant:
            return Response({"error": "Profil étudiant introuvable"}, status=404)
        
        # On récupère les emplois du temps liés à la classe de l'étudiant
        classe_ids = etudiant.inscriptions.values_list('classe_id', flat=True)
        niveau_ids = etudiant.inscriptions.values_list('niveau_id', flat=True)
        
        queryset = EmploiDuTemps.objects.filter(
            models.Q(classe_id__in=classe_ids) | 
            models.Q(niveau_id__in=niveau_ids, classe__isnull=True)
        )
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as e:
            raise serializers.ValidationError({"non_field_errors": e.messages})

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as e:
            raise serializers.ValidationError({"non_field_errors": e.messages})


class EmploiDuTempsDocumentViewSet(viewsets.ModelViewSet):
    queryset = EmploiDuTempsDocument.objects.all()
    serializer_class = EmploiDuTempsDocumentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, EmploiDuTempsDocumentPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["classe", "est_actif"]
    search_fields = ["titre", "classe__nom", "description"]
    ordering_fields = ["created_at", "titre", "date_effective"]

    def get_queryset(self):
        return EmploiDuTempsDocument.objects.select_related(
            "classe", "classe__filiere", "classe__niveau", "classe__annee_academique"
        )

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        """Récupère les documents d'emploi du temps pour l'étudiant connecté."""
        etudiant = getattr(request.user, 'etudiant_profile', None)
        if not etudiant:
            return Response({"error": "Profil étudiant introuvable"}, status=404)

        classe_ids = etudiant.inscriptions.values_list('classe_id', flat=True)
        queryset = EmploiDuTempsDocument.objects.filter(
            classe_id__in=classe_ids,
            est_actif=True
        ).select_related("classe", "classe__filiere", "classe__niveau", "classe__annee_academique").order_by('-date_effective', '-created_at')

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="formateur")
    def for_formateur(self, request):
        """Récupère les documents d'emploi du temps des classes du formateur connecté."""
        formateur = getattr(request.user, 'formateur_profile', None)
        if not formateur:
            return Response({"error": "Profil formateur introuvable"}, status=404)

        from academique.models import Affectation
        from academique.middleware import get_current_academic_year_id

        annee_id = get_current_academic_year_id()

        aff_classe_ids = Affectation.objects.filter(enseignant=formateur)
        if annee_id:
            aff_classe_ids = aff_classe_ids.filter(classe__annee_academique_id=annee_id)
        aff_ids = set(aff_classe_ids.values_list('classe_id', flat=True))

        edt_classe_ids = EmploiDuTemps.objects.filter(formateur=formateur)
        if annee_id:
            edt_classe_ids = edt_classe_ids.filter(classe__annee_academique_id=annee_id)
        edt_ids = set(edt_classe_ids.values_list('classe_id', flat=True))

        all_classe_ids = aff_ids | edt_ids
        if not all_classe_ids:
            for module in formateur.specialites.all():
                c_qs = module.classes_academique.all()
                if annee_id:
                    c_qs = c_qs.filter(annee_academique_id=annee_id)
                all_classe_ids.update(c_qs.values_list('id', flat=True))

        queryset = EmploiDuTempsDocument.objects.filter(
            classe_id__in=all_classe_ids,
            est_actif=True
        ).select_related("classe", "classe__filiere", "classe__niveau", "classe__annee_academique").order_by('-date_effective', '-created_at')

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

