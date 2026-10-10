from datetime import date as date_cls

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response

from users.permissions import user_has_read_access, user_has_write_access
from .models import Coordination, PointageEnseignant, RecapMensuel
from .serializers import CoordinationSerializer, PointageEnseignantSerializer, RecapMensuelSerializer
from . import services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(valeur, defaut=None):
    if not valeur:
        return defaut or timezone.localdate()
    try:
        return date_cls.fromisoformat(str(valeur))
    except ValueError:
        raise ValidationError({"date": "Format attendu : AAAA-MM-JJ."})


def _parse_mois_annee(request):
    today = timezone.localdate()
    try:
        mois = int(request.query_params.get("mois") or request.data.get("mois") or today.month)
        annee = int(request.query_params.get("annee") or request.data.get("annee") or today.year)
    except (TypeError, ValueError):
        raise ValidationError({"mois": "mois et annee doivent être des entiers."})
    if not 1 <= mois <= 12:
        raise ValidationError({"mois": "Le mois doit être compris entre 1 et 12."})
    return mois, annee


def _est_admin_pedagogie(user, ecriture=False):
    fn = user_has_write_access if ecriture else user_has_read_access
    return fn(user, "can_manage_pedagogie")


def _est_admin_finance(user, ecriture=False):
    fn = user_has_write_access if ecriture else user_has_read_access
    return fn(user, "can_manage_finance")


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class CoordinationPermission(BasePermission):
    """Attribution des coordonnateurs : réservée à la pédagogie (lecture / écriture)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return _est_admin_pedagogie(user, ecriture=request.method not in SAFE_METHODS)


class EstCoordonnateur(BasePermission):
    message = "Vous n'êtes coordonnateur d'aucune filière."

    def has_permission(self, request, view):
        return bool(services.filieres_coordonnees_ids(request.user))


class RecapAdminPermission(BasePermission):
    """Lecture : finance ou pédagogie. Validation / rejet : finance en écriture."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return _est_admin_finance(user) or _est_admin_pedagogie(user)
        return _est_admin_finance(user, ecriture=True)


# ---------------------------------------------------------------------------
# Administration : coordonnateurs
# ---------------------------------------------------------------------------

class CoordinationViewSet(viewsets.ModelViewSet):
    serializer_class = CoordinationSerializer
    permission_classes = [IsAuthenticated, CoordinationPermission]
    filterset_fields = ["formateur", "filiere", "est_active"]

    def get_queryset(self):
        return Coordination.objects.select_related("formateur", "filiere")


# ---------------------------------------------------------------------------
# Pointages (coordonnateur ; lecture seule pour la pédagogie)
# ---------------------------------------------------------------------------

class PointageEnseignantViewSet(viewsets.ModelViewSet):
    serializer_class = PointageEnseignantSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["formateur", "filiere", "classe", "module", "statut", "date"]

    def get_queryset(self):
        user = self.request.user
        qs = PointageEnseignant.objects.select_related("formateur", "filiere", "classe", "module", "saisi_par")
        filieres = services.filieres_coordonnees_ids(user)
        if _est_admin_pedagogie(user) or _est_admin_finance(user):
            pass
        elif filieres:
            qs = qs.filter(filiere_id__in=filieres)
        else:
            return qs.none()

        params = self.request.query_params
        if params.get("mois") and params.get("annee"):
            qs = qs.filter(date__month=params["mois"], date__year=params["annee"])
        if params.get("date_debut"):
            qs = qs.filter(date__gte=params["date_debut"])
        if params.get("date_fin"):
            qs = qs.filter(date__lte=params["date_fin"])
        return qs

    def _verifier_droit_ecriture(self, filiere_id):
        user = self.request.user
        if filiere_id in services.filieres_coordonnees_ids(user):
            return
        if _est_admin_pedagogie(user, ecriture=True):
            return
        raise PermissionDenied("Seul le coordonnateur de cette filière peut saisir les présences.")

    def _verifier_non_verrouille(self, pointage):
        if pointage.est_verrouille:
            raise ValidationError(
                {"detail": "Le récapitulatif de ce mois est clôturé : rouvrez-le avant de modifier les pointages."}
            )

    @transaction.atomic
    def perform_create(self, serializer):
        filiere = serializer.validated_data["filiere"]
        self._verifier_droit_ecriture(filiere.id)
        pointage = PointageEnseignant(**serializer.validated_data)
        self._verifier_non_verrouille(pointage)
        instance = serializer.save(saisi_par=self.request.user)
        services.mettre_a_jour_recap_du_pointage(instance)

    @transaction.atomic
    def perform_update(self, serializer):
        ancien = serializer.instance
        self._verifier_droit_ecriture(ancien.filiere_id)
        self._verifier_non_verrouille(ancien)
        nouvelle_filiere = serializer.validated_data.get("filiere")
        if nouvelle_filiere and nouvelle_filiere.id != ancien.filiere_id:
            self._verifier_droit_ecriture(nouvelle_filiere.id)
        ancien_snapshot = PointageEnseignant(
            formateur_id=ancien.formateur_id, filiere_id=ancien.filiere_id, date=ancien.date
        )
        instance = serializer.save(saisi_par=self.request.user)
        self._verifier_non_verrouille(instance)
        services.mettre_a_jour_recap_du_pointage(ancien_snapshot)
        services.mettre_a_jour_recap_du_pointage(instance)

    @transaction.atomic
    def perform_destroy(self, instance):
        self._verifier_droit_ecriture(instance.filiere_id)
        self._verifier_non_verrouille(instance)
        snapshot = PointageEnseignant(
            formateur_id=instance.formateur_id, filiere_id=instance.filiere_id, date=instance.date
        )
        instance.delete()
        services.mettre_a_jour_recap_du_pointage(snapshot)


