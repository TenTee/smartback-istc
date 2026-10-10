from django.test import TestCase
from django.core.exceptions import ValidationError
from datetime import time
from formateurs.models import Formateur
from modules.models import Module
from academique.models import Filiere, Departement, UniversiteTutelle
from emploidutemps.models import EmploiDuTemps, Salle

class EmploiDuTempsTests(TestCase):
    def setUp(self):
        # Création des structures parentes
        self.tutelle = UniversiteTutelle.objects.create(nom="Tutelle Test")
        self.dept = Departement.objects.create(nom="Dept Test", universite_tutelle=self.tutelle)

        # Création d’un formateur
        self.formateur = Formateur.objects.create(nom="M. Dupont")

        # Création d’un module
        self.module = Module.objects.create(nom="Mathématiques")

        # Création de deux filières
        self.filiereA = Filiere.objects.create(nom="Filiere A", departement=self.dept)
        self.filiereB = Filiere.objects.create(nom="Filiere B", departement=self.dept)

        # Création des salles
        self.salle101 = Salle.objects.create(nom="Salle 101")
        self.salle102 = Salle.objects.create(nom="Salle 102")
        self.salle103 = Salle.objects.create(nom="Salle 103")

    def test_seance_creation(self):
        """Créer une séance dans Filiere A."""
        seance = EmploiDuTemps.objects.create(
            filiere=self.filiereA,
            module=self.module,
            formateur=self.formateur,
            jour="Lundi",
            heure_debut=time(9, 0),
            heure_fin=time(11, 0),
            salle=self.salle101
        )

        # Vérifier que la séance existe dans Filiere A
        self.assertTrue(
            EmploiDuTemps.objects.filter(filiere=self.filiereA, module=self.module).exists()
        )

    def test_pause_non_autorisee(self):
        """Vérifier qu'une séance pendant la pause (12h-13h) est refusée."""
        with self.assertRaises(ValidationError):
            seance = EmploiDuTemps(
                filiere=self.filiereA,
                module=self.module,
                formateur=self.formateur,
                jour="Mardi",
                heure_debut=time(12, 0),
                heure_fin=time(12, 30),
                salle=self.salle102
            )
            seance.clean()  # déclenche la validation

    def test_conflit_de_salle(self):
        """Vérifier qu'une salle ne peut pas accueillir deux séances en même temps."""
        EmploiDuTemps.objects.create(
            filiere=self.filiereA,
            module=self.module,
            formateur=self.formateur,
            jour="Mercredi",
            heure_debut=time(10, 0),
            heure_fin=time(11, 0),
            salle=self.salle103
        )

        moduleB = Module.objects.create(nom="Physique")

        # Tentative de créer une autre séance dans la même salle et créneau
        with self.assertRaises(ValidationError):
            seance_conflict = EmploiDuTemps(
                filiere=self.filiereB,
                module=moduleB,
                formateur=self.formateur,
                jour="Mercredi",
                heure_debut=time(10, 30),
                heure_fin=time(11, 30),
                salle=self.salle103
            )
            seance_conflict.clean()

    def test_emploi_du_temps_document_creation(self):
        """Tester la création et les propriétés d'un EmploiDuTempsDocument."""
        from academique.models import Cycle, Niveau, Classe, AnneeAcademique, CycleGlobal
        from emploidutemps.models import EmploiDuTempsDocument
        from django.core.files.uploadedfile import SimpleUploadedFile

        annee = AnneeAcademique.objects.create(libelle="2026-2027", est_active=True)
        type_cycle = CycleGlobal.objects.create(nom="Cycle L")
        cycle = Cycle.objects.create(type_cycle=type_cycle, filiere=self.filiereA, nom="Licence")
        niveau = Niveau.objects.create(cycle=cycle, nom="L1")
        classe = Classe.objects.create(filiere=self.filiereA, cycle=cycle, niveau=niveau, annee_academique=annee, nom="L1 Info")

        pdf_file = SimpleUploadedFile("emploi_test.pdf", b"file_content", content_type="application/pdf")
        doc = EmploiDuTempsDocument.objects.create(
            titre="Emploi du Temps L1 Info",
            classe=classe,
            fichier=pdf_file,
            description="Planning du S1"
        )

        self.assertEqual(doc.titre, "Emploi du Temps L1 Info")
        self.assertEqual(doc.extension, "pdf")
        self.assertTrue(doc.is_pdf)
        self.assertFalse(doc.is_image)
        self.assertTrue(doc.est_actif)

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase


class EmploiDuTempsDocumentApiTests(APITestCase):
    """Permissions et validation de l'API des documents d'emploi du temps."""

    url = "/api/emploi-du-temps-documents/"

    def setUp(self):
        from academique.models import Cycle, Niveau, Classe, AnneeAcademique, CycleGlobal
        from users.models import Role

        User = get_user_model()
        tutelle = UniversiteTutelle.objects.create(nom="Tutelle API")
        dept = Departement.objects.create(nom="Dept API", universite_tutelle=tutelle)
        filiere = Filiere.objects.create(nom="Filiere API", departement=dept)
        annee = AnneeAcademique.objects.create(libelle="2026-2027", est_active=True)
        cycle = Cycle.objects.create(
            type_cycle=CycleGlobal.objects.create(nom="Cycle API"), filiere=filiere, nom="Licence"
        )
        niveau = Niveau.objects.create(cycle=cycle, nom="L1")
        self.classe = Classe.objects.create(
            filiere=filiere, cycle=cycle, niveau=niveau, annee_academique=annee, nom="L1 API"
        )

        Role.objects.create(code="lecteur_peda", libelle="Lecteur", can_manage_pedagogie="lecture")
        self.admin = User.objects.create(noms="Admin", prenoms="Test", email="admin@test.local", role="admin")
        self.lecteur = User.objects.create(noms="Lect", prenoms="Test", email="lect@test.local", role="lecteur_peda")
        self.sans_droit = User.objects.create(noms="Etu", prenoms="Test", email="etu@test.local", role="etudiant")

    def _payload(self, name="edt.pdf", content=b"%PDF-1.4 test"):
        return {
            "titre": "EDT S1",
            "classe": self.classe.id,
            "fichier": SimpleUploadedFile(name, content, content_type="application/octet-stream"),
        }

    def test_admin_peut_importer_un_pdf(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.url, self._payload(), format="multipart")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["is_pdf"])

    def test_extension_interdite_refusee(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.url, self._payload(name="script.exe"), format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("fichier", res.data)

    def test_lecture_seule_ne_peut_pas_importer(self):
        self.client.force_authenticate(self.lecteur)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        res = self.client.post(self.url, self._payload(), format="multipart")
        self.assertEqual(res.status_code, 403)

    def test_utilisateur_sans_droit_bloque_hors_portail(self):
        self.client.force_authenticate(self.sans_droit)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self._payload(), format="multipart").status_code, 403)
        # L'action portail reste accessible (404 car pas de profil étudiant, pas 403)
        self.assertEqual(self.client.get(self.url + "me/").status_code, 404)
