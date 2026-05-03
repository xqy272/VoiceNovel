# Context Fetch Engine — AI Agent Guide

## Purpose
Assembles a `ContextCapsule` from a `ContextSpec` by querying the `BookModel` (Project Store).

## Key Concepts
- **ContextSpec**: Declared by each service, specifies what context it needs
- **ContextCapsule**: Assembled by the Fetch Engine, contains the actual data
- **Scene priority**: current chapter > recent chapters > whole book

## Module: `vn_core/context/`

### `assemble_context(spec, book_model, store) -> ContextCapsule`
1. Load target segments from store by segment_ids or chapter_id
2. Build left/right text context from neighboring segments
3. Load active characters from book_model
4. Load recent dialogue state
5. Load scene snapshot if available
6. Load glossary terms if requested
7. Load pronunciation overrides if requested
8. Load prior reading decisions if requested
9. Load locked items if requested

## Data Contracts
- Input: `ContextSpec` (contracts/context_spec.py)
- Output: `ContextCapsule` (contracts/context_capsule.py)

## Dependencies
- `vn_core.store.ProjectStore` — for all data queries
- `vn_core.book_model.BookModel` — for character/scene queries