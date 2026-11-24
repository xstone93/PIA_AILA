"""Software release identifier; independent of study and assessment versions."""

APP_VERSION = "0.1.0"


def version_label(value):
    """Do not attribute today's version to unversioned historic records."""
    return value if isinstance(value, str) and value.strip() else "Nicht erfasst"
