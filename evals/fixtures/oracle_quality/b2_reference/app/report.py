"""Generate a combined report of text statistics."""

from app.tokenize import tokenize
from app.word_frequencies import word_frequencies
from app.neighbor_pairs import neighbor_pairs


def combined_report(text):
    """Generate a combined report of word frequencies and neighboring word pairs.
    
    Args:
        text (str): The text to analyze
        
    Returns:
        str: A human-readable report combining both findings
    """
    # Tokenize the text
    tokens = tokenize(text)
    
    # Compute word frequencies
    frequencies = word_frequencies(tokens)
    
    # Compute neighboring word pairs
    pairs = neighbor_pairs(tokens)
    
    # Format the report
    report_lines = []
    report_lines.append("TEXT STATISTICS REPORT")
    report_lines.append("=" * 25)
    report_lines.append("")
    
    # Add word frequencies section
    report_lines.append("WORD FREQUENCIES:")
    report_lines.append("-" * 17)
    for word, count in sorted(frequencies.items()):
        report_lines.append(f"  {word}: {count}")
    report_lines.append("")
    
    # Add neighboring word pairs section
    report_lines.append("NEIGHBORING WORD PAIRS:")
    report_lines.append("-" * 23)
    for pair, count in sorted(pairs.items()):
        report_lines.append(f"  {pair[0]} -> {pair[1]}: {count}")
    
    return "\n".join(report_lines)