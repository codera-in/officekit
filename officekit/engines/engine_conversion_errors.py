"""Safe, stable errors for invalid user-supplied conversion input."""


class ConversionInputError(ValueError):
    """An input file or requested format cannot be converted safely."""

    public_message = "The file or requested format cannot be converted. Check the input and try again."

    def __str__(self) -> str:
        return self.public_message
