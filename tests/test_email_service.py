import re
from services.email_service import generate_ics_content


def test_generate_ics_content_sanitizes_fields():
    ics = generate_ics_content(
        "2023-01-01",
        "2023-01-02",
        "Team,\rOuting",
        "Discuss\r\nRoadmap,\nitems",
    )

    assert "SUMMARY:Team\\,\\nOuting" in ics
    assert "DESCRIPTION:Discuss\\nRoadmap\\,\\nitems" in ics
    # Ensure no stray CR characters remain in individual lines
    for line in ics.split("\r\n"):
        assert "\r" not in line
    # Commas should only appear escaped
    assert not re.search(r"[^\\],", ics)
