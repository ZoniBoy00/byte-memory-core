"""Character n-gram tokenizer for TF-IDF semantic-lite matching."""

import re
from typing import List

from bmc.config import NGRAM_MIN, NGRAM_MAX


def tokenize(text: str) -> List[str]:
    """Extract overlapping character n-grams for fuzzy matching.

    Char n-grams capture partial-word matches, typos, and related
    surface forms (e.g. 'tarkistaa' ~ 'tarkistus') that standard
    FTS5 keyword search would miss.
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    tokens: List[str] = []
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        for i in range(len(text) - n + 1):
            ngram = text[i: i + n]
            if ngram.strip():
                tokens.append(ngram)
    return tokens