# ---------------------------------------------------------------------------
# Espace coordonnateur (portail formateur)
# ---------------------------------------------------------------------------

class CoordonnateurViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, EstCoordonnateur]

    def _filieres(self, request):
        ids = services.filieres_coordonnees_ids(request.user)
        filiere = request.query_params.get("filiere") or request.data.get("filiere")
        if filiere:
            try:
                filiere = int(filiere)
            except (TypeError, ValueError):
                raise ValidationError({"filiere": "Identifiant invalide."})
            if filiere not in ids:
                raise PermissionDenied("Vous n'êtes pas coordonnateur de cette filière.")
            return {filiere}
        return ids

    @action(detail=False, methods=["get"], url_path="mes-filieres")
    def mes_filieres(self, request):
        from academique.models import Filiere

        ids = services.filieres_coordonnees_ids(request.user)
        data = [{"id": f.id, "nom": f.nom, "code": f.code} for f in Filiere.objects.filter(id__in=ids).order_by("nom")]
        return Response(data)

    @action(detail=False, methods=["get"], url_path="enseignants")
    def enseignants(self, request):
        return Response(services.enseignants_de_filiere(self._filieres(request)))

    @action(detail=False, methods=["get"], url_path="seances")
    def seances(self, request):
        """Séances planifiées du jour + leur pointage, et pointages hors planning (rattrapages)."""
        jour = _parse_date(request.query_params.get("date"))
        filieres = self._filieres(request)
        seances, pointages = services.seances_du_jour(filieres, jour)

        lignes = []
        for s in seances:
            p = pointages.get(s.id)
            lignes.append({
                "seance_id": s.id,
                "planifiee": True,
                "formateur": s.formateur_id,
                "formateur_nom": s.formateur.nom,
                "type_formateur": s.formateur.type_formateur,
                "filiere": services.filiere_de_seance(s),
                "classe": s.classe_id,
                "classe_nom": s.classe.nom if s.classe_id else "",
                "module": s.module_id,
                "module_nom": s.module.nom if s.module_id else "",
                "salle_nom": s.salle.nom if s.salle_id else "",
                "heure_debut_prevue": s.heure_debut.strftime("%H:%M"),
                "heure_fin_prevue": s.heure_fin.strftime("%H:%M"),
                "pointage": PointageEnseignantSerializer(p).data if p else None,
            })

        for p in services.pointages_hors_planning(filieres, jour):
            lignes.append({
                "seance_id": None,
                "planifiee": False,
                "formateur": p.formateur_id,
                "formateur_nom": p.formateur.nom,
                "type_formateur": p.formateur.type_formateur,
                "filiere": p.filiere_id,
                "classe": p.classe_id,
                "classe_nom": p.classe.nom if p.classe_id else "",
                "module": p.module_id,
                "module_nom": p.module.nom if p.module_id else "",
                "salle_nom": "",
                "heure_debut_prevue": p.heure_debut_prevue.strftime("%H:%M") if p.heure_debut_prevue else "",
                "heure_fin_prevue": p.heure_fin_prevue.strftime("%H:%M") if p.heure_fin_prevue else "",
                "pointage": PointageEnseignantSerializer(p).data,
            })

        return Response({
            "date": jour.isoformat(),
            "jour": services.jour_de_la_semaine(jour),
            "est_futur": jour > timezone.localdate(),
            "seances": lignes,
        })

    @action(detail=False, methods=["get"], url_path="recaps")
    def recaps(self, request):
        mois, annee = _parse_mois_annee(request)
        filieres = self._filieres(request)
        services.synchroniser_recaps(mois, annee, filiere_ids=filieres)
        qs = RecapMensuel.objects.filter(mois=mois, annee=annee, filiere_id__in=filieres).select_related(
            "formateur", "filiere", "cloture_par", "valide_par"
        )
        return Response({
            "mois": mois,
            "annee": annee,
            "mois_termine": services.mois_termine(mois, annee),
            "recaps": RecapMensuelSerializer(qs, many=True).data,
        })

    def _get_recap(self, request, pk):
        recap = RecapMensuel.objects.filter(pk=pk).select_related("formateur", "filiere").first()
        if not recap:
            raise ValidationError({"detail": "Récapitulatif introuvable."})
        if recap.filiere_id not in services.filieres_coordonnees_ids(request.user):
            raise PermissionDenied("Vous n'êtes pas coordonnateur de cette filière.")
        return recap

    @action(detail=False, methods=["post"], url_path=r"recaps/(?P<pk>[0-9]+)/cloturer")
    @transaction.atomic
    def cloturer(self, request, pk=None):
        recap = self._get_recap(request, pk)
        if recap.statut not in (RecapMensuel.STATUT_OUVERT, RecapMensuel.STATUT_REJETE):
            raise ValidationError({"detail": "Seul un récapitulatif ouvert ou rejeté peut être clôturé."})
        if not services.mois_termine(recap.mois, recap.annee):
            raise ValidationError({"detail": "Le récapitulatif ne peut être clôturé qu'à partir du dernier jour du mois."})
        recap.recalculer()
        recap.statut = RecapMensuel.STATUT_CLOTURE
        recap.cloture_par = request.user
        recap.date_cloture = timezone.now()
        recap.commentaire_coordonnateur = str(request.data.get("commentaire", "") or recap.commentaire_coordonnateur)
        recap.save()
        return Response(RecapMensuelSerializer(recap).data)

    @action(detail=False, methods=["post"], url_path="recaps/cloturer-tout")
    @transaction.atomic
    def cloturer_tout(self, request):
        mois, annee = _parse_mois_annee(request)
        if not services.mois_termine(mois, annee):
            raise ValidationError({"detail": "Le mois n'est pas encore terminé."})
        filieres = self._filieres(request)
        services.synchroniser_recaps(mois, annee, filiere_ids=filieres)
        recaps = RecapMensuel.objects.filter(
            mois=mois, annee=annee, filiere_id__in=filieres,
            statut__in=(RecapMensuel.STATUT_OUVERT, RecapMensuel.STATUT_REJETE),
        )
        n = 0
        for recap in recaps:
            recap.recalculer()
            recap.statut = RecapMensuel.STATUT_CLOTURE
            recap.cloture_par = request.user
            recap.date_cloture = timezone.now()
            recap.save()
            n += 1
        return Response({"clotures": n})

    @action(detail=False, methods=["post"], url_path=r"recaps/(?P<pk>[0-9]+)/rouvrir")
    @transaction.atomic
    def rouvrir(self, request, pk=None):
        recap = self._get_recap(request, pk)
        if recap.statut != RecapMensuel.STATUT_CLOTURE:
            raise ValidationError({"detail": "Seul un récapitulatif clôturé (non encore validé) peut être rouvert."})
        recap.statut = RecapMensuel.STATUT_OUVERT
        recap.date_cloture = None
        recap.cloture_par = None
        recap.save()
        return Response(RecapMensuelSerializer(recap).data)


