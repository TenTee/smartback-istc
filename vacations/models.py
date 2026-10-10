"""
Gestion des vacations enseignants.

- Coordination : un formateur est désigné coordonnateur d'une filière.
- PointageEnseignant : le coordonnateur enregistre, séance par séance, l'heure
  d'arrivée et de fin d'un enseignant (ou son absence).
- RecapMensuel : à la fin du mois, les heures d'un enseignant dans une filière
  sont totalisées ; le coordonnateur clôture le récap, la finance le valide, puis
  les heures validées alimentent automatiquement la campagne de paie.
"""
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from academique.models import Filiere, Classe
from formateurs.models import Formateur
from modules.models import Module


QUART_HEURE = Decimal("0.25")


def arrondir_quart_heure(heures: Decimal) -> Decimal:
    """Arrondit un nombre d'heures au quart d'heure le plus proche."""
    if heures <= 0:
        return Decimal("0.00")
    quarts = (heures / QUART_HEURE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (quarts * QUART_HEURE).quantize(Decimal("0.01"))


def duree_en_heures(debut, fin) -> Decimal:
    """Durée (en heures décimales, non arrondie) entre deux `time` du même jour."""
    if not debut or not fin:
        return Decimal("0")
    d = datetime.combine(date.today(), fin) - datetime.combine(date.today(), debut)
    secondes = Decimal(int(d.total_seconds()))
    return secondes / Decimal(3600) if secondes > 0 else Decimal("0")


class Coordination(models.Model):
    """Un formateur coordonnateur d'une filière."""

    formateur = models.ForeignKey(Formateur, on_delete=models.CASCADE, related_name="coordinations")
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="coordinations")
    est_active = models.BooleanField(default=True)
    date_debut = models.DateField(default=timezone.localdate)
    date_fin = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Coordination de filière"
        verbose_name_plural = "Coordinations de filières"
        ordering = ["filiere__nom", "formateur__nom"]
        constraints = [
            models.UniqueConstraint(fields=["formateur", "filiere"], name="unique_coordination_formateur_filiere"),
        ]

    def __str__(self):
        return f"{self.formateur.nom} → {self.filiere.nom}"


class PointageEnseignant(models.Model):
    STATUT_PRESENT = "present"
    STATUT_ABSENT = "absent"
    STATUT_CHOICES = [
        (STATUT_PRESENT, "Présent"),
        (STATUT_ABSENT, "Absent"),
    ]

    formateur = models.ForeignKey(Formateur, on_delete=models.CASCADE, related_name="pointages")
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="pointages_enseignants")
    classe = models.ForeignKey(Classe, on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages_enseignants")
    module = models.ForeignKey(Module, on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages_enseignants")
    seance = models.ForeignKey(
        "emploidutemps.EmploiDuTemps",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pointages",
        help_text="Séance planifiée de l'emploi du temps (vide = séance non planifiée / rattrapage)",
    )

    date = models.DateField()
    heure_debut_prevue = models.TimeField(null=True, blank=True)
    heure_fin_prevue = models.TimeField(null=True, blank=True)
    heure_arrivee = models.TimeField(null=True, blank=True)
    heure_fin = models.TimeField(null=True, blank=True)
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_PRESENT)

    heures_calculees = models.DecimalField(max_digits=6, decimal_places=2, default=0, editable=False)
    heures_corrigees = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Correction manuelle du coordonnateur (remplace le calcul automatique)",
    )
    commentaire = models.TextField(blank=True, default="")

    saisi_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages_saisis"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pointage enseignant"
        verbose_name_plural = "Pointages enseignants"
        ordering = ["-date", "heure_debut_prevue", "formateur__nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["seance", "date"],
                condition=models.Q(seance__isnull=False),
                name="unique_pointage_par_seance_et_date",
            ),
        ]
        indexes = [models.Index(fields=["formateur", "date"]), models.Index(fields=["filiere", "date"])]

    def clean(self):
        errors = {}
        if self.statut == self.STATUT_PRESENT:
            if not self.heure_arrivee:
                errors["heure_arrivee"] = "L'heure d'arrivée est obligatoire pour un enseignant présent."
            if self.heure_arrivee and self.heure_fin and self.heure_fin <= self.heure_arrivee:
                errors["heure_fin"] = "L'heure de fin doit être postérieure à l'heure d'arrivée."
        if self.heures_corrigees is not None and self.heures_corrigees < 0:
            errors["heures_corrigees"] = "Les heures corrigées ne peuvent pas être négatives."
        if self.date and self.date > timezone.localdate():
            errors["date"] = "Impossible de pointer une séance future."
        if self.classe_id and self.filiere_id and self.classe.filiere_id and self.classe.filiere_id != self.filiere_id:
            errors["classe"] = "La classe n'appartient pas à la filière du pointage."
        if errors:
            raise ValidationError(errors)

    def calculer_heures(self) -> Decimal:
        if self.statut != self.STATUT_PRESENT or not self.heure_arrivee or not self.heure_fin:
            return Decimal("0.00")
        return arrondir_quart_heure(duree_en_heures(self.heure_arrivee, self.heure_fin))

    @property
    def heures_retenues(self) -> Decimal:
        if self.statut != self.STATUT_PRESENT:
            return Decimal("0.00")
        if self.heures_corrigees is not None:
            return self.heures_corrigees
        return self.heures_calculees

    @property
    def est_verrouille(self) -> bool:
        """Verrouillé dès que le récap du mois est clôturé (ou au-delà)."""
        return RecapMensuel.objects.filter(
            formateur_id=self.formateur_id,
            filiere_id=self.filiere_id,
            mois=self.date.month,
            annee=self.date.year,
            statut__in=RecapMensuel.STATUTS_VERROUILLES,
        ).exists()

    def save(self, *args, **kwargs):
        if self.classe_id and not self.filiere_id:
            self.filiere_id = self.classe.filiere_id
        self.heures_calculees = self.calculer_heures()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.formateur.nom} - {self.date} ({self.get_statut_display()})"


