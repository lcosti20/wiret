---
title: "Markup Languages"
document_type: "Reference article with extended analysis"
source: "https://en.wikipedia.org/wiki/Markup_language"
formatted: 2026-10-28
---

# Markup Languages

> **Structure of this document.** Part I follows the Wikipedia article ([Markup language](https://en.wikipedia.org/wiki/Markup_language)). The section titled *Extended Analysis* is supplementary explanation added for research purposes; it is not part of the Wikipedia text.

![Example of RecipeML, a simple markup language based on XML for creating recipes. The markup can be converted programmatically for display into, for example, HTML, PDF or Rich Text Format.](https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/RecipeML.svg/500px-RecipeML.svg.png)

*Example of RecipeML, a simple markup language based on XML for creating recipes. The markup can be converted programmatically for display into, for example, HTML, PDF or Rich Text Format.*

A **markup language** is a text-encoding system which specifies the structure and formatting of a document and potentially the relationships among its parts. Markup can control the display of a document or enrich its content to facilitate automated processing.

A markup language is a set of rules governing what markup information may be included in a document and how it is combined with the content of the document in a way to facilitate use by humans and computer programs. The idea and terminology evolved from the marking up of paper manuscripts (e.g., with revision instructions by editors), traditionally written with a red pen or blue pencil on authors' manuscripts.

Older markup languages, which typically focus on typesetting and presentation, include troff, TeX, and LaTeX. Scribe and most modern markup languages, such as XML, identify document components (for example headings, paragraphs, and tables), with the expectation that technology, such as stylesheets, will be used to apply formatting or other processing.

Some markup languages, such as the widely used HTML, have pre-defined presentation semantics, meaning that their specifications prescribe some aspects of how to present the structured data on particular media. HTML, like DocBook, Open eBook, JATS, and many others, are based on the markup metalanguages XML and SGML. That is, SGML and XML allow designers to specify particular schemas, which determine which elements, attributes, and other features are permitted, and where.

A key characteristic of most markup languages is that they allow combining markup with content such as text and pictures. For example, if a few words in a sentence need to be emphasized, or identified as a proper name, defined term, or another special item, the markup may be inserted between the characters of the sentence.

## Contents

- [Etymology](#etymology)
- [Types of markup language](#types-of-markup-language)
- [History](#history)
  - [GenCode](#gencode)
  - [troff and nroff](#troff-and-nroff)
  - [TeX](#tex)
  - [Scribe, GML, and SGML](#scribe-gml-and-sgml)
  - [HTML](#html)
  - [XML](#xml)
  - [XHTML](#xhtml)
  - [Other XML-based applications](#other-xml-based-applications)
- [Features](#features)
- [Broader use](#broader-use)
- [See also](#see-also)
- [Notes](#notes)
- [Extended Analysis: Structure, Processing, and Design](#extended-analysis-structure-processing-and-design)
  - [1. What is a markup language, really?](#1-what-is-a-markup-language-really)
  - [2. The three traditional categories of markup](#2-the-three-traditional-categories-of-markup)
  - [3. A taxonomy of markup languages](#3-a-taxonomy-of-markup-languages)
  - [4. Syntax: how markup is written](#4-syntax-how-markup-is-written)
  - [5. The structure of a marked-up document](#5-the-structure-of-a-marked-up-document)
  - [6. How markup is processed](#6-how-markup-is-processed)
  - [7. Major markup languages in greater depth](#7-major-markup-languages-in-greater-depth)
  - [HTML](#html-1)
  - [XML](#xml-1)
  - [Markdown](#markdown)
  - [TeX and LaTeX](#tex-and-latex)
  - [TEI](#tei)
  - [8. Markup languages and programming languages](#8-markup-languages-and-programming-languages)
  - [9. Design principles and trade-offs](#9-design-principles-and-trade-offs)
  - [10. Markup languages beyond publishing](#10-markup-languages-beyond-publishing)
  - [11. Limitations, security, and accessibility](#11-limitations-security-and-accessibility)
  - [12. A deeper historical interpretation](#12-a-deeper-historical-interpretation)
  - [1960s–70s](#1960s70s)
  - [1970s–80s](#1970s80s)
  - [1990s](#1990s)
  - [2000s onward](#2000s-onward)
  - [13. Research directions worth exploring next](#13-research-directions-worth-exploring-next)
  - [14. Recommended primary references](#14-recommended-primary-references)
  - [Conclusion](#conclusion)

## Etymology

The word *markup* is derived from the traditional publishing practice of marking up a manuscript, which involves adding handwritten annotations in the form of conventional symbolic printer's instructions—in the margins and text of a paper or printed manuscript.

For centuries, this task was done primarily by skilled typographers known as *markup men* or *markers* who marked up text to indicate what typeface, style, and size should be applied to each part, and who passed the marked-up copy to the compositors for typesetting.

The term *markup language* is therefore a natural extension of the traditional concept, applied to computer-based document preparation.

## Types of markup language

There are three main general categories of electronic markup:

- **Presentational markup** — The traditional kind used by word-processing systems. It focuses on the appearance of the document (e.g., bold, italic, font size).
- **Procedural markup** — Provides instructions for programs that process the text (e.g., troff, TeX).
- **Descriptive markup** — Labels parts of the document according to their meaning or role (e.g., "heading", "paragraph", "emphasis"). This is the approach of SGML, XML, and HTML.

There is considerable overlap between these categories. Modern systems often mix presentational and descriptive markup, and many languages that began as presentational have evolved descriptive features.

## History

### GenCode

The first well-known public presentation of markup languages in computer text processing was made by William W. Tunnicliffe at a conference in 1967, although he preferred to call it *generic coding*. It can be seen as a response to the emergence of processing programs such as RUNOFF that each used their own control notation, often specific to the target typesetting device. In the 1970s, Tunnicliffe led the development of a standard called GenCode for the publishing industry. Book designer Stanley Rice published speculation along similar lines in 1970.

Brian Reid, in his 1980 dissertation at Carnegie Mellon University, developed a theory and working implementation of descriptive markup in actual use. However, IBM researcher Charles Goldfarb is more commonly considered the inventor of markup languages. Goldfarb developed the basic idea while working on a primitive document management system intended for law firms in 1969, and helped invent IBM's Generalized Markup Language (GML) later that same year. GML was first publicly disclosed in 1973.

In 1975, Goldfarb moved from Cambridge, Massachusetts to Silicon Valley and became a product planner at the IBM Almaden Research Center. There, he convinced IBM's executives to deploy GML commercially in 1978 as part of IBM's Document Composition Facility product, and it was widely used in business within a few years.

Standard Generalized Markup Language (SGML), the first standard descriptive markup language, was based on both GML and GenCode. It was the result of an International Organization for Standardization (ISO) committee that was first chaired by Tunnicliffe, and which Goldfarb also worked on beginning in 1974. Goldfarb eventually became chair of the committee. SGML was first released by ISO as the ISO 8879 standard in October 1986.

### troff and nroff

Some early examples of computer markup languages available outside the publishing industry can be found in typesetting tools on Unix systems such as troff and nroff. In these systems, formatting commands were inserted into the document text so that typesetting software could format the text according to the editor's specifications. It was a trial and error iterative process to correctly print a document. The availability of WYSIWYG publishing software supplanted much use of these languages among casual users, though professional publishing work still uses markup to specify the non-visual structure of texts, and WYSIWYG editors now usually save documents in a markup-language-based format.

### TeX

Another major publishing standard is TeX, created and refined by Donald Knuth in the 1970s and 1980s. TeX concentrated on the detailed layout of text and font descriptions to typeset mathematical books. This required Knuth to spend considerable time investigating the art of typesetting. TeX is mainly used in academia, where it is a de facto standard in many scientific disciplines. A TeX macro package known as LaTeX provides a descriptive markup system on top of TeX, and is widely used both among the scientific community and the publishing industry.

### Scribe, GML, and SGML

The first language to make a clear distinction between structure and presentation was Scribe, developed by Brian Reid and described in his doctoral thesis in 1980. Scribe was revolutionary in a number of ways, introducing the idea of styles separated from the marked-up document, and a grammar that controlled the usage of descriptive elements. Scribe influenced the development of GML and later SGML, and is a direct ancestor to HTML and LaTeX.

In the early 1980s, the idea that markup should focus on the structural aspects of a document and leave the visual presentation of that structure to the interpreter led to the creation of SGML. The language was developed by a committee chaired by Goldfarb. It incorporated ideas from many different sources, including Tunnicliffe's project, GenCode. Sharon Adler, Anders Berglund, and James A. Marke were also key members of the SGML committee.

SGML specifies a syntax for including the markup in documents, as well as one for separately describing what tags are allowed, and where (the document type definition (DTD), later known as a schema). This allows authors to create and use any markup they want, selecting tags that make the most sense to them and are named in their own natural languages, while also allowing automated verification. Thus, SGML is properly a *metalanguage*, and many markup languages are derived from it. From the late 1980s onward, most substantial new markup languages have been based on SGML, including the Text Encoding Initiative (TEI) guidelines and DocBook. SGML was promulgated as the ISO 8879 standard in 1986.

### HTML

In 1989, Tim Berners-Lee wrote a memo proposing an Internet-based hypertext system and specified HTML and wrote the browser and server software in late 1990. In that year, Berners-Lee and CERN data systems engineer Robert Cailliau collaborated on a joint request for funding, but the project was not formally adopted by CERN. In his personal notes from 1990 he lists "some of the many areas in which hypertext is used" and puts an encyclopedia first.

HTML was based on an in-house SGML-based documentation format at CERN, and very similar to the sample schema in the SGML standard. Eleven of these elements still exist in HTML 4.

Berners-Lee considered HTML an SGML application. The Internet Engineering Task Force (IETF) formally defined it as such with the mid-1993 publication of the first proposal for an HTML specification: "Hypertext Markup Language (HTML)" by Berners-Lee and Dan Connolly, which included an SGML DTD to define the grammar. Many of the HTML text elements are found in the 1988 ISO technical report TR 9537 *Techniques for using SGML*, which in turn covers the features of early text formatting languages, such as that used by the RUNOFF command developed in the early 1960s for the Compatible Time-Sharing System operating system. These formatting commands were derived from those used by typesetters to manually format documents. Steven DeRose argues that HTML's use of descriptive markup (and the influence of SGML in particular) was a major factor in the success of the Web, because of the flexibility and extensibility that it enabled. HTML became the main markup language for creating web pages and other information that can be displayed in a web browser and is likely the most used markup language in the world in the 21st century.

### XML

XML (Extensible Markup Language) is a widely used meta markup language. It was developed by the World Wide Web Consortium (W3C) in a committee created and chaired by Jon Bosak. The main purpose of XML was to simplify SGML by focusing on a particular use case—documents on the Internet. XML remains a metalanguage like SGML, allowing users to create any tags needed (hence *extensible*) and then describing those tags and their permitted uses.

XML adoption was hastened by the fact that every XML document can be written so that it is also an SGML document, allowing existing SGML users and software to switch to XML fairly easily. At the same time, XML eliminates many complex features of SGML to simplify implementation environments such as documents and publications. It appears to balance simplicity and flexibility, as well as support very robust schema definitions and validation tools, and was rapidly adopted for many uses. XML is now widely used for communicating data between applications, serializing program data, for hardware communication protocols, vector graphics, and other uses besides documents.

### XHTML

From January 2000 until HTML 5 was released, all W3C recommendations for HTML were based on XML, using XHTML (Extensible HyperText Markup Language). The language specification requires that XHTML documents be well-formed XML documents. This allows for more rigorous and robust documents, by avoiding many syntax errors which historically led to unwanted browser behavior, while still using document components familiar to HTML users.

One of the most noticeable differences between HTML and XHTML is the latter's rule that all tags must be closed: empty HTML tags such as `<br>` must either be closed with a regular end-tag, or replaced by a special form: `<br />` (the space before the slash on the end tag is optional but frequently used, because it enables some pre-XML web browsers and SGML parsers to accept the tag). Another difference is that all attribute values in tags must be quoted. Both these differences are commonly criticized as verbose but also praised because they make it far easier to detect, localize, and repair errors. Finally, all tag and attribute names within the XHTML namespace must be lowercase to be valid. HTML, on the other hand, was case-insensitive.

### Other XML-based applications

Many XML-based applications exist, including the Resource Description Framework as RDF/XML, XForms, DocBook, SOAP, and the Web Ontology Language (OWL). For a partial list of these, see [list of XML markup languages](https://en.wikipedia.org/wiki/List_of_XML_markup_languages).

## Features

A common feature of many markup languages is that they intermix the text of a document with markup instructions in the same data stream or file. This is not necessary; it is possible to isolate markup from text content, using pointers, offsets, IDs, or other methods to coordinate the two. Such *standoff markup* is typical for the internal representations that programs use to work with marked-up documents. However, embedded or *inline markup* is much more common elsewhere.

For example, the following is a small section of text marked up in HTML:

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>My test page</title>
  </head>
  <body>
    <h1>Wikipedia HTML example!</h1>
    <img src="images/wikipedia-logo.png" alt="A globe consisting of puzzle pieces with each piece representing a language">

    <p>At Wikipedia, you can find the following content in articles (and more):</p>

    <ul>
      <li>Text</li>
      <li>Images</li>
      <li>Audio</li>
    </ul>

    <p>You can edit Wikipedia and make it better!</p>

    <p>Visit <a href="https://wikipedia.org/">Wikipedia</a> today!</p>
  </body>
</html>
```

The codes enclosed in angle-brackets (`<like this>`) are markup instructions (known as tags), while the text between these instructions is the actual text of the document. The codes `h1`, `p`, and `em` are examples of *semantic markup*, in that they describe the intended purpose or the meaning of the text they include. Specifically, `h1` means the enclosed text is a first-level heading, `p` means a paragraph, and `em` means an emphasized word or phrase. A program interpreting such structural markup may apply its own rules or styles for presenting the various pieces of text, using different typefaces, boldness, font size, indentation, color, or other styles, as desired.

In contrast, the `i` tag in HTML 4 is an example of *presentational markup*, which is generally used to specify a characteristic of the text without specifying the reason for that appearance. In this case, the `i` element dictates the use of an italic typeface. However, in HTML 5, this element has been repurposed with a more semantic usage: to denote "a span of text in an alternate voice or mood, or otherwise offset from the normal prose in a manner indicating a different quality of text". For example, it is appropriate to use the `i` element to indicate a taxonomic designation or a phrase in another language. The change was made to ease the transition from HTML 4 to 5 as smoothly as possible so that deprecated uses of presentational elements would preserve the most likely intended meaning.

TEI has published extensive guidelines for how to encode texts of interest in the humanities and social sciences, developed through years of international cooperative work. These guidelines are used for encoding historical documents, and the works of particular scholars, periods, and genres.

## Broader use

While the idea of markup language originated with text documents, they are increasingly used in the presentation of other types of information, including playlists, vector graphics, web services, content syndication, and user interfaces. Most of these are XML applications because XML is a well-defined and extensible language.

The use of XML has also led to the possibility of combining multiple markup languages into a single profile, like XHTML+SMIL and XHTML+MathML+SVG.

## See also

- [ADDML](https://en.wikipedia.org/wiki/ADDML)
- [Comparison of document markup languages](https://en.wikipedia.org/wiki/Comparison_of_document_markup_languages)
- [Curl (programming language)](https://en.wikipedia.org/wiki/Curl_(programming_language))
- [List of markup languages](https://en.wikipedia.org/wiki/List_of_markup_languages)
- [Programming language](https://en.wikipedia.org/wiki/Programming_language)
- [Modeling language](https://en.wikipedia.org/wiki/Modeling_language)
- [Plain text](https://en.wikipedia.org/wiki/Plain_text)
- [Formatted text](https://en.wikipedia.org/wiki/Formatted_text)
- [Texy!](https://en.wikipedia.org/wiki/Texy!)
- [ReStructuredText](https://en.wikipedia.org/wiki/ReStructuredText)
- [SCRIPT (markup)](https://en.wikipedia.org/wiki/SCRIPT_(markup))
- [Style sheet language](https://en.wikipedia.org/wiki/Style_sheet_language)

## Notes

1. HTML is a particular instance of SGML, whereas LaTeX is designed with the separation-between-content-and-design philosophy of Scribe in mind.

## Extended Analysis: Structure, Processing, and Design

The foundational material introduces the history and major families of markup languages, including the distinction between describing document structure and controlling presentation. The following sections examine how markup represents information, how documents are processed, and how design philosophies affect practical use.

The additional discussion builds on those foundations with technical explanations, comparisons, and broader context.

### 1. What is a markup language, really?

A markup language is a formal notation for adding information to content. That additional information can describe the content's structure, meaning, presentation, relationships, or intended processing.

Consider the same sentence represented in four ways.

**Plain text**

```text
The History of Computing
```

**HTML — document structure**

```html
<h1>The History of Computing</h1>
```

**Markdown — lightweight authoring**

```text
## The History of Computing
```

**LaTeX — document typesetting**

```text
\section{The History of Computing}
```

All three marked-up examples communicate that the text has a particular role, but they use different syntax, conventions, and processing systems. HTML represents a heading in a web document, Markdown offers a compact authoring notation, and LaTeX expresses a section within a typeset document.

This illustrates an important principle: markup is not merely decoration; it can encode information about how content is organized and understood.

A heading might appear in large, bold text, but its semantic role as a heading is more important than those visual characteristics. A screen reader, document outline generator, search engine, or conversion tool may use that role independently of its appearance.

#### The components of a marked-up document

A useful way to understand markup is to separate five concepts:

- **Content:** the underlying information, such as words, numbers, images, or mathematical expressions.
- **Markup syntax:** the notation used to express additional information, such as tags, delimiters, attributes, or indentation.
- **Structure:** the organization of content into elements, sections, lists, tables, and other components.
- **Semantics:** the intended meaning or role of those components.
- **Processing:** the interpretation, validation, transformation, storage, or rendering of the marked-up information.

These concepts are related, but they are not interchangeable. A syntax defines how markup is written; a vocabulary defines which elements and attributes exist; a schema may constrain how those elements can be combined; and a processor determines what to do with the resulting document.

For example, XML defines much of the syntax used to write tags, but it does not automatically tell a processor what a custom element such as `<invoice-total>` means. That meaning comes from the vocabulary, its specification, and the software that uses it.

### 2. The three traditional categories of markup

The Wikipedia article identifies three categories: presentational, procedural, and descriptive markup. These categories are best understood as different answers to the question, What information should the markup express?

#### 2.1 Presentational markup

Presentational markup specifies how content should look.

For example, a word might be marked as bold, italic, red, or 18 points in size. The markup directly encodes a visual property rather than necessarily explaining why that property is appropriate.

**Advantages:** direct control over appearance.

**Disadvantages:** appearance becomes intertwined with content, making redesign, reuse, and consistent formatting harder.

#### 2.2 Procedural markup

Procedural markup tells a processing system what actions or operations to perform.

A typesetting document might instruct a processor to change fonts, insert vertical space, or begin a new page. The markup expresses operations in a sequence rather than simply identifying the meaning of each passage.

**Advantages:** fine-grained control over production.

**Disadvantages:** documents can become dependent on a particular processor, sequence of operations, or output medium.

#### 2.3 Descriptive markup

Descriptive markup identifies the role or meaning of a piece of content.

For example, a passage might be identified as a heading, quotation, mathematical expression, person, or bibliographic reference. A separate processing system can decide how to display or use that information.

**Advantages:** reuse, consistency, transformation, accessibility, and machine processing.

**Disadvantages:** meaningful markup requires a vocabulary and conventions that processors must understand.

These categories are not mutually exclusive. LaTeX, for example, provides commands for identifying document structure while also offering precise typesetting control. HTML has semantic elements, but its rendering is also influenced by presentation rules and CSS.

#### Why descriptive markup became so important

Suppose a document contains a heading.

A presentation-oriented approach says:

> Render this text in 24-point bold type.

A descriptive approach says:

> This text is a level-one heading.

The second description leaves room for different output decisions. A website might render the heading in large text, a printed book might apply a different typeface, and a text-to-speech system might announce it as a heading.

This is the principle commonly called separation of content and presentation. It improves portability because a document's meaning can survive changes in styling, layout, and output technology.

However, descriptive markup does not eliminate presentation concerns. It makes the distinction explicit so that the same underlying structure can support different presentation policies.

### 3. A taxonomy of markup languages

The three traditional categories describe markup's purpose. Another useful classification groups languages according to their syntax, domain, and intended use.

| Family | Primary purpose | Examples |
| --- | --- | --- |
| General-purpose metalanguages | Define other markup vocabularies | SGML, XML |
| Web document markup | Structure and describe web content | HTML, XHTML |
| Lightweight markup | Author readable source with minimal notation | Markdown, reStructuredText, AsciiDoc |
| Typesetting markup | Control document composition and typography | TeX, LaTeX |
| Technical publishing | Represent structured technical documentation | DocBook |
| Scholarly text encoding | Represent texts and editorial scholarship | TEI |
| Vector graphics | Describe scalable two-dimensional graphics | SVG |
| Mathematical markup | Represent mathematical notation and structure | MathML |
| Data-oriented markup | Represent structured records and exchanged information | XML-based vocabularies, including Atom |
| Interface-oriented markup | Describe interface structure or layout | XAML and XUL |

The boundaries overlap. SVG, for example, describes graphics using XML syntax; MathML represents mathematical content; and HTML can combine text, images, audio, video, and interactive controls. The HTML standard defines both document semantics and extensive browser behavior.

*Source: W3C (+2 more)*

A language's classification therefore depends on what aspect we are examining. XML is a syntax and metalanguage, while SVG is a domain-specific vocabulary built on that syntax. Markdown is a lightweight authoring language, while HTML is the web document language it commonly generates.

#### 3.1 Markup languages versus metalanguages

One of the most important distinctions in the original article is between a markup language and a metalanguage.

A markup language provides a notation for describing documents. A metalanguage provides rules for defining other languages.

XML illustrates the distinction. Its syntax permits authors to create named elements:

```xml
<book>
  <title>Introduction to Computing</title>
  <author>A. Example</author>
</book>
```

XML itself does not define what a `book` or `author` is. An application-specific vocabulary assigns meaning to those names. A schema can then specify which elements are allowed, how they relate, and what data they may contain.

This creates several distinct layers:

- **Syntax:** how a document is written.
- **Vocabulary:** which names and constructs are available.
- **Schema:** which combinations of constructs are permitted.
- **Semantics:** what the constructs mean.
- **Processing model:** what a consuming application does with them.

These layers are related but independent. Two documents may both be valid XML while expressing completely different kinds of information.

XML's specification distinguishes a well-formed document from a valid document. Well-formedness concerns XML's basic syntactic rules, such as properly nested and matched tags. Validity adds conformance to applicable declarations or constraints.

*Source: W3C*

This layered architecture is a major reason XML became useful for document interchange, publishing, and application-to-application communication.

### 4. Syntax: how markup is written

Markup languages differ not only in what they represent, but also in how authors express it.

#### 4.1 Tag-based syntax

HTML and XML commonly use angle-bracket tags.

```html
<article>
  <h1>Markup Languages</h1>
  <p>Markup adds structure to content.</p>
</article>
```

The tags identify elements, and their nesting expresses a hierarchical structure. Attributes provide additional information about an element.

For example:

```xml
<a href="https://example.com/">Visit the website</a>
```

The element represents a link, while the `href` attribute supplies its destination.

This syntax is explicit and extensible, although its opening and closing tags can make documents verbose.

#### 4.2 Delimiter-based syntax

Lightweight markup often uses punctuation as a shorthand for structural or presentational concepts.

```text
## Markup Languages

Markup adds **structure** to content.

- HTML
- XML
- Markdown
```

The source is readable without being rendered. Its brevity makes it attractive for notes, documentation, source-code repositories, and collaborative writing.

However, the original Markdown ecosystem developed multiple implementations with differing interpretations of ambiguous syntax. CommonMark addresses this problem by defining a more precise specification and a conformance test suite.

*Source: spec.commonmark.org (+1 more)*

#### 4.3 Command-based syntax

TeX and LaTeX use commands introduced by a backslash.

```text
\section{Markup Languages}

Markup adds \textbf{structure} to content.
```

Commands can describe document structure, select formatting, invoke macros, and control complex typesetting operations. This makes the approach powerful for scientific documents and publications requiring precise mathematical notation.

The trade-off is that a document's interpretation can depend on macro definitions, packages, and the typesetting engine.

#### 4.4 Indentation-sensitive syntax

Some structured text formats use indentation to express hierarchy rather than explicit tags.

YAML is an important example:

```yaml
book:
  title: Introduction to Computing
  author: A. Example
```

YAML is primarily a data-serialization language rather than a traditional document-markup language. Nevertheless, it is a useful comparison because it illustrates how a format can represent nested information without angle-bracket tags.

The general lesson is that markup is not synonymous with XML-style tags. It is the broader idea of using a formal notation to distinguish content and its organization or interpretation.

### 5. The structure of a marked-up document

A marked-up document can be understood as a structured object rather than merely a sequence of characters.

Consider this XML document:

```xml
<article>
  <title>Markup Languages</title>
  <paragraph>
    Markup describes the structure of a document.
  </paragraph>
  <paragraph>
    It can also support automated processing.
  </paragraph>
</article>
```

The document contains an article element, a title element, and two paragraph elements. Each element has a position in the hierarchy.

```text
article (root element)
├── title (text content)
├── paragraph (text content)
└── paragraph (text content)
```

*Simplified structural representation.*

This hierarchical organization is often represented internally as a tree. Each element becomes a node, nested elements become children, and the overall document has a root.

The tree model is particularly important for HTML and XML processing. Browsers construct a Document Object Model (DOM) for HTML documents, while XML parsers can expose a corresponding tree of elements, attributes, and text nodes.

#### 5.1 Elements, attributes, and text

Three basic components of tag-based markup are worth distinguishing.

- Elements represent document components, such as paragraphs, headings, books, or products.
- Attributes attach additional information to elements, such as identifiers, links, language codes, or classifications.
- Text nodes hold textual content within the document.

For example:

```xml
<person id="p17" role="editor">
  Ada Example
</person>
```

Here, `person` is the element name, `id` and `role` are attributes, and `Ada Example` is the text content.

Attributes and child elements can sometimes represent similar information. Choosing between them is a design decision influenced by the vocabulary's intended semantics, validation rules, and processing requirements.

#### 5.2 Inline markup and standoff markup

The Wikipedia article also discusses two different ways to associate markup with content.

Inline markup places the markup directly in the document:

```html
<p>The <em>important</em> result was published.</p>
```

Standoff markup stores annotations separately and associates them with the original content through identifiers, offsets, or other references.

A simplified example might look like this:

```json
{
  "text": "The important result was published.",
  "annotations": [
    {
      "start": 4,
      "end": 13,
      "type": "emphasis"
    }
  ]
}
```

This JSON is illustrative, not a standardized standoff-markup format.

Inline markup is straightforward for ordinary nested documents. Standoff markup can be more convenient when annotations overlap, when the source must remain unchanged, or when multiple independent annotation layers must coexist.

For instance, a researcher studying a historical letter might need to annotate the same words with linguistic information, editorial commentary, named entities, and uncertain readings. These annotations may overlap in ways that are awkward to represent through a single nested element hierarchy.

The distinction reveals a deeper question: Does markup belong inside the document, or should it be maintained as a separate layer of information about the document?

### 6. How markup is processed

Markup does not normally produce a visible result by itself. Software interprets the source according to the relevant language specification and processing rules.

A typical workflow looks like this:

1. **Source document** — Text plus markup
2. **Parsing** — Recognize syntax and structure
3. **Interpretation and validation** — Apply language rules and optional constraints
4. **Processing** — Build a document tree, transform data, or apply styles
5. **Output** — A web page, PDF, structured data, or another representation

This is a conceptual pipeline, not a requirement that every markup language follow exactly these steps.

#### 6.1 Parsing

A parser recognizes the notation and determines how the document is structured.

For example, it determines which text belongs inside a paragraph, whether a sequence of tags is properly nested, and whether a Markdown delimiter indicates emphasis or another construct.

Different languages require different parsing strategies. HTML parsing, XML parsing, and Markdown parsing do not follow identical rules.

#### 6.2 Validation

Validation checks a document against additional requirements.

For XML, this might involve checking whether a document conforms to a Document Type Definition (DTD) or another schema. In HTML, conformance checkers can identify violations of the language's authoring requirements.

A document may be syntactically parseable without satisfying every semantic or application-specific constraint. A structurally valid XML document, for example, might still contain a nonsensical date or a reference to a nonexistent product.

Validation therefore has several possible levels:

- Syntax and structural correctness.
- Conformance to a vocabulary or schema.
- Domain-specific consistency.
- Application-level business rules.

#### 6.3 Transformation and rendering

After parsing, a processor may transform the document into another format or render it for a particular medium.

A recipe document encoded in XML could be transformed into HTML for a website, PDF for printing, or plain text for a compact recipe card.

Likewise, a Markdown document can be converted to HTML. A stylesheet can determine how structured elements are displayed in a browser. CSS is specifically designed to control aspects of web-document presentation such as typography, colors, and spacing.

*Source: W3C (+1 more)*

This ability to separate a source document from its output is one of the most important practical benefits of markup.

### 7. Major markup languages in greater depth

The original article concentrates on the historical development of SGML, HTML, XML, and TeX-related systems. For a more complete study, it helps to compare these with lightweight markup and domain-specific vocabularies.

### HTML

**HyperText Markup Language**

HTML is the core markup language of the Web. It defines elements for headings, paragraphs, links, images, forms, tables, and many other document and interface components.

Unlike a completely user-defined XML vocabulary, HTML has a standardized set of element names and defined browser-processing behavior. Modern HTML is maintained as a living standard.

*Source: HTML Living Standard (+1 more)*

**Best suited for:** web pages, browser-based documents, and web application structure.

### XML

**Extensible Markup Language**

XML provides rules for creating structured documents with named elements and attributes.

It is useful when applications need explicit document structure, predictable syntax, extensible vocabularies, and validation. Its flexibility comes with a cost: verbose notation and the need to define conventions for each application.

**Best suited for:** structured documents, configuration, document exchange, and specialized data vocabularies.

*Source: W3C*

### Markdown

**Lightweight markup**

Markdown prioritizes human-readable source. Authors can create headings, lists, links, code blocks, and emphasis without writing a tag for every element.

Its simplicity makes it popular for software documentation, notes, readme files, and collaborative writing. Different implementations may support different extensions, so compatibility requires attention to the dialect or specification being used.

**Best suited for:** documentation, technical notes, and relatively simple structured writing.

*Source: spec.commonmark.org (+1 more)*

### TeX and LaTeX

**Typesetting and document preparation**

TeX is a typesetting system, while LaTeX is a document preparation system built on TeX. LaTeX provides higher-level commands for sections, references, mathematical notation, bibliographies, and document structure.

It combines descriptive commands with detailed control over composition, making it especially useful for academic and mathematical publishing.

**Best suited for:** scientific papers, technical books, mathematical writing, and publication workflows.

### TEI

**Text Encoding Initiative**

TEI provides extensive guidelines for encoding texts for scholarly research, particularly in the humanities and social sciences.

A TEI document can represent structural divisions, speakers, dates, names, textual variants, editorial interventions, and other features relevant to scholarly interpretation.

**Best suited for:** digital editions, historical documents, literary studies, and linguistic research.

#### 7.1 Why there are so many markup languages

No single markup language is ideal for every task.

HTML is optimized for web documents and browser behavior. XML supports the creation of specialized vocabularies. Markdown emphasizes writing convenience. LaTeX focuses on high-quality typesetting, while TEI supports the detailed representation of texts as scholarly objects.

This diversity reflects different priorities:

- Readability for human authors.
- Expressive power.
- Strictness and predictability.
- Ease of parsing.
- Semantic precision.
- Extensibility.
- Compatibility with existing systems.
- Suitability for particular output formats.

A language designed for one of these goals may be less convenient for another. For example, XML's explicit tags can improve structural clarity but make simple prose more verbose than Markdown.

### 8. Markup languages and programming languages

A useful extension to the Wikipedia article is to examine the boundary between markup languages and programming languages.

A traditional markup language describes the organization, properties, or interpretation of content. A programming language expresses computations or behavior. This is a distinction of primary purpose, not an absolute boundary.

Consider:

```xml
<button>Save</button>
```

This HTML describes a button in a document. By itself, it does not implement an application's save operation.

Now consider JavaScript:

```javascript
button.addEventListener("click", () => {
  saveDocument();
});
```

The JavaScript specifies behavior in response to an event. Together, the HTML and JavaScript can define both the interface component and its behavior.

Some systems blur this boundary. TeX macros can express substantial computation; XSLT is a declarative transformation language for XML; and HTML includes elements whose behavior is defined by the browser.

It is therefore more useful to classify a language according to its expressive capabilities and intended role than to assume that every markup language is passive or that every language containing angle brackets is markup.

#### Markup versus data serialization

Another related distinction is between markup languages and data formats.

XML can represent both documents and data records. JSON primarily represents data structures, while YAML is commonly used for configuration and data serialization. They can serve overlapping purposes without belonging to exactly the same conceptual category.

The important distinction is whether a format is principally concerned with annotating and structuring content, representing data values, defining executable behavior, or combining these roles.

### 9. Design principles and trade-offs

When evaluating or designing a markup language, several questions become particularly important.

| Design dimension | Key question | Common trade-off |
| --- | --- | --- |
| Readability | Can humans understand the source easily? | Conciseness versus explicitness |
| Expressiveness | Can the language represent the required concepts? | Simplicity versus flexibility |
| Extensibility | Can new concepts be introduced safely? | Freedom versus interoperability |
| Validation | Can invalid structures be detected? | Strictness versus authoring convenience |
| Semantics | Are the meanings of constructs clear? | Generality versus domain specificity |
| Presentation | Can content be rendered in different ways? | Reuse versus fine-grained visual control |
| Interoperability | Do different processors interpret documents consistently? | Implementation freedom versus standardization |
| Complexity | How difficult is parsing and implementation? | Power versus ease of implementation |

These are not merely theoretical concerns. They explain why two languages with superficially similar syntax can behave very differently in practice.

#### 9.1 Extensibility versus interoperability

A highly extensible language permits users to define new elements or constructs. This can be powerful, but extensibility creates a challenge: a processor cannot necessarily understand a vocabulary that it has never encountered.

XML addresses the syntactic side of this problem by providing a general framework for defining elements. Applications still need shared vocabulary definitions and processing conventions if independently developed systems are to exchange information reliably.

Thus, syntactic compatibility does not guarantee semantic interoperability.

Two applications may parse the same document successfully yet disagree about what its elements mean.

#### 9.2 Strictness versus robustness

Strict syntax can make errors easier to detect. XML, for example, requires properly nested elements and matching start and end tags.

HTML has a different processing model. Browsers are designed to handle a wide range of real-world documents, including many with authoring errors. That behavior improves practical compatibility, but it also means that a document's interpreted structure may not be obvious from its source alone.

Neither approach is universally superior. The appropriate balance depends on whether the priority is reliable data exchange, tolerant display, ease of authoring, or some combination of these goals.

#### 9.3 Semantics versus appearance

A document that describes content semantically can be reused in ways that a purely presentational document may not support.

A heading identified as a heading can contribute to navigation and accessibility. A date encoded as a date can be validated or processed independently of its displayed formatting. A bibliographic reference can be transformed into different citation styles without changing the underlying information.

These benefits depend on the vocabulary actually expressing meaningful distinctions. Merely inventing descriptive-looking tag names does not ensure that a document has clear semantics.

### 10. Markup languages beyond publishing

The article observes that markup has expanded into graphics, mathematical notation, playlists, web services, and user interfaces.

These applications demonstrate that markup is a general technique for representing structured information.

**Graphics — SVG**

SVG represents two-dimensional graphics through elements such as paths, shapes, text, and groups. Because it describes geometry rather than only a fixed-resolution bitmap, it can be scaled and manipulated by compatible software.

**Mathematics — MathML**

MathML represents mathematical expressions and their structure, supporting uses in which mathematics must be interpreted or processed rather than stored only as an image.

**Technical documentation — DocBook**

DocBook provides a vocabulary for structured technical books and articles. A document can identify chapters, sections, procedures, examples, and other components for downstream publishing.

**User interfaces — XAML and similar systems**

Interface-oriented markup can describe windows, controls, layouts, and relationships between visual components. Application frameworks then interpret that structure and connect it to application behavior.

These examples show that markup is not inherently tied to prose or even to human-readable documents. It can describe any domain in which structured, machine-interpretable representations are useful.

### 11. Limitations, security, and accessibility

A comprehensive study should also consider what markup languages do not guarantee.

#### 11.1 Markup does not guarantee correct meaning

A document can be well-formed but factually wrong, logically inconsistent, or unsuitable for its intended purpose. Structural validation cannot automatically establish the truth of the content.

#### 11.2 Markup does not guarantee accessibility

Semantic structure can support assistive technologies, but only when authors use appropriate elements and provide necessary information. A visually clear document may still have a poor heading hierarchy, inaccessible controls, or missing descriptions for meaningful images.

#### 11.3 Markup processing can introduce security risks

Markup is often processed using complex software, and some features can be dangerous when used with untrusted input.

XML processing, for example, requires careful configuration around external entities and resource resolution. HTML applications must also handle untrusted content safely to prevent injection attacks, including cross-site scripting.

Security therefore depends on the language, processor, configuration, and surrounding application—not simply on whether a document is valid.

#### 11.4 Markup can become overly complicated

An excessively detailed vocabulary can make authoring and maintenance difficult. Excessively permissive markup can lead to inconsistent usage, while overly restrictive markup can make legitimate documents difficult to express.

A successful markup design balances expressiveness with clarity, predictable processing, and practical ease of use.

### 12. A deeper historical interpretation

The history described in the Wikipedia article can be understood as a progression through several different problems.

### 1960s–70s

**Standardizing publishing instructions**

Early systems such as RUNOFF, troff, and nroff used embedded commands to direct text processing. GenCode and IBM's GML helped advance the idea that documents could use generalized descriptions instead of device-specific instructions.

### 1970s–80s

**Separating structure from presentation**

Scribe and the development of SGML advanced descriptive markup and the idea that document structure should be distinct from its eventual visual form. TeX simultaneously demonstrated the importance of sophisticated control over typography and mathematical composition.

### 1990s

**The Web and extensible document formats**

HTML made structured hypertext central to the Web. XML simplified aspects of SGML for broader use, including data exchange and specialized vocabularies.

### 2000s onward

**Lightweight authoring and specialized applications**

Markdown became popular for readable source documents, while markup-based technologies continued to support graphics, mathematical expressions, scholarly editions, configuration, and interface descriptions.

This is a thematic summary rather than a complete chronology.

One important qualification is that the history is not a simple progression in which each new language replaces the previous one. Presentational, procedural, and descriptive approaches continue to coexist because different tasks require different kinds of control.

The enduring development is the increasing ability to describe content independently of a particular output device or application, while retaining specialized tools for cases where exact presentation or processing behavior matters.

### 13. Research directions worth exploring next

To research markup languages in depth, the investigation could expand into six areas.

1. **Comparative language design** — Compare XML, HTML, Markdown, LaTeX, and SGML in terms of syntax, semantics, extensibility, validation, and processing. This is the best starting point for understanding the field's major design trade-offs.
2. **Formal grammars and parsing** — Investigate grammars, tokenization, parsing algorithms, error recovery, tree construction, and how language specifications define what counts as a valid document.
3. **Semantics and knowledge representation** — Explore how vocabularies encode meaning, how metadata is represented, and why syntactic validity is different from semantic correctness.
4. **Document transformation and publishing** — Study stylesheets, XSLT, Markdown conversion pipelines, typesetting engines, and multi-format publishing systems.
5. **Interoperability and security** — Examine schema design, versioning, namespaces, compatibility, safe parsing, and the challenges of exchanging structured documents between independent systems.
6. **Scholarly and historical encoding** — Investigate TEI, digital editions, archival documents, overlapping annotations, and the role of markup in preserving the interpretation and provenance of texts.

### 14. Recommended primary references

For research beyond the Wikipedia article, these specifications and documentation sources are particularly valuable.

- [XML 1.0 — W3C](https://www.w3.org/TR/xml/) — The formal specification for XML syntax, well-formedness, and validity terminology.
- [HTML Living Standard — WHATWG](https://html.spec.whatwg.org/multipage/) — The authoritative technical reference for HTML's elements, document structure, parsing, and browser behavior.

[CommonMark specification](https://spec.commonmark.org/)

A precise specification for Markdown syntax, useful for studying ambiguity, parsing, and interoperability.

- [CSS — W3C](https://www.w3.org/Style/CSS/) — Documentation on the language used to control the presentation of web documents.
- [TEI Guidelines](https://www.tei-c.org/guidelines/) — A substantial reference for scholarly text encoding and the modeling of complex textual features. These sources complement the historical overview with primary technical material. *(W3C (+3 more)).*

### Conclusion

Markup languages are best understood as a family of systems for representing structured information. Their common feature is the use of formal notation to distinguish content from additional information about its organization, interpretation, presentation, or processing.

Their development has involved several recurring tensions: meaning versus appearance, simplicity versus expressiveness, flexibility versus interoperability, and human readability versus machine precision.

The most important conceptual distinction is that a document's structure, its meaning, its visual presentation, and the operations performed on it are separate concerns, even when a particular language combines them.

Understanding that distinction makes it easier to compare existing languages, understand their histories, select the appropriate format for a task, and evaluate the design of new markup systems.

> **Research note.** The Wikipedia text in Part I is the basis for the historical framework and original categories. The technical examples, comparisons, and research directions above are additional explanatory material; they are not all claims made by the original article.
