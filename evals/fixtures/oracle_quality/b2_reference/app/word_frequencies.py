"""Count word frequencies in a list of tokens."""

from collections import Counter
from app.tokenize import tokenize


def word_frequencies(tokens):
    """Count the frequency of each word in a list of tokens.
    
    Args:
        tokens (list): A list of word tokens
        
    Returns:
        dict: A dictionary mapping each word to its frequency count
    """
    return dict(Counter(tokens))


if __name__ == "__main__":
    # Example usage
    sample_text = "The cat sat on the mat. The cat ran."
    tokens = tokenize(sample_text)
    frequencies = word_frequencies(tokens)
    print(f"Tokens: {tokens}")
    print(f"Frequencies: {frequencies}")