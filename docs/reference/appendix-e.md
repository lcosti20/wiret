## Appendix E. Changes in Draft 0.6

Draft 0.6 changes two pieces of surface syntax to make node statements easier to read. The model, the bytecode and the semantic hash of a graph are unchanged; only the text changes.

| Change | Detail | Section |
| --- | --- | --- |
| `::<` for generics | Every generic argument list is introduced by `::`: node type arguments (`Add::<i32>`), declaration type parameters (`macro ForEach::<T>`) and generic types (`array::<i32>`, `map::<K, V>`). A node line binds an id to a kind, so with a bare `<` a node like `NodeType<a, b> variable` could read as a comparison. The old form is a syntax error whose message shows the new one. | 2.1, 2.2, 2.3, 3 |
| Inputs below the node | Inputs are no longer written like call arguments (`Add<i32>(a: x, b: y)`). Each one is its own line below the node line, `.pin <- value`, indented one level further. `<-` mirrors the `->` of exec wires. Every input of a node can be read down one column, and rewiring one input changes exactly one line. Node lines no longer wrap (canonical rule 7). | 2.3, 2.5, 2.6 |
