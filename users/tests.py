import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


@pytest.mark.django_db
def test_login_ignores_invalid_academic_year_header():
    user = User.objects.create_user(
        username='alice',
        email='alice@example.com',
        password='securepass123',
    )

    client = APIClient()
    response = client.post(
        reverse('token_obtain_pair'),
        {'username': 'alice', 'password': 'securepass123'},
        HTTP_X_ACADEMIC_YEAR='999999',
    )

    assert response.status_code == 200, response.data
    assert 'access' in response.data
    assert 'refresh' in response.data
    assert response.data['user']['id'] == user.id