# ---------------------------------------------------------------------------
# Espace enseignant : mes heures
# ---------------------------------------------------------------------------

class MesHeuresViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        formateur = services.get_formateur(request.user)
        if not formateur:
            return Response({"detail": "Profil formateur introuvable."}, status=status.HTTP_404_NOT_FOUND)
        mois, annee = _parse_mois_annee(request)
        services.synchroniser_recaps(mois, annee, formateur=formateur)

        recaps = RecapMensuel.objects.filter(formateur=formateur, mois=mois, annee=annee).select_related("filiere")
        pointages = PointageEnseignant.objects.filter(
            formateur=formateur, date__month=mois, date__year=annee
        ).select_related("filiere", "classe", "module").order_by("date", "heure_arrivee")

        recaps_data = RecapMensuelSerializer(recaps, many=True).data
        total_heures = sum((r.total_heures for r in recaps), 0)
        montant = sum((r.montant for r in recaps), 0)
        montant_valide = sum(
            (r.montant for r in recaps if r.statut in (RecapMensuel.STATUT_VALIDE, RecapMensuel.STATUT_PAYE)), 0
        )
        return Response({
            "formateur": {
                "id": formateur.id,
                "nom": formateur.nom,
                "type_formateur": formateur.type_formateur,
                "taux_horaire": str(formateur.taux_horaire or 0),
            },
            "mois": mois,
            "annee": annee,
            "totaux": {
                "heures": str(total_heures),
                "seances": sum(r.nombre_seances for r in recaps),
                "absences": sum(r.nombre_absences for r in recaps),
                "montant_estime": str(montant),
                "montant_valide": str(montant_valide),
            },
            "recaps": recaps_data,
            "pointages": PointageEnseignantSerializer(pointages, many=True).data,
        })

    @action(detail=False, methods=["get"], url_path="historique")
    def historique(self, request):
        formateur = services.get_formateur(request.user)
        if not formateur:
            return Response({"detail": "Profil formateur introuvable."}, status=status.HTTP_404_NOT_FOUND)
        lignes = {}
        for r in RecapMensuel.objects.filter(formateur=formateur).order_by("-annee", "-mois")[:60]:
            cle = (r.annee, r.mois)
            e = lignes.setdefault(cle, {"annee": r.annee, "mois": r.mois, "heures": 0, "montant": 0, "statuts": set()})
            e["heures"] += r.total_heures
            e["montant"] += r.montant
            e["statuts"].add(r.statut)
        data = []
        for e in list(lignes.values())[:12]:
            data.append({**e, "heures": str(e["heures"]), "montant": str(e["montant"]), "statuts": sorted(e["statuts"])})
        return Response(data)


