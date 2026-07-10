"""Count neighboring word pairs in token lists."""

from collections import defaultdict
from app.tokenize import tokenize


def neighbor_pairs(tokens):
    """Count adjacent word pairs in a token list.
    
    Args:
        tokens (list): A list of tokens from app.tokenize.tokenize
        
    Returns:
        dict: A dictionary mapping (word, next_word) tuples to their counts
    """
    if len(tokens) < 2:
        return {}
    
    pairs = defaultdict(int)
    for i in range(len(tokens) - 1):
        pair = (tokens[i], tokens[i + 1])
        pairs[pair] += 1
    
    return dict(pairs)