class RecapMensuel(models.Model):
    STATUT_OUVERT = "ouvert"
    STATUT_CLOTURE = "cloture"
    STATUT_VALIDE = "valide"
    STATUT_REJETE = "rejete"
    STATUT_PAYE = "paye"
    STATUT_CHOICES = [
        (STATUT_OUVERT, "Ouvert"),
        (STATUT_CLOTURE, "Clôturé par le coordonnateur"),
        (STATUT_VALIDE, "Validé par la finance"),
        (STATUT_REJETE, "Rejeté (à corriger)"),
        (STATUT_PAYE, "Payé"),
    ]
    STATUTS_VERROUILLES = (STATUT_CLOTURE, STATUT_VALIDE, STATUT_PAYE)

    formateur = models.ForeignKey(Formateur, on_delete=models.CASCADE, related_name="recaps_mensuels")
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="recaps_mensuels")
    mois = models.PositiveSmallIntegerField()
    annee = models.PositiveSmallIntegerField()

    nombre_seances = models.PositiveIntegerField(default=0)
    nombre_absences = models.PositiveIntegerField(default=0)
    total_heures = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    taux_horaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    montant = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_OUVERT)
    commentaire_coordonnateur = models.TextField(blank=True, default="")
    motif_rejet = models.TextField(blank=True, default="")

    cloture_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recaps_clotures"
    )
    date_cloture = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recaps_valides"
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    bulletin = models.ForeignKey(
        "paie.BulletinPaie", on_delete=models.SET_NULL, null=True, blank=True, related_name="recaps_vacations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Récapitulatif mensuel des heures"
        verbose_name_plural = "Récapitulatifs mensuels des heures"
        ordering = ["-annee", "-mois", "formateur__nom"]
        constraints = [
            models.UniqueConstraint(fields=["formateur", "filiere", "mois", "annee"], name="unique_recap_formateur_filiere_mois"),
        ]

    def pointages(self):
        return PointageEnseignant.objects.filter(
            formateur_id=self.formateur_id,
            filiere_id=self.filiere_id,
            date__month=self.mois,
            date__year=self.annee,
        )

    def recalculer(self):
        """Recalcule les totaux à partir des pointages (taux horaire figé au moment du calcul)."""
        qs = list(self.pointages())
        presents = [p for p in qs if p.statut == PointageEnseignant.STATUT_PRESENT]
        self.nombre_seances = len(presents)
        self.nombre_absences = len(qs) - len(presents)
        self.total_heures = sum((p.heures_retenues for p in presents), Decimal("0.00"))
        self.taux_horaire = Decimal(str(self.formateur.taux_horaire or 0))
        if self.formateur.type_formateur == "vacataire":
            self.montant = (self.total_heures * self.taux_horaire).quantize(Decimal("0.01"))
        else:
            self.montant = Decimal("0.00")

    def __str__(self):
        return f"{self.formateur.nom} - {self.filiere.nom} - {self.mois:02d}/{self.annee} ({self.statut})"
