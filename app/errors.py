"""Only these fixed, nonsecret categories cross the HTTP error boundary."""


class GridWiseError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)