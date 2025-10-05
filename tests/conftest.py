import os
import sys


# Provide default administrator credentials required by ``server`` during
# import. Test environments should override these with secure values if
# necessary.
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_USERNAME", "test-admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

for key, value in (
    ("SMTP_SERVER", "smtp.test"),
    ("SMTP_PORT", "2525"),
    ("SMTP_USERNAME", "user@test"),
    ("SMTP_PASSWORD", "secret"),
):
    os.environ.setdefault(key, value)
