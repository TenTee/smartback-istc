# etudiants/serializers.py
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from .models import Etudiant, EtudiantDocument, Inscription, SanctionDisciplinaire
from academique.models import Filiere, Cycle, Niveau, Classe, AnneeAcademique
from academique.serializers import FiliereSerializer

# --- Documents liés aux étudiants ---
class EtudiantDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtudiantDocument
        fields = ["id", "type_document", "fichier", "date_upload"]


class SanctionDisciplinaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = SanctionDisciplinaire
        fields = ["id", "type_sanction", "motif", "date_sanction", "duree", "active"]


# --- Inscriptions ---
class InscriptionSerializer(serializers.ModelSerializer):
    classe_nom = serializers.CharField(source='classe.nom', read_only=True)
    niveau_nom = serializers.CharField(source='niveau.nom', read_only=True)
    filiere_nom = serializers.CharField(source='niveau.cycle.filiere.nom', read_only=True)
    cycle_id = serializers.IntegerField(source="niveau.cycle_id", read_only=True)
    cycle_nom = serializers.CharField(source="niveau.cycle.nom", read_only=True)
    annee_academique_ref_libelle = serializers.CharField(source='annee_academique_ref.libelle', read_only=True)

    class Meta:
        model = Inscription
        fields = [
            'id',
            'etudiant',
            'classe',
            'classe_nom',
            'niveau',
            'niveau_nom',
            'filiere_nom',
            'cycle_id',
            'cycle_nom',
            'annee_academique',
            'annee_academique_ref',
            'annee_academique_ref_libelle',
            'date_inscription',
        ]


# --- Étudiant ---
class EtudiantSerializer(serializers.ModelSerializer):
    # Lecture
    filiere_details = FiliereSerializer(source="filiere", read_only=True)
    
    # Écriture
    filiere_id = serializers.PrimaryKeyRelatedField(
        queryset=Filiere.objects.all(),
        source="filiere",
        write_only=True
    )
    cycle_id = serializers.PrimaryKeyRelatedField(
        queryset=Cycle.objects.all(),
        write_only=True,
        required=False,
    )
    niveau_id = serializers.IntegerField(write_only=True, required=False)
    classe_id = serializers.IntegerField(write_only=True, required=False)
    annee_academique_ref_id = serializers.IntegerField(write_only=True, required=False)

    # Lecture seule
    documents = EtudiantDocumentSerializer(many=True, read_only=True)
    inscriptions = InscriptionSerializer(many=True, read_only=True)
    sanctions = SanctionDisciplinaireSerializer(many=True, read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Etudiant
        fields = [
            "id",
            "matricule",
            "nom",
            "date_naissance",
            "contact",
            "email",
            "nom_parent",
            "whatsapp_parent",
            "filiere_details",
            "filiere_id",
            "cycle_id",
            "niveau_id",
            "classe_id",
            "annee_academique_ref_id",
            "statut",
            "documents",
            "inscriptions",
            "sanctions",
            "username",
            "initial_password",
        ]
        # Généré automatiquement à la création du compte : jamais modifiable via l'API.
        read_only_fields = ["matricule", "initial_password"]

    def create(self, validated_data):
        try:
            return self._create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, "message_dict", None) or {"non_field_errors": exc.messages})

    def update(self, instance, validated_data):
        try:
            return self._update(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, "message_dict", None) or {"non_field_errors": exc.messages})

    @transaction.atomic
    def _create(self, validated_data):
        validated_data.pop('cycle_id', None)
        niveau_id = validated_data.pop('niveau_id', None)
        classe_id = validated_data.pop('classe_id', None)
        annee_academique_ref_id = validated_data.pop('annee_academique_ref_id', None)

        etudiant = super().create(validated_data)

        if classe_id:
            try:
                classe = Classe.objects.get(pk=classe_id)
                annee = classe.annee_academique
                if annee_academique_ref_id:
                    annee = AnneeAcademique.objects.get(pk=annee_academique_ref_id)
                Inscription.objects.create(
                    etudiant=etudiant,
                    classe=classe,
                    niveau=classe.niveau,
                    annee_academique=annee.libelle,
                    annee_academique_ref=annee,
                )
            except (Classe.DoesNotExist, AnneeAcademique.DoesNotExist):
                pass
        elif niveau_id:
            try:
                niveau = Niveau.objects.get(pk=niveau_id)
                annee = AnneeAcademique.objects.filter(est_active=True).first()
                if annee is None:
                    raise serializers.ValidationError({"niveau_id": "Aucune année académique active n'est configurée."})
                Inscription.objects.create(
                    etudiant=etudiant,
                    niveau=niveau,
                    annee_academique=annee.libelle,
                    annee_academique_ref=annee
                )
            except Niveau.DoesNotExist:
                pass

        return etudiant

    @transaction.atomic
    def _update(self, instance, validated_data):
        validated_data.pop('cycle_id', None)
        validated_data.pop('niveau_id', None)
        classe_id = validated_data.pop('classe_id', None)
        annee_academique_ref_id = validated_data.pop('annee_academique_ref_id', None)

        instance = super().update(instance, validated_data)

        if classe_id:
            try:
                classe = Classe.objects.get(pk=classe_id)
                annee = classe.annee_academique
                if annee_academique_ref_id:
                    annee = AnneeAcademique.objects.get(pk=annee_academique_ref_id)
                inscription = instance.inscriptions.filter(annee_academique_ref=annee).first()
                if inscription:
                    # save() (et non update()) : recalcule niveau/année et déclenche la
                    # création des notes des modules de la nouvelle classe.
                    inscription.classe = classe
                    inscription.niveau = classe.niveau
                    inscription.save()
                else:
                    Inscription.objects.create(
                        etudiant=instance,
                        classe=classe,
                        niveau=classe.niveau,
                        annee_academique=annee.libelle,
                        annee_academique_ref=annee,
                    )
            except (Classe.DoesNotExist, AnneeAcademique.DoesNotExist):
                pass

        return instance
