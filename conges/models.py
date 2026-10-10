from django.db import models


class Conge(models.Model):
    date_debut = models.DateField()
    date_fin = models.DateField()
    type_conge = models.CharField(max_length=50)
    raison = models.TextField(null=True, blank=True)

    statut = models.CharField(
        max_length=20,
        default='en_attente',
        choices=[
            ('en_attente', 'En attente'),
            ('accepte', 'Accepté'),
            ('refuse', 'Refusé'),
        ]
    )

    personnel = models.ForeignKey(
        'personnels.Personnel',
        on_delete=models.CASCADE,
        related_name='conges'
    )

    @staticmethod
    def calculate_working_days(start_date, end_date):
        """
        Nombre de jours ouvrés (lundi→vendredi) entre start_date et end_date, BORNES INCLUSES.
        (Auparavant la date de fin était exclue : un congé du lundi au vendredi comptait
        4 jours et un congé d'une seule journée était impossible.)
        """
        from datetime import timedelta
        if not start_date or not end_date or end_date < start_date:
            return 0
        days = (end_date - start_date).days + 1
        return sum(1 for i in range(days) if (start_date + timedelta(days=i)).weekday() < 5)

    @property
    def jours_ouvres(self):
        return self.calculate_working_days(self.date_debut, self.date_fin)

    def _jours_deja_decomptes(self):
        """Jours déjà retirés du solde pour ce congé (s'il était déjà accepté en base)."""
        if not self.pk:
            return 0
        original = Conge.objects.filter(pk=self.pk).first()
        if original and original.statut == 'accepte':
            return original.jours_ouvres
        return 0

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.date_debut and self.date_fin:
            if self.date_fin < self.date_debut:
                raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")
            if self.jours_ouvres <= 0:
                raise ValidationError("La période choisie ne contient aucun jour ouvré (uniquement des weekends).")

        if self.personnel_id and self.statut != 'refuse':
            if not self.personnel.est_eligible_conges:
                raise ValidationError(f"Ce membre du personnel n'est pas encore éligible aux congés (Ancienneté: {self.personnel.anciennete_annees} an(s)). Il faut au moins 1 an.")

            # Solde disponible pour CE congé : le solde actuel + ce que ce congé a déjà consommé.
            disponible = self.personnel.solde_conges_restant + self._jours_deja_decomptes()
            if disponible < self.jours_ouvres:
                raise ValidationError(f"Solde de congés insuffisant. Restant: {disponible} jour(s) ouvré(s), Demandé: {self.jours_ouvres} jour(s).")

    def save(self, *args, **kwargs):
        """
        Correctif : le solde était débité AVANT la validation ; la validation échouait alors
        (le solde venait d'être réduit) mais le débit restait enregistré, si bien qu'accepter
        un congé échouait la plupart du temps tout en consommant le solde.
        Désormais : validation d'abord, puis ajustement du solde dans la même transaction,
        et le solde est rendu si un congé accepté est refusé, modifié ou supprimé.
        """
        from django.db import transaction
        from personnels.models import Personnel

        self.full_clean()
        with transaction.atomic():
            deja = self._jours_deja_decomptes()
            nouveau = self.jours_ouvres if self.statut == 'accepte' else 0
            delta = nouveau - deja
            super().save(*args, **kwargs)
            if delta:
                personnel = Personnel.objects.select_for_update().get(pk=self.personnel_id)
                personnel.solde_conges_restant = max(0, personnel.solde_conges_restant - delta)
                personnel.save(update_fields=['solde_conges_restant'])

    def delete(self, *args, **kwargs):
        from django.db import transaction
        from personnels.models import Personnel

        with transaction.atomic():
            if self.statut == 'accepte' and self.personnel_id:
                personnel = Personnel.objects.select_for_update().get(pk=self.personnel_id)
                personnel.solde_conges_restant += self.jours_ouvres
                personnel.save(update_fields=['solde_conges_restant'])
            return super().delete(*args, **kwargs)
