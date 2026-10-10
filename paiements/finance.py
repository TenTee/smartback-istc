"""
Calcul unique de la situation financière d'un étudiant pour une année académique.

Auparavant trois vues faisaient ce calcul chacune à leur manière :
- le suivi de scolarité (aggregated) tenait compte des plans personnalisés et des réductions,
- le portail étudiant (paiements/me) ignorait réductions et bourses, et additionnait les
  paiements de TOUTES les années,
- le tableau de bord financier ignorait aussi les réductions et les années.
Un même étudiant pouvait donc apparaître soldé côté administration et débiteur dans son portail.
"""
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Frais, Paiement, ReductionEtudiant, StudentPaymentPlan

ZERO = Decimal("0")


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def inscription_de_l_annee(etudiant, year_id=None):
    if year_id:
        return etudiant.inscriptions.filter(annee_academique_ref_id=year_id).select_related("classe").first()
    return etudiant.inscriptions.select_related("classe").order_by("-date_inscription").first()


def paiements_de_l_annee(etudiant, year_id=None):
    qs = Paiement.objects.filter(etudiant=etudiant)
    if year_id:
        qs = qs.filter(Q(frais__classe__annee_academique_id=year_id) | Q(frais__isnull=True))
    return qs


def situation_financiere(etudiant, year_id=None):
    inscription = inscription_de_l_annee(etudiant, year_id)
    classe = inscription.classe if inscription else None

    du_inscription = ZERO
    du_formation = ZERO
    if classe:
        frais = Frais.objects.filter(classe=classe)
        du_inscription = _sum(frais.filter(libelle__icontains="inscription"), "montant")
        du_formation = _sum(frais.exclude(libelle__icontains="inscription"), "montant")

    # Plan personnalisé (réduction appliquée aux tranches de formation)
    plan = StudentPaymentPlan.objects.filter(
        etudiant=etudiant, status=StudentPaymentPlan.STATUS_ACTIVE, is_override=True
    ).first()
    if plan:
        du_formation = Decimal(str(plan.total_amount))

    reduction = ReductionEtudiant.objects.filter(etudiant=etudiant).select_related("bourse").order_by("-created_at").first()
    if reduction and reduction.montant_reduction > 0:
        montant = Decimal(str(reduction.montant_reduction))
        if reduction.target == "INSCRIPTION":
            du_inscription = max(ZERO, du_inscription - montant)
        elif not plan:
            # Réduction sur la formation sans plan personnalisé : on la déduit ici.
            du_formation = max(ZERO, du_formation - montant)

    paiements = paiements_de_l_annee(etudiant, year_id)
    paye_inscription = _sum(paiements.filter(paiement_type="INSCRIPTION"), "montant_paye")
    paye_formation = _sum(paiements.filter(paiement_type="FORMATION"), "montant_paye")

    return {
        "inscription": inscription,
        "classe": classe,
        "reduction": reduction,
        "plan": plan,
        "paiements": paiements,
        "du_inscription": du_inscription,
        "du_formation": du_formation,
        "paye_inscription": paye_inscription,
        "paye_formation": paye_formation,
        "du_total": du_inscription + du_formation,
        "paye_total": paye_inscription + paye_formation,
    }
