"""Generic client-facing error payloads for the local desktop API."""


def internal_error_payload() -> dict[str, dict[str, str]]:
    return {
        "error": {
            "code": "internal_error",
            "message": "The operation could not be completed. Try again.",
        }
    }
