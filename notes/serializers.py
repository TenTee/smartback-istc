from rest_framework import serializers
from .models import Note


def validate_note_max_20(value):
    # We allow component values up to 100 (component maxima are configurable)
    if value is not None and value > 100:
        raise serializers.ValidationError("La note ne peut pas dépasser 100.")
    if value is not None and value < 0:
        raise serializers.ValidationError("La note ne peut pas être négative.")
    return value


class NoteSerializer(serializers.ModelSerializer):
    etudiant_nom = serializers.CharField(source="etudiant.nom", read_only=True)
    etudiant_matricule = serializers.CharField(source="etudiant.matricule", read_only=True)
    module_nom = serializers.CharField(source="module.nom", read_only=True)
    module_semestre = serializers.SerializerMethodField()
    classe_nom = serializers.SerializerMethodField()
    evaluation_nom = serializers.SerializerMethodField()
    formation = serializers.SerializerMethodField()
    formateur_nom = serializers.SerializerMethodField()
    note_sur_20 = serializers.SerializerMethodField()
    besoin_rattrapage = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "id",
            "etudiant",
            "etudiant_nom",
            "etudiant_matricule",
            "formation",
            "classe",
            "classe_nom",
            "module",
            "module_nom",
            "module_semestre",
            "evaluation",
            "evaluation_nom",
            "session",
            "formateur_nom",
            "note_cc",
            "note_sn",
            "note_rattrapage",
            "note_finale",
            "note_sur_20",
            "besoin_rattrapage",
            "validee",
        ]
        read_only_fields = ["id", "note_finale", "session"]

    def validate_note_cc(self, value):
        return validate_note_max_20(value)

    def validate_note_sn(self, value):
        return validate_note_max_20(value)

    def validate_note_rattrapage(self, value):
        return validate_note_max_20(value)

    def validate(self, attrs):
        from academique.models import ParametresGlobaux
        params = ParametresGlobaux.get_parametres()
        pc = params.pourcentage_cc or 0
        psn = params.pourcentage_sn or 0

        cc = attrs.get("note_cc", self.instance.note_cc if self.instance else None)
        sn = attrs.get("note_sn", self.instance.note_sn if self.instance else None)
        r = attrs.get("note_rattrapage", self.instance.note_rattrapage if self.instance else None)

        if cc is not None and cc > pc:
            raise serializers.ValidationError({"note_cc": f"La note CC ne peut pas dépasser {pc}."})
        if sn is not None and sn > psn:
            raise serializers.ValidationError({"note_sn": f"La note SN ne peut pas dépasser {psn}."})
        if r is not None and r > psn:
            raise serializers.ValidationError({"note_rattrapage": f"La note de rattrapage ne peut pas dépasser {psn}."})

        return attrs

    def get_note_sur_20(self, obj):
        return float(obj.note_sur_20) if obj.note_sur_20 is not None else None

    def get_besoin_rattrapage(self, obj):
        return obj.besoin_rattrapage

    def get_classe_nom(self, obj):
        if obj.classe:
            return obj.classe.nom
        return None

    def get_evaluation_nom(self, obj):
        if obj.evaluation:
            return getattr(obj.evaluation, 'libelle', None) or str(obj.evaluation)
        return None

    def get_formation(self, obj):
        if obj.etudiant and obj.etudiant.filiere:
            return obj.etudiant.filiere.nom
        return None

    def get_module_semestre(self, obj):
        return getattr(obj.module, 'semestre', '') or obj.session or ''

    def get_formateur_nom(self, obj):
        if obj.classe_id and obj.module_id:
            from academique.models import Affectation
            aff = Affectation.objects.filter(
                module_id=obj.module_id,
                classe_id=obj.classe_id,
            ).select_related('enseignant').first()
            if aff and aff.enseignant:
                return aff.enseignant.nom or ""
        return ""


class NoteSummarySerializer(serializers.Serializer):
    etudiant_id = serializers.IntegerField()
    etudiant_nom = serializers.CharField()
    etudiant_matricule = serializers.CharField()
    formation = serializers.CharField(allow_null=True)
    session = serializers.CharField(allow_null=True)
    moyenne_generale = serializers.FloatField()
    mention = serializers.CharField()


class NoteDetailSerializer(serializers.Serializer):
    module_id = serializers.IntegerField()
    module_nom = serializers.CharField()
    note_cc = serializers.FloatField(allow_null=True)
    note_sn = serializers.FloatField(allow_null=True)
    note_rattrapage = serializers.FloatField(allow_null=True)
    note_finale = serializers.FloatField(allow_null=True)
    note_sur_20 = serializers.FloatField(allow_null=True)


class EtudiantNoteSerializer(serializers.Serializer):
    module_id = serializers.IntegerField()
    module_nom = serializers.CharField()
    note_cc = serializers.FloatField(allow_null=True)
    note_sn = serializers.FloatField(allow_null=True)
    note_rattrapage = serializers.FloatField(allow_null=True)
    note_finale = serializers.FloatField(allow_null=True)
    note_sur_20 = serializers.FloatField(allow_null=True)


class EtudiantFiliereSerializer(serializers.Serializer):
    etudiant_id = serializers.IntegerField()
    etudiant_nom = serializers.CharField()
    etudiant_matricule = serializers.CharField()
    session = serializers.CharField(allow_null=True)
    notes = EtudiantNoteSerializer(many=True)


class NoteFiliereSerializer(serializers.Serializer):
    filiere_id = serializers.IntegerField()
    filiere_nom = serializers.CharField()
    modules = serializers.ListField(child=serializers.DictField())
    etudiants = EtudiantFiliereSerializer(many=True)
