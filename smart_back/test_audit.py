"""
Tests de non-régression des corrections de l'audit (octobre 2026).
Chaque test correspond à un bug identifié et corrigé.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from academique.models import (
    AnneeAcademique, Classe, Cycle, CycleGlobal, Departement, Filiere, Niveau, PreInscription, UniversiteTutelle,
)
from conges.models import Conge
from demandes.models import DemandeArticle, LigneDemande
from emploidutemps.models import EmploiDuTemps, Salle
from etudiants.models import Etudiant, Inscription
from formateurs.models import Formateur
from inventaires.models import Article, Mouvement
from modules.models import Module
from notes.models import Note
from paie.models import CampagnePaie
from paiements.models import Frais, Paiement, ReductionEtudiant
from personnels.models import Personnel
from users.models import Role

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        dept = Departement.objects.create(nom="Dept", universite_tutelle=UniversiteTutelle.objects.create(nom="Tut"))
        self.filiere = Filiere.objects.create(nom="Informatique", departement=dept)
        self.annee = AnneeAcademique.objects.create(libelle="2026-2027", est_active=True)
        self.cg = CycleGlobal.objects.create(nom="Licence")
        self.cycle = Cycle.objects.create(type_cycle=self.cg, filiere=self.filiere, nom="Licence")
        self.niveau = Niveau.objects.create(cycle=self.cycle, nom="L1")
        self.classe = Classe.objects.get(niveau=self.niveau, annee_academique=self.annee)
        self.module = Module.objects.create(nom="Algo", semestre="Semestre 2")
        self.classe.modules.add(self.module)

        self.admin = User.objects.create(noms="Admin", prenoms="A", email="admin@t.local", role="admin")
        Role.objects.create(code="secretaire", libelle="Secrétaire", can_manage_etudiants="ecriture")
        self.staff = User.objects.create(noms="Staff", prenoms="S", email="staff@t.local", role="secretaire")

        self.etudiant = Etudiant.objects.create(nom="Jean Dupont", contact="1", email="jean@t.local", filiere=self.filiere)
        self.etudiant.refresh_from_db()
        Inscription.objects.create(etudiant=self.etudiant, classe=self.classe, niveau=self.niveau,
                                   annee_academique=self.annee.libelle)
        self.u_etu = self.etudiant.user

        self.u_form = User.objects.create(noms="Prof", prenoms="P", email="prof@t.local", role="formateur")
        self.formateur = Formateur.objects.create(nom="Prof", email="prof2@t.local", contact="2", user=self.u_form)


class SecuriteAccesTests(Base):
    def test_etudiant_bloque_hors_portail(self):
        self.client.force_authenticate(self.u_etu)
        # le jeton est nécessaire pour le middleware : on utilise un vrai JWT
        from rest_framework_simplejwt.tokens import AccessToken
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.u_etu)}")
        self.assertEqual(self.client.get("/api/etudiants/").status_code, 403)
        self.assertEqual(self.client.get("/api/paie/campagnes/").status_code, 403)
        self.assertEqual(self.client.post("/api/assiduite/", {}).status_code, 403)
        self.assertEqual(self.client.get("/api/etudiants/me/").status_code, 200)
        self.assertEqual(self.client.get("/api/notes/me/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/roles/").status_code, 200)

    def test_formateur_bloque_hors_portail(self):
        from rest_framework_simplejwt.tokens import AccessToken
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.u_form)}")
        self.assertEqual(self.client.get("/api/paiements/").status_code, 403)
        self.assertEqual(self.client.get("/api/formateurs/portal/me/").status_code, 200)

    def test_gestion_des_comptes_reservee_a_l_admin(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get("/api/auth/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/auth/{self.admin.id}/reset-password/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/auth/{self.staff.id}/").status_code, 200)  # sa propre fiche
        self.assertEqual(self.client.get(f"/api/auth/{self.admin.id}/").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/roles/", {"code": "x", "libelle": "x"}).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/auth/").status_code, 200)

    def test_annee_archivee_bloquee_pour_non_superuser(self):
        from rest_framework_simplejwt.tokens import AccessToken
        ancienne = AnneeAcademique.objects.create(libelle="2020-2021", est_active=False)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.staff)}",
                                HTTP_X_ACADEMIC_YEAR=str(ancienne.id))
        self.assertEqual(self.client.get("/api/etudiants/").status_code, 403)
        # la liste des années reste accessible pour corriger la sélection
        self.assertEqual(self.client.get("/api/v2/annees-academiques/").status_code, 200)
        # année inexistante : ignorée (auparavant 404 sur toutes les requêtes)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.staff)}",
                                HTTP_X_ACADEMIC_YEAR="999999")
        self.assertEqual(self.client.get("/api/etudiants/").status_code, 200)

    def test_etudiant_avec_email_du_personnel_ne_recupere_pas_son_compte(self):
        e = Etudiant.objects.create(nom="Intrus", contact="3", email="admin@t.local", filiere=self.filiere)
        e.refresh_from_db()
        self.assertIsNone(e.user)

    def test_suppression_etudiant_desactive_le_compte(self):
        self.etudiant.delete()
        self.u_etu.refresh_from_db()
        self.assertFalse(self.u_etu.is_active)


class PreInscriptionTests(Base):
    def test_formulaire_public_force_le_statut(self):
        res = self.client.post("/api/v2/pre-inscriptions/", {
            "nom_candidat": "A", "prenom_candidat": "B", "email": "cand@t.local", "telephone": "699000111",
            "filiere_souhaitee": self.filiere.id, "niveau_souhaite": self.niveau.id, "statut": "APPROUVEE",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(PreInscription.objects.get(email="cand@t.local").statut, "EN_ATTENTE")

    def test_approbation_annulee_ne_laisse_aucune_donnee(self):
        pre = PreInscription.objects.create(nom_candidat="C", prenom_candidat="D", email="c@t.local", telephone="1",
                                            filiere_souhaitee=self.filiere, niveau_souhaite=self.niveau)
        self.client.force_authenticate(self.admin)
        res = self.client.post(f"/api/v2/pre-inscriptions/{pre.id}/approve/",
                               {"type_reduction": "BOURSE", "bourse_code": "INCONNU"}, format="json")
        self.assertEqual(res.status_code, 400)
        pre.refresh_from_db()
        self.assertEqual(pre.statut, "EN_ATTENTE")
        self.assertFalse(Etudiant.objects.filter(email="c@t.local").exists())


class NotesTests(Base):
    def test_une_seule_note_par_module_dans_son_semestre(self):
        notes = Note.objects.filter(etudiant=self.etudiant, module=self.module)
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.first().session, "Semestre 2")

    def test_effacer_les_composantes_efface_la_note_finale(self):
        note = Note.objects.get(etudiant=self.etudiant, module=self.module)
        note.note_cc, note.note_sn = Decimal("20"), Decimal("40")
        note.save()
        self.assertEqual(note.note_finale, Decimal("60.00"))
        note.note_cc = note.note_sn = None
        note.save()
        self.assertIsNone(note.note_finale)

    def test_saisie_formateur_limitee_a_ses_classes(self):
        from academique.models import Affectation
        autre_classe = Classe.objects.create(filiere=self.filiere, cycle=self.cycle, niveau=self.niveau,
                                             annee_academique=AnneeAcademique.objects.create(libelle="2027-2028"),
                                             nom="Autre")
        Affectation.objects.create(enseignant=self.formateur, module=self.module, classe=self.classe)
        self.client.force_authenticate(self.u_form)
        res = self.client.post("/api/formateurs/portal/saisir-notes/", {"notes": [
            {"etudiant_id": self.etudiant.id, "module_id": self.module.id, "classe_id": autre_classe.id, "note_cc": 10},
            {"etudiant_id": self.etudiant.id, "module_id": self.module.id, "classe_id": self.classe.id, "note_cc": 0},
        ]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["updated"] + res.data["created"], 1)
        self.assertEqual(len(res.data["errors"]), 1)
        res = self.client.get("/api/formateurs/portal/mes-notes/")
        self.assertEqual(res.data[0]["note_cc"], 0.0)  # un 0 n'est plus affiché comme « vide »


class CongesTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Personnel.objects.create(nom="Agent", contact="1", date_embauche=date(2020, 1, 1),
                                          solde_conges_initial=5)

    def test_accepter_un_conge_debite_le_solde_une_seule_fois(self):
        lundi = date(2026, 11, 2)
        conge = Conge.objects.create(personnel=self.p, date_debut=lundi, date_fin=lundi + timedelta(days=4),
                                     type_conge="annuel")
        self.assertEqual(conge.jours_ouvres, 5)  # bornes incluses
        conge.statut = "accepte"
        conge.save()  # auparavant : échec de validation + solde débité quand même
        self.p.refresh_from_db()
        self.assertEqual(self.p.solde_conges_restant, 0)
        conge.statut = "refuse"
        conge.save()
        self.p.refresh_from_db()
        self.assertEqual(self.p.solde_conges_restant, 5)

    def test_conge_d_une_journee(self):
        jour = date(2026, 11, 3)
        conge = Conge.objects.create(personnel=self.p, date_debut=jour, date_fin=jour, type_conge="annuel")
        self.assertEqual(conge.jours_ouvres, 1)

    def test_erreur_metier_renvoie_400(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post("/api/conges/", {"personnel_id": self.p.id, "date_debut": "2026-11-02",
                                                "date_fin": "2026-11-20", "type_conge": "annuel"}, format="json")
        self.assertEqual(res.status_code, 400)


class FinancesTests(Base):
    def test_portail_tient_compte_de_la_reduction(self):
        Frais.objects.create(classe=self.classe, libelle="Frais d'inscription", montant=Decimal("50000"))
        ReductionEtudiant.objects.create(etudiant=self.etudiant, type_reduction="LIBRE_INSCRIPTION",
                                         target="INSCRIPTION", montant_reduction=Decimal("10000"))
        Paiement.objects.create(etudiant=self.etudiant, paiement_type="INSCRIPTION", montant_paye=Decimal("40000"))
        self.client.force_authenticate(self.u_etu)
        res = self.client.get("/api/paiements/me/")
        self.assertEqual(res.data["inscription"]["du"], 40000.0)
        self.assertEqual(res.data["inscription"]["reste"], 0.0)

    def test_pas_de_double_campagne_le_meme_mois(self):
        CampagnePaie.objects.create(mois=9, annee=2026, type_beneficiaire="tous")
        self.client.force_authenticate(self.admin)
        res = self.client.post("/api/paie/campagnes/generer/", {"mois": 9, "annee": 2026, "type_beneficiaire": "formateur"},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_filtre_des_campagnes_par_type(self):
        CampagnePaie.objects.create(mois=8, annee=2026, type_beneficiaire="personnel")
        CampagnePaie.objects.create(mois=8, annee=2026, type_beneficiaire="formateur")
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/paie/campagnes/?type_beneficiaire=formateur")
        data = res.data if isinstance(res.data, list) else res.data["results"]
        self.assertEqual({c["type_beneficiaire"] for c in data}, {"formateur"})


class LogistiqueTests(Base):
    def test_livraison_sans_stock_suffisant_ne_sort_rien(self):
        article = Article.objects.create(nom="Chaise")
        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/inventaires/articles/{article.id}/ajouter_stock/", {"quantite": 1}, format="json")
        demande = DemandeArticle.objects.create(objet="Chaises", statut="approuvee")
        LigneDemande.objects.create(demande=demande, article=article, quantite_demandee=3)
        res = self.client.post(f"/api/demandes/{demande.id}/livrer/")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Mouvement.objects.filter(type_mouvement="sortie").exists())

    def test_quantite_de_stock_invalide(self):
        article = Article.objects.create(nom="Table")
        self.client.force_authenticate(self.admin)
        res = self.client.post(f"/api/inventaires/articles/{article.id}/ajouter_stock/", {"quantite": "abc"}, format="json")
        self.assertEqual(res.status_code, 400)


class EmploiDuTempsTests(Base):
    def test_suppression_limitee_au_tronc_commun(self):
        salle1, salle2 = Salle.objects.create(nom="S1"), Salle.objects.create(nom="S2")
        autre_form = Formateur.objects.create(nom="Autre", email="autre@t.local", contact="4")
        a = EmploiDuTemps.objects.create(classe=self.classe, module=self.module, formateur=self.formateur,
                                         jour="Lundi", heure_debut=time(8), heure_fin=time(10), salle=salle1)
        EmploiDuTemps.objects.create(classe=self.classe, module=self.module, formateur=autre_form,
                                     jour="Lundi", heure_debut=time(8), heure_fin=time(10), salle=salle2)
        a.delete()
        self.assertEqual(EmploiDuTemps.objects.count(), 1)  # auparavant : les deux supprimés

    def test_heure_de_fin_avant_le_debut_refusee(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            EmploiDuTemps.objects.create(classe=self.classe, module=self.module, formateur=self.formateur,
                                         jour="Mardi", heure_debut=time(10), heure_fin=time(9),
                                         salle=Salle.objects.create(nom="S3"))
