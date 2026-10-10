from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Coordination, PointageEnseignant, RecapMensuel


class CoordinationSerializer(serializers.ModelSerializer):
    formateur_nom = serializers.CharField(source="formateur.nom", read_only=True)
    formateur_email = serializers.CharField(source="formateur.email", read_only=True)
    filiere_nom = serializers.CharField(source="filiere.nom", read_only=True)

    class Meta:
        model = Coordination
        fields = [
            "id", "formateur", "formateur_nom", "formateur_email",
            "filiere", "filiere_nom", "est_active", "date_debut", "date_fin", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        debut = attrs.get("date_debut", getattr(self.instance, "date_debut", None))
        fin = attrs.get("date_fin", getattr(self.instance, "date_fin", None))
        if debut and fin and fin < debut:
            raise serializers.ValidationError({"date_fin": "La date de fin doit être postérieure à la date de début."})
        return attrs


class PointageEnseignantSerializer(serializers.ModelSerializer):
    formateur_nom = serializers.CharField(source="formateur.nom", read_only=True)
    type_formateur = serializers.CharField(source="formateur.type_formateur", read_only=True)
    filiere_nom = serializers.CharField(source="filiere.nom", read_only=True)
    classe_nom = serializers.CharField(source="classe.nom", read_only=True, default="")
    module_nom = serializers.CharField(source="module.nom", read_only=True, default="")
    heures_retenues = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    est_verrouille = serializers.BooleanField(read_only=True)
    saisi_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = PointageEnseignant
        fields = [
            "id", "formateur", "formateur_nom", "type_formateur",
            "filiere", "filiere_nom", "classe", "classe_nom", "module", "module_nom", "seance",
            "date", "heure_debut_prevue", "heure_fin_prevue", "heure_arrivee", "heure_fin",
            "statut", "heures_calculees", "heures_corrigees", "heures_retenues", "commentaire",
            "est_verrouille", "saisi_par", "saisi_par_nom", "created_at", "updated_at",
        ]
        read_only_fields = ["heures_calculees", "saisi_par", "created_at", "updated_at"]
        extra_kwargs = {"filiere": {"required": False}, "formateur": {"required": False}}
        # La contrainte (seance, date) est vérifiée dans validate() avec un message clair.
        validators = []

    def get_saisi_par_nom(self, obj):
        u = obj.saisi_par
        if not u:
            return ""
        return f"{getattr(u, 'noms', '')} {getattr(u, 'prenoms', '')}".strip() or u.username

    def validate(self, attrs):
        instance = self.instance
        seance = attrs.get("seance", getattr(instance, "seance", None))

        # Une séance planifiée impose enseignant / module / classe / filière / horaires prévus.
        if seance is not None:
            attrs["formateur"] = attrs.get("formateur") or seance.formateur
            attrs.setdefault("module", seance.module)
            attrs.setdefault("classe", seance.classe)
            if not attrs.get("filiere"):
                attrs["filiere"] = seance.classe.filiere if seance.classe_id else seance.filiere
            attrs.setdefault("heure_debut_prevue", seance.heure_debut)
            attrs.setdefault("heure_fin_prevue", seance.heure_fin)

        classe = attrs.get("classe", getattr(instance, "classe", None))
        if not attrs.get("filiere") and not getattr(instance, "filiere_id", None) and classe is not None:
            attrs["filiere"] = classe.filiere

        if not attrs.get("filiere") and not getattr(instance, "filiere_id", None):
            raise serializers.ValidationError({"filiere": "La filière est obligatoire (ou choisissez une classe)."})
        if not attrs.get("formateur") and not getattr(instance, "formateur_id", None):
            raise serializers.ValidationError({"formateur": "L'enseignant est obligatoire."})

        date = attrs.get("date", getattr(instance, "date", None))
        if seance is not None and date is not None:
            doublon = PointageEnseignant.objects.filter(seance=seance, date=date)
            if instance is not None:
                doublon = doublon.exclude(pk=instance.pk)
            if doublon.exists():
                raise serializers.ValidationError({"seance": "Cette séance a déjà été pointée pour cette date."})

        # Si absent, on efface les heures saisies.
        statut = attrs.get("statut", getattr(instance, "statut", PointageEnseignant.STATUT_PRESENT))
        if statut == PointageEnseignant.STATUT_ABSENT:
            attrs["heure_arrivee"] = None
            attrs["heure_fin"] = None
            attrs["heures_corrigees"] = None

        # Validation métier du modèle (heures cohérentes, date non future, classe ↔ filière).
        candidat = PointageEnseignant(**{
            **({f.name: getattr(instance, f.name) for f in PointageEnseignant._meta.concrete_fields} if instance else {}),
            **attrs,
        })
        try:
            candidat.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class RecapMensuelSerializer(serializers.ModelSerializer):
    formateur_nom = serializers.CharField(source="formateur.nom", read_only=True)
    type_formateur = serializers.CharField(source="formateur.type_formateur", read_only=True)
    filiere_nom = serializers.CharField(source="filiere.nom", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    cloture_par_nom = serializers.SerializerMethodField()
    valide_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = RecapMensuel
        fields = [
            "id", "formateur", "formateur_nom", "type_formateur", "filiere", "filiere_nom",
            "mois", "annee", "nombre_seances", "nombre_absences", "total_heures",
            "taux_horaire", "montant", "statut", "statut_libelle",
            "commentaire_coordonnateur", "motif_rejet",
            "cloture_par", "cloture_par_nom", "date_cloture",
            "valide_par", "valide_par_nom", "date_validation", "bulletin",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    @staticmethod
    def _nom(u):
        if not u:
            return ""
        return f"{getattr(u, 'noms', '')} {getattr(u, 'prenoms', '')}".strip() or u.username

    def get_cloture_par_nom(self, obj):
        return self._nom(obj.cloture_par)

    def get_valide_par_nom(self, obj):
        return self._nom(obj.valide_par)
