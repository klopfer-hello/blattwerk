"""One error shape for the whole API: {"error": message, "fields"?: {field: msg}}.
Handlers raise ApiError; main.py turns it into the JSON answer."""


class ApiError(Exception):
    def __init__(self, status: int, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = fields or {}


def not_found(what: str) -> ApiError:
    return ApiError(404, f"{what} not found")


def invalid(field: str, message: str) -> ApiError:
    return ApiError(422, "invalid input", {field: message})
