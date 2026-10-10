import os
from django.db import models
from datetime import time
from django.utils import timezone
from formateurs.models import Formateur
from modules.models import Module
from academique.models import Filiere, Niveau
from django.core.exceptions import ValidationError

class Salle(models.Model):
    nom = models.CharField(max_length=100, unique=True)
    capacite = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Salle"
        verbose_name_plural = "Salles"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

class EmploiDuTemps(models.Model):
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, null=True, blank=True)
    niveau = models.ForeignKey(Niveau, on_delete=models.CASCADE, null=True, blank=True)
    classe = models.ForeignKey("academique.Classe", on_delete=models.SET_NULL, null=True, blank=True, related_name="emplois_du_temps_academique")
    module = models.ForeignKey(Module, on_delete=models.CASCADE)
    formateur = models.ForeignKey(Formateur, on_delete=models.CASCADE)
    jour = models.CharField(max_length=20)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    salle = models.ForeignKey(Salle, on_delete=models.CASCADE, related_name="emplois_du_temps")
    date_effective = models.DateField(null=True, blank=True, help_text="Date d'effet ou date spécifique (permet d'antidater)")

    def clean(self):
        """Validation métier (admin/tests)."""

        if self.heure_debut and self.heure_fin and self.heure_fin <= self.heure_debut:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")

        if self.classe_id:
            if self.filiere_id and self.classe.filiere_id != self.filiere_id:
                raise ValidationError("La classe fournie n'appartient pas à la filière sélectionnée.")
            if self.niveau_id and self.classe.niveau_id != self.niveau_id:
                raise ValidationError("La classe fournie n'appartient pas au niveau sélectionné.")

        # 1️⃣ Bloquer la pause par cycle
        if self.classe_id and self.classe.cycle and self.classe.cycle.type_cycle:
            cg = self.classe.cycle.type_cycle
            pause_debut = cg.heure_pause_debut
            pause_fin = cg.heure_pause_fin
            
            if self.heure_debut < pause_fin and self.heure_fin > pause_debut:
                raise ValidationError(f"⏸️ Impossible de programmer une séance pendant la pause ({pause_debut.strftime('%H:%M')}–{pause_fin.strftime('%H:%M')}).")
            
            # 1.1 Bloquer hors horaires journée
            debut_j = cg.heure_debut_journee
            fin_j = cg.heure_fin_journee
            if self.heure_debut < debut_j or self.heure_fin > fin_j:
                raise ValidationError(f"🕒 Hors créneau autorisé pour ce cycle ({debut_j.strftime('%H:%M')}–{fin_j.strftime('%H:%M')}).")
        else:
            # Fallback for old records or missing cycle info
            pause_debut = time(12, 0)
            pause_fin = time(13, 0)
            if self.heure_debut < pause_fin and self.heure_fin > pause_debut:
                raise ValidationError("⏸️ Impossible de programmer une séance pendant la pause déjeuner (12h00–13h00).")

        # Les créneaux des années précédentes ne doivent pas bloquer la nouvelle année.
        meme_annee = EmploiDuTemps.objects.all()
        if self.classe_id:
            meme_annee = meme_annee.filter(
                models.Q(classe__annee_academique_id=self.classe.annee_academique_id) | models.Q(classe__isnull=True)
            )

        # 2️⃣ Empêcher conflits de salle (hors tronc communs du même module)
        conflits_salle = meme_annee.filter(
            jour=self.jour,
            salle=self.salle,
            heure_debut__lt=self.heure_fin,
            heure_fin__gt=self.heure_debut
        ).exclude(module=self.module)

        if self.pk:
            conflits_salle = conflits_salle.exclude(pk=self.pk)

        if conflits_salle.exists():
            raise ValidationError("⚠️ Conflit de salle : cette salle est déjà occupée à ce créneau.")

        # 3️⃣ Empêcher conflits de classe
        if self.classe_id:
            conflits_classe = meme_annee.filter(
                jour=self.jour,
                classe=self.classe,
                heure_debut__lt=self.heure_fin,
                heure_fin__gt=self.heure_debut
            ).exclude(module=self.module)

            if self.pk:
                conflits_classe = conflits_classe.exclude(pk=self.pk)

            if conflits_classe.exists():
                raise ValidationError("⚠️ Conflit de classe : cette classe a déjà un cours à ce créneau.")

        # 4️⃣ Empêcher conflits de formateur
        if self.formateur_id:
            conflits_formateur = meme_annee.filter(
                jour=self.jour,
                formateur=self.formateur,
                heure_debut__lt=self.heure_fin,
                heure_fin__gt=self.heure_debut
            ).exclude(module=self.module)

            if self.pk:
                conflits_formateur = conflits_formateur.exclude(pk=self.pk)

            if conflits_formateur.exists():
                raise ValidationError("⚠️ Conflit de formateur : ce formateur a déjà un cours à ce créneau.")

    def save(self, *args, **kwargs):
        """Sauvegarde + propagation directe des tronc communs."""
        if self.classe_id:
            self.niveau = self.classe.niveau
            self.filiere = self.classe.filiere
        self.full_clean()
        super().save(*args, **kwargs)


    def delete(self, *args, **kwargs):
        """
        Suppression synchronisée des troncs communs : même module, même créneau, même
        formateur et même salle (cours commun à plusieurs classes), sur la même année.
        Auparavant seuls module + créneau étaient comparés : supprimer le cours d'une classe
        effaçait aussi ceux d'autres classes et des années précédentes.
        """
        qs = EmploiDuTemps.objects.filter(
            module=self.module,
            jour=self.jour,
            heure_debut=self.heure_debut,
            heure_fin=self.heure_fin,
            formateur=self.formateur,
            salle=self.salle,
        )
        if self.classe_id:
            qs = qs.filter(classe__annee_academique_id=self.classe.annee_academique_id)
        else:
            qs = qs.filter(pk=self.pk)
        return qs.delete()

    def __str__(self):
        return f"{self.filiere} | {self.jour} {self.heure_debut}-{self.heure_fin} | {self.module} ({self.formateur})"


class EmploiDuTempsDocument(models.Model):
    titre = models.CharField(max_length=255, default="Emploi du temps")
    classe = models.ForeignKey("academique.Classe", on_delete=models.CASCADE, related_name="emplois_du_temps_documents")
    fichier = models.FileField(upload_to="emplois_du_temps_documents/")
    description = models.TextField(blank=True, default="")
    date_effective = models.DateField(default=timezone.localdate, help_text="Date d'effet / Date de l'emploi du temps (peut être antidatée)")
    est_actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Emploi du temps (Document)"
        verbose_name_plural = "Emplois du temps (Documents)"
        ordering = ["-date_effective", "-created_at"]


    def __str__(self):
        return f"{self.titre} - {self.classe.nom}"

    @property
    def extension(self):
        if self.fichier:
            name, ext = os.path.splitext(self.fichier.name)
            return ext.lower().replace(".", "")
        return ""

    @property
    def is_pdf(self):
        return self.extension == "pdf"

    @property
    def is_image(self):
        return self.extension in ["png", "jpg", "jpeg", "webp", "gif"]

