# conges/serializers.py
from rest_framework import serializers
from .models import Conge
from personnels.models import Personnel
from personnels.serializers import PersonnelSerializer

class CongeSerializer(serializers.ModelSerializer):
    personnel_id = serializers.PrimaryKeyRelatedField(
        queryset=Personnel.objects.all(),
        source='personnel',
        write_only=True
    )

    personnel = PersonnelSerializer(read_only=True)

    class Meta:
        model = Conge
        fields = [
            'id',
            'date_debut',
            'date_fin',
            'type_conge',
            'raison',
            'statut',
            'personnel',
            'personnel_id'
        ]

    def _save(self, fn, *args):
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            return fn(*args)
        except DjangoValidationError as exc:
            # Les règles métier du modèle (solde, ancienneté…) renvoyaient une erreur 500.
            raise serializers.ValidationError(getattr(exc, "message_dict", None) or {"non_field_errors": exc.messages})

    def create(self, validated_data):
        return self._save(super().create, validated_data)

    def update(self, instance, validated_data):
        return self._save(super().update, instance, validated_data)
