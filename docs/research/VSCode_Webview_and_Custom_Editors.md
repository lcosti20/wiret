---
title: "VS Code Webviews and Custom Editors"
document_type: "Research note"
formatted: 2026-10-28
---

# VS Code Webviews and Custom Editors

A deep dive into building rich visual programming tools inside Visual Studio Code, with an emphasis on graph editors, node-based languages, and bidirectional synchronization between a visual canvas and a text document.

## Contents

- [1. Overview](#1-overview)
- [2. The architecture](#2-the-architecture)
- [3. Choosing the right VS Code API](#3-choosing-the-right-vs-code-api)
- [4. Bundling React, Svelte, or vanilla JavaScript](#4-bundling-react-svelte-or-vanilla-javascript)
- [5. Bidirectional synchronization: the central engineering problem](#5-bidirectional-synchronization-the-central-engineering-problem)
- [6. Messaging between the webview and extension](#6-messaging-between-the-webview-and-extension)
- [7. Choosing a graph rendering technology](#7-choosing-a-graph-rendering-technology)
- [8. Performance engineering](#8-performance-engineering)
- [9. Undo, redo, and multiple views](#9-undo-redo-and-multiple-views)
- [10. Handling invalid and partially edited source](#10-handling-invalid-and-partially-edited-source)
- [11. Recommended implementation roadmap](#11-recommended-implementation-roadmap)
- [12. Further research directions](#12-further-research-directions)
- [Official documentation and references](#official-documentation-and-references)

## 1. Overview

The central idea is to treat VS Code as the host application and embed a specialized graphical editor inside it. The user can manipulate nodes, connections, diagrams, or other structured objects visually, while the underlying file remains a normal, version-controllable text document.

For example, imagine a visual programming language where a user can drag a node onto a canvas, connect its output to another node, and immediately see the corresponding source text update. Editing that source text should also update the canvas.

7

VS Code provides two closely related technologies for this:

- Webviews provide a sandboxed web-based UI that can run HTML, CSS, JavaScript, and frameworks such as React or Svelte.
- Custom editors integrate that UI with VS Code's document and editor infrastructure, allowing an extension to provide a specialized editing experience for a file type.

A custom editor is generally built on top of the webview API. The webview renders the visual interface; the extension host connects it to files, commands, language services, and other VS Code capabilities.

The difficult part is not rendering a graph. It is designing a reliable document model and synchronization protocol so that visual edits, textual edits, undo/redo, saving, and multiple editor instances behave consistently.

## 2. The architecture

A useful starting point is to divide the system into three layers.

*Figure: three-layer architecture*

- **Webview UI — the visual editor** — React / Svelte / vanilla JS · Canvas or SVG · Gestures · Selection · Layout
   - *Typed messages and serialized state*
- **Extension host — the controller** — Custom editor provider · Validation · Commands · Document edits · Lifecycle
   - *Document edits and change notifications*
- **Text document — the source of truth** — Text representation · File on disk · VS Code document model · Undo/redo

These layers have distinct responsibilities.

| Layer | Primary responsibility |
| --- | --- |
| Webview | Rendering, pointer interaction, visual layout, temporary UI state |
| Extension host | Coordinating edits, validation, VS Code integration, lifecycle and messaging |
| Text document | Persisted program or diagram representation, save state and document history |

A fourth logical layer is often worth introducing: a shared semantic model. It represents the actual nodes, edges, identifiers, properties, and relationships independently of both the text syntax and the visual layout.

This separation prevents the graph renderer from becoming tightly coupled to the details of the file format.

## 3. Choosing the right VS Code API

There are three main approaches, and they solve different problems.

**A. Standalone Webview Panel**

*Custom UI, not a file editor*

Use `vscode.window.createWebviewPanel()` when building a visualization, dashboard, debugger, or graph explorer that doesn't need to own the editing experience for a particular file.

**Trade-off:** You must implement your own file association and synchronization if the panel edits a document.

**B. `CustomTextEditorProvider`**

*Best for text-based graph languages*

Use this when the underlying resource is a text file, such as `.graph`, `.json`, or a custom DSL. VS Code maintains the `TextDocument`, handles standard text editing and undo/redo, and provides the usual save and backup behavior.

**Trade-off:** the extension must translate visual operations into text edits and translate text changes back into visual state.

**C. `CustomEditorProvider`**

*Custom document model*

Use this when the resource is binary or when the application genuinely needs to own the document model—for example, a proprietary graph database file or a binary visual asset.

**Trade-off:** You must implement more document lifecycle, save, backup, dirty-state, and potentially undo/redo behavior yourself.

The official guidance is straightforward: for a text-based format, prefer `CustomTextEditorProvider`; for a custom binary document, use `CustomEditorProvider`.

*Source: Visual Studio Code Extension API (+1 more)*

For a visual programming language whose canonical representation is text, the recommended starting point is a custom text editor rather than inventing a parallel document system.

### What a custom text editor provides

The provider API has one particularly important method:

```text
resolveCustomTextEditor(
 document: vscode.TextDocument,
 webviewPanel: vscode.WebviewPanel,
 token: vscode.CancellationToken
): void | Thenable<void>
```

This method connects a text document to a webview. The extension initializes the webview, sends the initial document state, listens for webview messages, and observes changes to the underlying document.

VS Code also permits the same resource to have multiple editor instances. If a user splits the editor, each view has its own webview, but the views share the same underlying `TextDocument`. That distinction is fundamental to correct synchronization.

*Source: Visual Studio Code Extension API (+1 more)*

## 4. Bundling React, Svelte, or vanilla JavaScript

A webview is essentially a sandboxed browser surface embedded in VS Code. It can render sophisticated web applications, but it is not a normal webpage and cannot directly access the extension API. Communication takes place through message passing.

*Source: GitHub (+1 more)*

A typical extension project might look like this:

```text
your-graph-extension/
├── package.json
├── tsconfig.json
├── esbuild.mjs
├── src/
│ ├── extension.ts
│ ├── graphEditorProvider.ts
│ ├── documentController.ts
│ ├── parser.ts
│ ├── serializer.ts
│ └── webview/
│ ├── main.tsx
│ ├── App.tsx
│ ├── GraphCanvas.tsx
│ ├── graphModel.ts
│ └── styles.css
└── dist/
 ├── extension.js
 └── webview/
 ├── main.js
 └── main.css
```

The extension host and webview are two distinct JavaScript execution environments. A bundler such as esbuild or webpack produces separate bundles for them.

| Concern | Extension host | Webview |
| --- | --- | --- |
| Runtime | Node.js-based extension environment | Browser-like webview environment |
| Entry point | `extension.ts` | `main.tsx` or `main.ts` |
| VS Code API | Full supported extension API | Limited `acquireVsCodeApi()` bridge |
| File access | VS Code workspace APIs and permitted Node APIs | No direct arbitrary filesystem access |
| Main task | Document management and synchronization | Visual interaction and rendering |

### Register the custom editor

The extension contributes a custom editor and declares which file extensions it handles.

A simplified `package.json` contribution looks like this:

```json
{
  "activationEvents": [
    "onCustomEditor:graphEditor"
  ],
  "contributes": {
    "customEditors": [
      {
        "viewType": "graphEditor",
        "displayName": "Graph Editor",
        "selector": [
          {
            "filenamePattern": "*.graph"
          }
        ],
        "priority": "default"
      }
    ]
  }
}
```

The provider must register the same view type:

```text
context.subscriptions.push(
 vscode.window.registerCustomEditorProvider(
 "graphEditor",
 new GraphEditorProvider(context),
 {
 webviewOptions: {
 retainContextWhenHidden: false
 },
 supportsMultipleEditorsPerDocument: true
 }
 )
);
```

The exact activation configuration may depend on the VS Code version and manifest setup. The `viewType` must match between the contribution and registration. Supporting multiple editors is appropriate only if the document controller and synchronization logic can safely maintain several views.

### Generate secure webview HTML

The extension constructs HTML that loads its compiled assets through webview-approved resource URIs.

```typescript
const webview = panel.webview;

webview.options = {
  enableScripts: true,
  localResourceRoots: [
    vscode.Uri.joinPath(context.extensionUri, "dist", "webview")
  ]
};

const scriptUri = webview.asWebviewUri(
  vscode.Uri.joinPath(
    context.extensionUri,
    "dist",
    "webview",
    "main.js"
  )
);

const nonce = getNonce();

panel.webview.html = `
  <!DOCTYPE html>
  <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta
        http-equiv="Content-Security-Policy"
        content="default-src 'none';
                 script-src 'nonce-${nonce}';
                 style-src ${webview.cspSource};
                 img-src ${webview.cspSource} data:;
                 font-src ${webview.cspSource};"
      >
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Graph Editor</title>
    </head>
    <body>
      <div id="root"></div>
      <script nonce="${nonce}" src="${scriptUri}"></script>
    </body>
  </html>
`;
```

This is a structural example, not a complete production template. `getNonce()` must generate a cryptographically strong random nonce. The HTML must also escape or safely construct any dynamic values, and the content security policy must be adapted to the resources the application actually needs. If CSS is emitted as a separate file, load it through `asWebviewUri()` and authorize it under the policy.

Important implementation rules:

- Use `webview.asWebviewUri()` for local assets.
- Restrict `localResourceRoots` to the directories the webview needs.
- Apply a restrictive Content Security Policy (CSP).
- Avoid inline scripts and `eval()`-dependent bundler output.
- Treat every message received from the webview as untrusted input; validate its shape and permissions before applying edits.

These restrictions are not merely deployment inconveniences. They encourage a clean separation between the UI and the privileged extension host. The [official Webview API guide](https://code.visualstudio.com/api/extension-guides/webview) explains the security model and resource-loading requirements.

*Source: GitHub (+1 more)*

## 5. Bidirectional synchronization: the central engineering problem

The editor must support two independent paths of change:

1. **Visual → text:** A user drags a node, edits a property, creates a connection, or deletes an element.
2. **Text → visual:** A user types in the source file, invokes undo/redo, formats the file, or another extension modifies it.

A naïve implementation repeatedly serializes the entire graph and replaces the entire document. That may work for a prototype, but it creates problems with cursor position, formatting, selection, undo granularity, performance, and concurrent edits.

A better design separates the semantic model from its textual encoding.

### 5.1 Establish the document model

Consider a small graph:

```mermaid
graph Example {
 node input { type: "Number", x: 80, y: 100 }
 node output { type: "Display", x: 320, y: 100 }

 edge input.value -> output.value
}
```

The parser converts this into a model that the canvas can render:

```typescript
interface GraphDocument {
  nodes: Map<string, GraphNode>;
  edges: Map<string, GraphEdge>;
}

interface GraphNode {
  id: string;
  type: string;
  x: number;
  y: number;
  properties: Record<string, unknown>;
}

interface GraphEdge {
  id: string;
  sourceNode: string;
  sourcePort: string;
  targetNode: string;
  targetPort: string;
}
```

The `id` fields are especially important. A node should retain its identity when its position or properties change. If identity is derived from the node's line number or current coordinates, simple edits can accidentally make it a different node.

The model also needs to distinguish between:

- **Semantic state:** node types, connections, properties, execution order, and other language-level information.
- **Presentation state:** node positions, zoom, pan, selection, collapsed groups, and viewport state.
- **Source representation:** whitespace, comments, source ranges, formatting, and syntax that may not be directly represented by the graph.

This third category is often overlooked. A parser and serializer that preserve only semantic state can unintentionally erase comments, formatting, or syntax it does not understand.

For an AI-friendly graph language, stable identifiers and a syntax-preserving parser can be especially valuable.

### 5.2 Visual → text: apply targeted edits

Suppose a user drags the `input` node from `(80, 100)` to `(80, 180)`.

The webview sends a semantic operation rather than a complete serialized document:

```json
{
  type: "graph/patch",
  revision: 12,
  operations: [
    {
      op: "setNodePosition",
      id: "input",
      x: 80,
      y: 180
    }
  ]
}
```

The extension then:

1. Validates the message and checks the revision.
2. Identifies the affected node in the current document model.
3. Locates the relevant source range or syntax-tree property.
4. Constructs a minimal `WorkspaceEdit`.
5. Applies the edit to the `TextDocument`.
6. Allows the normal document-change event to propagate the resulting state back to the views.

A conceptual example:

```javascript
const edit = new vscode.WorkspaceEdit();

edit.replace(
  document.uri,
  positionPropertyRange,
  "x: 80, y: 180"
);

await vscode.workspace.applyEdit(edit);
```

Here, `positionPropertyRange` represents a source range calculated by the parser or syntax tree. It must be computed from the current document rather than hard-coded.

This approach preserves unrelated text and makes the edit more compatible with normal editor behavior.

Important: Not every visual action should immediately become a document edit. During a drag, the canvas can update its local position continuously, then commit one logical edit when the user releases the pointer. This avoids generating hundreds of tiny undo steps.

### 5.3 Text → visual: observe document changes

The extension subscribes to `workspace.onDidChangeTextDocument`. When the underlying file changes, it updates the visual representation.

```mermaid
const subscription =
 vscode.workspace.onDidChangeTextDocument(event => {
 if (event.document.uri.toString() !== document.uri.toString()) {
 return;
 }

 const graph = parseGraph(event.document.getText());

 for (const panel of panelsForDocument(document.uri)) {
 panel.webview.postMessage({
 type: "graph/replace",
 revision: getCurrentRevision(document.uri),
 graph: serializeForWebview(graph)
 });
 }
 });
```

This illustrates the flow rather than a complete implementation. A production implementation needs document-scoped revision tracking, disposal of subscriptions, parse-error handling, and a policy for updating views while an edit is still in progress.

The crucial detail is that a change caused by the visual editor also triggers the document-change event. The extension must not treat that notification as an entirely new user operation and send it back as another edit.

The official custom-editor documentation explicitly warns about this feedback loop and recommends handling invalid document states gracefully.

*Source: Visual Studio Code Extension API (+1 more)*

### 5.4 Avoid synchronization loops

A simple, reliable architecture assigns one authority for committed state: the text document.

*Figure: edit round trip*

1. **User interaction in canvas** — Temporary visual state
2. **Validated operation** — Position change, node creation, property edit
3. **Text document edit** — WorkspaceEdit → onDidChangeTextDocument
4. **Reconcile all views** — Update graph state without emitting another edit

Three techniques make this robust:

- **One-way propagation after commit:** a document-change notification updates the graph but does not trigger a new document edit.
- **Operation IDs:** assign each visual operation a unique ID. Use the ID to correlate the resulting document update with the originating operation, especially when optimistic UI updates are involved.
- **Revision numbers:** associate messages and document snapshots with monotonically increasing revisions. Reject or reconcile stale operations instead of blindly overwriting newer state.

A revision number is not, by itself, a conflict-resolution algorithm. If two views issue changes based on revision 12, the extension must decide whether the second operation can safely be rebased onto revision 13 or must be rejected and resynchronized.

For simple single-user editing, serializing edits through one extension-host controller is often enough. A full operational transformation or CRDT implementation is generally unnecessary unless the language needs concurrent collaboration or more complex distributed editing.

## 6. Messaging between the webview and extension

The webview bridge is asynchronous and message-based. The extension can call `webview.postMessage(...)`; inside the webview, the UI obtains the VS Code API using `acquireVsCodeApi()` and sends messages using `postMessage(...)`.

*Source: GitHub (+1 more)*

Initialize the API once:

```javascript
const vscode = acquireVsCodeApi();

vscode.postMessage({
  type: "graph/ready",
  protocolVersion: 1
});

window.addEventListener("message", event => {
  const message = event.data;

  if (message.type === "graph/replace") {
    renderGraph(message.graph);
  }
});
```

The extension receives the message:

```javascript
panel.webview.onDidReceiveMessage(message => {
  if (!isValidGraphMessage(message)) {
    return;
  }

  switch (message.type) {
    case "graph/ready":
      sendInitialGraph();
      break;

    case "graph/patch":
      applyGraphOperations(message);
      break;
  }
});
```

These snippets are illustrative; `isValidGraphMessage`, `renderGraph`, `sendInitialGraph`, and `applyGraphOperations` are application-specific.

### Define a protocol, not a collection of ad hoc messages

A message schema should include at least:

| Field | Purpose |
| --- | --- |
| `type` | Message kind, such as `graph/patch` |
| `protocolVersion` | Detect incompatible extension/UI versions |
| `requestId` | Correlate request and response when needed |
| `revision` | Detect stale state |
| `payload` | Validated operation or state data |

For example:

```mermaid
type GraphMessage =
 | {
 type: "graph/ready";
 protocolVersion: number;
 }
 | {
 type: "graph/patch";
 revision: number;
 operationId: string;
 operations: GraphOperation[];
 }
 | {
 type: "graph/replace";
 revision: number;
 graph: SerializedGraph;
 }
 | {
 type: "graph/error";
 requestId?: string;
 message: string;
 };
```

Use runtime validation as well as TypeScript types. TypeScript types disappear at runtime, so they do not validate incoming messages from a webview.

For large graphs, avoid posting a full snapshot after every pointer movement. Prefer compact operations, coalesced position updates, and occasional full snapshots for initialization or recovery.

## 7. Choosing a graph rendering technology

The webview is just the container. The canvas technology determines how easy it is to implement selection, panning, zooming, connections, accessibility, and large graphs.

- **React Flow** — *React · Node editors · Interactive diagrams.* A strong starting point for node-based programming tools. It supplies node and edge abstractions, connection handling, viewport controls, and customizable node components. [React Flow](https://reactflow.dev/)
- **Svelte Flow** — *Svelte · Reactive graph interfaces.* A natural option if you prefer Svelte's component and reactivity model. It provides node-editor concepts similar to React Flow. [Svelte Flow](https://svelteflow.dev/)
- **Vanilla JavaScript with SVG** — *Custom renderer · Fine-grained control.* SVG works well for moderately sized graphs, particularly when individual nodes and connection points need DOM events, accessibility hooks, and CSS styling. [MDN SVG documentation](https://developer.mozilla.org/en-US/docs/Web/SVG)

Canvas or WebGL

**Large graphs · Custom rendering**

Consider Canvas 2D or WebGL when the graph has many thousands of visible primitives or when you need custom rendering and hit-testing. You will need to implement more of the interaction and accessibility behavior yourself.

For a first implementation, React Flow or Svelte Flow is a reasonable default unless there is a specific requirement that demands a custom renderer.

One caveat: graph performance is not determined only by the rendering engine. Unnecessary component re-renders, expensive edge routing, layout calculations, and repeated parsing can become bottlenecks long before raw drawing performance does.

## 8. Performance engineering

A good implementation distinguishes three performance concerns.

### Rendering performance

- Keep pointer movement and drag previews local to the webview.
- Avoid rebuilding the entire graph component tree for every coordinate update.
- Use memoization, selective component updates, and viewport culling when appropriate.
- Run expensive automatic layout algorithms asynchronously or in a worker within the webview, where supported.
- Keep zoom and pan separate from document semantics.

### Synchronization performance

- Coalesce rapid drag updates and commit a single logical operation at drag end.
- Apply minimal text edits instead of replacing the entire document.
- Debounce expensive parsing and layout operations when appropriate.
- Use incremental parsing or syntax-tree updates if whole-document parsing becomes a measured bottleneck.
- Send full snapshots only when initializing a view or recovering from a synchronization mismatch.

### Lifecycle and memory

- Avoid retaining every webview's state indefinitely.
- Dispose of event listeners when a panel closes.
- Be cautious with `retainContextWhenHidden: true`. It can preserve webview state but increases memory use.
- Persist enough state to restore the view when its webview is recreated.

The official documentation cautions that webviews have meaningful resource costs and should be used where native VS Code APIs are insufficient.

*Source: GitHub (+1 more)*

## 9. Undo, redo, and multiple views

These are among the most important architectural decisions to make early.

### Undo and redo

With `CustomTextEditorProvider`, visual edits become ordinary text edits. This allows VS Code's text-document undo/redo machinery to handle those edits naturally.

For a custom text language, one logical graph operation should ideally correspond to one sensible text-edit transaction. For example, creating a node and its required default properties should not produce a dozen unrelated undo steps.

There is an important distinction between transient canvas interactions and committed document changes:

- Dragging a node across the screen should not produce hundreds of undo steps.
- Releasing the mouse should commit the final position as one logical edit.
- Pressing Undo should revert that committed change and update the graph.
- Undoing a textual change should also update the graph.

With `CustomEditorProvider`, the extension instead reports edits using `onDidChangeCustomDocument`. Implementing `CustomDocumentEditEvent` allows VS Code to invoke the extension's undo and redo callbacks. A content-change event alone marks the document dirty but does not provide undo/redo support.

*Source: Visual Studio Code Extension API (+1 more)*

### Multiple views of one file

Imagine a user opens `example.graph` in two split editor groups.

Both webviews must show the same committed graph, but their viewport state can differ.

| State | Shared across views? |
| --- | --- |
| Nodes, edges, properties | Yes |
| Committed node positions | Yes |
| Undo/redo results | Yes |
| Zoom level and pan | Usually no |
| Current selection | Usually no |
| Temporary drag preview | No |

This suggests maintaining two state stores:

1. A document-scoped model, owned by the extension's controller.
2. A view-scoped UI state, owned by each webview.

Do not store the only copy of committed graph data inside a React component or a single webview. A hidden, reloaded, or disposed webview must not be able to destroy the document's state.

## 10. Handling invalid and partially edited source

A text editor can contain invalid syntax at any moment. This is normal during typing, but it creates a challenge for a visual editor.

For example, the user may temporarily delete a closing brace while editing the text. The graph parser can no longer produce a complete valid model.

A robust implementation should support at least three states:

**Valid source**

Parse the document and render the current semantic graph.

**Partially valid source**

Preserve the last valid graph where possible, show syntax diagnostics, and clearly distinguish stale graph content from the current source.

**Unrecoverable parse error**

Show an error state and provide a path back to the source editor. Do not silently overwrite the malformed source with a serialization of the last valid graph.

This is one reason a syntax tree or concrete syntax tree (CST) can be preferable to a simple parse-and-regenerate approach. A CST can retain comments, whitespace, and syntax details that the semantic graph does not represent.

For a visual programming language, consider defining explicit rules about which parts of the source are editable through the graph and which require textual editing.

## 11. Recommended implementation roadmap

The recommended approach is to build the extension in stages rather than starting with a fully featured canvas.

1. Register a custom text editor. Open a sample file and render a static graph in the webview.
2. Implement parsing and validation. Convert the source file into a stable semantic graph model and display syntax errors.
3. Implement text → graph synchronization. Listen to document changes and refresh the graph, including when the source is edited in a normal text editor.
4. Implement graph → text synchronization. Start with a single operation such as changing a node's position. Apply a minimal `WorkspaceEdit`.
5. Test undo/redo and invalid source. Verify that changes propagate in both directions without feedback loops or data loss.
6. Add the full canvas. Implement node creation, edge connections, selection, deletion, dragging, and automatic layout.
7. Support split editors and restoration. Test multiple views, hidden webviews, reopening files, and workspace reloads.
8. Optimize from measurements. Add incremental parsing, message batching, and rendering optimizations only where they are needed.

### Suggested test matrix

| Test | Expected result |
| --- | --- |
| Drag a node | Correct text changes; one logical undo step |
| Edit source externally | Canvas updates without losing view state unnecessarily |
| Undo and redo | Both source and graph stay consistent |
| Introduce invalid syntax | Clear error state; no destructive rewrite |
| Split editor | Both views reflect the same document |
| Close and reopen editor | Graph reconstructs from saved document |
| Rapidly move many nodes | UI stays responsive; no stale commits |
| Save while a view is hidden | Latest committed document is saved correctly |

## 12. Further research directions

For a research project, these are particularly useful topics to investigate next:

- **Bidirectional transformations (lenses):** formal models for keeping structured representations synchronized while preserving unrelated source details.
- **Incremental parsing:** updating a syntax tree from small text edits instead of reparsing an entire file.
- **Operational transformation and CRDTs:** strategies for resolving concurrent edits, particularly if multiple views or collaborators can edit at once.
- **Syntax-preserving serialization:** maintaining comments, whitespace, source ordering, and unknown syntax during visual modifications.
- **AI-friendly syntax design:** choosing stable identifiers, explicit structure, and localized edits so both LLMs and graphical tools can modify the source reliably.
- **Language Server Protocol (LSP):** keeping diagnostics, completions, definitions, and references available even when the main editor surface is graphical.

These topics connect naturally to the broader investigation of bidirectional text/graph synchronization: the custom editor API supplies the integration boundary, but the language representation and synchronization algorithm determine how reliable the editor actually is.

## Official documentation and references

1. Visual Studio Code Custom Editor API — [Custom editor lifecycle, document models, edits, and synchronization](https://code.visualstudio.com/api/extension-guides/custom-editors).
2. Visual Studio Code Webview API — [Webview messaging, security, and resource loading](https://code.visualstudio.com/api/extension-guides/webview).
3. VS Code API reference — [CustomTextEditorProvider, CustomEditorProvider, WorkspaceEdit, and WebviewPanel](https://code.visualstudio.com/api/references/vscode-api).
4. VS Code extension samples — [Working example extensions](https://github.com/microsoft/vscode-extension-samples).

The key architectural recommendation is to use `CustomTextEditorProvider` + a syntax-aware document controller + a webview graph canvas for a text-based visual programming language. Let the text document remain authoritative for committed source changes, and keep transient interaction state inside the webview.
