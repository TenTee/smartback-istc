# SmartCampus — API (Django / DRF)

## Démarrage (dev)

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # puis adapter (DATABASE_URL, SECRET_KEY…)
python manage.py migrate
python manage.py runserver
```

Sans `DATABASE_URL`, le projet utilise SQLite (`db.sqlite3`).
Documentation interactive : `/api/docs/` (Swagger) et `/api/redoc/`.

Frontend (Next.js) : dossier `../frontend`, variable `NEXT_PUBLIC_API_BASE_URL` (ex. `http://127.0.0.1:8000`), puis `npm install && npm run dev`.

## Tests

```bash
python -m pytest
```

## Contrôle d'accès

- Les comptes **étudiant** et **formateur** n'ont accès qu'aux routes des portails
  (`users/middleware.py`, liste `PORTAL_RULES`). Toute nouvelle route utilisée par un portail
  doit y être ajoutée.
- La gestion des comptes (`/api/auth/`) et l'écriture des rôles sont réservées à l'administration.
- Une année académique archivée (en-tête `X-Academic-Year`) n'est accessible qu'au super-admin.
- reCAPTCHA vérifié côté serveur (login, pré-inscription) si `RECAPTCHA_SECRET_KEY` est défini.

## Endpoints principaux

- Pré-inscriptions : `POST /api/v2/pre-inscriptions/` (public), `POST /api/v2/pre-inscriptions/{id}/approve/`
- Notes : `/api/notes/` (`saisie-groupee/`, `batch-save/`, `valider/`, `me/`, `{id}/releve-notes/`)
- Portail formateur : `/api/formateurs/portal/…` ; vacations / pointage : `/api/vacations/…`
- Paie : `/api/paie/…` ; scolarité : `/api/paiements/…`
