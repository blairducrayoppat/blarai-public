"""Tokenize text into words."""

import re


def tokenize(text):
    """Break a piece of text into individual words.
    
    Each word is lowercased with surrounding punctuation stripped,
    and returned as a list in reading order.
    
    Args:
        text (str): The text to tokenize
        
    Returns:
        list: A list of lowercase words with punctuation stripped
    """
    # Split on whitespace and punctuation
    words = re.split(r'\W+', text)
    # Filter out empty strings and convert to lowercase
    return [word.lower() for word in words if word]

