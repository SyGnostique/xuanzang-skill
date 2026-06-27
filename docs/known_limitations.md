# Known Limitations

- Real semantic TOC reconstruction requires a configured LLM or human semantic review for hard books.
- The local mock translation provider validates mechanical preservation only; it is not a publication translation.
- PaddleOCR is optional and not required by default tests.
- EPUB reinsertion in v1.0 is text-node oriented and expects stable XHTML text-node ordering.