# ---------------------------------------------------------------------------
# Administration : validation finance des récaps
# ---------------------------------------------------------------------------

class RecapAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = RecapMensuelSerializer
    permission_classes = [IsAuthenticated, RecapAdminPermission]
    filterset_fields = ["mois", "annee", "statut", "filiere", "formateur"]

    def get_queryset(self):
        return RecapMensuel.objects.select_related("formateur", "filiere", "cloture_par", "valide_par")

    @action(detail=True, methods=["get"], url_path="pointages")
    def pointages(self, request, pk=None):
        recap = self.get_object()
        qs = recap.pointages().select_related("filiere", "classe", "module", "formateur").order_by("date", "heure_arrivee")
        return Response(PointageEnseignantSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="valider")
    @transaction.atomic
    def valider(self, request, pk=None):
        recap = self.get_object()
        if recap.statut != RecapMensuel.STATUT_CLOTURE:
            raise ValidationError({"detail": "Seul un récapitulatif clôturé par le coordonnateur peut être validé."})
        recap.statut = RecapMensuel.STATUT_VALIDE
        recap.valide_par = request.user
        recap.date_validation = timezone.now()
        recap.motif_rejet = ""
        recap.save()
        return Response(self.get_serializer(recap).data)

    @action(detail=True, methods=["post"], url_path="rejeter")
    @transaction.atomic
    def rejeter(self, request, pk=None):
        recap = self.get_object()
        if recap.statut not in (RecapMensuel.STATUT_CLOTURE, RecapMensuel.STATUT_VALIDE):
            raise ValidationError({"detail": "Seul un récapitulatif clôturé ou validé (non payé) peut être rejeté."})
        if recap.bulletin_id:
            raise ValidationError({"detail": "Ce récapitulatif est déjà intégré à une campagne de paie."})
        motif = str(request.data.get("motif", "") or "").strip()
        if not motif:
            raise ValidationError({"motif": "Le motif du rejet est obligatoire."})
        recap.statut = RecapMensuel.STATUT_REJETE
        recap.motif_rejet = motif
        recap.valide_par = None
        recap.date_validation = None
        recap.save()
        return Response(self.get_serializer(recap).data)

    @action(detail=False, methods=["get"], url_path="heures-validees")
    def heures_validees(self, request):
        """Heures validées par enseignant pour un mois (pré-remplissage de la campagne de paie)."""
        mois, annee = _parse_mois_annee(request)
        data = [
            {"formateur_id": fid, "heures": str(v["heures"]), "montant": str(v["montant"]), "recaps": v["recap_ids"]}
            for fid, v in services.heures_validees_par_formateur(mois, annee).items()
        ]
        en_attente = RecapMensuel.objects.filter(
            mois=mois, annee=annee, statut__in=(RecapMensuel.STATUT_OUVERT, RecapMensuel.STATUT_CLOTURE, RecapMensuel.STATUT_REJETE)
        ).count()
        return Response({"mois": mois, "annee": annee, "heures": data, "recaps_non_valides": en_attente})
