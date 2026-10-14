"""The ISIN check every place that takes an ISIN shares."""

import re

FORMAT = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def is_valid_isin(value: str) -> bool:
    """Whether it is a real ISIN: country code, nine alphanumerics, check digit.

    The check digit is the Luhn checksum over the code with each letter
    replaced by its number (A is 10, Z is 35).
    """
    if not FORMAT.fullmatch(value):
        return False
    digits = "".join(str(int(c, 36)) for c in value)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += sum(divmod(n, 10))
    return total % 10 == 0
