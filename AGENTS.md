# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is a radiology examination PDF to Anki flashcard converter. The main script `create_anki_deck.py` processes PDF files containing Q&A pairs and converts them into Anki deck files (.apkg) with image-based flashcards.

## Development Commands

- **Run the main script**: `uv run create_anki_deck.py`
- **Install/sync dependencies**: `uv sync`
- **Run tests**: `uv run pytest`
- **Add runtime dependencies**: `uv add <package>`
- **Add development dependencies**: `uv add --dev <package>`
- **Important PDF dependency note**: use `PyMuPDF` / `pymupdf`; do not install the unrelated PyPI package named `fitz`.

## Architecture

- **Single script architecture**: `create_anki_deck.py` handles the entire conversion pipeline
- **Dependency management**: `pyproject.toml` and `uv.lock` define the reproducible uv environment
- **Tests**: `tests/` contains pytest coverage for stable Anki IDs and processing result checks
- **Input**: PDF files placed in `input/` directory
- **Output**: Anki deck files (.apkg) generated in `output/` directory
- **Processing flow**: PDF parsing → marker detection → image extraction → Anki deck creation

## Key Components

- **Marker detection**: Recognizes Q/A patterns like "Q1", "A1" and special format "編號:xx"
- **Image extraction**: Crops PDF regions at 200 DPI resolution and merges multi-part content
- **Anki generation**: Creates image-to-image flashcards using genanki library; card backs show both question and answer images
- **Stable Anki identity**: Deck/model IDs and note GUIDs are deterministic so reruns import consistently

## Configuration

- `EXPECTED_CARDS = 50`: Expected number of cards per deck (warns if mismatch)
- `INPUT_DIR = "input"`: Source directory for PDF files
- `OUTPUT_DIR = "output"`: Destination for generated Anki decks
- Image DPI set to 200 for quality balance
