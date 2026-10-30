## 8. Versioning and compatibility

- The text header `wiret N` and the bytecode `version` are independent integers. A reader must reject a file with a higher major number than it supports.
- Within a major version, changes are additive: new node kinds, new semantic attributes, new custom sections, new instructions under the `FB` prefix. Old tools keep unknown attributes and skip unknown custom sections, so a new editor's file survives a round trip through an old one.
- A new node kind can only be compiled by a compiler that knows it. Older compilers report `E0501` rather than guessing.
- The semantic hash is stable across editor-only changes. Changing the canonical-form rules in section 2.5 is a major-version change.
