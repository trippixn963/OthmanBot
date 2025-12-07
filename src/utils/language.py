"""
Othman Discord Bot - Language Detection Utilities
==================================================

Utilities for detecting and validating text language.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import unicodedata
from src.core.config import MIN_MESSAGE_LENGTH, MIN_MESSAGE_LENGTH_ARABIC


def is_primarily_arabic(text: str) -> bool:
    """
    Check if text is primarily Arabic (>50% Arabic characters).

    Args:
        text: Text to analyze

    Returns:
        True if text is primarily Arabic
    """
    if not text:
        return False

    arabic_count = 0
    total_chars = 0

    for char in text:
        if char.isalpha():
            total_chars += 1
            # Arabic Unicode ranges
            if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F':
                arabic_count += 1

    if total_chars == 0:
        return False

    return (arabic_count / total_chars) > 0.5


def get_min_message_length(text: str) -> int:
    """
    Get minimum message length based on detected language.

    Arabic text requires more characters due to denser word structure.

    Args:
        text: Text to analyze

    Returns:
        Minimum character count (400 for Arabic, 200 for others)
    """
    return MIN_MESSAGE_LENGTH_ARABIC if is_primarily_arabic(text) else MIN_MESSAGE_LENGTH


def is_english_only(text: str) -> bool:
    """
    Check if text contains only English characters, numbers, and common punctuation.

    Args:
        text: The text to validate

    Returns:
        True if text is English-only, False otherwise

    DESIGN: Allows English letters, numbers, spaces, and common punctuation
    Rejects Arabic, Chinese, Cyrillic, and other non-Latin scripts
    """
    for char in text:
        # Allow English letters, numbers, spaces, and common punctuation
        if char.isascii():
            continue

        # Check Unicode category - reject anything that's not Latin-based
        name = unicodedata.name(char, "")

        # Reject Arabic, Chinese, Cyrillic, Hebrew, etc.
        if any(script in name for script in [
            "ARABIC",
            "CHINESE",
            "CJK",  # Chinese, Japanese, Korean
            "CYRILLIC",
            "HEBREW",
            "DEVANAGARI",
            "BENGALI",
            "TAMIL",
            "THAI",
            "HANGUL",  # Korean
            "HIRAGANA",  # Japanese
            "KATAKANA",  # Japanese
        ]):
            return False

    return True


__all__ = [
    "is_primarily_arabic",
    "get_min_message_length",
    "is_english_only",
]
