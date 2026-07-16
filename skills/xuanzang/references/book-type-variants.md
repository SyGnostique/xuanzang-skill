# Book-Type Variants for Semantic Reconstruction

Load this reference after `book_architecture.prompt.md` classifies the source. The core protocol does not change; evidence interpretation does.

## Monograph

Expected grammar is often Part > Chapter > Subsection, but introductions and conclusions may sit outside numbered Parts. Test whether Part pages carry prose. Repeated book titles are likely half-titles or running headers. Numbering continuity is useful but cannot invent omitted entries.

## Edited Collection or Essay Anthology

Contribution title, subtitle, contributor byline, and sometimes affiliation form one opening group. Printed TOCs may put author before or after title. Internal numbered headings must not become sibling essays. A large section may be a whole contribution rather than under-segmentation. Preserve each contributor's notes and bibliography policy as the source presents them.

## Lecture, Course, Seminar, or Transcript

Dates may identify lectures, sessions, or editorial groupings; they may also repeat in running headers. Inspect the entire date sequence and opening discourse. Speaker labels and timestamps are usually internal structure. Editorial introductions, session summaries, and appendices require separate semantic types.

## Interview or Dialogue

Speaker names, questions, and answers are normally content units, not chapters. Interview title, participants, venue/date, and editor introduction may form one opening group. Repeated question typography is not chapter-level evidence.

## Catalogue, Fashion Book, Art Book, or Image-Heavy Reference

Visual dividers, full-page plates, object groups, captions, and gallery sequences may carry more structural evidence than OCR text. An image-only page is not empty. Use contact sheets and high-resolution boundary renders. Preserve image-caption-credit groups and source order. Separate text translation from later image-localization work.

## Bilingual or Parallel Text

Determine whether languages are facing-page, alternating-section, or duplicated-volume structures. Parallel manifestations may map to one logical TOC node with two source ranges. Do not treat the second language as duplicated noise. Boundary maps must record language lanes or parallel ranges explicitly.

## Critical Edition, Commentary, or Annotated Primary Text

Primary text, editor introduction, textual apparatus, commentary, notes, variants, and bibliography have different structural roles. Page headers may repeat work/book/line identifiers. Do not merge apparatus into primary prose or split every line/lemma as a chapter unless the edition's navigation does.

## Notes-Heavy Scholarly Book

Notes may be one global section, grouped by chapter, or footnotes embedded in body pages. A Notes container may have chapter-level internal headings that should not become body chapters. Preserve note numbers, cross-references, page ranges, and cited metadata. Do not normalize references as prose.

## Index, Glossary, or Reference-Heavy Backmatter

Alphabet letters, headwords, page spans, `see`, and `see also` relations are internal reference structure. Usually materialize the Index or Glossary as a section while preserving entries inside it. Translate or normalize only under the relevant downstream policy. A malformed index entry must not become a chapter title.

## Chinese or Mixed-Language Scan

Do not begin semantic TOC work until OCR has usable CJK coverage or readable page images. PaddleOCR should be primary for Chinese, with engine provenance and fallback audit. Visual reasoning may recover hierarchy despite OCR corruption, but display-title transcription must preserve uncertainty and cannot hallucinate unreadable Chinese characters.

## Dirty EPUB

One spine file may contain several chapters; one chapter may span several files. nav/NCX can be flat, incomplete, page-based, duplicated, or collapsed onto one locator. Inspect rendered XHTML, DOM headings, IDs, images, and semantic transitions. Keep reinsertion locators even when logical sections cross file boundaries.

## No Reliable Printed TOC

Build a provisional TOC from repeated body-opening patterns, numbering, section semantics, typography, nav/outline evidence, and whole-book argument. Label the source as `no_reliable_printed_toc`, lower confidence, retain competing hypotheses, and require exhaustive reverse audit. Never present an inferred title as source-printed text.
