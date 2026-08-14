from django.test import TestCase
from django.core.exceptions import ValidationError
from academique.models import ParametresGlobaux, UniversiteTutelle, Departement, Filiere, CycleGlobal, Cycle, Niveau, Classe, AnneeAcademique
from etudiants.models import Etudiant, Inscription
from modules.models import Module
from notes.models import Note
from decimal import Decimal

class NoteCalculationTest(TestCase):
    def setUp(self):
        # 1. Config active
        self.params = ParametresGlobaux.get_parametres()
        self.params.pourcentage_cc = 30
        self.params.pourcentage_sn = 70
        self.params.save()

        # 2. Hierarchy
        self.uni, _ = UniversiteTutelle.objects.get_or_create(nom="Test Uni")
        self.dept, _ = Departement.objects.get_or_create(universite_tutelle=self.uni, nom="Test Dept")
        self.filiere, _ = Filiere.objects.get_or_create(departement=self.dept, nom="Test Filiere")
        self.cg, _ = CycleGlobal.objects.get_or_create(nom="Test Cycle Global")
        self.cycle, _ = Cycle.objects.get_or_create(filiere=self.filiere, type_cycle=self.cg, nom="Test Cycle")
        self.niveau, _ = Niveau.objects.get_or_create(cycle=self.cycle, nom="Test Niveau")
        self.annee, _ = AnneeAcademique.objects.get_or_create(libelle="2025-2026", defaults={"est_active": True})
        self.classe, _ = Classe.objects.get_or_create(
            filiere=self.filiere,
            cycle=self.cycle,
            niveau=self.niveau,
            annee_academique=self.annee,
            defaults={"nom": "Test Classe"}
        )

        # 3. Module & Etudiant
        self.module, _ = Module.objects.get_or_create(nom="Test Module", defaults={"coefficient": 2})
        self.etudiant = Etudiant.objects.create(
            email="student@test.com",
            nom="Student Test",
            contact="123456",
            filiere=self.filiere,
            statut="Inscrit"
        )
        self.inscription = Inscription.objects.create(
            etudiant=self.etudiant,
            classe=self.classe,
            niveau=self.niveau,
            annee_academique="2025-2026",
            annee_academique_ref=self.annee
        )

    def test_valid_note_calculation(self):
        # Create a note CC=24 (out of 30), SN=49 (out of 70) -> final = 73
        note = Note.objects.create(
            etudiant=self.etudiant,
            module=self.module,
            classe=self.classe,
            note_cc=Decimal('24'),
            note_sn=Decimal('49'),
            session="Semestre 1"
        )
        self.assertEqual(note.note_finale, Decimal('73.00'))
        self.assertEqual(note.note_sur_20, Decimal('14.60'))
        self.assertEqual(Note.moyenne_etudiant(self.etudiant, session="Semestre 1"), 73.00)
        self.assertEqual(Note.mention_etudiant(self.etudiant, session="Semestre 1"), "Bien")

    def test_invalid_note_validation(self):
        # Try to save a note with CC > 30 (limit) -> should raise ValidationError
        note = Note(
            etudiant=self.etudiant,
            module=self.module,
            classe=self.classe,
            note_cc=Decimal('31'),
            note_sn=Decimal('49'),
            session="Semestre 1"
        )
        with self.assertRaises(ValidationError):
            note.save()

    def test_dynamic_config_change_recalculation(self):
        # Create a valid note CC=24 (out of 30), SN=49 (out of 70)
        note = Note.objects.create(
            etudiant=self.etudiant,
            module=self.module,
            classe=self.classe,
            note_cc=Decimal('24'),
            note_sn=Decimal('49'),
            session="Semestre 1"
        )
        self.assertEqual(note.note_finale, Decimal('73.00'))

        # Change config to CC=40, SN=60
        self.params.pourcentage_cc = 40
        self.params.pourcentage_sn = 60
        self.params.save()

        # Refresh note from db and check recalculated values
        note.refresh_from_db()
        # note_cc: (24 / 30) * 40 = 32
        self.assertEqual(note.note_cc, Decimal('32.00'))
        # note_sn: (49 / 70) * 60 = 42
        self.assertEqual(note.note_sn, Decimal('42.00'))
        # note_finale: 32 + 42 = 74
        self.assertEqual(note.note_finale, Decimal('74.00'))
