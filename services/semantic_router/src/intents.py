"""
Intent Route Definitions — Semantic Router
=============================================
USE-CASE-004, P1.7: Route centroids for cosine-similarity classification.

Each IntentRoute maps a set of representative phrases to an intent
category. At load time, the router embeds all phrases via bge-small-en-v1.5
and computes the mean centroid vector per route. At classify time, the
query embedding is compared against all centroids via cosine similarity.

The highest-similarity route whose score exceeds the confidence threshold
is returned. If no route exceeds the threshold, the query is classified
as OUT_OF_SCOPE (Fail-Closed).

Security:
  - No external network calls.
  - Route definitions are static and deterministic.
  - Adding/removing routes requires code change + test re-run.
  - Route phrases must NOT contain sensitive data or PII.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntentRoute:
    """A route mapping representative phrases to an intent classification.

    Attributes:
        intent: Intent category name (must match an Intent enum value).
        phrases: Representative phrases defining this intent's semantic space.
            At least 5 phrases recommended for stable centroid geometry.
        skill_target: Target skill for SKILL_DISPATCH intents. None for CONVERSATIONAL.
    """

    intent: str
    phrases: list[str] = field(default_factory=list)
    skill_target: str | None = None


# ---------------------------------------------------------------------------
# Default Intent Routes
# ---------------------------------------------------------------------------
# These define the semantic space for each intent category.
# The router computes a centroid embedding for each route at load time.
# Phrases should be diverse, representative, and natural-language queries
# that a user would actually type.
# ---------------------------------------------------------------------------

INTENT_ROUTES: list[IntentRoute] = [
    IntentRoute(
        intent="CONVERSATIONAL",
        phrases=[
            "Tell me about this topic",
            "What can you help me with",
            "Explain this concept to me",
            "How does this work",
            "I have a question about something",
            "Help me understand this",
            "What do you think about this",
            "Can you summarize this for me",
            "Describe how this process works",
            "Give me an overview of this subject",
        ],
    ),
    IntentRoute(
        intent="SKILL_DISPATCH",
        skill_target="code_agent",
        phrases=[
            "Write a Python function to sort a list",
            "Fix the bug in this code",
            "Refactor this module for better performance",
            "Generate unit tests for this class",
            "Review this code and suggest improvements",
            "Help me debug this error message",
            "Create a new file with this implementation",
            "Optimize this algorithm for speed",
        ],
    ),
    IntentRoute(
        intent="SKILL_DISPATCH",
        skill_target="search",
        phrases=[
            "Find all files containing this string",
            "Search the codebase for this function",
            "Where is the configuration file located",
            "Look up the definition of this class",
            "List all test files in the project",
            "Show me the imports in this module",
        ],
    ),
    IntentRoute(
        intent="SKILL_DISPATCH",
        skill_target="cleaner",
        phrases=[
            "Import this document into the knowledge base",
            "Process and normalize this PDF file",
            "Ingest this file into the substrate",
            "Clean and prepare this data for storage",
            "Parse this document and extract the content",
        ],
    ),
]
