"""Parsing of the comma-separated lists a WhatsApp recipient holds (several
numbers, several group names, several group IDs in one entry)."""
import re

SEPARATORS = re.compile(r'[,;\n]+')


def split_list(text):
    """'a, b ;c\\nd' -> ['a', 'b', 'c', 'd'] (blank items dropped, duplicates removed, order kept)."""
    items = [' '.join(part.split()) for part in SEPARATORS.split(text or '')]
    return list(dict.fromkeys(item for item in items if item))


def normalise_numbers(text):
    """Split a list of phone numbers and reduce each to digits only.
    Returns (numbers, invalid_items) - a valid number is 8-15 digits with country code."""
    numbers, invalid = [], []
    for item in split_list(text):
        digits = re.sub(r'\D', '', item)
        if 8 <= len(digits) <= 15:
            numbers.append(digits)
        else:
            invalid.append(item)
    return list(dict.fromkeys(numbers)), invalid
