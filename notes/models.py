# notes/models.py
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal, ROUND_HALF_UP
from etudiants.models import Etudiant
from modules.models import Module

class Note(models.Model):
    SESSION_CHOICES = [
        ("Semestre 1", "Semestre 1"),
        ("Semestre 2", "Semestre 2"),
    ]

    etudiant = models.ForeignKey(Etudiant, on_delete=models.CASCADE, related_name="notes")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="notes")
    classe = models.ForeignKey(
        "academique.Classe",
        on_delete=models.SET_NULL,
        related_name="notes",
        null=True,
        blank=True,
    )
    evaluation = models.ForeignKey(
        "academique.Evaluation",
        on_delete=models.SET_NULL,
        related_name="notes",
        null=True,
        blank=True,
    )
    session = models.CharField(max_length=20, choices=SESSION_CHOICES)
    annee_academique = models.CharField(max_length=9, default="2024-2025")
    annee_academique_ref = models.ForeignKey(
        "academique.AnneeAcademique",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )

    # ✅ Notes
    # These component fields are entered on their configured maxima (e.g. CC on 30, SN on 70)
    note_cc = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Note CC (échelle configurable, ex. 30)", validators=[MinValueValidator(0), MaxValueValidator(100)])
    note_sn = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Note SN (échelle configurable, ex. 70)", validators=[MinValueValidator(0), MaxValueValidator(100)])
    note_rattrapage = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Note Rattrapage (échelle configurable, facultatif)", validators=[MinValueValidator(0), MaxValueValidator(100)])

    # ✅ Calcul automatique
    # note_finale is stored on a 0-100 scale
    note_finale = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Note finale sur 100")

    # ✅ Validation administrative
    validee = models.BooleanField(
        default=False,
        help_text="Note visible par l'étudiant uniquement après validation par l'administration",
    )

    def clean(self):
        super().clean()
        from academique.models import ParametresGlobaux
        params = ParametresGlobaux.get_parametres()
        pc = params.pourcentage_cc or 0
        psn = params.pourcentage_sn or 0

        if self.note_cc is not None:
            self.note_cc = round(self.note_cc, 2)
            if self.note_cc > pc:
                raise ValidationError({"note_cc": f"La note CC ne peut pas dépasser la configuration de {pc}."})
        if self.note_sn is not None:
            self.note_sn = round(self.note_sn, 2)
            if self.note_sn > psn:
                raise ValidationError({"note_sn": f"La note SN ne peut pas dépasser la configuration de {psn}."})
        if self.note_rattrapage is not None:
            self.note_rattrapage = round(self.note_rattrapage, 2)
            if self.note_rattrapage > psn:
                raise ValidationError({"note_rattrapage": f"La note de rattrapage ne peut pas dépasser la configuration de {psn}."})

    def save(self, *args, **kwargs):
        self.clean()
        """
        Calcul automatique de la note finale sur 100.
        CC et SN sont saisies directement sur leurs quotas configurés
        (par exemple CC /30 et SN /70) : la note finale est donc leur somme.
        - Si rattrapage existe → SN remplacée par rattrapage
        """
        if self.evaluation_id:
            self.module = self.evaluation.module
            self.classe = self.evaluation.classe
            if self.evaluation.semestre_id:
                self.session = self.evaluation.semestre.nom
                self.annee_academique = self.evaluation.semestre.annee_academique.libelle
                self.annee_academique_ref = self.evaluation.semestre.annee_academique
            else:
                self.annee_academique = self.evaluation.classe.annee_academique.libelle
                self.annee_academique_ref = self.evaluation.classe.annee_academique
        else:
            if self.module_id and not self.session:
                self.session = self.module.semestre

            # Auto-assign classe from student's current inscription if not set
            if not self.classe_id and self.etudiant_id:
                from etudiants.models import Inscription
                inscription = Inscription.objects.filter(
                    etudiant_id=self.etudiant_id,
                    classe__isnull=False,
                ).select_related('classe__annee_academique').order_by('-date_inscription').first()
                if inscription:
                    self.classe = inscription.classe
                    self.annee_academique = inscription.classe.annee_academique.libelle
                    self.annee_academique_ref = inscription.classe.annee_academique

            # Update annee_academique from classe if set
            if self.classe_id and (not self.annee_academique or self.annee_academique == "2024-2025"):
                self.annee_academique = self.classe.annee_academique.libelle

        if not self.annee_academique_ref_id and self.classe_id and self.classe and self.classe.annee_academique_id:
            self.annee_academique_ref = self.classe.annee_academique

        m = self.module
        if m and (self.note_cc is not None or self.note_sn is not None or self.note_rattrapage is not None):
            from academique.models import ParametresGlobaux
            params = ParametresGlobaux.get_parametres()
            pc = params.pourcentage_cc or 0
            psn = params.pourcentage_sn or 0

            # Interpret component scores as entered on their configured maxima
            # e.g. if pc=30 and psn=70 then note_cc should be 0..30 and note_sn 0..70
            sn_or_r = self.note_rattrapage if self.note_rattrapage is not None else self.note_sn

            try:
                cc_val = float(self.note_cc) if self.note_cc is not None else 0.0
            except Exception:
                cc_val = 0.0
            try:
                sn_val = float(sn_or_r) if sn_or_r is not None else 0.0
            except Exception:
                sn_val = 0.0

            # Chaque composante est déjà saisie sur son propre quota :
            # CC / pc + SN / psn donne directement une note finale /100.
            contrib_cc = cc_val if pc > 0 else 0.0
            contrib_sn = sn_val if psn > 0 else 0.0
            total = contrib_cc + contrib_sn
            # Clamp to 0-100
            if total < 0:
                total = 0.0
            if total > 100:
                total = 100.0

            self.note_finale = Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


    @property
    def note_sur_20(self):
        """Retourne la note finale mise à l'échelle sur 20 (à partir de la valeur stockée sur 100)."""
        if self.note_finale is None:
            return None
        try:
            return round((float(self.note_finale) / 100.0) * 20.0, 2)
        except Exception:
            return None

    @property
    def besoin_rattrapage(self):
        """Retourne True si la note finale est inférieure à 45/100."""
        n20 = self.note_sur_20
        return (n20 is not None) and (n20 < 9)

    # ✅ Méthodes globales pour un étudiant
    @classmethod
    def moyenne_etudiant(cls, etudiant, session=None):
        """
        Calcule la moyenne générale pondérée par coefficients (sur 100).
        - Si session est précisée → moyenne pour ce semestre uniquement.
        - Sinon → moyenne sur toutes les notes.
        """
        notes = cls.objects.filter(etudiant=etudiant).select_related("module")
        if session:
            notes = notes.filter(session=session)

        total_coeff = 0
        total_points = 0.0
        for n in notes:
            if n.note_finale is not None and n.module is not None:
                coeff = getattr(n.module, "coefficient", 1) or 1
                total_coeff += coeff
                total_points += float(n.note_finale) * coeff

        if total_coeff == 0:
            return None  # aucune note saisie

        return round(total_points / total_coeff, 2)

    @classmethod
    def mention_etudiant(cls, etudiant, session=None):
        """
        Détermine la mention globale d'un étudiant selon sa moyenne.
        """
        moyenne = cls.moyenne_etudiant(etudiant, session=session)
        if moyenne is None:
            return "--"  # pas encore de notes

        if moyenne < 50:
            return "Échec"
        elif 50 <= moyenne < 60:
            return "Passable"
        elif 60 <= moyenne < 70:
            return "Assez Bien"
        elif 70 <= moyenne < 80:
            return "Bien"
        else:
            return "Très Bien"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["etudiant", "module", "classe", "evaluation", "session"],
                name="unique_note_per_student_module_classe_eval_session",
            ),
        ]

    def __str__(self):
        return f"{self.etudiant.nom} - {self.module.nom} ({self.session}) : {self.note_finale or '--'}"
