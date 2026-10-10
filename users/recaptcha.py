"""
Vérification serveur du reCAPTCHA v2.

Le frontend envoie `recaptcha_token`. La vérification n'est active que si la variable
d'environnement RECAPTCHA_SECRET_KEY est définie (sinon comportement inchangé : utile en dev).
"""
import json
import logging
import os
import urllib.parse
import urllib.request

from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)
VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def verify_recaptcha(request):
    secret = os.getenv("RECAPTCHA_SECRET_KEY", "").strip()
    if not secret:
        return
    token = request.data.get("recaptcha_token") if hasattr(request, "data") else None
    if not token:
        raise ValidationError({"recaptcha": "Veuillez valider le reCAPTCHA."})
    payload = urllib.parse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": request.META.get("REMOTE_ADDR", ""),
    }).encode()
    try:
        with urllib.request.urlopen(VERIFY_URL, data=payload, timeout=8) as resp:
            result = json.loads(resp.read().decode())
    except Exception:  # réseau indisponible : on refuse plutôt que d'ouvrir la porte
        logger.exception("Vérification reCAPTCHA impossible")
        raise ValidationError({"recaptcha": "Vérification reCAPTCHA indisponible, réessayez."})
    if not result.get("success"):
        raise ValidationError({"recaptcha": "reCAPTCHA invalide ou expiré, veuillez réessayer."})
