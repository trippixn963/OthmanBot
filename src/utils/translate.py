"""
Othman Discord Bot - Translation Utility
=========================================

OpenAI-powered translation for non-English text.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from openai import OpenAI
from src.core.logger import logger


def translate_to_english(text: str) -> str:
    """
    Translate non-English text to English using OpenAI.

    Args:
        text: The text to translate

    Returns:
        English translation of the text

    Raises:
        Exception: If OpenAI API call fails
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY not found in environment variables")
            return "Error: Translation service unavailable"

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and cheap model for translations
            messages=[
                {
                    "role": "system",
                    "content": "You are a translator. Translate the following text to English. Output ONLY the English translation, nothing else. Keep it concise and natural."
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            max_tokens=100,
            temperature=0.3  # Low temperature for consistent translations
        )

        translation = response.choices[0].message.content.strip()
        logger.info(f"Translation: '{text}' → '{translation}'")
        return translation

    except Exception as e:
        logger.error(f"Failed to translate text: {e}")
        return f"Error: Could not translate title"


__all__ = ["translate_to_english"]
