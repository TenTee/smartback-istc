"""Logique métier des vacations (séances du jour, enseignants d'une filière, récaps)."""
import calendar
import unicodedata
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import Coordination, PointageEnseignant, RecapMensuel

JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).strip().lower()


def jour_de_la_semaine(d: date) -> str:
    return JOURS_SEMAINE[d.weekday()]


def get_formateur(user):
    return getattr(user, "formateur_profile", None) if user and user.is_authenticated else None


def filieres_coordonnees_ids(user) -> set:
    """Filières dont l'utilisateur (formateur) est coordonnateur actif."""
    formateur = get_formateur(user)
    if not formateur:
        return set()
    today = timezone.localdate()
    return set(
        Coordination.objects.filter(formateur=formateur, est_active=True)
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=today))
        .values_list("filiere_id", flat=True)
    )


def _annee_courante_id():
    try:
        from academique.middleware import get_current_academic_year_id
        return get_current_academic_year_id()
    except Exception:
        return None


def seances_filiere_qs(filiere_ids):
    """Séances d'emploi du temps rattachées aux filières (via la classe, ou la filière si pas de classe)."""
    from emploidutemps.models import EmploiDuTemps

    qs = EmploiDuTemps.objects.filter(
        Q(classe__filiere_id__in=filiere_ids) | Q(classe__isnull=True, filiere_id__in=filiere_ids)
    ).select_related("formateur", "module", "classe", "classe__filiere", "filiere", "salle")
    annee_id = _annee_courante_id()
    if annee_id:
        qs = qs.filter(Q(classe__annee_academique_id=annee_id) | Q(classe__isnull=True))
    return qs


def filiere_de_seance(seance):
    if seance.classe_id and seance.classe.filiere_id:
        return seance.classe.filiere_id
    return seance.filiere_id


def seances_du_jour(filiere_ids, jour: date):
    """Séances planifiées un jour donné (jour de semaine + date d'effet), avec leur pointage éventuel."""
    nom_jour = jour_de_la_semaine(jour)
    seances = [
        s for s in seances_filiere_qs(filiere_ids)
        if _normaliser(s.jour) == nom_jour and (not s.date_effective or s.date_effective <= jour)
    ]
    seances.sort(key=lambda s: (s.heure_debut, s.formateur.nom))

    pointages = {
        p.seance_id: p
        for p in PointageEnseignant.objects.filter(date=jour, seance_id__in=[s.id for s in seances])
    }
    return seances, pointages


def pointages_hors_planning(filiere_ids, jour: date):
    return (
        PointageEnseignant.objects.filter(date=jour, filiere_id__in=filiere_ids, seance__isnull=True)
        .select_related("formateur", "module", "classe", "filiere")
    )


def enseignants_de_filiere(filiere_ids):
    """Enseignants devant intervenir dans les filières (affectations + emploi du temps)."""
    from academique.models import Affectation

    resultat = {}

    def _ajouter(formateur, filiere_id, module, classe):
        entree = resultat.setdefault(formateur.id, {
            "id": formateur.id,
            "nom": formateur.nom,
            "email": formateur.email,
            "contact": formateur.contact,
            "type_formateur": formateur.type_formateur,
            "taux_horaire": str(formateur.taux_horaire or 0),
            "filieres": set(),
            "cours": {},
        })
        entree["filieres"].add(filiere_id)
        if module:
            cle = (module.id, classe.id if classe else None)
            entree["cours"][cle] = {
                "module_id": module.id,
                "module_nom": module.nom,
                "classe_id": classe.id if classe else None,
                "classe_nom": classe.nom if classe else "",
            }

    aff_qs = Affectation.objects.filter(classe__filiere_id__in=filiere_ids).select_related("enseignant", "module", "classe")
    annee_id = _annee_courante_id()
    if annee_id:
        aff_qs = aff_qs.filter(classe__annee_academique_id=annee_id)
    for aff in aff_qs:
        _ajouter(aff.enseignant, aff.classe.filiere_id, aff.module, aff.classe)

    for s in seances_filiere_qs(filiere_ids):
        _ajouter(s.formateur, filiere_de_seance(s), s.module, s.classe)

    enseignants = []
    for e in resultat.values():
        e["filieres"] = sorted(e["filieres"])
        e["cours"] = sorted(e["cours"].values(), key=lambda c: (c["module_nom"], c["classe_nom"]))
        enseignants.append(e)
    return sorted(enseignants, key=lambda e: e["nom"].lower())


def synchroniser_recaps(mois: int, annee: int, filiere_ids=None, formateur=None):
    """
    Crée/met à jour les récaps du mois pour chaque couple (enseignant, filière) ayant des pointages.
    Seuls les récaps ouverts ou rejetés sont recalculés (les autres sont figés).
    """
    qs = PointageEnseignant.objects.filter(date__month=mois, date__year=annee)
    if filiere_ids is not None:
        qs = qs.filter(filiere_id__in=filiere_ids)
    if formateur is not None:
        qs = qs.filter(formateur=formateur)

    couples = set(qs.values_list("formateur_id", "filiere_id"))
    recaps = []
    for formateur_id, filiere_id in couples:
        recap, _ = RecapMensuel.objects.get_or_create(
            formateur_id=formateur_id, filiere_id=filiere_id, mois=mois, annee=annee
        )
        if recap.statut in (RecapMensuel.STATUT_OUVERT, RecapMensuel.STATUT_REJETE):
            recap.recalculer()
            recap.save()
        recaps.append(recap)

    # Récaps ouverts dont tous les pointages ont été supprimés : remis à zéro.
    orphelins = RecapMensuel.objects.filter(mois=mois, annee=annee, statut=RecapMensuel.STATUT_OUVERT)
    if filiere_ids is not None:
        orphelins = orphelins.filter(filiere_id__in=filiere_ids)
    if formateur is not None:
        orphelins = orphelins.filter(formateur=formateur)
    for recap in orphelins.exclude(id__in=[r.id for r in recaps]):
        recap.recalculer()
        recap.save()

    return recaps


def mettre_a_jour_recap_du_pointage(pointage):
    """Recalcule le récap concerné après création/modification/suppression d'un pointage."""
    recap = RecapMensuel.objects.filter(
        formateur_id=pointage.formateur_id,
        filiere_id=pointage.filiere_id,
        mois=pointage.date.month,
        annee=pointage.date.year,
        statut__in=(RecapMensuel.STATUT_OUVERT, RecapMensuel.STATUT_REJETE),
    ).first()
    if recap:
        recap.recalculer()
        recap.save()


def mois_termine(mois: int, annee: int, aujourd_hui: date = None) -> bool:
    """Un récap ne peut être clôturé qu'à partir du dernier jour du mois."""
    aujourd_hui = aujourd_hui or timezone.localdate()
    dernier_jour = date(annee, mois, calendar.monthrange(annee, mois)[1])
    return aujourd_hui >= dernier_jour


def heures_validees_par_formateur(mois: int, annee: int):
    """{formateur_id: {"heures": Decimal, "montant": Decimal, "recap_ids": [...]}} pour les récaps validés non encore payés."""
    resultat = {}
    for recap in RecapMensuel.objects.filter(
        mois=mois, annee=annee, statut=RecapMensuel.STATUT_VALIDE, bulletin__isnull=True
    ):
        entree = resultat.setdefault(recap.formateur_id, {"heures": Decimal("0"), "montant": Decimal("0"), "recap_ids": []})
        entree["heures"] += recap.total_heures
        entree["montant"] += recap.montant
        entree["recap_ids"].append(recap.id)
    return resultat
