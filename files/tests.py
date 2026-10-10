# files/tests.py
# Tests réécrits : les anciens utilisaient des champs (fichier, uploaded_by, type) et une
# route (file-list-create) qui n'existent plus dans le modèle et les URLs actuels.
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from .models import File

User = get_user_model()


def _pdf():
    return SimpleUploadedFile("test.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")


@pytest.mark.django_db
def test_upload_file():
    client = APIClient()
    user = User.objects.create_user(username="testuser", email="test@test.com", password="pass")
    client.force_authenticate(user=user)

    response = client.post(reverse("file-upload"), {"file": _pdf()}, format="multipart")

    assert response.status_code == 201, response.data
    assert File.objects.filter(owner=user, name="test.pdf").exists()


@pytest.mark.django_db
def test_file_download_permission():
    client = APIClient()
    owner = User.objects.create_user(username="user1", email="u1@test.com", password="pass")
    other = User.objects.create_user(username="user2", email="u2@test.com", password="pass")
    file = File.objects.create(file=_pdf(), owner=owner, name="test.pdf")

    client.force_authenticate(user=other)
    response = client.get(reverse("file-download", args=[file.id]))

    # Un autre utilisateur ne peut pas télécharger (404 : on ne révèle pas l'existence du fichier)
    assert response.status_code == 404


@pytest.mark.django_db
def test_file_owner_can_download():
    client = APIClient()
    owner = User.objects.create_user(username="owner", email="owner@test.com", password="pass")
    file = File.objects.create(file=_pdf(), owner=owner, name="test.pdf")

    client.force_authenticate(user=owner)
    response = client.get(reverse("file-download", args=[file.id]))

    assert response.status_code == 200
