# Formatting notes

## Applied to every file
- Removed `utm_source=chatgpt.com` tracking parameters from all links, plus favicon images, scraped image-carousel cards, and stray `&#x20;` entities.
- Converted citation chips (`GitHub+1`) to *Source:* notes; rebuilt title/author/description/link reference cards as list entries.
- Restored structure the export flattened: numbered steps, bold term labels, lead-ins (Example:, Best for:), bullet labels, checklists.
- Rebuilt about 50 flattened diagrams as ordered lists, tables, or text trees.
- Re-indented code blocks whose indentation had collapsed (JSON, JS/TS, C/C++/C#, YAML, Lua, Python); added language tags.
- Normalised LaTeX to `$…$`, compacted tables, enforced a single H1 and no skipped heading levels, added front matter and Contents.
- Repaired export damage: "I/O" had become "the author/O"; "your own" had become "the own"; several sentences began lowercase or had broken grammar ("the recommendation is to defining…").
- Removed chat remnants: UI widgets ("Develop this direction", "Copy checklist"), an embedded follow-up prompt, "Let's expand…", "You could replace the original TODO…".
- C_Foreign_Function_Interface_FFI.md contained two documents; the second is now *Part II — Technical Proposal* with headings demoted one level.

## Please verify (reconstructed, not recovered)
- Text_To_Diagram_Tools.md: two Mermaid diagrams were lost (only CSS survived); rebuilt from the surrounding description.
- ASCII figures rebuilt from flattened labels: Schema_and_Serialization (multiplication graph), Visual_programming_language (Input→Multiply→Output), tree diagrams in Dual_Representation_Systems, Intermediate_representation, Markup_language.
- Nesting in flow figures (sub-bullets for transitions/branches) is inferred from label order.
- Code blocks whose indentation was rebuilt by rule rather than from the source: all JSON/JS/TS/C-family blocks in the notes; skim before reuse.
- Blank lines inside a few reconstructed Python snippets were not recoverable and are omitted.

## Deliberately left as-is
- Generic second-person phrasing ("you may need to…") in how-to passages.
- Wikipedia-derived Part I text (only formatting touched).
