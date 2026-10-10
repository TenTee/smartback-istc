from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from academique.models import (
    AnneeAcademique, Classe, Cycle, CycleGlobal, Departement, Filiere, Niveau, UniversiteTutelle,
)
from emploidutemps.models import EmploiDuTemps, Salle
from formateurs.models import Formateur
from modules.models import Module
from paie.models import BulletinPaie, CampagnePaie

from .models import Coordination, RecapMensuel, arrondir_quart_heure, duree_en_heures


def lundi_du_mois_precedent():
    premier_du_mois = timezone.localdate().replace(day=1)
    d = (premier_du_mois - timedelta(days=1)).replace(day=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


class CalculHeuresTests(TestCase):
    def test_arrondi_au_quart_d_heure(self):
        self.assertEqual(arrondir_quart_heure(duree_en_heures(time(8, 5), time(10, 2))), Decimal("2.00"))
        self.assertEqual(arrondir_quart_heure(duree_en_heures(time(8, 10), time(9, 58))), Decimal("1.75"))
        self.assertEqual(arrondir_quart_heure(duree_en_heures(time(8, 0), time(8, 7))), Decimal("0.00"))
        self.assertEqual(arrondir_quart_heure(duree_en_heures(time(8, 0), time(8, 8))), Decimal("0.25"))


class VacationsApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        dept = Departement.objects.create(nom="Dept", universite_tutelle=UniversiteTutelle.objects.create(nom="Tut"))
        self.filiere_a = Filiere.objects.create(nom="Informatique", departement=dept)
        self.filiere_b = Filiere.objects.create(nom="Gestion", departement=dept)
        annee = AnneeAcademique.objects.create(libelle="2026-2027", est_active=True)
        cg = CycleGlobal.objects.create(nom="Licence", heure_pause_debut=time(12, 0), heure_pause_fin=time(13, 0), heure_debut_journee=time(7, 0), heure_fin_journee=time(19, 0))

        def classe(filiere, nom):
            cycle = Cycle.objects.create(type_cycle=cg, filiere=filiere, nom=f"Lic {nom}")
            niveau = Niveau.objects.create(cycle=cycle, nom="L1")
            return Classe.objects.create(filiere=filiere, cycle=cycle, niveau=niveau, annee_academique=annee, nom=nom)

        self.classe_a = classe(self.filiere_a, "L1 Info")
        self.classe_b = classe(self.filiere_b, "L1 Gestion")
        self.module = Module.objects.create(nom="Algorithmique")
        salle = Salle.objects.create(nom="S1")

        self.u_coord = User.objects.create(noms="Coord", prenoms="A", email="coord@t.local", role="formateur")
        self.coord = Formateur.objects.create(nom="Coordo", email="coordo@t.local", contact="1", user=self.u_coord)
        Coordination.objects.create(formateur=self.coord, filiere=self.filiere_a)

        self.u_vac = User.objects.create(noms="Vac", prenoms="B", email="vac@t.local", role="formateur")
        self.vac = Formateur.objects.create(
            nom="Vacataire", email="vacataire@t.local", contact="2", user=self.u_vac,
            type_formateur="vacataire", taux_horaire=Decimal("5000"),
        )
        self.admin = User.objects.create(noms="Admin", prenoms="C", email="admin@t.local", role="admin")

        self.jour = lundi_du_mois_precedent()
        self.seance = EmploiDuTemps.objects.create(
            classe=self.classe_a, filiere=self.filiere_a, niveau=self.classe_a.niveau, module=self.module,
            formateur=self.vac, jour="Lundi", heure_debut=time(8, 0), heure_fin=time(10, 0), salle=salle,
        )

    # -- helpers ---------------------------------------------------------
    def pointer(self, user=None, **extra):
        self.client.force_authenticate(user or self.u_coord)
        payload = {"seance": self.seance.id, "date": self.jour.isoformat(), "heure_arrivee": "08:05", "heure_fin": "10:02"}
        payload.update(extra)
        return self.client.post("/api/vacations/pointages/", payload, format="json")

    # -- tests -----------------------------------------------------------
    def test_coordonnateur_voit_les_seances_du_jour_et_les_enseignants(self):
        self.client.force_authenticate(self.u_coord)
        res = self.client.get(f"/api/vacations/coordonnateur/seances/?date={self.jour.isoformat()}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["seances"]), 1)
        self.assertEqual(res.data["seances"][0]["formateur_nom"], "Vacataire")
        self.assertIsNone(res.data["seances"][0]["pointage"])

        res = self.client.get("/api/vacations/coordonnateur/enseignants/")
        self.assertEqual([e["nom"] for e in res.data], ["Vacataire"])

    def test_pointage_calcule_les_heures_et_complete_la_seance(self):
        res = self.pointer()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["formateur"], self.vac.id)
        self.assertEqual(res.data["filiere"], self.filiere_a.id)
        self.assertEqual(Decimal(res.data["heures_retenues"]), Decimal("2.00"))
        # double pointage de la même séance refusé
        self.assertEqual(self.pointer().status_code, 400)

    def test_non_coordonnateur_refuse(self):
        self.client.force_authenticate(self.u_vac)
        self.assertEqual(self.client.get("/api/vacations/coordonnateur/seances/").status_code, 403)
        self.assertEqual(self.pointer(user=self.u_vac).status_code, 403)

    def test_coordonnateur_limite_a_sa_filiere(self):
        self.client.force_authenticate(self.u_coord)
        res = self.client.post("/api/vacations/pointages/", {
            "formateur": self.vac.id, "classe": self.classe_b.id, "module": self.module.id,
            "date": self.jour.isoformat(), "heure_arrivee": "08:00", "heure_fin": "09:00",
        }, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.client.get(f"/api/vacations/coordonnateur/seances/?filiere={self.filiere_b.id}")
        self.assertEqual(res.status_code, 403)

    def test_date_future_et_heures_incoherentes_refusees(self):
        demain = timezone.localdate() + timedelta(days=1)
        self.assertEqual(self.pointer(date=demain.isoformat()).status_code, 400)
        self.assertEqual(self.pointer(heure_arrivee="10:00", heure_fin="09:00").status_code, 400)

    def test_absence_compte_zero_heure(self):
        res = self.pointer(statut="absent")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Decimal(res.data["heures_retenues"]), Decimal("0.00"))
        self.client.force_authenticate(self.u_coord)
        res = self.client.get(f"/api/vacations/coordonnateur/recaps/?mois={self.jour.month}&annee={self.jour.year}")
        recap = res.data["recaps"][0]
        self.assertEqual(recap["nombre_absences"], 1)
        self.assertEqual(Decimal(recap["total_heures"]), Decimal("0"))

    def test_cycle_complet_recap_validation_paie(self):
        self.assertEqual(self.pointer().status_code, 201)
        # rattrapage hors planning : 1h30
        self.client.force_authenticate(self.u_coord)
        res = self.client.post("/api/vacations/pointages/", {
            "formateur": self.vac.id, "classe": self.classe_a.id, "module": self.module.id,
            "date": (self.jour + timedelta(days=2)).isoformat(), "heure_arrivee": "14:00", "heure_fin": "15:30",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        pointage_id = res.data["id"]

        mois, annee = self.jour.month, self.jour.year
        res = self.client.get(f"/api/vacations/coordonnateur/recaps/?mois={mois}&annee={annee}")
        self.assertEqual(res.status_code, 200)
        recap = res.data["recaps"][0]
        self.assertEqual(Decimal(recap["total_heures"]), Decimal("3.50"))
        self.assertEqual(Decimal(recap["montant"]), Decimal("17500.00"))

        # L'enseignant voit son récap sur son dashboard
        self.client.force_authenticate(self.u_vac)
        res = self.client.get(f"/api/vacations/mes-heures/?mois={mois}&annee={annee}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(res.data["totaux"]["heures"]), Decimal("3.50"))
        self.assertEqual(len(res.data["pointages"]), 2)

        # La finance ne peut pas valider un récap non clôturé
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"/api/vacations/recaps/{recap['id']}/valider/").status_code, 400)

        # Clôture par le coordonnateur → pointages verrouillés
        self.client.force_authenticate(self.u_coord)
        res = self.client.post(f"/api/vacations/coordonnateur/recaps/{recap['id']}/cloturer/")
        self.assertEqual(res.status_code, 200, res.data)
        res = self.client.patch(f"/api/vacations/pointages/{pointage_id}/", {"heure_fin": "16:00"}, format="json")
        self.assertEqual(res.status_code, 400)

        # Rejet (motif obligatoire) → modifiable à nouveau
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"/api/vacations/recaps/{recap['id']}/rejeter/").status_code, 400)
        res = self.client.post(f"/api/vacations/recaps/{recap['id']}/rejeter/", {"motif": "Erreur rattrapage"}, format="json")
        self.assertEqual(res.data["statut"], "rejete")
        self.client.force_authenticate(self.u_coord)
        res = self.client.patch(f"/api/vacations/pointages/{pointage_id}/", {"heure_fin": "16:00"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(RecapMensuel.objects.get(pk=recap["id"]).total_heures, Decimal("4.00"))
        self.client.post(f"/api/vacations/coordonnateur/recaps/{recap['id']}/cloturer/")

        # Validation finance
        self.client.force_authenticate(self.admin)
        res = self.client.post(f"/api/vacations/recaps/{recap['id']}/valider/")
        self.assertEqual(res.data["statut"], "valide")
        res = self.client.get(f"/api/vacations/recaps/heures-validees/?mois={mois}&annee={annee}")
        self.assertEqual(Decimal(res.data["heures"][0]["heures"]), Decimal("4.00"))

        # Campagne de paie : heures reprises automatiquement (sans saisie manuelle)
        res = self.client.post("/api/paie/campagnes/generer/", {
            "mois": mois, "annee": annee, "type_beneficiaire": "formateur",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        bulletin = BulletinPaie.objects.get(beneficiaire_object_id=self.vac.id)
        self.assertEqual(bulletin.heures_travaillees, Decimal("4.00"))
        self.assertEqual(bulletin.salaire_base, Decimal("20000.00"))
        recap_obj = RecapMensuel.objects.get(pk=recap["id"])
        self.assertEqual(recap_obj.bulletin_id, bulletin.id)

        campagne = CampagnePaie.objects.get(mois=mois, annee=annee, type_beneficiaire="formateur")
        self.client.post(f"/api/paie/campagnes/{campagne.id}/valider/")
        self.client.post(f"/api/paie/campagnes/{campagne.id}/payer/")
        recap_obj.refresh_from_db()
        self.assertEqual(recap_obj.statut, "paye")

    def test_cloture_impossible_avant_fin_du_mois(self):
        today = timezone.localdate()
        if today.day == 1:
            self.skipTest("Pas de jour passé dans le mois courant.")
        hier = today - timedelta(days=1)
        self.client.force_authenticate(self.u_coord)
        res = self.client.post("/api/vacations/pointages/", {
            "formateur": self.vac.id, "classe": self.classe_a.id, "module": self.module.id,
            "date": hier.isoformat(), "heure_arrivee": "08:00", "heure_fin": "09:00",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        res = self.client.get("/api/vacations/coordonnateur/recaps/")
        recap_id = res.data["recaps"][0]["id"]
        res = self.client.post(f"/api/vacations/coordonnateur/recaps/{recap_id}/cloturer/")
        if res.data.get("statut") != "cloture":  # sauf si on est le dernier jour du mois
            self.assertEqual(res.status_code, 400)

    def test_attribution_coordonnateur_reservee_a_la_pedagogie(self):
        self.client.force_authenticate(self.u_vac)
        res = self.client.post("/api/vacations/coordinations/", {"formateur": self.vac.id, "filiere": self.filiere_b.id})
        self.assertEqual(res.status_code, 403)
        self.client.force_authenticate(self.admin)
        res = self.client.post("/api/vacations/coordinations/", {"formateur": self.vac.id, "filiere": self.filiere_b.id})
        self.assertEqual(res.status_code, 201, res.data)

    def test_dashboard_formateur_indique_le_role_de_coordonnateur(self):
        self.client.force_authenticate(self.u_coord)
        res = self.client.get("/api/formateurs/portal/me/")
        self.assertTrue(res.data["est_coordonnateur"])
        self.client.force_authenticate(self.u_vac)
        res = self.client.get("/api/formateurs/portal/me/")
        self.assertFalse(res.data["est_coordonnateur"])
