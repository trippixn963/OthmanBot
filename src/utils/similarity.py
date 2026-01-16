"""
OthmanBot - Text Similarity Utilities
=====================================

Content-based duplicate detection using cosine similarity.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
import math
from collections import Counter
from typing import Optional

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

# Similarity threshold - articles above this are considered duplicates
SIMILARITY_THRESHOLD = 0.75

# Minimum text length for meaningful comparison
MIN_TEXT_LENGTH = 100


# =============================================================================
# Text Processing
# =============================================================================

def _tokenize(text: str) -> list[str]:
    """
    Tokenize text into words, removing punctuation and normalizing.

    Args:
        text: Raw text to tokenize

    Returns:
        List of normalized word tokens
    """
    # Convert to lowercase
    text = text.lower()

    # Remove Arabic diacritics (tashkeel)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)

    # Split on non-word characters (keeps Arabic letters)
    words = re.findall(r'[\w\u0600-\u06FF]+', text)

    # Filter very short tokens
    return [w for w in words if len(w) > 2]


def _get_word_vector(text: str) -> Counter:
    """
    Convert text to word frequency vector.

    Args:
        text: Text to vectorize

    Returns:
        Counter with word frequencies
    """
    tokens = _tokenize(text)
    return Counter(tokens)


# =============================================================================
# Similarity Calculation
# =============================================================================

def cosine_similarity(text1: str, text2: str) -> float:
    """
    Calculate cosine similarity between two texts.

    Uses term frequency vectors (bag of words approach).
    Fast and effective for detecting near-duplicate content.

    Args:
        text1: First text to compare
        text2: Second text to compare

    Returns:
        Similarity score between 0.0 (different) and 1.0 (identical)
    """
    # Handle edge cases
    if not text1 or not text2:
        return 0.0

    if len(text1) < MIN_TEXT_LENGTH or len(text2) < MIN_TEXT_LENGTH:
        return 0.0

    # Get word frequency vectors
    vec1 = _get_word_vector(text1)
    vec2 = _get_word_vector(text2)

    # Find common words
    common_words = set(vec1.keys()) & set(vec2.keys())

    if not common_words:
        return 0.0

    # Calculate dot product
    dot_product = sum(vec1[w] * vec2[w] for w in common_words)

    # Calculate magnitudes
    magnitude1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
    magnitude2 = math.sqrt(sum(v ** 2 for v in vec2.values()))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    # Cosine similarity
    return dot_product / (magnitude1 * magnitude2)


def is_duplicate_content(
    new_text: str,
    existing_texts: list[str],
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[bool, float, Optional[int]]:
    """
    Check if new text is a duplicate of any existing text.

    Args:
        new_text: Text to check
        existing_texts: List of existing texts to compare against
        threshold: Similarity threshold for duplicate detection

    Returns:
        Tuple of (is_duplicate, highest_similarity, matching_index)
    """
    if not new_text or not existing_texts:
        return (False, 0.0, None)

    highest_similarity = 0.0
    matching_index = None

    for i, existing in enumerate(existing_texts):
        similarity = cosine_similarity(new_text, existing)

        if similarity > highest_similarity:
            highest_similarity = similarity
            matching_index = i

    is_duplicate = highest_similarity >= threshold

    if is_duplicate:
        logger.tree("Duplicate Content Detected", [
            ("Similarity", f"{highest_similarity:.2%}"),
            ("Threshold", f"{threshold:.0%}"),
            ("Match Index", str(matching_index)),
            ("Compared Against", f"{len(existing_texts)} articles"),
        ], emoji="🔍")

    return (is_duplicate, highest_similarity, matching_index if is_duplicate else None)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "cosine_similarity",
    "is_duplicate_content",
    "SIMILARITY_THRESHOLD",
]
