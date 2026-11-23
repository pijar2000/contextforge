class ParsingError(Exception):
    """Raised for unreadable or corrupted files. Carries enough detail to debug later."""

    def __init__(self, parser: str, message: str, detail: str | None = None):
        super().__init__(f"[{parser}] {message}")
        self.parser = parser
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"parser": self.parser, "message": self.message, "detail": self.detail}
