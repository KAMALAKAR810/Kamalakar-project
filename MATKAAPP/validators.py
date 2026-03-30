import re

from django.core.exceptions import ValidationError


class SpecialCharacterValidator:
    """Require at least one non-alphanumeric character."""

    def validate(self, password, user=None):
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':\"\\|,.<>\/?]', password):
            raise ValidationError(
                "Your password must contain at least one special character (!@#$%^&* etc.).",
                code="password_no_special",
            )

    def get_help_text(self):
        return "Your password must contain at least one special character."


class UppercaseValidator:
    def validate(self, password, user=None):
        if not re.search(r"[A-Z]", password):
            raise ValidationError(
                "Your password must contain at least one uppercase letter.",
                code="password_no_upper",
            )

    def get_help_text(self):
        return "Your password must contain at least one uppercase letter."


class LowercaseValidator:
    def validate(self, password, user=None):
        if not re.search(r"[a-z]", password):
            raise ValidationError(
                "Your password must contain at least one lowercase letter.",
                code="password_no_lower",
            )

    def get_help_text(self):
        return "Your password must contain at least one lowercase letter."


class DigitValidator:
    def validate(self, password, user=None):
        if not re.search(r"\d", password):
            raise ValidationError(
                "Your password must contain at least one digit.",
                code="password_no_digit",
            )

    def get_help_text(self):
        return "Your password must contain at least one digit."


class MaximumLengthValidator:
    """Validate that the password is not too long."""

    def __init__(self, max_length=15):
        self.max_length = max_length

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(
                f"This password is too long. It must be no more than {self.max_length} characters.",
                code="password_too_long",
            )

    def get_help_text(self):
        return f"Your password must be no more than {self.max_length} characters."
