"""Ontology candidate extraction (classes, attributes, relations) from requirements and design documents."""

from .llm import LLM, ClaudeCodeLLM, CodexLLM, make_llm
from .pipeline import Config, Pipeline

__all__ = ["LLM", "ClaudeCodeLLM", "CodexLLM", "make_llm", "Config", "Pipeline"]

__version__ = "2.0.0-direct-tbox"
