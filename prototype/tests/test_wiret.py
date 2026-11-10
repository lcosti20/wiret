"""Prototype test suite (spec sections 1.6 Tier 0 and 7.4).

Run from `prototype/`:  python3 -m unittest discover tests
"""
import contextlib
import copy
import io
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wiret import wbc  # noqa: E402
from wiret.checker import check  # noqa: E402
from wiret.compiler import compile_module as compile_declared  # noqa: E402
from wiret.disasm import disassemble  # noqa: E402
from wiret.flow import view_flow  # noqa: E402
from wiret.model import Lit, PinRef, Place, note_detached, note_text, notes  # noqa: E402
from wiret.ops import add_note, convert_comments, delete_box, delete_node  # noqa: E402
from wiret.parser import ParseError, parse  # noqa: E402
from wiret.printer import layout_hash, print_module, semantic_hash  # noqa: E402
from wiret.vm import VM, WiretError  # noqa: E402

DEMO = os.path.join(os.path.dirname(HERE), "examples", "demo.wiret")


def compile_module(*args, export_all=True, **kw):
    """The tests call functions by name, as `wiretc run` and the editor do, so they build with
    --export-all (section 5.2). ExportModeTests use compile_declared for a normal build."""
    return compile_declared(*args, export_all=export_all, **kw)


def demo() -> str:
    with open(DEMO, encoding="utf-8") as f:
        return f.read()

FOR_RANGE = """
macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32

  flow {
    bump -> test
    entry -> init
    init -> test
    seq.then0 -> each_out
    seq.then1 -> bump
    test.then -> seq
    test.else -> finish
  }

  node bump = SetLocal i(
    .value <- Add::<i32>(
      .a <- cur,
      .b <- 1,
    ),
  )
  node cur = GetLocal i()
  node each_out = Exit each(
    .index <- cur,
  )
  node entry = Entry()
  node finish = Exit done()
  node init = SetLocal i(
    .value <- entry.first,
  )
  node seq = Sequence() @count(2)
  node test = Branch(
    .cond <- Le::<i32>(
      .a <- cur,
      .b <- entry.last,
    ),
  )
}
"""


def module(body: str, macros=True) -> str:
    return ("wiret 1\nmodule t\n\nextern func host.Log(message: string)\n"
            + (FOR_RANGE if macros else "") + body)


def build(text):
    m = parse(text)
    r = compile_module(m, text)
    if not r.ok:
        raise AssertionError("\n".join(str(d) for d in r.diags))
    return m, r


def run(text, func, *args, trace=None):
    _, r = build(text)
    out = []
    def hook(f, n, S, depth, snap, phase):
        if phase == "enter":
            trace.append((n, tuple(S)))
    hook = hook if trace is not None else None
    vm = VM(output=out.append, hook=hook)
    res = vm.call(vm.load(r.wbc), func, list(args))
    return res, out


def codes(text):
    return sorted({d.code for d in check(parse(text))})


def instruction_bytes(data: bytes) -> list:
    return [b.code for b in wbc.decode_module(data).bodies]


class FormatTests(unittest.TestCase):
    def test_demo_is_canonical_and_idempotent(self):
        text = demo()
        once = print_module(parse(text))
        self.assertEqual(once, text, "examples/demo.wiret is not in canonical form")
        self.assertEqual(print_module(parse(once)), once)

    def test_non_canonical_input_is_normalised(self):
        text = module("""
func F(x: i32) -> (y: i32) {
  node ret   = Return(  .y   <-   s.result
  )
  node entry = Entry(
  )
  node s     = Add::<i32>(

    .b <- 0x10,
  .a <- entry.x )

  flow {
    entry.then -> ret
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn("func F(x: i32) -> (y: i32) = Add::<i32>(\n  .a <- x,\n  .b <- 16,\n)\n",
                      out)
        self.assertEqual(print_module(parse(out)), out)

    def test_single_use_nodes_are_written_inline(self):
        text = module("""
func Main() {
  local score: i32
  node as_text = Convert::<i32, string>(
    .value <- now.value,
  )
  node entry = Entry()
  node line = Call std.string.Concat(
    .a <- "Your score is ",
    .b <- as_text.result,
  )
  node now = GetLocal score()
  node show = Call host.Log(
    .message <- line.result,
  )

  flow {
    entry -> show
  }

  layout {
    #[note("Log needs text, so Convert turns the number into text.")]
    as_text at (600, 320)
    line at (780, 180)
    now at (440, 420)
    show at (980, 0)
  }
}
""", macros=False)
        want = module("""
func Main() {
  local score: i32

  flow {
    entry -> show
  }

  node entry = Entry()
  node show = Call host.Log(
    .message <- Call std.string.Concat(
      .a <- "Your score is ",
      .b <- Convert::<i32, string>(
        .value <- GetLocal score(),
      ),
    ),
  )

  layout {
    show at (980, 0)
    show.message at (780, 180)
    #[note("Log needs text, so Convert turns the number into text.")]
    show.message.b at (600, 320)
    show.message.b.value at (440, 420)
  }
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), want)
        m = parse(want)
        self.assertEqual(print_module(m), want)
        g = m.graph("Main")
        self.assertEqual(sorted(n.id for n in g.nodes),
                         ["entry", "show", "show.message", "show.message.b",
                          "show.message.b.value"])
        self.assertEqual(g.node("show.message.b").binding("value").value.node,
                         "show.message.b.value")
        self.assertEqual(run(want, "Main"), ([], ["Your score is 0"]))
        # a node read twice is declared, under a name made from its old dotted id
        from wiret.model import PinRef
        g.node("show.message").binding("a").value = PinRef("show.message.b", "result")
        out = print_module(m)
        self.assertIn("  node show_message_b = Convert::<i32, string>(\n"
                      "    .value <- GetLocal score(),\n  )\n", out)
        self.assertIn("      .a <- show_message_b,\n      .b <- show_message_b,\n", out)
        self.assertIn("    show_message_b at (600, 320)\n    show_message_b.value at (440, 420)\n",
                      out)
        self.assertEqual(print_module(parse(out)), out)

    def test_nodes_with_exec_pins_or_attributes_are_declared(self):
        text = module("""
func F() -> (n: i32) {
  flow {
    entry -> get
    get -> r
  }

  node entry = Entry()
  node get = Call G()
  node r = Return(
    .n <- get,
  )
  node seq = Sequence() @count(2)
}

func G() -> (n: i32) {
  flow {
    entry -> r
  }

  node entry = Entry()
  node r = Return(
    .n <- 1,
  )
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)

    def test_unknown_metadata_and_layout_props_survive(self):
        text = module("""
#[x.acme.review("ok", level: 2)]
func F() {
  node entry = Entry()
  layout {
    #[Hash(1)]
    entry at (1, 2) [label = "Start", x.acme.pin = [a, b]]
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn('#[x.acme.review("ok", level: 2)]\nfunc F() {', out)
        self.assertIn("    #[Hash(1)]\n    entry at (1, 2)", out)
        self.assertIn('x.acme.pin = [a, b]', out)

    def test_metadata_lines_stand_above_their_statement(self):
        text = module("""
#[note("second")]
#[keywords("a", "b")]
#[note("first")]
#[doc("Does F.")]
func F() @pure {
  #[note("why")]
  local x: i32
  node entry = Entry()
  layout {
    #[doc("the start")]
    entry
    #[note("a group")]
    box g "G" at (0, 0) size (10, 10) [members = [entry]]
  }
}
""", macros=False)
        m = parse(text)
        out = print_module(m)
        self.assertIn('#[doc("Does F.")]\n#[keywords("a", "b")]\n#[note("second")]\n'
                      '#[note("first")]\nfunc F() @pure {', out)
        self.assertIn('  #[note("why")]\n  local x: i32\n', out)
        self.assertIn('  node entry = Entry()\n', out)
        self.assertIn('    #[doc("the start")]\n    entry\n', out)
        self.assertEqual(m.graph("F").node("entry").meta[0].name, "doc")
        self.assertIn('    #[note("a group")]\n    box g "G"', out)
        self.assertEqual(print_module(parse(out)), out)
        self.assertEqual(m.graph("F").meta[0].name, "note")   # the model keeps written order

    def test_metadata_must_touch_its_statement(self):
        for body, hint in (('#[note("x")]\n\n  local x: i32', "no blank line"),
                           ('node entry = Entry()\n  #[note("x")]', "directly above"),
                           ('node entry = Entry()\n  flow {\n    #[note("x")]\n    entry -> entry\n  }',
                            "flow wires"),
                           ('#[note("x")]\n  node entry = Entry()', "layout block"),
                           ('node entry = Entry()\n  layout {\n    entry\n  }', "at (x, y)"),
                           ('#[note("x")] local x: i32', "next line")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)

    def test_stale_layout_line_is_kept_with_W0605(self):
        # an inline node's name is its position, so an edit that moves it leaves its layout
        # line and notes naming nothing; that is a warning and the text is kept, not an error
        text = module("""
func F() {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )

  layout {
    entry at (0, 0)
    log at (200, 0)
    #[note("Says hi.")]
    log.message at (100, 120)
    #[note("Only a note, no position.")]
    log.message.value
  }
}
""", macros=False)
        m = parse(text)
        diags = [d for d in check(m) if d.code == "W0605"]
        self.assertEqual(sorted(d.node for d in diags), ["log.message", "log.message.value"])
        self.assertEqual(print_module(m), text)          # nothing is dropped or moved
        self.assertTrue(compile_module(m, text).ok)
        # a merge keeps the stale lines too
        from wiret.merge import merge_texts
        merged = merge_texts(text, text, text)
        self.assertIn('#[note("Says hi.")]\n    log.message at (100, 120)', merged.text)

    def test_promoted_inline_node_skips_taken_and_retired_ids(self):
        # an inline node that comes to feed a second input is declared under its dotted
        # name with underscores, then _2, _3, ... past live ids and ids retired in wiret.ids
        from wiret.model import Binding, PinRef
        text = module("""
func F() {
  node entry = Entry()
  node log = Call host.Log(
    .message <- Call std.string.Concat(
      .a <- "a",
      .b <- "b",
    ).result,
  )
  node log_message = Call host.Log(
    .message <- "taken",
  )
  node again = Call host.Log()

  flow {
    entry -> log
    log -> log_message
    log_message -> again
  }
}
""", macros=False)

        def promoted(retired):
            m = parse(text)
            g = m.graph("F")
            g.node("again").bindings.append(Binding("message", PinRef("log.message", "result")))
            m.retired_nodes = {("F", r) for r in retired}
            out = print_module(m)
            return re.findall(r"node (log_message\w*) = Call std.string.Concat", out), out

        self.assertEqual(promoted(())[0], ["log_message_2"])     # log_message is live
        names, out = promoted(("log_message_2", "log_message_3"))
        self.assertEqual(names, ["log_message_4"])
        self.assertIn(".message <- log_message_4,", out)
        # a retired id in another graph does not count
        self.assertEqual(promoted(())[0], ["log_message_2"])
        m = parse(text)
        m.retired_nodes = {("G", "log_message_2")}
        m.graph("F").node("again").bindings.append(
            Binding("message", PinRef("log.message", "result")))
        self.assertIn("node log_message_2 = Call std.string.Concat", print_module(m))

    def test_markup_block_is_rejected_with_a_hint(self):
        with self.assertRaises(ParseError) as cm:
            parse(module("\nfunc F() {\n  node entry = Entry()\n  markup {\n"
                         '    attribute a = Note(message: "x")\n  }\n}\n', macros=False))
        self.assertIn('#[note(', cm.exception.msg)

    def test_at_doc_is_e0104_with_a_hint(self):
        text = module('\nfunc F() @doc("x") {\n  node entry = Entry() @x.acme.review\n}\n',
                      macros=False)
        diags = [d for d in check(parse(text)) if d.code == "E0104"]
        self.assertEqual(len(diags), 2)
        self.assertIn("#[doc(", diags[0].message)
        self.assertEqual(diags[1].node, "entry")

    def test_inputs_go_in_parentheses_one_per_line(self):
        text = module("""
func F() {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn('  node log = Call host.Log(\n    .message <- "hi",\n  )\n', out)
        self.assertEqual(out, text)
        # one line, no trailing comma: read the same
        one = text.replace('Call host.Log(\n    .message <- "hi",\n  )',
                           'Call host.Log(.message <- "hi")')
        self.assertEqual(print_module(parse(one)), text)

    def test_old_syntax_is_rejected_with_a_hint(self):
        for body, hint in (('node log = Call host.Log(message: "hi")', ".pin <- value"),
                           ("node a = Add<i32>()", "Add::<i32>"),
                           ("local xs: array<i32>", "array::<i32>"),
                           ('node log = Call host.Log\n    .message <- "hi"', "in parentheses"),
                           ("node entry = Entry", "'Entry()'"),
                           ('node log = Call host.Log(.message <- "hi" .x <- 1)', "',' or ')'"),
                           ("node a = Add::<i32>(.a <- Call host.Log())", "no output"),
                           ('node log = Call host.Log() .message <- "hi"', "end of line")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)
        with self.assertRaises(ParseError) as cm:
            parse(module("\nmacro M<T>(in: exec) {\n}\n", macros=False))
        self.assertIn("::<", cm.exception.msg)

    def test_comments_directly_above_a_statement_are_kept(self):
        text = module("""
// A test module.
// Two lines.
enum Mode {
  // the quiet one
  Idle
  Run
}

func F() {
  // the start
  //
  //   indented, as written
  node entry = Entry()
  node log = Call host.Log(
    // what it says
    .message <- Format "{n} items"(
      .n <- 3,
    ),
  )

  layout {
    entry at (0, 0)
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertEqual(out, text)
        self.assertNotIn("W0603", {d.code for d in check(parse(text))})
        # the flow block moves above the nodes, and its wire keeps its comment
        wired = text.replace("  node entry = Entry()\n", "  node entry = Entry()\n\n  flow {\n"
                             "    // first\n    entry -> log\n  }\n\n")
        out = print_module(parse(wired))
        self.assertIn("func F() {\n  flow {\n    // first\n    entry -> log\n  }\n\n"
                      "  // the start\n  //\n  //   indented, as written\n  node entry", out)
        self.assertIn("    // what it says\n    .message <- Format", out)
        self.assertEqual(print_module(parse(out)), out)
        # not part of the semantic text, so a comment edit does not change the semantic hash
        self.assertEqual(semantic_hash(parse(out)),
                         semantic_hash(parse(out.replace("what it says", "its message"))))
        self.assertNotEqual(layout_hash(parse(out)),
                            layout_hash(parse(out.replace("what it says", "its message"))))
        # a commented node is declared, never written inline, so its comment has a place
        m = parse(out)
        m.graph("F").node("log.message").comment = ["the text"]
        self.assertIn("  // the text\n  node log_message = Format", print_module(m))

    def test_comments_are_reported_and_convertible(self):
        text = module("""
func F() {
  // explain the entry

  node entry = Entry()  // and a trailing one
}
""", macros=False)
        m = parse(text)
        self.assertIn("W0603", {d.code for d in check(m)})
        self.assertEqual(len(m.comments), 2)
        convert_comments(m)
        out = print_module(m)
        self.assertIn('    #[note("explain the entry")]\n', out)

    def test_parse_errors_have_positions(self):
        with self.assertRaises(ParseError) as cm:
            parse("wiret 1\nmodule t\nfunc F( {\n}\n")
        self.assertEqual(cm.exception.line, 3)


TYPE_DECLS = """
const MAX: i32 = 3

#[doc("What an enemy is doing.")]
enum Mode: u8 @id("en_k3f9") {
  Idle = 0
  #[note("Moving towards the player.")]
  Chase @id("m_c")
  Flee = 7
}

struct Empty {}

#[doc("A point on the map.")]
struct Vec2 {
  y: f32 = 1.5
  #[doc("Across.")]
  x: f32 @id("f_x")
  name: string = "origin"
}

func Main() {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )
}
"""


class TypeDeclTests(unittest.TestCase):
    """Step 1 of struct/enum support: parse, print and hash the declarations (section 2.2)."""

    def test_canonical_round_trip(self):
        text = module(TYPE_DECLS, macros=False)
        m = parse(text)
        out = print_module(m)
        self.assertEqual(out, text)
        self.assertEqual(print_module(parse(out)), out)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Main")[1], ["hi"])

    def test_model(self):
        m = parse(module(TYPE_DECLS, macros=False))
        items = {it.name: it for it in m.items}
        mode, vec = items["Mode"], items["Vec2"]
        self.assertEqual(mode.base, "u8")
        self.assertEqual([(x.name, x.value) for x in mode.members],
                         [("Idle", 0), ("Chase", None), ("Flee", 7)])
        self.assertEqual(note_text(notes(mode.member("Chase").meta)[0]),
                         "Moving towards the player.")
        self.assertEqual([f.name for f in vec.fields], ["y", "x", "name"])
        self.assertEqual(vec.field("y").default.value, 1.5)
        self.assertEqual(vec.field("x").attrs[0].name, "id")
        self.assertEqual(items["Empty"].fields, [])

    def test_items_sorted_by_kind_then_name_members_kept_in_order(self):
        text = module("""
func Main() {
  node entry = Entry()
}
struct B {
  z: i32
  a: i32
}
struct A {}
enum E { Second=2
  First = 1
}
const K: i32 = 1
""", macros=False)
        out = print_module(parse(text))
        body = out.split("extern func host.Log(message: string)\n", 1)[1]
        self.assertEqual(body, """
const K: i32 = 1

enum E {
  Second = 2
  First = 1
}

struct A {}

struct B {
  z: i32
  a: i32
}

func Main() {
  node entry = Entry()
}
""")

    def test_metadata_is_not_semantic_but_member_order_is(self):
        text = module(TYPE_DECLS, macros=False)
        m1, m2 = parse(text), parse(text)
        for it in m2.items:
            it.meta = []
            for x in getattr(it, "fields", []) + getattr(it, "members", []):
                x.meta = []
        self.assertEqual(semantic_hash(m1), semantic_hash(m2))
        self.assertNotEqual(layout_hash(m1), layout_hash(m2))
        m3 = parse(text)
        vec = next(it for it in m3.items if it.name == "Vec2")
        vec.fields.reverse()
        self.assertNotEqual(semantic_hash(m1), semantic_hash(m3))

    def test_unknown_attributes_on_members_are_e0104(self):
        text = module("""
enum Mode {
  Idle @doc("x")
}

struct P {
  hp: i32 = 100 @bogus
}
""", macros=False)
        diags = [d for d in check(parse(text)) if d.code == "E0104"]
        self.assertEqual(len(diags), 2)
        self.assertIn("#[doc(", diags[0].message)
        self.assertIn("'P.hp'", diags[1].message)

    def test_parse_errors(self):
        for src, hint in (("enum E: f32 {\n}\n", "integer type"),
                          ("enum E: Mode {\n}\n", "integer type"),
                          ("enum E {\n  A = 1u8\n}\n", "plain integer"),
                          ('enum E {\n  A = "x"\n}\n', "plain integer"),
                          ("enum E {\n  A B\n}\n", "end of line"),
                          ("struct S {\n  x\n}\n", "expected :"),
                          ("struct S {\n  x: i32 y: i32\n}\n", "end of line"),
                          ("struct S::<T> {\n}\n", "no type parameters"),
                          ("struct S {\n  #[doc(\"x\")]\n}\n", "directly above"),
                          ("class C::<T> {\n}\n", "no type parameters"),
                          ("class C {\n  macro M() {\n  }\n}\n", "module level"),
                          ("interface I {\n  x: i32\n}\n", "lists methods"),
                          ("interface I {\n  func F() {\n  }\n}\n", "no body")):
            with self.subTest(src):
                with self.assertRaises(ParseError) as cm:
                    parse(module("\n" + src, macros=False))
                self.assertIn(hint, cm.exception.msg)


class TypeCheckTests(unittest.TestCase):
    """Step 2 of struct/enum support: resolve the types and check the declarations."""

    def diags(self, body):
        return check(parse(module(body, macros=False)))

    def found(self, body):
        return sorted(((d.code, d.pin) for d in self.diags(body)), key=lambda x: (x[0], x[1] or ""))

    def test_declared_types_resolve(self):
        body = """
var mode: Mode

enum Mode {
  Idle
}

struct Vec2 {
  x: f32
}

struct Path {
  points: array::<Vec2>
  mode: Mode
}

func Move(p: Vec2, ps: array::<Vec2>) -> (m: Mode) {
  local last: Vec2
  node entry = Entry()
}
"""
        self.assertEqual(self.found(body), [])
        r = compile_module(parse(module(body, macros=False)))
        self.assertTrue(r.ok, [str(d) for d in r.diags])

    def test_unknown_types(self):
        diags = self.diags("""
struct S {
  a: Vector
  b: array::<Nope>
  c: t.S
  d: exec
}

func F(x: Missing) {
  node entry = Entry()
}
""")
        self.assertEqual(sorted((d.code, d.graph, d.pin) for d in diags),
                         [("E0501", "F", None), ("E0501", "S", "a"), ("E0501", "S", "b"),
                          ("E0501", "S", "c"), ("E0501", "S", "d")])
        by_pin = {d.pin: d.message for d in diags}
        self.assertIn("write 'S'", by_pin["c"])
        self.assertIn("exec is only", by_pin["d"])

    def test_duplicate_names(self):
        self.assertEqual(self.found("""
enum E {
  A
  A
}

struct S {
  x: i32
  x: f32
}

struct i32 {}

struct array {}

struct E {}
"""), [("E0102", None), ("E0102", None), ("E0102", None), ("E0102", "A"), ("E0102", "x")])

    def test_field_defaults(self):
        self.assertEqual(self.found("""
struct Vec2 {}

struct S {
  ok_int: i32 = 3
  ok_float: f64 = 1
  ok_list: array::<i32> = null
  bad_text: i32 = "x"
  bad_range: u8 = 256
  bad_neg: u16 = -1
  bad_struct: Vec2 = null
  bad_bool: bool = 0
}
"""), [("E0110", "bad_bool"), ("E0110", "bad_neg"), ("E0110", "bad_range"),
       ("E0110", "bad_struct"), ("E0110", "bad_text")])

    def test_enum_values(self):
        from wiret.registry import enum_values
        m = parse(module("""
enum E: i8 {
  A
  B = 5
  C
  D = -128
  E
  F = 127
}
""", macros=False))
        self.assertEqual(enum_values(m.items[1]),
                         [("A", 0), ("B", 5), ("C", 6), ("D", -128), ("E", -127), ("F", 127)])
        self.assertEqual(codes(print_module(m)), [])
        self.assertEqual(self.found("""
enum Small: u8 {
  Top = 255
  Over
}

enum Signed: i8 {
  Low = -129
}

enum Wide {
  Big = 2147483648
}
"""), [("E0110", "Big"), ("E0110", "Low"), ("E0110", "Over")])

    def test_struct_cycles(self):
        diags = [d for d in self.diags("""
struct Self {
  me: Self
}

struct A {
  b: B
}

struct B {
  c: C
}

struct C {
  a: A
}

struct Tree {
  label: string
  children: array::<Tree>
}

struct UsesA {
  a: A
}
""") if d.code == "E0503"]
        self.assertEqual(sorted(d.message for d in diags),
                         ["struct 'A' contains itself by value: A -> B -> C -> A",
                          "struct 'Self' contains itself by value: Self -> Self"])

    def test_new_diagnostics_have_plain_explanations(self):
        from wiret.explain import explain
        diags = self.diags("""
enum Small: u8 {
  Top = 256
  Top
}

struct i32 {}

struct S {
  me: S
  hp: i32 = "x"
  t: Vector
  q: t.S
  e: exec
}
""")
        self.assertEqual(len(diags), 9)
        for d in diags:
            with self.subTest(d=str(d)):
                friendly = explain(d)
                self.assertNotEqual(friendly, d.message)
                self.assertNotIn(d.code, friendly)
                self.assertNotIn("None", friendly)


STRUCT_NODES = """
enum Mode: u8 {
  Idle
  Chase
  Flee = 5
}

struct Enemy {
  pos: Vec2
  mode: Mode = Mode::Idle
  hp: i32 = 10
}

struct Vec2 {
  x: f32
  y: f32 = 1.5
}

func Spawn() -> (e: Enemy) @pure {
  flow {
    entry -> r
  }

  node entry = Entry()
  node r = Return(
    .e <- MakeStruct Enemy(
      .pos <- MakeStruct Vec2(),
      .mode <- Mode::Chase,
    ),
  )
}

func Step(e: Enemy) -> (out: Enemy, fleeing: bool) {
  flow {
    entry -> sw
    sw.case0 -> r1
    sw.case1 -> r1
    sw.default -> r2
  }

  node chased = WithField Enemy.pos(
    .obj <- entry.e,
    .value <- MakeStruct Vec2(
      .x <- Add::<f32>(
        .a <- parts.x,
        .b <- 1,
      ),
      .y <- parts.y,
    ),
  )
  node entry = Entry()
  node mode = GetField Enemy.mode(
    .obj <- entry.e,
  )
  node parts = BreakStruct Vec2(
    .obj <- GetField Enemy.pos(
      .obj <- entry.e,
    ),
  )
  node r1 = Return(
    .out <- chased,
    .fleeing <- Eq::<Mode>(
      .a <- mode,
      .b <- Mode::Flee,
    ),
  )
  node r2 = Return(
    .out <- entry.e,
    .fleeing <- Lt::<Mode>(
      .a <- mode,
      .b <- Mode::Flee,
    ),
  )
  node sw = Switch::<Mode>(
    .value <- Select::<Mode>(
      .cond <- Eq::<Enemy>(
        .a <- entry.e,
        .b <- chased,
      ),
      .a <- Mode::Idle,
      .b <- Convert::<u8, Mode>(
        .value <- Convert::<Mode, u8>(
          .value <- mode,
        ),
      ),
    ),
  ) @cases(Mode::Idle, Mode::Chase)
}
"""


class StructNodeTests(unittest.TestCase):
    """Step 3 of struct/enum support: struct nodes, enum values and enum-aware kinds."""

    def found(self, body):
        diags = [d for d in check(parse(module(body, macros=False))) if d.severity == "error"]
        return sorted(((d.code, d.node or d.graph or "", d.pin or "") for d in diags))

    def graph_errors(self, nodes, decls=""):
        """Diagnostics for nodes placed in a function next to STRUCT_NODES' types."""
        types = STRUCT_NODES.split("\nfunc Spawn")[0]
        return self.found(types + decls + "\nfunc G(e: Enemy, v: Vec2, m: Mode) {\n"
                          "  node entry = Entry()\n" + nodes + "}\n")

    def test_program_checks_and_round_trips(self):
        text = module(STRUCT_NODES, macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        self.assertEqual(codes(text), [])
        g = m.graph("Step")
        self.assertEqual(g.node("r1.fleeing").binding("b").value.kind, "enum")
        self.assertEqual(g.node("sw").attr("cases").args[1][1].kind, "enum")
        enemy = next(it for it in m.items if it.name == "Enemy")
        self.assertEqual(enemy.field("mode").default.kind, "enum")
        # MakeStruct inputs default to the field's declared default, else to the zero value
        spawn = parse(text.replace("    .mode <- Mode::Chase\n",
                                   "    .mode <- Mode::Idle\n    .hp <- 10\n"))
        self.assertEqual(print_module(spawn), text.replace("    .mode <- Mode::Chase\n", ""))

    def test_pins(self):
        from wiret.registry import ModuleIndex, signature
        m = parse(module(STRUCT_NODES, macros=False))
        idx, g = ModuleIndex(m), m.graph("Step")

        def pins(nid):
            s = signature(g.node(nid), g, idx)
            return ([(p.name, p.type) for p in s.inputs], [(p.name, p.type) for p in s.outputs],
                    s.purity)

        self.assertEqual(pins("parts"), ([("obj", "Vec2")], [("x", "f32"), ("y", "f32")], "pure"))
        self.assertEqual(pins("chased.value"), ([("x", "f32"), ("y", "f32")], [("result", "Vec2")],
                                         "pure"))
        self.assertEqual(pins("mode"), ([("obj", "Enemy")], [("value", "Mode")], "pure"))
        self.assertEqual(pins("chased"), ([("obj", "Enemy"), ("value", "Vec2")],
                                          [("result", "Enemy")], "pure"))

    def test_struct_node_errors(self):
        self.assertEqual(self.graph_errors("""
  node a = GetField Enemy()
  node b = GetField Nope.x()
  node c = GetField Mode.Idle()
  node d = GetField Enemy.zz()
  node f = MakeStruct Vec2::<i32>()
  node g = MakeStruct Enemy.pos()
  node h = BreakStruct()
  node i = SetField Enemy.hp()
  node j = GetField Enemy.hp(
    .obj <- entry.v,
  )
"""), [("E0110", "j", "obj")] + [("E0501", x, "") for x in "abcdfghi"])

    def test_enum_values(self):
        self.assertEqual(self.graph_errors("""
  node a = Eq::<Mode>(
    .a <- entry.m,
    .b <- Mode::Run,
  )
  node b = Eq::<i32>(
    .a <- 1,
    .b <- Mode::Idle,
  )
  node c = Eq::<Mode>(
    .a <- entry.m,
    .b <- 1,
  )
  node d = Eq::<Mode>(
    .a <- entry.m,
    .b <- Mood::Idle,
  )
""", decls="\nvar ok: Mode = Mode::Chase\n\nvar bad: Mode = Mode::Zip\n"),
            [("E0110", "b", "b"), ("E0110", "c", "b"), ("E0501", "a", "b"),
             ("E0501", "bad", "bad"), ("E0501", "d", "b")])
        self.assertEqual(self.found("""
enum A {
  X
}

enum B {
  Y
}

struct S {
  a: A = A::Nope
  b: A = B::Y
}

func F(p: A = B::Y) {
  local l: A = A::X

  node entry = Entry()
}
"""), [("E0110", "F", "p"), ("E0110", "S", "b"), ("E0501", "S", "a")])

    def test_enum_aware_kinds(self):
        self.assertEqual(self.graph_errors("""
  node lt = Lt::<Mode>(
    .a <- entry.m,
    .b <- Mode::Idle,
  )
  node sel = Select::<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node eq = Eq::<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node to_int = Convert::<Mode, u8>(
    .value <- entry.m,
  )
  node bad_lt = Lt::<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node bad_add = Add::<Mode>(
    .a <- entry.m,
    .b <- entry.m,
  )
  node bad_conv = Convert::<Mode, i32>(
    .value <- entry.m,
  )
  node bad_text = Convert::<Mode, string>(
    .value <- entry.m,
  )
  node bad_struct = Convert::<Vec2, i32>(
    .value <- entry.v,
  )
"""), [("E0110", x, "") for x in ("bad_add", "bad_conv", "bad_lt", "bad_struct", "bad_text")])

    def test_switch_cases(self):
        self.assertEqual(self.graph_errors("""
  node a = Switch::<Mode>(
    .value <- entry.m,
  ) @cases(Mode::Idle, 3, Mode::Nope)
  node b = Switch::<i32>(
    .value <- 0,
  ) @cases(1, "two")
  node c = Switch::<u8>(
    .value <- 0,
  ) @cases(300)
  node Mode = Branch()
"""), [("E0110", "a", "case1"), ("E0110", "b", "case1"),       # a node may be called Mode
       ("E0110", "c", "case0"), ("E0501", "a", "case2")])

    def test_enum_value_literals(self):
        from wiret.parser import parse_literal
        lit = parse_literal("Mode::Chase")
        self.assertEqual((lit.kind, lit.value), ("enum", "Mode.Chase"))
        self.assertEqual(parse_literal("Mode.Chase"), lit)              # Draft 0.11 spelling
        with self.assertRaises(ParseError) as cm:
            parse_literal("a.b.c")
        self.assertIn("Enum::Member", cm.exception.msg)

    def test_a_struct_used_only_inside_a_graph_runs(self):
        text = module("""
struct Vec2 {
  x: f32
}

func Main() {
  node entry = Entry()
  node v = MakeStruct Vec2(
    .x <- 2,
  )
  node x = GetField Vec2.x(
    .obj <- v.result,
  )
  node text = Convert::<f32, string>(
    .value <- x.value,
  )
  node log = Call host.Log(
    .message <- text.result,
  )

  flow {
    entry -> log
  }
}
""", macros=False)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Main")[1], ["2.0"])

    def test_palette_and_explanations(self):
        from wiret import palette
        from wiret.explain import explain
        from wiret.registry import ModuleIndex
        m = parse(module(STRUCT_NODES, macros=False))
        self.assertTrue(palette.items(m.graph("Step"), ModuleIndex(m)))
        types = STRUCT_NODES.split("\nfunc Spawn")[0]
        text = module(types + """
var bad: Mode = Mode::Zip

func G(e: Enemy, v: Vec2, m: Mode, p: Mode = Other.X) {
  node entry = Entry()
  node a = GetField Enemy()
  node b = GetField Nope.x()
  node c = GetField Mode.Idle()
  node d = GetField Enemy.zz()
  node f = MakeStruct Vec2::<i32>()
  node g = MakeStruct Enemy.pos()
  node i = SetField Enemy.hp()
  node j = Eq::<i32>(
    .a <- 1,
    .b <- Mode::Idle,
  )
  node k = Switch::<Mode>(
    .value <- entry.m,
  ) @cases(Mode::Idle, 3)
  node Mode = Branch()
}
""", macros=False)
        diags = [d for d in check(parse(text)) if d.severity == "error"]
        self.assertEqual(len(diags), 11)   # a node called Mode is no clash: j.b is Mode::Idle
        for d in diags:
            with self.subTest(d=str(d)):
                friendly = explain(d)
                self.assertNotEqual(friendly, d.message)
                self.assertNotIn(d.code, friendly)
                self.assertNotIn("None", friendly)


STRUCT_DATA = """
const START: Mode = Mode::Chase

var best: Enemy

var mode: Mode = Mode::Flee

enum Mode: u8 {
  Idle
  Chase
  Flee = 5
}

enum Wide: i64 {
  Far = 5000000000
}

struct Enemy {
  pos: Vec2
  mode: Mode = Mode::Idle
  hp: i32 = 10
  name: string = "grunt"
}

struct Path {
  points: array::<Vec2>
}

struct Tree {
  label: string
  children: array::<Tree>
}

struct Vec2 {
  x: f32
  y: f32 = 1.5
}

func Defaults() -> (local_e: Enemy, global_e: Enemy, m: Mode, s: Mode, made: Enemy) {
  local e: Enemy
  node entry = Entry()
  node ge = GetVar best()
  node gm = GetVar mode()
  node le = GetLocal e()
  node mk = MakeStruct Enemy()
  node r = Return(
    .local_e <- le.value,
    .global_e <- ge.value,
    .m <- gm.value,
    .s <- st.value,
    .made <- mk.result,
  )
  node st = GetVar START()

  flow {
    entry -> r
  }
}

func Equal(a: Enemy, b: Enemy) -> (eq: bool, ne: bool) {
  node entry = Entry()
  node eq = Eq::<Enemy>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node ne = Ne::<Enemy>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node r = Return(
    .eq <- eq.result,
    .ne <- ne.result,
  )

  flow {
    entry -> r
  }
}

func Far() -> (w: Wide, back: i64) {
  node entry = Entry()
  node to_int = Convert::<Wide, i64>(
    .value <- Wide::Far,
  )
  node r = Return(
    .w <- Wide::Far,
    .back <- to_int.result,
  )

  flow {
    entry -> r
  }
}

func Leaf(name: string) -> (t: Tree) {
  node entry = Entry()
  node r = Return(
    .t <- tree.result,
  )
  node tree = MakeStruct Tree(
    .label <- entry.name,
  )

  flow {
    entry -> r
  }
}

func Points(n: i32) -> (path: Path, last_x: f32, count: i32) {
  local pts: array::<Vec2>
  node add = ArrayAdd::<Vec2> pts(
    .item <- point.result,
  )
  node entry = Entry()
  node get = ArrayGet::<Vec2>(
    .array <- now.value,
    .index <- last.result,
  )
  node last = Sub::<i32>(
    .a <- len.length,
    .b <- 1,
  )
  node len = ArrayLength::<Vec2>(
    .array <- now.value,
  )
  node loop = Macro std.flow.ForRange(
    .first <- 0,
    .last <- entry.n,
  )
  node now = GetLocal pts()
  node path = MakeStruct Path(
    .points <- now.value,
  )
  node point = MakeStruct Vec2(
    .x <- x.result,
  )
  node r = Return(
    .path <- path.result,
    .last_x <- x_of.value,
    .count <- len.length,
  )
  node x = Convert::<i32, f32>(
    .value <- loop.index,
  )
  node x_of = GetField Vec2.x(
    .obj <- get.item,
  )

  flow {
    entry -> loop
    loop.each -> add
    loop.done -> r
  }
}

func Pick(m: Mode) -> (word: string) {
  node chase = Return(
    .word <- "chase",
  )
  node entry = Entry()
  node other = Return(
    .word <- "other",
  )
  node sw = Switch::<Mode>(
    .value <- entry.m,
  ) @cases(Mode::Idle, Mode::Chase)
  node wait = Return(
    .word <- "wait",
  )

  flow {
    entry -> sw
    sw.case0 -> wait
    sw.case1 -> chase
    sw.default -> other
  }
}
"""


class StructRunTests(unittest.TestCase):
    """Step 4 of struct/enum support: lowering, the verifier and the VM."""

    def setUp(self):
        self.text = module(STRUCT_DATA)
        _, self.r = build(self.text)
        self.vm = VM()
        self.mod = self.vm.load(self.r.wbc)

    def call(self, func, *args):
        return self.vm.call(self.mod, func, list(args))

    def test_step3_program(self):
        text = module(STRUCT_NODES, macros=False)
        e, = run(text, "Spawn")[0]
        self.assertEqual(e, ((0.0, 1.5), 1, 10))
        self.assertEqual(run(text, "Step", e)[0], [((1.0, 1.5), 1, 10), 0])
        self.assertEqual(run(text, "Step", ((0.0, 1.5), 5, 10))[0], [((0.0, 1.5), 5, 10), 0])

    def test_defaults(self):
        grunt = ((0.0, 1.5), 0, 10, "grunt")
        self.assertEqual(self.call("Defaults"), [grunt, grunt, 5, 1, grunt])

    def test_equality_is_field_by_field(self):
        a = ((1.0, 2.0), 1, 10, "a")
        self.assertEqual(self.call("Equal", a, a), [1, 0])
        for b in (((1.0, 2.5), 1, 10, "a"), ((1.0, 2.0), 0, 10, "a"), ((1.0, 2.0), 1, 10, "b")):
            with self.subTest(b=b):
                self.assertEqual(self.call("Equal", a, b), [0, 1])
        nan = ((math.nan, 2.0), 1, 10, "a")
        self.assertEqual(self.call("Equal", nan, nan), [0, 1])   # as Eq::<f32> on NaN

    def test_arrays_of_structs_and_recursive_types(self):
        path, last_x, count = self.call("Points", 3)
        self.assertEqual(path, (((0.0, 1.5), (1.0, 1.5), (2.0, 1.5), (3.0, 1.5)),))
        self.assertEqual((last_x, count), (3.0, 4))
        self.assertEqual(self.call("Leaf", "root"), [("root", ())])

    def test_enums(self):
        self.assertEqual(self.call("Far"), [5000000000, 5000000000])
        self.assertEqual([self.call("Pick", m)[0] for m in (0, 1, 5)], ["wait", "chase", "other"])

    def test_debug_build_runs_the_same(self):
        r = compile_module(parse(self.text), self.text, debug=True)
        vm = VM()
        mod = vm.load(r.wbc)
        self.assertEqual(vm.call(mod, "Points", [2])[1:], [2.0, 3])
        self.assertEqual(vm.call(mod, "Defaults", [])[2:4], [5, 1])

    def test_cli_values(self):
        from wiret.runner import format_results, parse_args_for
        m = parse(self.text)
        self.assertEqual(format_results(m, "Defaults", self.call("Defaults")).split(", m =")[0],
                         'local_e = Enemy { pos: Vec2 { x: 0.0, y: 1.5 }, mode: Mode::Idle, '
                         'hp: 10, name: \'grunt\' }, global_e = Enemy { pos: Vec2 { x: 0.0, '
                         'y: 1.5 }, mode: Mode::Idle, hp: 10, name: \'grunt\' }')
        self.assertEqual(format_results(m, "Leaf", self.call("Leaf", "r")),
                         "t = Tree { label: 'r', children: [] }")
        self.assertEqual(parse_args_for(m, "Pick", ["Mode::Flee"]), [5])
        for bad in ("5", "Mode::Run", "Wide::Far"):
            with self.subTest(bad), self.assertRaises(ValueError) as cm:
                parse_args_for(m, "Pick", [bad])
            self.assertIn("Mode::Idle, Mode::Chase, Mode::Flee", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            parse_args_for(m, "Equal", ["1", "2"])
        self.assertIn("cannot be typed", str(cm.exception))

    def test_verifier_rejects_bad_struct_code(self):
        good = wbc.decode_module(self.r.wbc)
        st = next(i for i, t in enumerate(good.types) if isinstance(t, wbc.StructType)
                  and len(t.fields) == 2)                   # Vec2
        fn = next(i for i, b in enumerate(good.bodies) if b.code)

        def status(fn_):
            m = wbc.decode_module(self.r.wbc)
            fn_(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def code(*b):
            def f(m):
                m.bodies[fn].code = bytes(b)
            return f

        def self_by_value(m):
            m.types[st] = wbc.StructType(((wbc.Ref(st), None),))

        def ref_to_func_type(m):
            ft = next(i for i, t in enumerate(m.types) if isinstance(t, tuple))
            m.types[st] = wbc.StructType(((wbc.Ref(ft), None),))

        cases = {
            "field out of range": code(0x22, 0, 0, 0, 0, 0x22, 0, 0, 0, 0, 0xD0, st, 0xD1, st, 9,
                                       0x10, 0x05),
            "wrong field type": code(0x20, 1, 0x22, 0, 0, 0, 0, 0xD0, st, 0x10, 0x05),
            "get on a number": code(0x20, 1, 0xD1, st, 0, 0x10, 0x05),
            "not a struct type": code(0x20, 0, 0xD0, 0, 0x10, 0x05),
            "self by value": self_by_value,
            "ref to a func type": ref_to_func_type,
        }
        for name, fn_ in cases.items():
            with self.subTest(name):
                self.assertEqual(status(fn_), "WR_ERR_VERIFY")

    def test_fuzzed_struct_modules_never_crash_the_loader(self):
        rng = random.Random(4321)
        data = bytearray(self.r.wbc)
        for _ in range(1500):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            if rng.random() < 0.2:
                d = d[:rng.randrange(len(d))]
            try:
                VM().load(bytes(d))
            except WiretError:
                pass

    def test_embedded_source_and_disassembly(self):
        m = wbc.decode_module(self.r.wbc)
        self.assertEqual(zlib.decompress(m.custom("wr.graph")).decode(),
                         print_module(parse(self.text)))
        dis = disassemble(self.r.wbc)
        self.assertIn("struct.new", dis)
        self.assertIn("struct.get", dis)


class StructEditorTests(unittest.TestCase):
    """Step 5 of struct/enum support: what the palette and menus offer."""

    def setUp(self):
        from wiret.registry import ModuleIndex
        self.m = parse(module(STRUCT_DATA))
        self.idx = ModuleIndex(self.m)
        self.g = self.m.graph("Equal")

    def labels(self):
        from wiret import palette
        return {it.label: it for it in palette.items(self.g, self.idx)}

    def test_type_choices(self):
        from wiret.registry import key_type_ok, type_choices
        self.assertEqual(type_choices("switch", self.idx)[-2:], ["Mode", "Wide"])
        eq = type_choices("eq", self.idx)
        self.assertIn("Enemy", eq)
        self.assertIn("Tree", type_choices("any", self.idx))
        self.assertIn("Path", eq)             # holds an array, compared element-wise
        self.assertIn("Tree", eq)
        self.assertNotIn("Path", [t for t in eq if key_type_ok(t, self.idx)])
        self.assertNotIn("Enemy", type_choices("ord", self.idx))
        self.assertEqual(type_choices("number", self.idx), type_choices("number"))

    def test_palette_offers_struct_and_enum_nodes(self):
        labels = self.labels()
        for label in ("Make Vec2", "Break Enemy", "Get Enemy.mode", "With Vec2.y (changed copy)",
                      "Switch::<Mode>", "Eq::<Enemy>", "Lt::<Mode>", "Select::<Tree>",
                      "MakeArray::<Vec2>", "Convert::<Mode, u8> (to whole number)",
                      "Convert::<u8, Mode> (to a Mode)", "Eq::<Path>", "Ne::<array::<Vec2>>"):
            with self.subTest(label):
                self.assertIn(label, labels)
        for label in ("Lt::<Vec2>", "Add::<Mode>", "Convert::<Mode, i32> (to whole number)"):
            with self.subTest(label):
                self.assertNotIn(label, labels)
        self.assertEqual(labels["Make Vec2"].category, "Structs")
        self.assertEqual(labels["Get Enemy.mode"].description,
                         "Reads the field 'mode' of an Enemy.")

    def test_struct_docs_reach_the_palette(self):
        from wiret import palette
        src = (STRUCT_NODES.replace("struct Vec2 {", '#[doc("A point.")]\nstruct Vec2 {')
               .replace("  x: f32\n", '  #[doc("Across.")]\n  x: f32\n'))
        m = parse(module(src, macros=False))
        from wiret.registry import ModuleIndex
        idx = ModuleIndex(m)
        self.assertTrue(palette.describe("MakeStruct", "Vec2", idx).endswith("A point."))
        self.assertTrue(palette.describe("GetField", "Vec2.x", idx).endswith("Across."))

    def test_dropping_a_struct_wire_offers_its_nodes(self):
        from wiret import palette
        fits = {it.label for it in palette.items(self.g, self.idx)
                if palette.compatible(it, self.g, self.idx, "out", "Vec2") is not None}
        for label in ("Break Vec2", "Get Vec2.x", "With Vec2.x (changed copy)", "Eq::<Vec2>"):
            self.assertIn(label, fits)
        self.assertNotIn("Break Enemy", fits)
        into = {it.label for it in palette.items(self.g, self.idx)
                if palette.compatible(it, self.g, self.idx, "in", "Mode") is not None}
        self.assertIn("Get Enemy.mode", into)

    def test_pin_colours(self):
        from wiret.viewmodel import type_color
        self.assertEqual(type_color("array::<i32>"), "#f0a830")
        self.assertNotEqual(type_color("Vec2", self.idx), type_color("Vec2"))
        self.assertNotEqual(type_color("Mode", self.idx), type_color("Vec2", self.idx))


CONTAINERS = """
var seen: set::<i32>

struct Cell {
  x: i32
  y: i32
}

struct Grid {
  cells: map::<Cell, string>
}

func Count(words: array::<string>) -> (counts: map::<string, i32>, n: i32, first: string, firstn: i32) {
  local m: map::<string, i32>
  node add = MapSet::<string, i32> m(
    .key <- w.item,
    .value <- plus.result,
  )
  node cur = GetLocal m()
  node entry = Entry()
  node find = MapFind::<string, i32>(
    .map <- cur.value,
    .key <- w.item,
  )
  node k0 = MapKeyAt::<string, i32>(
    .map <- cur.value,
    .index <- 0,
  )
  node len = MapLength::<string, i32>(
    .map <- cur.value,
  )
  node plus = Add::<i32>(
    .a <- find.value,
    .b <- 1,
  )
  node r = Return(
    .counts <- cur.value,
    .n <- len.length,
    .first <- k0.key,
    .firstn <- v0.value,
  )
  node v0 = MapValueAt::<string, i32>(
    .map <- cur.value,
    .index <- 0,
  )
  node w = Macro std.flow.ForEach::<string>(
    .array <- entry.words,
  )

  flow {
    entry -> w
    w.each -> add
    w.done -> r
  }
}

func Describe(m: map::<string, i32>) -> (text: string) {
  local acc: string
  node add = SetLocal acc(
    .value <- line.result,
  )
  node entry = Entry()
  node eq = Call std.string.Concat(
    .a <- loop.key,
    .b <- "=",
  )
  node kv = Call std.string.Concat(
    .a <- eq.result,
    .b <- num.result,
  )
  node line = Call std.string.Concat(
    .a <- old.value,
    .b <- kv.result,
  )
  node loop = Macro std.flow.ForEachMap::<string, i32>(
    .map <- entry.m,
  )
  node num = Convert::<i32, string>(
    .value <- loop.value,
  )
  node old = GetLocal acc()
  node r = Return(
    .text <- old.value,
  )

  flow {
    entry -> loop
    loop.done -> r
    loop.each -> add
  }
}

func Remember(x: i32) -> (added: bool, size: i32, has: bool, removed: bool) {
  node add = SetAdd::<i32> seen(
    .item <- entry.x,
  )
  node entry = Entry()
  node has = SetHas::<i32>(
    .set <- now.value,
    .item <- entry.x,
  )
  node now = GetVar seen()
  node r = Return(
    .added <- add.added,
    .size <- size.length,
    .has <- has.result,
    .removed <- rm.removed,
  )
  node rm = SetRemove::<i32> seen(
    .item <- 999,
  )
  node size = SetLength::<i32>(
    .set <- now.value,
  )

  flow {
    add -> rm
    entry -> add
    rm -> r
  }
}

func Missing(m: map::<string, i32>, key: string) -> (value: i32, found: bool, removed: bool, left: i32) {
  local copy: map::<string, i32>
  node entry = Entry()
  node find = MapFind::<string, i32>(
    .map <- entry.m,
    .key <- entry.key,
  )
  node keep = SetLocal copy(
    .value <- entry.m,
  )
  node left = MapLength::<string, i32>(
    .map <- now.value,
  )
  node now = GetLocal copy()
  node r = Return(
    .value <- find.value,
    .found <- find.found,
    .removed <- rm.removed,
    .left <- left.length,
  )
  node rm = MapRemove::<string, i32> copy(
    .key <- entry.key,
  )

  flow {
    entry -> keep
    keep -> rm
    rm -> r
  }
}

func Place(g: Grid, x: i32, y: i32) -> (g2: Grid, what: string, found: bool) {
  local cells: map::<Cell, string>
  node at = MakeStruct Cell(
    .x <- entry.x,
    .y <- entry.y,
  )
  node entry = Entry()
  node find = MapFind::<Cell, string>(
    .map <- now.value,
    .key <- at.result,
  )
  node get = GetField Grid.cells(
    .obj <- entry.g,
  )
  node load = SetLocal cells(
    .value <- get.value,
  )
  node now = GetLocal cells()
  node put = MapSet::<Cell, string> cells(
    .key <- at.result,
    .value <- "tree",
  )
  node r = Return(
    .g2 <- out.result,
    .what <- find.value,
    .found <- find.found,
  )
  node out = WithField Grid.cells(
    .obj <- entry.g,
    .value <- now.value,
  )

  flow {
    entry -> load
    load -> put
    put -> r
  }
}

func Nans() -> (size: i32) {
  local s: set::<f64>
  node a = SetAdd::<f64> s(
    .item <- nan.result,
  )
  node b = SetAdd::<f64> s(
    .item <- nan.result,
  )
  node entry = Entry()
  node nan = Div::<f64>(
    .a <- 0.0,
    .b <- 0.0,
  )
  node now = GetLocal s()
  node r = Return(
    .size <- size.length,
  )
  node size = SetLength::<f64>(
    .set <- now.value,
  )

  flow {
    a -> b
    b -> r
    entry -> a
  }
}

func OutOfRange(m: map::<string, i32>) -> (k: string) {
  node at = MapKeyAt::<string, i32>(
    .map <- entry.m,
    .index <- 5,
  )
  node entry = Entry()
  node r = Return(
    .k <- at.key,
  )

  flow {
    entry -> r
  }
}
"""


class ContainerTests(unittest.TestCase):
    """set::<T> and map::<K, V>: insertion-ordered value types (sections 3.1, 3.3, 5.6)."""

    @classmethod
    def setUpClass(cls):
        cls.text = print_module(parse(module(CONTAINERS)))
        _, cls.r = build(cls.text)

    def setUp(self):
        self.vm = VM()
        self.mod = self.vm.load(self.r.wbc)

    def call(self, func, *args):
        return self.vm.call(self.mod, func, list(args))

    def test_canonical_and_clean(self):
        self.assertEqual(print_module(parse(self.text)), self.text)
        self.assertEqual(codes(self.text), [])
        self.assertIn("  node add = MapSet::<string, i32> m(\n", self.text)

    def test_maps_keep_insertion_order(self):
        counts, n, first, firstn = self.call("Count", ("b", "a", "b", "c", "b"))
        self.assertEqual(list(counts.items()), [("b", 3), ("a", 1), ("c", 1)])
        self.assertEqual((n, first, firstn), (3, "b", 3))
        self.assertEqual(self.call("Describe", {"z": 1, "a": 2}), ["z=1a=2"])

    def test_sets(self):
        self.assertEqual(self.call("Remember", 5), [1, 1, 1, 0])
        self.assertEqual(self.call("Remember", 7), [1, 2, 1, 0])
        self.assertEqual(self.call("Remember", 5), [0, 2, 1, 0])   # already there

    def test_value_semantics_and_missing_keys(self):
        m = {"a": 1, "b": 2}
        self.assertEqual(self.call("Missing", m, "a"), [1, 1, 1, 1])
        self.assertEqual(self.call("Missing", m, "zz"), [0, 0, 0, 2])
        self.assertEqual(m, {"a": 1, "b": 2})             # the caller's map is unchanged

    def test_struct_keys(self):
        # find is pure, so it is evaluated at the Return, after the MapSet (section 4.3)
        g, what, found = self.call("Place", ({},), 1, 2)
        self.assertEqual((g, what, found), (({(1, 2): "tree"},), "tree", 1))
        g2 = self.call("Place", g, 3, 4)[0]
        self.assertEqual(list(g2[0]), [(1, 2), (3, 4)])

    def test_nan_is_one_key(self):
        self.assertEqual(self.call("Nans"), [1])

    def test_out_of_range_is_a_fault(self):
        with self.assertRaises(WiretError) as cm:
            self.call("OutOfRange", {"a": 1})
        self.assertEqual(cm.exception.status, "WR_ERR_FAULT")
        self.assertIn("out of range", str(cm.exception))

    def test_errors(self):
        bad = module("""
struct Tree {
  label: string
  kids: array::<Tree>
}

var s: set::<i32>

func F(a: map::<array::<i32>, i32>, b: set::<Tree>, c: map::<string, Tree>) -> (y: i32) @pure {
  local m: map::<string, i32>
  node entry = Entry()
  node f1 = MapFind::<i32>(
    .key <- 1,
  )
  node m1 = MapSet::<string, i32>(
    .key <- "a",
    .value <- 1,
  )
  node m2 = MapSet::<string, f32> m(
    .key <- "a",
  )
  node s1 = SetAdd::<i32> s(
    .item <- 1,
  )
  node s2 = SetHas::<Tree>()
}
""", macros=False)
        found = sorted((d.code, d.graph, d.node or "") for d in check(parse(bad))
                       if d.severity == "error")
        self.assertEqual(found, [("E0110", "F", "m2"), ("E0130", "F", "m1"), ("E0302", "F", "s1"),
                                 ("E0501", "F", ""), ("E0501", "F", ""), ("E0501", "F", "s2"),
                                 ("E0502", "F", "f1")])

    def test_verifier(self):
        good = wbc.decode_module(self.r.wbc)
        mt = next(i for i, t in enumerate(good.types) if isinstance(t, wbc.MapType))
        st = next(i for i, t in enumerate(good.types) if isinstance(t, wbc.SetType))
        at = next(i for i, t in enumerate(good.types) if isinstance(t, wbc.ArrayType))
        fn = next(i for i, b in enumerate(good.bodies) if b.code)

        def status(fn_):
            m = wbc.decode_module(self.r.wbc)
            fn_(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def code(*b):
            def f(m):
                m.bodies[fn].code = bytes(b)
            return f

        def array_key(m):
            m.types[mt] = wbc.MapType(wbc.Ref(at), wbc.I32)

        cases = {"array key": array_key,
                 "map op on a set": code(0xE0, st, 0x10, 0x05),
                 "wrong key type": code(0xE0, mt, 0x22, 0, 0, 0, 0, 0xE4, mt, 0x10, 0x05),
                 "set.len on a number": code(0x20, 1, 0xED, st, 0x10, 0x05)}
        for name, fn_ in cases.items():
            with self.subTest(name):
                self.assertEqual(status(fn_), "WR_ERR_VERIFY")

    def test_fuzzed_container_modules_never_crash_the_loader(self):
        rng = random.Random(777)
        data = bytearray(self.r.wbc)
        for _ in range(1500):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            if rng.random() < 0.2:
                d = d[:rng.randrange(len(d))]
            try:
                VM().load(bytes(d))
            except WiretError:
                pass

    def test_cli_values(self):
        from wiret.runner import format_results, parse_args_for
        m = parse(self.text)
        self.assertEqual(parse_args_for(m, "Missing", ['{"a": 1, "b": 2}', "a"]),
                         [{"a": 1, "b": 2}, "a"])
        res = self.call("Count", ("x", "y", "x"))
        self.assertEqual(format_results(m, "Count", res),
                         "counts = {'x': 2, 'y': 1}, n = 2, first = 'x', firstn = 2")
        with self.assertRaises(ValueError):
            parse_args_for(m, "Missing", ["[1, 2]", "a"])

    def test_palette(self):
        from wiret import palette
        from wiret.registry import ModuleIndex
        m = parse(self.text)
        idx = ModuleIndex(m)
        labels = {it.label for it in palette.items(m.graph("Count"), idx)}
        for label in ("MapFind::<string, i32>", "MapSet m", "MapRemove m", "SetAdd seen",
                      "SetHas::<i32>", "MapFind::<Cell, string>",
                      "Macro std.flow.ForEachMap::<string, i32>"):
            with self.subTest(label):
                self.assertIn(label, labels)
        self.assertFalse(any("ForEachMap::<i32, i32>" in x for x in labels))


IDS_SRC = """wiret 1
module game.ids

struct Vec2 {
  x: f32
}

func Add1(v: i32) -> (r: i32, s: i32) {
  local tmp: i32

  flow {
    entry -> ret
  }

  node entry = Entry()
  node plus = Add::<i32>(
    .a <- entry.v,
    .b <- 1,
  )
  node ret = Return(
    .r <- plus,
    .s <- plus,
  )
}
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make_project(root, text=IDS_SRC, ids=""):
    with open(os.path.join(root, "wiret.toml"), "w", encoding="utf-8") as f:
        f.write('[project]\nname = "t"\nwiret = "1"\n')
    with open(os.path.join(root, "wiret.ids"), "w", encoding="utf-8") as f:
        f.write(ids)
    path = os.path.join(root, "game.wiret")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


EQUALITY = """
struct Vec2 {
  x: f64
  y: f64
}

struct Path {
  name: string
  points: array::<Vec2>
}
""" + "".join(['\nfunc Arrays(a: array::<f64>, b: array::<f64>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<array::<f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<array::<f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc Nested(a: array::<array::<i32>>, b: array::<array::<i32>>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<array::<array::<i32>>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<array::<array::<i32>>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc Maps(a: map::<string, i32>, b: map::<string, i32>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<map::<string, i32>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<map::<string, i32>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc Sets(a: set::<i32>, b: set::<i32>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<set::<i32>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<set::<i32>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc FloatSets(a: set::<f64>, b: set::<f64>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<set::<f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<set::<f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc FloatMaps(a: map::<f64, f64>, b: map::<f64, f64>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<map::<f64, f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<map::<f64, f64>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc Paths(a: Path, b: Path) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<Path>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<Path>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n', '\nfunc PathMaps(a: map::<string, Path>, b: map::<string, Path>) -> (eq: bool, ne: bool) {\n  node entry = Entry()\n  node eq = Eq::<map::<string, Path>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node ne = Ne::<map::<string, Path>>(\n    .a <- entry.a,\n    .b <- entry.b,\n  )\n  node r = Return(\n    .eq <- eq.result,\n    .ne <- ne.result,\n  )\n\n  flow {\n    entry -> r\n  }\n}\n'])


class ContainerEqualityTests(unittest.TestCase):
    """Eq and Ne on arrays, maps, sets and structs holding them (section 4.9)."""

    @classmethod
    def setUpClass(cls):
        cls.text = print_module(parse(module(EQUALITY)))
        _, cls.r = build(cls.text)

    def setUp(self):
        self.vm = VM()
        self.mod = self.vm.load(self.r.wbc)

    def same(self, func, a, b):
        eq, ne = self.vm.call(self.mod, func, [a, b])
        self.assertEqual(eq, 1 - ne)
        return bool(eq)

    def test_clean_and_lowered_to_the_natives(self):
        self.assertEqual(codes(self.text), [])
        m = wbc.decode_module(self.r.wbc)
        self.assertEqual(sorted(f"{a}.{b}" for a, b, _, _ in m.imports),
                         ["std.array.Equals", "std.map.Equals", "std.set.Equals"])
        for _, _, t, _ in m.imports:
            self.assertEqual(m.types[t], ([wbc.ANYREF, wbc.ANYREF], [wbc.I32]))
        self.assertIn("call std.array.Equals", disassemble(self.r.wbc))

    def test_arrays_compare_element_wise(self):
        self.assertTrue(self.same("Arrays", (1.0, 2.0), (1.0, 2.0)))
        self.assertTrue(self.same("Arrays", (), ()))
        self.assertTrue(self.same("Arrays", (0.0,), (-0.0,)))
        self.assertFalse(self.same("Arrays", (1.0, 2.0), (2.0, 1.0)))
        self.assertFalse(self.same("Arrays", (1.0,), (1.0, 1.0)))
        nan = float("nan")
        row = (nan,)
        self.assertFalse(self.same("Arrays", row, row))      # NaN is never equal
        self.assertTrue(self.same("Nested", ((1, 2), ()), ((1, 2), ())))
        self.assertFalse(self.same("Nested", ((1, 2), ()), ((1,), (2,))))

    def test_maps_and_sets_ignore_order(self):
        self.assertTrue(self.same("Maps", {"a": 1, "b": 2}, {"b": 2, "a": 1}))
        self.assertFalse(self.same("Maps", {"a": 1, "b": 2}, {"a": 1, "b": 3}))
        self.assertFalse(self.same("Maps", {"a": 1}, {"b": 1}))
        self.assertFalse(self.same("Maps", {"a": 1}, {"a": 1, "b": 2}))
        self.assertTrue(self.same("Sets", {3: None, 1: None}, {1: None, 3: None}))
        self.assertFalse(self.same("Sets", {1: None}, {1: None, 2: None}))
        self.assertFalse(self.same("Sets", {1: None, 2: None}, {1: None, 3: None}))

    def test_nan_keys_match_but_nan_values_do_not(self):
        from wiret.vm import NAN_KEY
        self.assertTrue(self.same("FloatSets", {NAN_KEY: None}, {NAN_KEY: None}))
        self.assertFalse(self.same("FloatMaps", {1.0: float("nan")}, {1.0: float("nan")}))

    def test_structs_holding_containers(self):
        a = ("route", ((0.0, 0.0), (1.0, 2.0)))
        self.assertTrue(self.same("Paths", a, ("route", ((0.0, 0.0), (1.0, 2.0)))))
        self.assertFalse(self.same("Paths", a, ("route", ((0.0, 0.0),))))
        self.assertFalse(self.same("Paths", a, ("other", a[1])))
        self.assertTrue(self.same("PathMaps", {"r": a}, {"r": a}))

    def test_fuel_grows_with_the_compared_length(self):
        def used(n):
            vm = VM(fuel=10_000)
            mod = vm.load(self.r.wbc)
            vm.call(mod, "Arrays", [(1.0,) * n, (1.0,) * n])
            return 10_000 - vm.fuel
        self.assertEqual(used(800) - used(0), 200)       # 1 per 8 elements, in Eq and in Ne
        with self.assertRaises(WiretError) as cm:
            vm = VM(fuel=1_000)
            vm.call(vm.load(self.r.wbc), "Arrays", [(1.0,) * 10_000, (1.0,) * 10_000])
        self.assertEqual(cm.exception.status, "WR_ERR_FUEL")

    def test_anyref_only_in_function_types(self):
        m = wbc.decode_module(self.r.wbc)
        st = next(i for i, t in enumerate(m.types) if isinstance(t, wbc.StructType))
        m.types[st] = wbc.StructType(((wbc.ANYREF, None),) + m.types[st].fields[1:])
        with self.assertRaises(WiretError) as cm:
            VM().load(wbc.encode_module(m))
        self.assertEqual(cm.exception.status, "WR_ERR_VERIFY")

    def test_a_number_is_not_an_anyref(self):
        m = wbc.decode_module(self.r.wbc)
        imp = next(i for i, (a, b, _, _) in enumerate(m.imports) if b == "Equals")
        fn = next(i for i, b in enumerate(m.bodies) if b.code)
        m.bodies[fn].code = bytes([0x20, 1, 0x20, 1, 0x06, imp, 0x10, 0x05])
        with self.assertRaises(WiretError) as cm:
            VM().load(wbc.encode_module(m))
        self.assertEqual(cm.exception.status, "WR_ERR_VERIFY")


class IdTests(unittest.TestCase):
    """@id generation, wiret.ids, E0140 and W0202 (sections 2.4, 7.3, 7.5)."""

    def test_assign_ids(self):
        from wiret.ids import PREFIX, assign_ids, elements
        from wiret.model import Attr, Lit
        m = parse(IDS_SRC)
        m.items[0].attrs.append(Attr("id", [(None, Lit("string", "st_mine"))]))
        changed = assign_ids(m, random.Random(1))
        self.assertEqual(sorted(e.kind for e in changed),
                         ["field", "func", "local", "module", "param", "result", "result"])
        ids = [e.id for e in elements(m)]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertIn("st_mine", ids)                        # existing ids are kept
        for e in changed:
            self.assertRegex(e.id, rf"^{PREFIX[e.kind]}_[a-z2-9]{{4}}$")
        self.assertEqual(assign_ids(m), [])                  # idempotent
        text = print_module(m)
        self.assertEqual(print_module(parse(text)), text)
        self.assertIn('module game.ids @id("mod_', text)
        self.assertIn("v: i32 @id(\"p_", text)

    def test_retired_between(self):
        from wiret.ids import Retired, retired_between
        old = parse(IDS_SRC)
        new = parse(IDS_SRC.replace("  local tmp: i32\n", "")
                    .replace("node plus", "node sum").replace("plus.result", "sum.result"))
        self.assertEqual(retired_between(old, new),
                         [Retired("game.ids", "Add1", "node", "plus")])
        self.assertEqual(retired_between(None, new), [])
        from wiret.ids import assign_ids
        assign_ids(old, random.Random(2))
        new = copy.deepcopy(old)
        new.graph("Add1").locals.clear()
        gone = retired_between(old, new)
        self.assertEqual([(r.graph, r.kind) for r in gone], [("-", "id")])
        self.assertTrue(gone[0].id.startswith("l_"))

    def test_undo_keeps_assigned_ids(self):
        from wiret.ids import assign_ids, carry_ids, elements
        cur = parse(IDS_SRC)
        assign_ids(cur, random.Random(5))
        old = parse(IDS_SRC.replace("  local tmp: i32\n", ""))   # an older snapshot
        self.assertEqual(carry_ids(cur, old), 7)
        want = {(e.kind, e.name): e.id for e in elements(cur) if e.kind != "local"}
        self.assertEqual({(e.kind, e.name): e.id for e in elements(old)}, want)
        self.assertEqual(carry_ids(cur, old), 0)

    def test_project_registry(self):
        from wiret.ids import Retired, find_project
        with tempfile.TemporaryDirectory() as d:
            path = make_project(d, ids="# retired ids\ngame.ids Add1 node old_node\n")
            sub = os.path.join(d, "a", "b")
            os.makedirs(sub)
            self.assertEqual(find_project(os.path.join(sub, "x.wiret")).root, d)
            proj = find_project(path)
            self.assertEqual(proj.retired, {Retired("game.ids", "Add1", "node", "old_node")})
            r = Retired("game.ids", "-", "id", "l_abcd")
            self.assertEqual(proj.retire([r, r]), [r])
            self.assertEqual(proj.retire([r]), [])
            proj.unretire([r])
            self.assertEqual(find_project(path).retired,
                             {Retired("game.ids", "Add1", "node", "old_node")})
        self.assertIsNone(find_project(os.path.join(os.sep, "no_project_here", "x.wiret"))
                          if not os.path.exists(os.path.join(os.sep, "wiret.toml")) else None)

    def test_diagnostics_in_a_project(self):
        from wiret.ids import assign_ids, find_project
        m = parse(IDS_SRC)
        self.assertEqual([d.code for d in check(m)], [])     # a lone file: no W0202
        with tempfile.TemporaryDirectory() as d:
            make_project(d, ids="game.ids Add1 node plus\ngame.ids - id fn_gone\n")
            proj = find_project(os.path.join(d, "game.wiret"))
            codes_ = sorted(d_.code for d_ in check(m, project=proj))
            self.assertEqual(codes_.count("W0202"), 8)
            self.assertIn("E0140", codes_)                   # node 'plus' is retired
            assign_ids(m, random.Random(3))
            m.graph("Add1").attrs = [a for a in m.graph("Add1").attrs if a.name != "id"]
            from wiret.model import Attr, Lit
            m.graph("Add1").attrs.append(Attr("id", [(None, Lit("string", "fn_gone"))]))
            m.graph("Add1").params[0].attrs = list(m.graph("Add1").result_list[0].attrs)
            found = sorted((d_.code, d_.message.split(" ")[0]) for d_ in check(m, project=proj))
            self.assertEqual([c for c, _ in found], ["E0102", "E0140", "E0140"])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_ids_check_against_git(self):
        from wiret.gitids import check_range
        from wiret.ids import assign_ids, find_project
        with tempfile.TemporaryDirectory() as d:
            m = parse(IDS_SRC)
            assign_ids(m, random.Random(4))
            path = make_project(d, print_module(m))

            def sh(*args):
                subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(args),
                               cwd=d, check=True, capture_output=True)
            sh("init", "-q")
            sh("add", ".")
            sh("commit", "-q", "-m", "base")
            m2 = parse(read(path))
            g = m2.graph("Add1")
            g.locals.clear()
            delete_node(g, "plus")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(print_module(m2))
            lines = []
            proj = find_project(path)
            self.assertEqual(check_range(proj, "HEAD", out=lines.append), 1)
            self.assertEqual(sum("was deleted without being retired" in x for x in lines), 2)
            lines.clear()
            self.assertEqual(check_range(proj, "HEAD", record=True, out=lines.append), 0)
            self.assertIn("recorded 2 retired id(s)", lines[0])
            sh("add", ".")
            sh("commit", "-q", "-m", "delete")
            self.assertEqual(check_range(find_project(path), "HEAD~1..HEAD", out=lines.append), 0)
            # bringing the node back is E0140
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(print_module(m))
            lines.clear()
            self.assertEqual(check_range(find_project(path), "HEAD", out=lines.append), 1)
            self.assertTrue(any("E0140" in x and "'plus'" in x for x in lines))
            self.assertIn("E0140", {d_.code for d_ in check(m, project=find_project(path))})

    def test_fmt_assign_ids(self):
        import wiretc
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wiret")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(IDS_SRC)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wiretc.main(["fmt", "--assign-ids", path]), 0)
            text = read(path)
            self.assertEqual(text.count("@id("), 8)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wiretc.main(["fmt", "--assign-ids", path]), 0)
            self.assertEqual(read(path), text)


RENAME_SRC = """
enum Mode {
  Idle
  Run
}

struct Vec2 {
  x: f32
  y: f32
}

func Double(v: i32) -> (r: i32) @pure {
  node entry = Entry()
  node ret = Return(
    .r <- twice.result,
  )
  node twice = Add::<i32>(
    .a <- entry.v,
    .b <- entry.v,
  )

  flow {
    entry -> ret
  }
}

func Main(m: Mode) -> (out: i32, len: f32, word: string) {
  local acc: i32
  node call = Call Double(
    .v <- 21,
  )
  node entry = Entry()
  node get = GetLocal acc()
  node len = GetField Vec2.x(
    .obj <- make.result,
  )
  node make = MakeStruct Vec2(
    .x <- 3.5,
  )
  node parts = BreakStruct Vec2(
    .obj <- make.result,
  )
  node r_idle = Return(
    .out <- get.value,
    .len <- parts.x,
    .word <- "idle",
  )
  node r_run = Return(
    .out <- get.value,
    .len <- len.value,
    .word <- "run",
  )
  node save = SetLocal acc(
    .value <- call.r,
  )
  node sw = Switch::<Mode>(
    .value <- entry.m,
  ) @cases(Mode::Idle)

  flow {
    entry -> save
    save -> sw
    sw.case0 -> r_idle
    sw.default -> r_run
  }
}
"""


def hash_of(text):
    return layout_hash(parse(text))


class EditTests(unittest.TestCase):
    """wiretc edit (section 7.2)."""

    def setUp(self):
        self.text = print_module(parse(module(RENAME_SRC, macros=False)))

    def edit(self, ops, text=None, project=None):
        from wiret.edit import apply_request
        text = text or self.text
        return apply_request(text, {"if_hash": hash_of(text), "ops": ops}, project)

    def test_stale_hash_is_e0900(self):
        from wiret.edit import apply_request
        r = apply_request(self.text, {"if_hash": "old", "ops": []})
        self.assertFalse(r.ok)
        self.assertEqual(r.error["code"], "E0900")
        self.assertEqual(r.text, self.text)

    def test_build_a_graph(self):
        r = self.edit([
            {"op": "create_node", "graph": "Main", "id": "log", "kind": "Call",
             "symbol": "host.Log", "bindings": {"message": '"hello"'}, "x": 100, "y": 50},
            {"op": "unwire_exec", "graph": "Main", "from": "entry"},
            {"op": "wire_exec", "graph": "Main", "from": "entry", "to": "log"},
            {"op": "wire_exec", "graph": "Main", "from": "log", "to": "save"},
            {"op": "set_meta", "graph": "Main", "node": "log", "meta": '#[note("Says hi.")]'},
            {"op": "set_attr", "graph": "Main", "node": "sw", "attr": "@cases(Mode::Idle, Mode::Run)"},
            {"op": "wire_exec", "graph": "Main", "from": "sw.case1", "to": "r_run"},
            {"op": "place", "graph": "Main", "node": "log", "props": {"label": '"Greet"'}},
        ])
        self.assertTrue(r.ok, r.error)
        self.assertEqual([d.code for d in r.diagnostics], [])
        self.assertEqual(print_module(parse(r.text)), r.text)
        self.assertIn('  node log = Call host.Log(\n    .message <- "hello",\n  )\n', r.text)
        self.assertIn("    entry -> log\n    log -> save\n", r.text)
        self.assertIn('    #[note("Says hi.")]\n    log at (100, 50) [label = "Greet"]\n', r.text)
        self.assertIn("+  node log = Call host.Log", r.diff)
        self.assertEqual(r.hash, hash_of(r.text))
        self.assertEqual(run(r.text, "Main", 0)[1], ["hello"])
        self.assertEqual(run(r.text, "Main", 1)[0][2], "run")

    def test_a_bad_op_changes_nothing(self):
        r = self.edit([{"op": "bind", "graph": "Main", "node": "save", "pin": "value", "value": "5"},
                       {"op": "bind", "graph": "Main", "node": "nope", "pin": "x", "value": "1"}])
        self.assertFalse(r.ok)
        self.assertEqual((r.error["op"], r.error["code"]), (1, "E0101"))
        self.assertEqual(r.text, self.text)
        for bad in ({"op": "frobnicate"}, {"op": "bind", "graph": "Main"},
                    {"op": "set_attr", "graph": "Main", "node": "sw", "attr": "cases(1)"},
                    {"op": "bind", "graph": "Main", "node": "save", "pin": "value", "value": "a b"},
                    {"op": "wire_exec", "graph": "Main", "from": "sw", "to": "save"}):
            with self.subTest(bad):
                self.assertFalse(self.edit([bad]).ok)

    def test_delete_node(self):
        r = self.edit([{"op": "delete_node", "graph": "Main", "node": "make"}])
        self.assertFalse(r.ok)
        self.assertIn("cascade", r.error["message"])
        r = self.edit([{"op": "set_meta", "graph": "Main", "node": "make", "meta": '#[note("n")]'},
                       {"op": "delete_node", "graph": "Main", "node": "make", "cascade": True}])
        self.assertTrue(r.ok)
        self.assertEqual(sorted(r.removed), ["make.result -> r_idle.len.obj",
                                             "make.result -> r_run.len.obj"])
        self.assertIn('#[note("n", detached: "make")]', r.text)
        self.assertEqual(sorted({d.code for d in r.diagnostics}), ["W0201", "W0604"])

    def test_edits_retire_ids_in_a_project(self):
        from wiret.ids import find_project
        with tempfile.TemporaryDirectory() as d:
            make_project(d, self.text)
            proj = find_project(os.path.join(d, "game.wiret"))
            r = self.edit([{"op": "rename", "graph": "Main", "node": "get", "to": "read"}],
                          project=proj)
            self.assertTrue(r.ok)
            self.assertEqual([x.line() for x in r.retired], ["t Main node get"])
            self.assertIn("t Main node get", read(os.path.join(d, "wiret.ids")))

    def test_cli(self):
        import wiretc
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wiret")
            req = os.path.join(d, "req.json")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.text)
            with open(req, "w", encoding="utf-8") as f:
                json.dump({"if_hash": hash_of(self.text), "ops": [
                    {"op": "bind", "graph": "Double", "node": "ret.r", "pin": "b", "value": "1"}]}, f)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(wiretc.main(["edit", path, req, "--dry-run"]), 0)
            self.assertEqual(read(path), self.text)
            self.assertTrue(json.loads(out.getvalue())["ok"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wiretc.main(["edit", path, req]), 0)
            self.assertIn(".b <- 1", read(path))
            with contextlib.redirect_stdout(io.StringIO()):          # the hash is now stale
                self.assertEqual(wiretc.main(["edit", path, req]), 1)


class RenameTests(unittest.TestCase):
    """rename by @id rewrites every reference (sections 2.4 and 7.2)."""

    def setUp(self):
        from wiret.ids import assign_ids
        m = parse(module(RENAME_SRC, macros=False))
        assign_ids(m, random.Random(7))
        self.m = m
        self.before = [run(print_module(m), "Main", x)[0] for x in (0, 1)]

    def id_of(self, kind, name):
        from wiret.ids import elements
        return next(e.id for e in elements(self.m) if e.kind == kind and e.name == name)

    def renamed(self, kind, name, new):
        from wiret.rename import rename
        rename(self.m, self.id_of(kind, name), new)
        text = print_module(self.m)
        self.assertEqual([d.code for d in check(parse(text)) if d.severity == "error"], [])
        self.assertEqual([run(text, "Main", x)[0] for x in (0, 1)], self.before)
        return text

    def test_function_param_result_and_local(self):
        text = self.renamed("func", "Double", "Twice")
        self.assertIn("    .value <- Call Twice(\n", text)
        text = self.renamed("param", "v", "n")
        self.assertIn("@pure = Add::<i32>(\n  .a <- n,\n  .b <- n,\n)\n", text)
        self.assertIn("      .n <- 21,\n", text)
        text = self.renamed("result", "r", "doubled")
        self.assertIn("-> (doubled: i32", text)
        text = self.renamed("local", "acc", "total")
        self.assertIn("node get = GetLocal total()\n", text)
        self.assertIn("node save = SetLocal total(\n", text)

    def test_struct_and_field(self):
        text = self.renamed("field", "x", "across")
        self.assertIn("    .len <- GetField Vec2.across(\n", text)
        self.assertIn("    .across <- 3.5,\n", text)
        self.assertIn("    ).across,\n", text)
        text = self.renamed("struct", "Vec2", "Point")
        self.assertIn("node make = MakeStruct Point(\n", text)
        self.assertIn("    .len <- GetField Point.across(\n", text)
        self.assertIn("struct Point", text)

    def test_enum_and_member(self):
        text = self.renamed("member", "Idle", "Resting")
        self.assertIn("@cases(Mode::Resting)", text)
        text = self.renamed("enum", "Mode", "State")
        self.assertIn("func Main(m: State", text)
        self.assertIn("node sw = Switch::<State>(\n", text)
        self.assertIn("  ) @cases(State::Resting)\n", text)

    def test_macro_exec_pins(self):
        from wiret.ids import assign_ids, elements
        from wiret.rename import rename
        src = module("""
macro Twice(go: exec, skip: exec) -> (out: exec) {
  node entry = Entry()
  node leave = Exit out()
  node log = Call host.Log(
    .message <- "tick",
  )
  node seq = Sequence() @count(2)

  flow {
    entry.go -> seq
    entry.skip -> leave
    log -> leave
    seq.then0 -> log
    seq.then1 -> log
  }
}

func Main() {
  node after = Call host.Log(
    .message <- "done",
  )
  node entry = Entry()
  node t = Macro Twice()

  flow {
    entry -> t.go
    t.out -> after
  }
}
""", macros=False)
        m = parse(src)
        assign_ids(m, random.Random(8))
        before = run(print_module(m), "Main")[1]
        ids = {(e.kind, e.name): e.id for e in elements(m)}
        rename(m, ids[("param", "go")], "start")
        rename(m, ids[("result", "out")], "finished")
        text = print_module(m)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Main")[1], before)
        # two exec parameters make Entry's pins named; one exec result keeps `t -> after`
        for line in ("entry.start -> seq", "entry -> t.start", "t -> after",
                     "node leave = Exit finished()", "-> (finished: exec"):
            self.assertIn(line, text)

    def test_refusals(self):
        from wiret.rename import RenameError, rename
        for kind, name, new in (("func", "Main", "Double"), ("param", "v", "r"),
                                ("local", "acc", "null"), ("func", "Main", "2x"),
                                ("module", "t", "u")):
            with self.subTest(name=name, new=new), self.assertRaises(RenameError):
                rename(self.m, self.id_of(kind, name), new)
        with self.assertRaises(RenameError):
            rename(self.m, "no_such_id", "x")

    def test_rename_through_edit(self):
        from wiret.edit import apply_request
        text = print_module(self.m)
        r = apply_request(text, {"if_hash": hash_of(text), "ops": [
            {"op": "rename", "id": self.id_of("member", "Run"), "to": "Go"}]})
        self.assertTrue(r.ok, r.error)
        self.assertIn("  Go @id(", r.text)


MERGE_BASE = """wiret 1
module t

extern func host.Log(message: string)

func Double(v: i32) -> (r: i32, s: i32) {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .r <- twice,
    .s <- twice,
  )
  node twice = Add::<i32>(
    .a <- entry.v,
    .b <- entry.v,
  )
}

func Main() {
  flow {
    a -> b
    entry -> a
  }

  node a = Call host.Log(
    .message <- "a",
  )
  node b = Call host.Log(
    .message <- "b",
  )
  node entry = Entry()

  layout {
    #[note("Says hello.")]
    a at (100, 0)
    b at (200, 0)
    entry at (0, 0)
    box grp "Group" at (0, 0) size (300, 100) [members = [a]]
  }
}
"""


def sub(text, old, new):
    assert old in text, old
    return text.replace(old, new)


class MergeTests(unittest.TestCase):
    """wiretc merge (section 7.1) and the identity tests of section 7.4."""

    def merge(self, ours, theirs, base=MERGE_BASE):
        from wiret.merge import merge_texts
        return merge_texts(base, ours, theirs)

    def test_base_is_canonical(self):
        self.assertEqual(print_module(parse(MERGE_BASE)), MERGE_BASE)

    def test_edits_to_different_nodes_merge(self):
        r = self.merge(sub(MERGE_BASE, '.message <- "a"', '.message <- "A"'),
                       sub(MERGE_BASE, '.message <- "b"', '.message <- "B"'))
        self.assertTrue(r.clean)
        self.assertEqual(r.text, MERGE_BASE.replace('"a"', '"A"').replace('"b"', '"B"'))
        self.assertEqual(run(r.text, "Main")[1], ["A", "B"])

    def test_same_change_on_both_sides(self):
        ours = sub(MERGE_BASE, '.message <- "a"', '.message <- "A"')
        r = self.merge(ours, ours)
        self.assertTrue(r.clean)
        self.assertEqual(r.text, ours)

    def test_per_field_merge_inside_one_node(self):
        ours = sub(MERGE_BASE, "    .b <- entry.v,\n", "    .b <- 3,\n")
        theirs = sub(MERGE_BASE, "node twice = Add::<i32>(", "node twice = Mul::<i32>(")
        r = self.merge(ours, theirs)
        self.assertTrue(r.clean)
        self.assertIn("  node twice = Mul::<i32>(\n    .a <- entry.v,\n    .b <- 3,\n  )\n", r.text)

    def test_conflicting_binding_is_one_line_each(self):
        r = self.merge(sub(MERGE_BASE, '.message <- "a"', '.message <- "ours"'),
                       sub(MERGE_BASE, '.message <- "a"', '.message <- "theirs"'))
        self.assertFalse(r.clean)
        self.assertEqual([c.where for c in r.conflicts], ["Main.a.message"])
        self.assertIn('<<<<<<< ours (Main.a.message)\n    .message <- "ours",\n=======\n'
                      '    .message <- "theirs",\n>>>>>>> theirs\n', r.text)

    def test_delete_against_change_is_a_conflict(self):
        ours = (MERGE_BASE.replace('  node b = Call host.Log(\n    .message <- "b",\n  )\n', "")
                .replace("    a -> b\n", "").replace("    b at (200, 0)\n", ""))
        r = self.merge(ours, sub(MERGE_BASE, '.message <- "b"', '.message <- "B"'))
        self.assertEqual([c.what for c in r.conflicts],
                         ["node deleted in ours, changed in the other"])
        self.assertIn('<<<<<<< ours (Main.b)\n=======\n  node b = Call host.Log(\n'
                      '    .message <- "B",\n  )\n>>>>>>> theirs\n', r.text)
        # deleted on one side and unchanged on the other: deleted
        r = self.merge(ours, MERGE_BASE)
        self.assertTrue(r.clean)
        self.assertNotIn("node b ", r.text)

    def test_rename_with_an_id_merges_as_a_rename(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(1))
        base = print_module(m)
        ours = base.replace("func Double(", "func Twice(")
        theirs = sub(base, "  node b = Call host.Log(",
                     "  node d = Call Double(\n    .v <- 2,\n  )\n  node b = Call host.Log(")
        r = self.merge(ours, theirs, base)
        self.assertTrue(r.clean, [c.what for c in r.conflicts])
        self.assertIn("func Twice(", r.text)
        self.assertIn("node d = Call Twice(\n", r.text)
        self.assertEqual([d.code for d in check(parse(r.text)) if d.severity == "error"], [])
        # without @ids the rename is a deletion plus an addition, and theirs' call breaks
        r = self.merge(MERGE_BASE.replace("func Double(", "func Twice("),
                       sub(MERGE_BASE, "  node b = Call host.Log(",
                           "  node d = Call Double(\n    .v <- 2,\n  )\n  node b = Call host.Log("))
        self.assertTrue(r.semantic or r.conflicts)

    def test_renamed_parameter_reaches_new_call_sites(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(2))
        base = print_module(m)
        ours = sub(base, "func Double(v: i32", "func Double(n: i32").replace("entry.v", "entry.n")
        theirs = sub(base, "  node b = Call host.Log(",
                     "  node d = Call Double(\n    .v <- 2,\n  )\n  node b = Call host.Log(")
        r = self.merge(ours, theirs, base)
        self.assertTrue(r.clean)
        self.assertIn("  node d = Call Double(\n    .n <- 2,\n  )\n", r.text)

    def test_ids_assigned_on_one_side_are_not_a_rename(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(3))
        r = self.merge(print_module(m), sub(MERGE_BASE, '.message <- "a"', '.message <- "A"'))
        self.assertTrue(r.clean)
        self.assertIn('.message <- "A"', r.text)
        self.assertEqual(r.text.count("@id("), print_module(m).count("@id("))

    def test_layout_never_blocks(self):
        r = self.merge(sub(MERGE_BASE, "a at (100, 0)", "a at (111, 0)"),
                       sub(MERGE_BASE, "a at (100, 0)", "a at (122, 0)"))
        self.assertTrue(r.clean)
        self.assertIn("a at (122, 0)", r.text)
        self.assertEqual(len(r.notices), 1)
        r = self.merge(sub(MERGE_BASE, "a at (100, 0)", "a at (111, 0)"),
                       sub(MERGE_BASE, '.message <- "a"', '.message <- "A"'))
        self.assertTrue(r.clean)
        self.assertIn("a at (111, 0)", r.text)
        self.assertIn('"A"', r.text)

    def test_box_members_merge_as_a_set(self):
        r = self.merge(sub(MERGE_BASE, "members = [a]", "members = [a, b]"),
                       sub(MERGE_BASE, "members = [a]", "members = [a, entry]"))
        self.assertTrue(r.clean)
        self.assertIn("members = [a, b, entry]", r.text)
        r = self.merge(sub(MERGE_BASE, "members = [a]", "members = []"),
                       sub(MERGE_BASE, "members = [a]", "members = [a, b]"))
        self.assertIn("members = [b]", r.text)

    def test_notes(self):
        r = self.merge(sub(MERGE_BASE, "    b at (", '    #[note("ours")]\n    b at ('),
                       sub(MERGE_BASE, "    b at (", '    #[note("theirs")]\n    b at ('))
        self.assertTrue(r.clean)
        self.assertIn('#[note("ours")]\n    #[note("theirs")]\n    b at (', r.text)
        r = self.merge(sub(MERGE_BASE, "Says hello.", "Ours."),
                       sub(MERGE_BASE, "Says hello.", "Theirs."))
        self.assertEqual([c.what for c in r.conflicts],
                         ["a note was replaced differently on both sides"])
        self.assertIn('<<<<<<< ours (Main.a note)\n    #[note("Ours.")]\n=======\n'
                      '    #[note("Theirs.")]\n>>>>>>> theirs\n', r.text)
        r = self.merge(sub(MERGE_BASE, '    #[note("Says hello.")]\n', ""),
                       sub(MERGE_BASE, '.message <- "b"', '.message <- "B"'))
        self.assertTrue(r.clean)
        self.assertNotIn("Says hello.", r.text)

    def test_semantic_conflicts_are_reported(self):
        ours = (MERGE_BASE.replace("  node twice = Add::<i32>(\n    .a <- entry.v,\n"
                                   "    .b <- entry.v,\n  )\n", "")
                .replace("    .r <- twice.result,\n    .s <- twice.result,\n",
                         "    .r <- 0,\n    .s <- 0,\n"))
        theirs = sub(MERGE_BASE, "  node ret = Return",
                     "  node half = Div::<i32>(\n    .a <- twice.result,\n    .b <- 2,\n  )\n"
                     "  node ret = Return")
        r = self.merge(ours, theirs)
        self.assertFalse(r.conflicts)
        self.assertEqual([(d.code, d.node) for d in r.semantic], [("E0101", "half")])
        self.assertFalse(r.clean)

    def test_unparseable_side_falls_back_to_a_line_merge(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        r = self.merge(MERGE_BASE + "garbage(\n", sub(MERGE_BASE, "Says hello.", "Hi."))
        self.assertTrue(r.fallback)
        self.assertTrue(r.clean)
        self.assertIn("garbage(", r.text)
        self.assertIn("Hi.", r.text)

    def test_declarations_merge_per_field(self):
        base = print_module(parse(MERGE_BASE.replace(
            "extern func host.Log", "var n: i32 = 1\n\nextern func host.Log")))
        r = self.merge(sub(base, "var n: i32 = 1", "var n: i32 = 2"),
                       sub(base, "var n: i32 = 1", "var n: i32 = 3"), base)
        self.assertIn("<<<<<<< ours (n.value)\nvar n: i32 = 2\n=======\nvar n: i32 = 3\n", r.text)
        r = self.merge(sub(base, "var n: i32 = 1", "var n: i32 = 2"),
                       sub(base, "var n: i32 = 1", "var n: i64 = 1"), base)
        self.assertTrue(r.clean)
        self.assertIn("var n: i64 = 2", r.text)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_git_merge_driver(self):
        import wiretc
        with tempfile.TemporaryDirectory() as d:
            def sh(*args, ok=(0,)):
                r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] +
                                   list(args), cwd=d, capture_output=True, text=True)
                self.assertIn(r.returncode, ok, r.stderr + r.stdout)
                return r
            sh("init", "-q", "-b", "main")
            path = os.path.join(d, "g.wiret")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(MERGE_BASE)
            cwd = os.getcwd()
            os.chdir(d)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(wiretc.init_git(), 0)
            finally:
                os.chdir(cwd)
            self.assertIn("*.wiret merge=wiret diff=wiret", read(os.path.join(d, ".gitattributes")))
            sh("add", ".")
            sh("commit", "-q", "-m", "base")
            sh("checkout", "-q", "-b", "other")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sub(MERGE_BASE, "    .b <- entry.v,\n", "    .b <- 3,\n"))
            sh("commit", "-q", "-am", "theirs")
            sh("checkout", "-q", "main")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sub(MERGE_BASE, "node twice = Add::<i32>(", "node twice = Mul::<i32>("))
            sh("commit", "-q", "-am", "ours")
            sh("merge", "-q", "--no-edit", "other")
            merged = read(path)
            self.assertIn("  node twice = Mul::<i32>(\n    .a <- entry.v,\n    .b <- 3,\n  )\n", merged)
            # the textconv changes what git diff shows (flow order), not what is stored
            shown = sh("diff", "HEAD~1", "HEAD", "--", "g.wiret").stdout
            raw = sh("diff", "--no-textconv", "HEAD~1", "HEAD", "--", "g.wiret").stdout
            self.assertIn(".b <- 3", shown)
            self.assertNotEqual(shown, raw)


class DiffTests(unittest.TestCase):
    """wiretc diff (section 7): behaviour first, then metadata, then layout."""

    def diff(self, a, b):
        from wiret.diff import semantic_diff
        return semantic_diff(parse(a), parse(b))

    def test_no_change(self):
        self.assertEqual(self.diff(MERGE_BASE, MERGE_BASE), "")

    def test_nodes_in_flow_order(self):
        b = sub(MERGE_BASE, '.message <- "b"', '.message <- "B"')
        b = sub(b, '    .message <- "B",\n  )\n  node entry = Entry()\n',
                '    .message <- "B",\n  )\n  node c = Call host.Log(\n    .message <- "c",\n  )\n'
                '  node entry = Entry()\n')
        b = sub(b, "    a -> b\n", "    a -> b\n    b -> c\n")
        b = sub(b, "    .r <- twice,\n    .s <- twice,\n",
                "    .r <- 1,\n    .s <- 1,\n")
        b = sub(b, "  node twice = Add::<i32>(\n    .a <- entry.v,\n    .b <- entry.v,\n  )\n", "")
        self.assertEqual(self.diff(MERGE_BASE, b), """func Double
  ~ node ret: .r: twice.result -> 1; .s: twice.result -> 1
  - node twice = Add
func Main
  ~ node b: .message: "b" -> "B"; exec then: (none) -> c
  + node c = Call host.Log(
        .message <- "c",
      )
""")

    def test_declarations(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(9))
        a = print_module(m)
        b = a.replace("func Double(v: i32", "func Twice(n: i32").replace("entry.v", "entry.n")
        b = b.replace("extern func host.Log", "var count: i32\n\nextern func host.Log")
        out = self.diff(a, b)
        self.assertIn("func Double -> Twice (renamed)\n  ~ param v -> n\n", out)
        self.assertIn("+ var count\n", out)
        self.assertIn("~ node twice: .a: entry.v -> entry.n; .b: entry.v -> entry.n", out)

    def test_metadata_and_layout_are_separate(self):
        b = sub(MERGE_BASE, "Says hello.", "Says hi.")
        b = sub(b, "a at (100, 0)", "a at (150, 0)")
        b = sub(b, "size (300, 100)", "size (320, 100)")
        self.assertEqual(self.diff(MERGE_BASE, b), """metadata (does not change behaviour):
  Main.a: - #[note("Says hello.")]
  Main.a: + #[note("Says hi.")]

layout only:
  Main.a: (100, 0) -> (150, 0)
  Main: box grp changed
""")

    def test_cli(self):
        import wiretc
        with tempfile.TemporaryDirectory() as d:
            pa, pb = os.path.join(d, "a.wiret"), os.path.join(d, "b.wiret")
            for path, text in ((pa, MERGE_BASE), (pb, sub(MERGE_BASE, '"a"', '"A"'))):
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(wiretc.main(["diff", pa, pb]), 1)
                self.assertEqual(wiretc.main(["diff", pa, pa]), 0)
            self.assertIn('~ node a: .message: "a" -> "A"', out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(wiretc.main(["diff", "--raw", pa, pb]), 1)
            self.assertIn('-    .message <- "a",\n+    .message <- "A",\n', out.getvalue())


class HashTests(unittest.TestCase):
    def test_reorder_and_layout_removal_do_not_change_semantics(self):
        text = demo()
        m1 = parse(text)
        _, r1 = build(text)
        m2 = parse(text)
        for g in m2.graphs():
            g.nodes.reverse()
            g.places, g.boxes, g.meta = [], [], []
            for n in g.nodes:
                n.meta = []
        _, r2 = build(print_module(m2))
        self.assertEqual(semantic_hash(m1), semantic_hash(m2))
        self.assertNotEqual(layout_hash(m1), layout_hash(m2))
        self.assertEqual(instruction_bytes(r1.wbc), instruction_bytes(r2.wbc))

    def test_layout_only_edit_keeps_semantic_hash(self):
        m = parse(demo())
        before = semantic_hash(m)
        m.graph("Main").place("hello").x += 40
        self.assertEqual(semantic_hash(m), before)

    def test_rewire_changes_semantic_hash(self):
        m = parse(demo())
        before = semantic_hash(m)
        m.graph("Main").node("hello").bindings[0].value.value = "changed"
        self.assertNotEqual(semantic_hash(m), before)

    def test_reroute_is_erased(self):
        plain = module("""
func F(x: i32) -> (y: i32) = x
""", macros=False)
        rerouted = module("""
func F(x: i32) -> (y: i32) {
  node bend = Reroute::<i32>(
    .in <- entry.x,
  )
  node entry = Entry()
  node hop = Reroute::<exec>()
  node ret = Return(
    .y <- bend.out,
  )

  flow {
    entry -> hop
    hop -> ret
  }
}
""", macros=False)
        self.assertEqual(semantic_hash(parse(plain)), semantic_hash(parse(rerouted)))
        self.assertEqual(run(rerouted, "F", 7)[0], [7])


class ExecutionTests(unittest.TestCase):
    def test_demo_functions(self):
        text = demo()
        self.assertEqual(run(text, "SumTo", 100)[0], [5050])
        self.assertEqual(run(text, "Fib", 15)[0], [610])
        self.assertEqual(run(text, "Clamp01", 1.5)[0], [1.0])
        self.assertEqual(run(text, "Clamp01", -2.0)[0], [0.0])
        _, out = run(text, "Main")
        self.assertEqual(out[0], "Hello from Wiret!")
        self.assertIn("Fib(10) = 55", out)
        self.assertEqual(out[-1], "SumTo(100) = 5050")

    def test_forrange_trace_matches_spec_4_2(self):
        trace = []
        res, _ = run(demo(), "SumTo", 2, trace=trace)
        self.assertEqual(res, [3])
        expected = [
            ("entry", ()), ("loop!in", ()), ("loop/init", ()), ("loop/test", ()),
            ("loop/seq", ()), ("loop/each_out", ("loop/bump",)), ("add", ("loop/bump",)),
            ("loop/bump", ()), ("loop/test", ()), ("loop/seq", ()),
            ("loop/each_out", ("loop/bump",)), ("add", ("loop/bump",)), ("loop/bump", ()),
            ("loop/test", ()), ("loop/finish", ()), ("ret", ())]
        self.assertEqual(trace, expected)

    def test_nested_loops(self):
        text = module("""
func Grid(n: i32) -> (count: i32) {
  local c: i32
  node entry = Entry()
  node outer = Macro ForRange(
    .first <- 1,
    .last <- entry.n,
  )
  node inner = Macro ForRange(
    .first <- 1,
    .last <- outer.index,
  )
  node cur = GetLocal c()
  node inc = Add::<i32>(
    .a <- cur.value,
    .b <- 1,
  )
  node bump = SetLocal c(
    .value <- inc.result,
  )
  node total = GetLocal c()
  node ret = Return(
    .count <- total.value,
  )

  flow {
    entry -> outer
    outer.each -> inner
    outer.done -> ret
    inner.each -> bump
  }
}
""")
        trace = []
        res, _ = run(text, "Grid", 3, trace=trace)
        self.assertEqual(res, [6])   # 1 + 2 + 3
        stacks = [S for n, S in trace if n == "bump"]
        self.assertTrue(all(S == ("outer/bump", "inner/bump") for S in stacks), stacks)

    def test_sequence_inside_macro_runs_chains_in_order(self):
        text = module("""
macro Twice(in: exec) -> (first: exec, second: exec) {
  node entry = Entry()
  node seq = Sequence()
  node a = Exit first()
  node b = Exit second()

  flow {
    entry -> seq
    seq.then0 -> a
    seq.then1 -> b
  }
}

func F() {
  node entry = Entry()
  node tw = Macro Twice()
  node log1 = Call host.Log(
    .message <- "one",
  )
  node log1b = Call host.Log(
    .message <- "one-b",
  )
  node log2 = Call host.Log(
    .message <- "two",
  )

  flow {
    entry -> tw
    tw.first -> log1
    tw.second -> log2
    log1 -> log1b
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["one", "one-b", "two"])

    def test_early_return_discards_pending_continuations(self):
        text = module("""
func FirstOver(limit: i32) -> (found: i32) {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 100,
  )
  node sq = Mul::<i32>(
    .a <- loop.index,
    .b <- loop.index,
  )
  node over = Gt::<i32>(
    .a <- sq.result,
    .b <- entry.limit,
  )
  node chk = Branch(
    .cond <- over.result,
  )
  node hit = Return(
    .found <- loop.index,
  )
  node none = Return(
    .found <- -1,
  )

  flow {
    entry -> loop
    loop.each -> chk
    loop.done -> none
    chk.then -> hit
  }
}
""")
        self.assertEqual(run(text, "FirstOver", 50)[0], [8])
        self.assertEqual(run(text, "FirstOver", 100000)[0], [-1])

    def test_unwired_exit_is_a_chain_end(self):
        text = module("""
func F() {
  node entry = Entry()
  node seq = Sequence()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 2,
  )
  node log = Call host.Log(
    .message <- "body",
  )
  node after = Call host.Log(
    .message <- "after",
  )

  flow {
    entry -> seq
    seq.then0 -> loop
    seq.then1 -> after
    loop.each -> log
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["body", "body", "after"])

    def test_join_and_E0310(self):
        text = module("""
func F(c: bool) -> (r: string) {
  node entry = Entry()
  node br = Branch(
    .cond <- entry.c,
  )
  node make = Call Make()
  node join = Return(
    .r <- make.s,
  )

  flow {
    entry -> br
    br.then -> make
    br.else -> join
    make -> join
  }
}

func Make() -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- "made",
  )

  flow {
    entry -> ret
  }
}
""", macros=False)
        # reading make.s at the join, where make may not have run, is rejected
        self.assertIn("E0310", codes(text))
        self.assertFalse(compile_module(parse(text), text).ok)
        # the fix: every path into the join stores the value in a local
        fixed = module("""
func F(c: bool) -> (r: string) {
  local s: string
  node entry = Entry()
  node br = Branch(
    .cond <- entry.c,
  )
  node make = Call Make()
  node keep = SetLocal s(
    .value <- make.s,
  )
  node none = SetLocal s(
    .value <- "",
  )
  node join = Return(
    .r <- GetLocal s().value,
  )

  flow {
    entry -> br
    br.then -> make
    br.else -> none
    make -> keep
    keep -> join
    none -> join
  }
}

func Make() -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- "made",
  )

  flow {
    entry -> ret
  }
}
""", macros=False)
        self.assertNotIn("E0310", codes(fixed))
        self.assertEqual(run(fixed, "F", 1)[0], ["made"])
        self.assertEqual(run(fixed, "F", 0)[0], [""])

    def test_pure_nodes_are_reevaluated_per_evaluation_point(self):
        text = module("""
var hp: i32 = 10

func F() -> (a: i32, b: i32) {
  local first: i32
  node entry = Entry()
  node cur = GetVar hp()
  node save = SetLocal first(
    .value <- cur.value,
  )
  node dmg = Sub::<i32>(
    .a <- cur.value,
    .b <- 3,
  )
  node hit = SetVar hp(
    .value <- dmg.result,
  )
  node got = GetLocal first()
  node ret = Return(
    .a <- got.value,
    .b <- cur.value,
  )

  flow {
    entry -> save
    save -> hit
    hit -> ret
  }
}
""", macros=False)
        # read at save, then at ret after hit wrote it: an error unless that is meant
        self.assertIn("E0320", codes(text))
        live = text.replace("  node cur = GetVar hp()\n", "  node cur = GetVar hp() @live\n")
        self.assertNotIn("E0320", codes(live))
        self.assertEqual(run(live, "F")[0], [10, 7])
        # @live on a node that reads it also excuses it, but not on an impure node
        dmg = text.replace("    .b <- 3,\n  )\n", "    .b <- 3,\n  ) @live\n")
        self.assertIn("E0320", codes(dmg))       # cur still reaches save and ret directly
        bad = text.replace("  node hit = SetVar hp(\n    .value <- dmg.result,\n  )\n",
                           "  node hit = SetVar hp(\n    .value <- dmg.result,\n  ) @live\n")
        self.assertIn("E0104", codes(bad))

    def test_reads_on_exclusive_paths_are_not_e0320(self):
        text = module("""
var hp: i32 = 10

func F(c: bool) -> (a: i32) {
  flow {
    entry -> chk
    chk.then -> r1
    chk.else -> r2
  }

  node chk = Branch(
    .cond <- entry.c,
  )
  node cur = GetVar hp()
  node entry = Entry()
  node r1 = Return(
    .a <- cur.value,
  )
  node r2 = Return(
    .a <- Add::<i32>(
      .a <- cur.value,
      .b <- 1,
    ),
  )
}
""", macros=False)
        self.assertNotIn("E0320", codes(text))
        # a loop body and the code after the loop do run one after the other
        loop = module("""
var hp: i32 = 10

func F() -> (a: i32) {
  flow {
    entry -> loop
    loop.each -> bump
    loop.done -> ret
  }

  node bump = SetVar hp(
    .value <- cur,
  )
  node cur = GetVar hp()
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 3,
  )
  node ret = Return(
    .a <- cur,
  )
}
""")
        self.assertIn("E0320", codes(loop))

    def test_do_once_state_is_per_expansion(self):
        text = module("""
macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool
  node entry = Entry()
  node flag = GetState fired()
  node check = Branch(
    .cond <- flag.value,
  )
  node mark = SetState fired(
    .value <- true,
  )
  node fire = Exit out()
  node clear = SetState fired(
    .value <- false,
  )

  flow {
    entry.in -> check
    entry.reset -> clear
    check.else -> mark
    mark -> fire
  }
}

func F() {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 3,
  )
  node seq = Sequence()
  node once_a = Macro DoOnce()
  node once_b = Macro DoOnce()
  node log_a = Call host.Log(
    .message <- "a",
  )
  node log_b = Call host.Log(
    .message <- "b",
  )

  flow {
    entry -> loop
    loop.each -> seq
    seq.then0 -> once_a
    seq.then1 -> once_b
    once_a.out -> log_a
    once_b.out -> log_b
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["a", "b"])

    def test_switch_select_and_conversions(self):
        text = module("""
func Name(v: i32) -> (s: string) {
  node entry = Entry()
  node sw = Switch::<i32>(
    .value <- entry.v,
  ) @cases(1, 2)
  node one = Return(
    .s <- "one",
  )
  node two = Return(
    .s <- "two",
  )
  node neg = Lt::<i32>(
    .a <- entry.v,
    .b <- 0,
  )
  node pick = Select::<string>(
    .cond <- neg.result,
    .a <- "negative",
    .b <- "many",
  )
  node other = Return(
    .s <- pick.result,
  )

  flow {
    entry -> sw
    sw.case0 -> one
    sw.case1 -> two
    sw.default -> other
  }
}

func Conv(x: f64) -> (i: i32, b: u8, s: string, back: f32) {
  node entry = Entry()
  node i = Convert::<f64, i32>(
    .value <- entry.x,
  )
  node b = Convert::<i32, u8>(
    .value <- i.result,
  )
  node s = Convert::<f64, string>(
    .value <- entry.x,
  )
  node f = Convert::<f64, f32>(
    .value <- entry.x,
  )
  node ret = Return(
    .i <- i.result,
    .b <- b.result,
    .s <- s.result,
    .back <- f.result,
  )

  flow {
    entry -> ret
  }
}
""", macros=False)
        self.assertEqual(run(text, "Name", 1)[0], ["one"])
        self.assertEqual(run(text, "Name", 2)[0], ["two"])
        self.assertEqual(run(text, "Name", 7)[0], ["many"])
        self.assertEqual(run(text, "Name", -4)[0], ["negative"])
        self.assertEqual(run(text, "Conv", 300.75)[0][:3], [300, 44, "300.75"])
        self.assertEqual(run(text, "Conv", 1e20)[0][0], 2**31 - 1)        # saturating
        self.assertEqual(run(text, "Conv", float("nan"))[0][0], 0)


LAZY = """
class Box {
  items: array::<i32>

  func Pick(i: i32) {
    state last: i32
    node entry = Entry()
    node save = SetState last(
      .value <- Select::<i32>(
        .cond <- Lt::<i32>(
          .a <- entry.i,
          .b <- 0,
        ).result,
        .a <- -1,
        .b <- ArrayGet::<i32>(
          .array <- GetField items(
            .obj <- entry.self,
          ).value,
          .index <- entry.i,
        ).item,
      ).result,
    )
    node log = Call host.Log(
      .message <- Convert::<i32, string>(
        .value <- GetState last().value,
      ).result,
    )

    flow {
      entry -> save
      save -> log
    }
  }
}

func Guard(i: i32) -> (r: i32) {
  node entry = Entry()
  node arr = MakeArray::<i32>(
    .item0 <- 10,
    .item1 <- 20,
  ) @count(2)
  node ok = And(
    .a <- Ge::<i32>(
      .a <- entry.i,
      .b <- 0,
    ).result,
    .b <- Lt::<i32>(
      .a <- entry.i,
      .b <- ArrayLength::<i32>(
        .array <- arr.result,
      ).length,
    ).result,
  )
  node ret = Return(
    .r <- Add::<i32>(
      .a <- 1000,
      .b <- Select::<i32>(
        .cond <- ok.result,
        .a <- ArrayGet::<i32>(
          .array <- arr.result,
          .index <- entry.i,
        ).item,
        .b <- Select::<i32>(
          .cond <- Or(
            .a <- ok.result,
            .b <- Eq::<i32>(
              .a <- Div::<i32>(
                .a <- 1,
                .b <- entry.i,
              ).result,
              .b <- 0,
            ).result,
          ).result,
          .a <- 1,
          .b <- -1,
        ).result,
      ).result,
    ).result,
  )

  flow {
    entry -> ret
  }
}

func Main() {
  node entry = Entry()
  node b = New Box()
  node add = ArrayAdd::<i32> Box.items(
    .obj <- b.result,
    .item <- 42,
  )
  node low = Call Box.Pick(
    .self <- b.result,
    .i <- -5,
  )
  node high = Call Box.Pick(
    .self <- b.result,
    .i <- 0,
  )

  flow {
    add -> low
    b -> add
    entry -> b
    low -> high
  }
}
"""


class LazyTests(unittest.TestCase):
    """Select evaluates only the input it chooses, and And and Or skip `b` when `a` decides
    the result, so a fault in the untaken side is never raised (section 4.3)."""

    def test_untaken_side_never_faults(self):
        text = module(LAZY, macros=False)
        # in range: the ArrayGet; out of range: the Or runs its Div, and 1 / i is 0 unless
        # i is 1, so the result is 1; And skips Lt and Or skips Div whenever they would fault
        for i, want in ((0, 1010), (1, 1020), (5, 1001), (-3, 1001)):
            self.assertEqual(run(text, "Guard", i)[0], [want], i)

    def test_the_taken_side_still_faults(self):
        text = module("""
func F(c: bool) -> (r: i32) = Select::<i32>(
  .cond <- c,
  .a <- Div::<i32>(
    .a <- 1,
    .b <- 0,
  ),
  .b <- 7,
)
""", macros=False)
        self.assertEqual(run(text, "F", 0)[0], [7])
        with self.assertRaises(WiretError):
            run(text, "F", 1)

    def test_lazy_input_of_a_state_slot_on_an_object(self):
        # SetState on an object pushes self before its value; the Select's branches must
        # still start on an empty operand stack, and the untaken ArrayGet (index -5) is skipped
        text = module(LAZY, macros=False)
        self.assertEqual(run(text, "Main")[1], ["-1", "42"])

    def test_debug_build_verifies_and_runs(self):
        text = module(LAZY, macros=False)
        r = compile_module(parse(text), text, debug=True)
        self.assertTrue(r.ok, [str(d) for d in r.diags])
        out = []
        vm = VM(output=out.append)
        mod = vm.load(r.wbc)
        self.assertEqual(vm.call(mod, "Guard", [7]), [1001])
        vm.call(mod, "Main", [])
        self.assertEqual(out, ["-1", "42"])



READABLE = """
struct Vec2 {
  x: f32
  y: f32
}

func Both(v: i32) -> (lo: i32, hi: i32) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .lo <- entry.v,
    .hi <- Mul::<i32>(
      .a <- entry.v,
      .b <- 2,
    ),
  )
}

func Clamp01(v: f32) -> (result: f32) @pure = Min::<f32>(
  .a <- Max::<f32>(
    .a <- v,
    .b <- 0.0,
  ),
  .b <- 1.0,
)

func Main() {
  local items: array::<i32>

  flow {
    entry -> say
    say -> pair
  }

  node entry = Entry()
  node pair = Call host.Log(
    .message <- Format "lo {lo}, hi {hi}, x {x}, {{literal}} {lo}"(
      .lo <- Call Both(
        .v <- 3,
      ).lo,
      .hi <- Call Both(
        .v <- 4,
      ).hi,
      .x <- BreakStruct Vec2(
        .obj <- MakeStruct Vec2(
          .x <- 0.5,
        ),
      ).x,
    ),
  )
  node say = Call host.Log(
    .message <- Format "{n} items, {f} clamped, {ok}, {big}, {name}"(
      .n <- ArrayLength::<i32>(
        .array <- GetLocal items(),
      ),
      .f <- Call Clamp01(
        .v <- 2.5,
      ),
      .ok <- Lt::<i32>(
        .a <- 1,
        .b <- 2,
      ),
      .big <- 3000000000u32,
      .name <- "done",
    ),
  )
}
"""


class ReadabilityTests(unittest.TestCase):
    """Draft 0.11: an inline node's one output is implied, Format builds text, a function
    can be written `= value`, the flow block comes first, and `//` comments are kept."""

    def text(self):
        return module(READABLE, macros=False)

    def test_canonical_and_runs(self):
        text = self.text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c[0] == "E"], [])
        self.assertEqual(run(text, "Main")[1], [
            "0 items, 1.0 clamped, true, 3000000000, done",
            "lo 3, hi 8, x 0.5, {literal} 3"])
        self.assertEqual(run(text, "Clamp01", -2.0)[0], [0.0])

    def test_one_output_is_implied_and_several_must_be_named(self):
        m = parse(self.text())
        say = m.graph("Main").node("say.message.f")
        self.assertEqual(m.graph("Main").node("say.message").binding("f").value,
                         PinRef("say.message.f", "result"))
        self.assertEqual(say.kind, "Call")
        # `.lo` can be left out of the text only when the node has one data output
        bad = self.text().replace("      ).lo,\n", "      ),\n")
        with self.assertRaises(ParseError) as cm:
            parse(bad)
        self.assertIn("several outputs (lo, hi)", cm.exception.msg)
        self.assertIn("'Call(...).lo'", cm.exception.msg)
        # written out, `.result` reads the same and is printed the short way
        long = self.text().replace("        .v <- 2.5,\n      ),", "        .v <- 2.5,\n      ).result,")
        self.assertNotEqual(long, self.text())
        self.assertEqual(print_module(parse(long)), self.text())

    def test_a_declared_node_s_one_output_is_implied_too(self):
        text = module("""
struct Vec2 {
  x: f32
  y: f32
}

func F(n: i32) -> (r: i32, x: f32, y: f32) {
  local acc: i32

  flow {
    entry -> loop
    loop.each -> add
    loop.done -> ret
  }

  node add = SetLocal acc(
    .value <- Add::<i32>(
      .a <- cur,
      .b <- loop.index,
    ),
  )
  node cur = GetLocal acc()
  node entry = Entry()
  node loop = Macro std.flow.ForRange(
    .first <- 1,
    .last <- entry.n,
  )
  node parts = BreakStruct Vec2(
    .obj <- MakeStruct Vec2(
      .x <- 1.5,
    ),
  )
  node ret = Return(
    .r <- cur,
    .x <- parts.x,
    .y <- parts.y,
  )
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(run(text, "F", 4)[0], [10, 1.5, 0.0])
        g = parse(text).graph("F")
        self.assertEqual(g.node("ret").binding("r").value, PinRef("cur", "value"))
        # written out, the one output reads the same and is printed the short way
        self.assertEqual(print_module(parse(text.replace("    .r <- cur,", "    .r <- cur.value,"))),
                         text)
        # Entry and a macro name their outputs, which are parameters and results: the bare
        # form is read, but written with the name
        bare = text.replace("    .last <- entry.n,", "    .last <- entry,")
        self.assertEqual(print_module(parse(bare)), text)
        # several outputs: the one read must be named
        with self.assertRaises(ParseError) as cm:
            parse(text.replace("    .x <- parts.x,", "    .x <- parts,"))
        self.assertIn("'parts' has several outputs (x, y)", cm.exception.msg)
        self.assertIn("'parts.x'", cm.exception.msg)
        # a node that does not exist is kept as written and reported, never unreadable
        gone = print_module(parse(text.replace("    .r <- cur,", "    .r <- old,")))
        self.assertIn("    .r <- old,\n", gone)
        self.assertEqual(print_module(parse(gone)), gone)
        found = [d for d in check(parse(gone)) if d.code == "E0101"]
        self.assertEqual([(d.node, d.pin) for d in found], [("ret", "r")])
        self.assertIn("'old()'", found[0].message)

    def test_format_templates_and_types(self):
        def errors(body):
            m = parse(module(body, macros=False))
            return [(d.code, d.message) for d in check(m) if d.code[0] == "E"]
        for bad in ("{v", "{ v }", "a } b", "{1}"):
            with self.subTest(bad):
                found = errors("""
func F() -> (s: string) = Format "TEMPLATE"(
  .v <- 1,
)
""".replace("TEMPLATE", bad))
                self.assertIn("E0501", [c for c, _ in found])
        found = errors("""
func F(xs: array::<i32>) -> (s: string) = Format "{xs}"(
  .xs <- xs,
)
""")
        self.assertTrue(any(c == "E0110" and "'xs' is array::<i32>" in m for c, m in found), found)
        # an unbound placeholder is empty text; doubled braces are braces
        text = module("""
func F() -> (s: string) = Format "[{gap}] {{x}}"()
""", macros=False)
        self.assertEqual(run(text, "F")[0], ["[] {x}"])

    def test_format_with_a_lazy_input_verifies(self):
        # the Select branches, so the template's text must not be on the operand stack yet
        text = module("""
func F(c: bool) -> (s: string) = Format "got {v}!"(
  .v <- Select::<i32>(
    .cond <- c,
    .a <- Div::<i32>(
      .a <- 1,
      .b <- 0,
    ),
    .b <- -1,
  ),
)
""", macros=False)
        self.assertEqual(run(text, "F", 0)[0], ["got -1!"])
        r = compile_module(parse(text), text, debug=True)
        self.assertTrue(r.ok, [str(d) for d in r.diags])

    def test_expression_body(self):
        text = self.text()
        m = parse(text)
        g = m.graph("Clamp01")
        self.assertEqual(sorted(n.id for n in g.nodes),
                         ["entry", "ret", "ret.result", "ret.result.a"])
        self.assertEqual(g.node("ret.result.a").binding("a").value, PinRef("entry", "v"))
        # once it has a layout (the editor placed it), it is written as a graph
        g.places.append(Place("ret", 300, 0))
        out = print_module(m)
        self.assertIn("func Clamp01(v: f32) -> (result: f32) @pure {\n  flow {\n"
                      "    entry -> ret\n  }\n\n  node entry = Entry()\n", out)
        self.assertIn("      .a <- entry.v,\n", out)
        g.places.clear()
        self.assertEqual(print_module(m), text)
        for head in ("macro M() -> (r: i32) = 1", "func F() -> (a: i32, b: i32) = 1",
                     "func F() = 1"):
            with self.subTest(head):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\n{head}\n", macros=False))
                self.assertIn("'= value'", cm.exception.msg)

    def test_the_editor_wires_a_number_straight_into_format(self):
        from wiret import canvasedit
        from wiret.checker import GraphInfo
        from wiret.registry import ModuleIndex
        text = module("""
func Main() {
  local n: i32 = 7

  flow {
    entry -> say
  }

  node entry = Entry()
  node get = GetLocal n()
  node say = Call host.Log(
    .message <- Format "n is {n}"(),
  )
}
""", macros=False)
        m = parse(text)
        g, idx = m.graph("Main"), ModuleIndex(m)
        msg = canvasedit.connect(g, GraphInfo(g, idx), idx, ("get", "out", "value"),
                                 ("say.message", "in", "n"), lambda nid: None)
        self.assertEqual(msg, "Bound say.message.n = get.value")       # no Convert in between
        self.assertEqual(run(print_module(m), "Main")[1], ["n is 7"])

    def test_comment_edits_merge_with_other_edits(self):
        from wiret.merge import merge_texts
        base = self.text().replace("  node entry = Entry()\n", "  // starts here\n  node entry = Entry()\n")
        ours = base.replace("// starts here", "// begins here")
        theirs = base.replace('.name <- "done"', '.name <- "finished"').replace(
            "    .message <- Format \"{n}", "    // the summary\n    .message <- Format \"{n}")
        r = merge_texts(base, ours, theirs)
        self.assertTrue(r.clean, [c.what for c in r.conflicts])
        self.assertIn("  // begins here\n  node entry = Entry()\n", r.text)
        self.assertIn("    // the summary\n    .message <- Format \"{n}", r.text)
        self.assertIn('.name <- "finished"', r.text)


LEAVE = """
func Nest() -> (n: i32) {
  local count: i32

  flow {
    chk.then -> outer.break
    entry -> outer
    inner.each -> seq
    outer.each -> inner
    outer.done -> ret
    seq.then0 -> chk
    seq.then1 -> add
  }

  node add = SetLocal count(
    .value <- Add::<i32>(
      .a <- GetLocal count(),
      .b <- 1,
    ),
  )
  node chk = Branch(
    .cond <- And(
      .a <- Eq::<i32>(
        .a <- outer.index,
        .b <- 2,
      ),
      .b <- Eq::<i32>(
        .a <- inner.index,
        .b <- 2,
      ),
    ),
  )
  node entry = Entry()
  node inner = Macro std.flow.ForRange(
    .first <- 1,
    .last <- 3,
  )
  node outer = Macro std.flow.ForRange(
    .first <- 1,
    .last <- 3,
  )
  node ret = Return(
    .n <- GetLocal count(),
  )
  node seq = Sequence() @count(2)
}

func Never() -> (n: i32) {
  flow {
    entry -> loop.break
    loop.done -> ret
  }

  node entry = Entry()
  node loop = Macro std.flow.ForRange(
    .first <- 1,
    .last <- 3,
  )
  node ret = Return(
    .n <- 7,
  )
}

func SumUntil(stop: i32) -> (total: i32) {
  local acc: i32

  flow {
    chk.then -> loop.break
    chk.else -> add
    entry -> loop
    loop.each -> chk
    loop.done -> ret
  }

  node add = SetLocal acc(
    .value <- Add::<i32>(
      .a <- GetLocal acc(),
      .b <- loop.index,
    ),
  )
  node chk = Branch(
    .cond <- Eq::<i32>(
      .a <- loop.index,
      .b <- entry.stop,
    ),
  )
  node entry = Entry()
  node loop = Macro std.flow.ForRange(
    .first <- 1,
    .last <- 10,
  )
  node ret = Return(
    .total <- GetLocal acc(),
  )
}
"""


class LeaveTests(unittest.TestCase):
    """`Leave o` ends a macro early: it drops every continuation the macro pushed since it was
    entered, so a loop's `break` input skips the rest of the loop (section 4.2)."""

    def text(self):
        return module(LEAVE, macros=False)

    def test_break_ends_the_loop_and_runs_done(self):
        text = self.text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c[0] == "E" or c == "W0302"], [])
        self.assertEqual(run(text, "SumUntil", 4)[0], [6])         # 1 + 2 + 3, then break
        self.assertEqual(run(text, "SumUntil", 99)[0], [55])       # never breaks

    def test_break_from_a_nested_loop_drops_the_inner_continuations(self):
        # outer pass 1 counts 3; pass 2 counts j = 1, then breaks the outer loop at j = 2,
        # dropping the inner loop's pending pass and the Sequence's pending `add`
        self.assertEqual(run(self.text(), "Nest")[0], [4])

    def test_a_break_before_the_loop_started_drops_nothing(self):
        self.assertEqual(run(self.text(), "Never")[0], [7])

    def test_debug_build_and_bytecode(self):
        text = self.text()
        r = compile_module(parse(text), text, debug=True)
        self.assertTrue(r.ok, [str(d) for d in r.diags])
        asm = disassemble(r.wbc)
        self.assertIn("cont.depth", asm)
        self.assertIn("cont.trunc", asm)
        vm = VM()
        self.assertEqual(vm.call(vm.load(r.wbc), "Nest", []), [4])

    def test_leave_belongs_in_a_macro(self):
        text = module("""
func F() {
  flow {
    entry -> out
  }

  node entry = Entry()
  node out = Leave done()
}
""", macros=False)
        diags = [d for d in check(parse(text)) if d.code == "E0501"]
        self.assertIn("Leave is only allowed in a macro", diags[0].message)


NAMES = """
enum Mode {
  Idle
  Chase
}

struct layout {
  size: i32
  flow: i32
}

class Box {
  func: i32 = 1
  event: i32 = 2
  dispatcher: i32 = 3
  state: i32 = 4

  func Total() -> (size: i32) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .size <- GetField Box.state(
        .obj <- entry.self,
      ),
    )
  }
}

func Main(node: i32) -> (size: i32) {
  local flow: i32
  local state: Mode

  flow {
    Mode.then -> local
    at -> box
    box -> Mode
    entry -> at
    local -> size
  }

  node Mode = Branch(
    .cond <- Eq::<Mode>(
      .a <- GetLocal state(),
      .b <- Mode::Idle,
    ),
  )
  node at = SetLocal flow(
    .value <- entry.node,
  )
  node box = SetLocal state(
    .value <- Mode::Idle,
  )
  node entry = Entry()
  node local = Call host.Log(
    .message <- Format "{size} {flow}"(
      .size <- GetField layout.size(
        .obj <- MakeStruct layout(
          .size <- 5,
        ),
      ),
      .flow <- GetLocal flow(),
    ),
  )
  node size = Return(
    .size <- GetLocal flow(),
  )

  layout {
    at at (100, 0)
    box at (200, 0)
    entry at (0, 0)
    size at (300, 0)
    box group "Group" at (0, 0) size (400, 100) [members = [at, box]]
  }
}
"""


class ContextualNameTests(unittest.TestCase):
    """Keywords are contextual (section 2.1), and an enum value is `Mode::Chase`, so a node,
    field, local, parameter or type may take a keyword's or an enum's name."""

    def text(self):
        return module(NAMES, macros=False)

    def test_keywords_and_enum_names_as_names(self):
        text = self.text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c[0] == "E"], [])
        m = parse(text)
        layout = next(it for it in m.items if getattr(it, "name", "") == "layout")
        self.assertEqual([f.name for f in layout.fields], ["size", "flow"])
        box = next(it for it in m.items if getattr(it, "name", "") == "Box")
        self.assertEqual([f.name for f in box.fields], ["func", "event", "dispatcher", "state"])
        g = m.graph("Main")
        self.assertEqual([b.id for b in g.boxes], ["group"])
        self.assertEqual(sorted(p.id for p in g.places), ["at", "box", "entry", "size"])
        # node Mode and enum Mode side by side: a wire is `Mode.then`, a value `Mode::Idle`
        self.assertEqual(g.node("box").binding("value").value, Lit("enum", "Mode.Idle"))
        self.assertEqual(run(text, "Main", 3), ([3], ["5 3"]))

    def test_only_values_are_reserved(self):
        from wiret import canvasedit
        m = parse(self.text())
        g = m.graph("Main")
        self.assertEqual(canvasedit.rename_node(g, "at", "state"), "Renamed at to state")
        with self.assertRaises(canvasedit.Refused):
            canvasedit.rename_node(g, "box", "true")

    def test_highlighting_follows_the_context(self):
        from wiret.syntax import spans
        kw = lambda line: [line[a:b] for a, b, t in spans(line) if t == "kw"]
        self.assertEqual(kw("  local flow: i32"), ["local"])
        self.assertEqual(kw("  state: i32 = 4"), [])
        self.assertEqual(kw("    .size <- GetField layout.size("), [])
        self.assertEqual(kw("  node at = SetLocal flow("), ["node", "at"])
        self.assertEqual(kw("    box.message at (1, 2)"), ["at"])


class SaturationTests(unittest.TestCase):
    """Float to integer conversion saturates to the target type's range (section 3.2)."""

    def test_narrow_types_saturate(self):
        types = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
        results = ", ".join(f"{t}_: {t}" for t in types)
        nodes = "".join(f"  node {t}_ = Convert::<f64, {t}>(\n    .value <- entry.x,\n  )\n" for t in types)
        binds = "".join(f"    .{t}_ <- {t}_.result,\n" for t in types)
        text = module(f"""
func Sat(x: f64) -> ({results}) @pure {{
  node entry = Entry()
{nodes}  node r = Return(
{binds}  )

  flow {{
    entry -> r
  }}
}}
""", macros=False)
        from wiret.runner import format_value
        cases = {
            300.7: [127, 255, 300, 300, 300, 300, 300, 300],
            -300.7: [-128, 0, -300, 0, -300, 0, -300, 0],
            1e10: [127, 255, 32767, 65535, 2**31 - 1, 2**32 - 1, 10**10, 10**10],
            -1e10: [-128, 0, -32768, 0, -2**31, 0, -10**10, 0],
            float("nan"): [0] * 8,
            float("inf"): [127, 255, 32767, 65535, 2**31 - 1, 2**32 - 1, 2**63 - 1, 2**64 - 1],
            -0.9: [0] * 8,
        }
        for x, want in cases.items():
            with self.subTest(x=x):
                got = run(text, "Sat", x)[0]
                self.assertEqual([int(format_value(t, v)) for t, v in zip(types, got)], want)


EXPORTS = module("""
var counter: i32 = 0 @export
var hidden: i32 = 0

enum Color: u8 @export {
  Red
  Green
}

struct Point @export {
  x: i32
  y: i32
}

struct Inner {
  v: i32
}

interface Named @export {
  func Name() -> (name: string)
}

class Box @export {
  size: i32 = 1

  func Grow(by: i32) -> (size: i32) @export {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .size <- entry.by,
    )
  }

  func Shrink(by: i32) -> (size: i32) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .size <- entry.by,
    )
  }
}

func Priv(x: i32) -> (y: i32) = x

func Pub(x: i32) -> (y: i32) @export {
  flow {
    call -> ret
    entry -> call
  }

  node call = Call Priv(
    .x <- entry.x,
  )
  node entry = Entry()
  node ret = Return(
    .y <- call,
  )
}
""", macros=False)


class ExportModeTests(unittest.TestCase):
    """Section 5.2: a normal build exports only what is marked @export, each with flag bit 3;
    an --export-all build also exports every func, event and method, without bit 3."""

    def exports(self, export_all):
        r = compile_declared(parse(EXPORTS), EXPORTS, export_all=export_all)
        self.assertTrue(r.ok, r.diags)
        return r, {name: (kind, flags) for name, kind, _, flags in r.module.exports}

    def test_normal_build_exports_only_declared_items(self):
        r, ex = self.exports(False)
        self.assertEqual(ex, {
            "Box.Grow": (wbc.EXPORT_FUNC, wbc.EX_DECLARED),
            "Pub": (wbc.EXPORT_FUNC, wbc.EX_DECLARED),
            "counter": (wbc.EXPORT_GLOBAL, wbc.EX_DECLARED),
            "Box": (wbc.EXPORT_TYPE, wbc.EX_DECLARED),
            "Named": (wbc.EXPORT_TYPE, wbc.EX_DECLARED),
            "Point": (wbc.EXPORT_TYPE, wbc.EX_DECLARED),
        })           # an enum has no type entry in WBC, so Color is not listed
        vm = VM(output=lambda _s: None)
        lm = vm.load(r.wbc)
        self.assertEqual(lm.meta["exports"], "declared")
        self.assertEqual(lm.declared, {"Box.Grow", "Pub", "counter", "Box", "Named", "Point"})
        self.assertEqual(vm.call(lm, "Pub", [7]), [7])    # Priv still runs inside Pub
        with self.assertRaises(WiretError) as e:
            vm.call(lm, "Priv", [7])
        self.assertEqual(e.exception.status, "WR_ERR_LINK")

    def test_export_all_adds_every_function_without_bit_3(self):
        r, ex = self.exports(True)
        self.assertEqual({n for n, (k, _) in ex.items() if k == wbc.EXPORT_FUNC},
                         {"Box.Grow", "Box.Shrink", "Priv", "Pub"})
        self.assertEqual({n for n, (k, _) in ex.items() if k != wbc.EXPORT_FUNC},
                         {"counter", "Box", "Named", "Point"})     # vars and types: still marked only
        self.assertEqual({n for n, (_, f) in ex.items() if f & wbc.EX_DECLARED},
                         {"Box.Grow", "Pub", "counter", "Box", "Named", "Point"})
        vm = VM(output=lambda _s: None)
        lm = vm.load(r.wbc)
        self.assertEqual(lm.meta["exports"], "export-all")
        self.assertEqual(vm.call(lm, "Priv", [3]), [3])

    def test_export_mode_changes_only_the_export_table(self):
        a, _ = self.exports(False)
        b, _ = self.exports(True)
        self.assertEqual([x.code for x in a.module.bodies], [x.code for x in b.module.bodies])
        self.assertEqual(a.module.types, b.module.types)
        self.assertEqual(a.module.funcs, b.module.funcs)
        meta = lambda r: VM().load(r.wbc).meta
        self.assertEqual(meta(a)["semantic_hash"], meta(b)["semantic_hash"])

    def test_export_on_an_enum_is_W0203(self):
        from wiret.explain import explain
        r, _ = self.exports(False)
        w = [d for d in r.diags if d.code == "W0203"]
        self.assertEqual([(d.graph, d.node) for d in w], [("Color", None)])
        self.assertIn("Enum 'Color' is marked @export", explain(w[0]))
        unmarked = EXPORTS.replace("enum Color: u8 @export {", "enum Color: u8 {")
        self.assertNotIn("W0203", codes(unmarked))

    def test_verifier_checks_type_export_index(self):
        r, _ = self.exports(False)
        m = wbc.decode_module(r.wbc)
        m.exports = [(n, k, 999 if k == wbc.EXPORT_TYPE else i, f) for n, k, i, f in m.exports]
        with self.assertRaises(WiretError) as e:
            VM().load(wbc.encode_module(m))
        self.assertIn("names type 999", str(e.exception))

    def test_wiretc_build_exports_declared_and_run_exports_all(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "t.wiret")
            with open(path, "w", encoding="utf-8") as f:
                f.write(EXPORTS)
            wiretc = os.path.join(os.path.dirname(HERE), "wiretc.py")
            sh = lambda *a: subprocess.run([sys.executable, wiretc, *a], capture_output=True,
                                           text=True)
            out = os.path.join(d, "t.wbc")
            self.assertEqual(sh("build", path, "-o", out).returncode, 0)
            refused = sh("run", out, "Priv", "1")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("no exported function 'Priv'", refused.stderr)
            self.assertIn("exports declared", sh("dis", out).stdout)
            self.assertEqual(sh("build", "--export-all", path, "-o", out).returncode, 0)
            self.assertEqual(sh("run", out, "Priv", "1").returncode, 0)
            ran = sh("run", path, "Priv", "4")             # run builds with --export-all
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertIn("y = 4", ran.stdout)
        finally:
            shutil.rmtree(d)


class SpecExampleRoundTrip(unittest.TestCase):
    """Tier 0 exit criterion (section 1.6): the section 2.6 example round-trips byte for byte.
    The spec shows it in flow order with no alignment (section 2.5), so the canonical writer's
    output, put back in flow order by `wiretc view --flow`, must be the example exactly."""

    def example(self):
        spec = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "reference",
                            "02-text-syntax.md")
        with open(spec, encoding="utf-8", newline="") as f:
            sec = f.read().split("### 2.6 A complete example", 1)[1]
        return sec.split("```\n", 1)[1].split("```", 1)[0]

    def test_section_2_6_round_trips_byte_for_byte(self):
        from wiret.flow import view_flow
        text = self.example()
        canonical = print_module(parse(text))
        self.assertEqual(print_module(parse(canonical)), canonical)     # fmt(fmt(x)) == fmt(x)
        self.assertEqual(view_flow(parse(canonical)), text)
        self.assertEqual(view_flow(parse(text)), text)

    def test_section_2_6_has_no_alignment_padding(self):
        for line in self.example().splitlines():
            with self.subTest(line=line):
                self.assertNotRegex(line.strip(), r"\S  +(=|at|<-|->) ")


class ArithmeticEdgeCases(unittest.TestCase):
    TEXT = module("""
func Div(a: i32, b: i32) -> (q: i32, r: i32) {
  node entry = Entry()
  node q = Div::<i32>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node r = Rem::<i32>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node ret = Return(
    .q <- q.result,
    .r <- r.result,
  )

  flow {
    entry -> ret
  }
}

func Shift(a: i32, n: i32) -> (r: i32) {
  node entry = Entry()
  node s = Shl::<i32>(
    .a <- entry.a,
    .b <- entry.n,
  )
  node ret = Return(
    .r <- s.result,
  )

  flow {
    entry -> ret
  }
}

func AddU8(a: u8, b: u8) -> (r: u8) {
  node entry = Entry()
  node s = Add::<u8>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node ret = Return(
    .r <- s.result,
  )

  flow {
    entry -> ret
  }
}

func MinMax(a: i32, b: i32) -> (lo: i32, hi: i32, abs: i32) {
  node entry = Entry()
  node lo = Min::<i32>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node hi = Max::<i32>(
    .a <- entry.a,
    .b <- entry.b,
  )
  node ab = Abs::<i32>(
    .value <- entry.a,
  )
  node ret = Return(
    .lo <- lo.result,
    .hi <- hi.result,
    .abs <- ab.result,
  )

  flow {
    entry -> ret
  }
}
""", macros=False)

    def test_division(self):
        self.assertEqual(run(self.TEXT, "Div", -7, 2)[0], [-3, -1])
        self.assertEqual(run(self.TEXT, "Div", -2**31, -1)[0], [-2**31, 0])
        with self.assertRaises(WiretError) as cm:
            run(self.TEXT, "Div", 1, 0)
        self.assertEqual(cm.exception.status, "WR_ERR_FAULT")
        self.assertEqual(cm.exception.traceback[-1], ("t.Div", "q"))    # the Div, not its user

    def test_wrapping_and_masking(self):
        self.assertEqual(run(self.TEXT, "Shift", 1, 33)[0], [2])
        self.assertEqual(run(self.TEXT, "Shift", 1, 31)[0], [-2**31])
        self.assertEqual(run(self.TEXT, "AddU8", 200, 100)[0], [44])
        self.assertEqual(run(self.TEXT, "MinMax", -5, 3)[0], [-5, 3, 5])

    def test_fuel_limit(self):
        text = module("""
func Spin() {
  node entry = Entry()
  node again = Sequence()

  flow {
    entry -> again
    again.then0 -> again
  }
}
""", macros=False)
        _, r = build(text)
        vm = VM(fuel=1000)
        with self.assertRaises(WiretError) as cm:
            vm.call(vm.load(r.wbc), "Spin", [])
        self.assertEqual(cm.exception.status, "WR_ERR_FUEL")


class ArrayTests(unittest.TestCase):
    BODY = """
var names: array::<string>

func Main(at: i32) -> (r: i32) {
  local nums: array::<i32>
  local total: i32

  flow {
    add -> set
    entry -> init
    init -> add
    loop.each -> keep
    loop.done -> name
    name -> say
    say -> r
    set -> loop
  }

  node add = ArrayAdd::<i32> nums(
    .item <- 30,
  )
  node entry = Entry()
  node init = SetLocal nums(
    .value <- mk,
  )
  node keep = SetLocal total(
    .value <- Add::<i32>(
      .a <- GetLocal total(),
      .b <- loop.item,
    ),
  )
  node loop = Macro std.flow.ForEach::<i32>(
    .array <- GetLocal nums(),
  )
  node mk = MakeArray::<i32>(
    .item0 <- 10,
    .item1 <- 20,
    .item2 <- 5,
  ) @count(3)
  node name = ArrayAdd::<string> names(
    .item <- "Ada",
  )
  node r = Return(
    .r <- GetLocal total(),
  )
  node say = Call host.Log(
    .message <- ArrayGet::<string>(
      .array <- GetVar names(),
      .index <- 0,
    ),
  )
  node set = ArraySet::<i32> nums(
    .index <- entry.at,
    .item <- 7,
  )
}
"""

    def test_build_change_and_loop(self):
        text = module(self.BODY, macros=False)
        self.assertEqual(run(text, "Main", 2), ([67], ["Ada"]))      # 10 + 20 + 7 + 30
        self.assertEqual(print_module(parse(text)), text)

    def test_out_of_range_is_a_fault(self):
        from wiret.explain import explain_runtime
        with self.assertRaises(WiretError) as cm:
            run(module(self.BODY, macros=False), "Main", 9)
        self.assertIn("out of range", str(cm.exception))
        self.assertIn("isn't in the array", explain_runtime("WR_ERR_FAULT", str(cm.exception)))
        self.assertEqual(cm.exception.traceback[-1], ("t.Main", "set"))

    def test_fault_in_pure_node_names_that_node(self):
        text = module(self.BODY.replace(".index <- 0", ".index <- 5"), macros=False)
        for debug in (False, True):
            with self.subTest(debug=debug):
                vm = VM(output=lambda s: None)
                with self.assertRaises(WiretError) as cm:
                    vm.call(vm.load(compile_module(parse(text), text, debug=debug).wbc), "Main", [0])
                self.assertEqual(cm.exception.traceback[-1], ("t.Main", "say.message"))   # not `say`

    def test_mutator_type_must_match_place(self):
        text = module(self.BODY.replace("ArrayAdd::<i32> nums", "ArrayAdd::<f64> nums"),
                      macros=False)
        self.assertIn("E0110", codes(text))


class DiagnosticTests(unittest.TestCase):
    """One failing graph per implemented diagnostic code (section 7.4)."""

    CASES = {
        "E0101": "node entry = Entry()\n  flow {\n    entry -> nowhere\n  }",
        "E0102": "node entry = Entry()\n  node entry = Return()",
        "E0103": "node entry = Entry()\n  node r = Return(\n    .bogus <- 1,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0110": "node entry = Entry()\n  node r = Return(\n    .y <- \"text\",\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0111": "node entry = Entry()\n  node r = Return(\n    .y <- 1,\n    .y <- 2,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0120": "node entry = Entry()\n  node r = Return(\n    .in <- 1,\n    .y <- 2,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0121": "node entry = Entry()\n  node r = Return(\n    .y <- 1,\n  )\n"
                 "  flow {\n    entry.then -> r\n    entry.then -> r\n  }",
        "E0130": "node entry = Entry()\n  node c = ArrayClear::<i32>()\n  node r = Return(\n    .y <- 1,\n  )\n"
                 "  flow {\n    entry -> c\n    c -> r\n  }",
        "E0301": "node entry = Entry()\n  node a = Add::<i32>(\n    .a <- b.result,\n    .b <- 1,\n  )\n"
                 "  node b = Add::<i32>(\n    .a <- a.result,\n    .b <- 1,\n  )\n"
                 "  node r = Return(\n    .y <- a.result,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0501": "node entry = Entry()\n  node w = Frobnicate()\n  node r = Return(\n    .y <- 1,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "E0502": "node entry = Entry()\n  node a = Add(\n    .a <- 1,\n    .b <- 2,\n  )\n"
                 "  node r = Return(\n    .y <- 1,\n  )\n"
                 "  flow {\n    entry -> r\n  }",
        "W0201": "node entry = Entry()\n  node r = Return()\n  flow {\n    entry -> r\n  }",
        "W0301": "node entry = Entry()\n  node r = Return(\n    .y <- 1,\n  )\n  node lost = Return(\n"
                 "    .y <- 2,\n  )\n  flow {\n    entry -> r\n  }",
        "W0302": "node entry = Entry()",
    }

    def test_each_code(self):
        for code, body in self.CASES.items():
            with self.subTest(code=code):
                text = module(f"\nfunc F() -> (y: i32) {{\n  {body}\n}}\n", macros=False)
                if code == "W0302":
                    m = parse(text)
                    r = compile_module(m)
                    found = {d.code for d in r.diags}
                else:
                    found = set(codes(text))
                self.assertIn(code, found)

    def test_purity_codes(self):
        base = module("""
var g: i32 = 0

func Impure() {
  node entry = Entry()
}
""", macros=False)
        e0302 = base + """
func P() -> (y: i32) @pure {
  node entry = Entry()
  node w = SetVar g(
    .value <- 1,
  )
  node r = Return(
    .y <- 1,
  )

  flow {
    entry -> w
    w -> r
  }
}
"""
        e0304 = base + """
func P() -> (y: i32) @pure {
  node entry = Entry()
  node v = GetVar g()
  node r = Return(
    .y <- v.value,
  )

  flow {
    entry -> r
  }
}
"""
        self.assertIn("E0302", codes(e0302))
        self.assertIn("E0304", codes(e0304))

    def test_macro_recursion(self):
        text = module("""
macro Loop(in: exec) -> (out: exec) {
  node entry = Entry()
  node again = Macro Loop()
  node done = Exit out()

  flow {
    entry -> again
    again.out -> done
  }
}
""", macros=False)
        self.assertIn("E0401", codes(text))

    def test_layout_and_note_warnings(self):
        text = module("""
#[note("orphan", detached: "gone")]
func F() {
  node entry = Entry()
  layout {
    box a "A" at (0, 0) size (10, 10) [members = [entry, ghost]]
    box b "B" at (0, 0) size (10, 10) [members = [entry]]
  }
}
""", macros=False)
        found = codes(text)
        for c in ("W0601", "W0602", "W0604"):
            self.assertIn(c, found)

    def test_delete_keeps_notes(self):
        m = parse(demo())
        g = m.graph("Main")
        removed = delete_node(g, "log_fib.message.b")
        self.assertTrue(removed)
        self.assertTrue(any(note_detached(a) == "log_fib.message.b" for a in notes(g.meta)))
        self.assertIn("W0604", {d.code for d in check(m)})
        out = print_module(m)
        self.assertIn('detached: "log_fib.message.b")]', out)
        self.assertEqual(print_module(parse(out)), out)

    def test_delete_box_keeps_notes(self):
        text = module("""
func F() {
  node entry = Entry()
  layout {
    #[note("the group")]
    box g "G" at (0, 0) size (10, 10) [members = [entry]]
  }
}
""", macros=False)
        m = parse(text)
        g = m.graph("F")
        delete_box(g, "g")
        self.assertEqual([(note_text(a), note_detached(a)) for a in notes(g.meta)],
                         [("the group", "g")])

    def test_notes_do_not_change_the_semantic_hash(self):
        m1 = parse(demo())
        m2 = parse(demo())
        g = m2.graph("Main")
        add_note(g, None, "a new graph note")
        add_note(g, g.nodes[0].id, "a new node note")
        self.assertEqual(semantic_hash(m1), semantic_hash(m2))
        self.assertNotEqual(layout_hash(m1), layout_hash(m2))

    def test_flow_view_keeps_notes_above_their_nodes(self):
        out = view_flow(parse(demo()))
        self.assertEqual(out.count("#[note("), demo().count("#[note("))
        for line_no, line in enumerate(out.split("\n")):
            if line.strip().startswith("#[note("):
                nxt = out.split("\n")[line_no + 1].strip()
                self.assertTrue(nxt.startswith(("#[", "func ", "event ", "macro "))
                                or re.match(r"[\w.]+( at \(|$)", nxt), nxt)


SAFE_DIV = """
func SafeDiv(a: i32, b: i32) -> (q: i32) {
  flow {
    bad -> fail
    entry -> t
    t.body -> ok
    t.fault -> bad
  }

  node bad = Call host.Log(
    .message <- t.message,
  )
  node entry = Entry()
  node fail = Return(
    .q <- t.code,
  )
  node ok = Return(
    .q <- Div::<i32>(
      .a <- entry.a,
      .b <- entry.b,
    ),
  )
  node t = Try()
}
"""


class FaultTests(unittest.TestCase):
    """Try and Throw (sections 3.3 and 4.6) and the fault rules of section 4.2."""

    def test_try_catches_a_built_in_fault(self):
        text = module(SAFE_DIV, macros=False)
        self.assertEqual(run(text, "SafeDiv", 7, 2), ([3], []))
        self.assertEqual(run(text, "SafeDiv", 7, 0), ([-1], ["integer divide by zero"]))

    def test_try_and_throw_round_trip(self):
        text = module(SAFE_DIV, macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])

    THROWER = """
func Check(x: i32) -> (r: i32) {
  node entry = Entry()
  node after = Call host.Log(
    .message <- "after",
  )
  node big = Gt::<i32>(
    .a <- entry.x,
    .b <- 10,
  )
  node boom = Throw(
    .message <- "too big",
    .code <- 42,
  )
  node chk = Branch(
    .cond <- big.result,
  )
  node logit = Call host.Log(
    .message <- t.message,
  )
  node ret = Return(
    .r <- t.code,
  )
  node t = Try()

  flow {
    after -> ret
    chk.then -> boom
    entry -> t
    t.body -> chk
    t.fault -> logit
    t.then -> after
  }
}
"""

    def test_then_runs_after_the_body_or_the_fault_chain(self):
        text = module(self.THROWER, macros=False)
        self.assertEqual(run(text, "Check", 3), ([0], ["after"]))
        self.assertEqual(run(text, "Check", 30), ([42], ["too big", "after"]))

    def test_handler_marker_sits_above_then_on_the_stack(self):
        text = module(self.THROWER, macros=False)
        trace = []
        run(text, "Check", 30, trace=trace)
        self.assertEqual(trace, [("entry", ()), ("t", ()), ("chk", ("after", "t!fault")),
                                 ("boom", ("after", "t!fault")), ("logit", ("after",)),
                                 ("after", ()), ("ret", ())])

    def test_uncaught_throw_reports_message_code_and_node(self):
        text = module("""
func Fail() {
  node entry = Entry()
  node boom = Throw(
    .message <- "no",
    .code <- 7,
  )

  flow {
    entry -> boom
  }
}
""", macros=False)
        with self.assertRaises(WiretError) as cm:
            run(text, "Fail")
        e = cm.exception
        self.assertEqual((e.status, e.message, e.code), ("WR_ERR_FAULT", "no", 7))
        self.assertEqual(e.traceback, [("t.Fail", "boom")])

    def test_fault_in_a_callee_unwinds_to_the_callers_try(self):
        text = module("""
func Inner(x: i32) -> (r: i32) {
  node entry = Entry()
  node div = Div::<i32>(
    .a <- 1,
    .b <- entry.x,
  )
  node log = Call host.Log(
    .message <- "inner done",
  )
  node ret = Return(
    .r <- div.result,
  )
  node seq = Sequence()

  flow {
    entry -> seq
    seq.then0 -> ret
    seq.then1 -> log
  }
}

func Outer(x: i32) -> (r: i32) {
  node entry = Entry()
  node call = Call Inner(
    .x <- entry.x,
  )
  node caught = Return(
    .r <- t.code,
  )
  node ok = Return(
    .r <- call.r,
  )
  node t = Try()

  flow {
    call -> ok
    entry -> t
    t.body -> call
    t.fault -> caught
  }
}
""", macros=False)
        self.assertEqual(run(text, "Outer", 1), ([1], []))
        self.assertEqual(run(text, "Outer", 0), ([-1], []))

    def test_fault_in_loop_body_with_try_outside_pops_the_pending_bump(self):
        # Required macro test 5, first half (section 4.2).
        text = module("""
func F() -> (n: i32) {
  local c: i32
  node entry = Entry()
  node boom = Throw(
    .message <- "stop",
  )
  node bump = SetLocal c(
    .value <- inc.result,
  )
  node chk = Branch(
    .cond <- two.result,
  )
  node cur = GetLocal c()
  node inc = Add::<i32>(
    .a <- cur.value,
    .b <- 1,
  )
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 5,
  )
  node ret = Return(
    .n <- cur.value,
  )
  node t = Try()
  node two = Eq::<i32>(
    .a <- loop.index,
    .b <- 2,
  )

  flow {
    chk.then -> boom
    chk.else -> bump
    entry -> t
    loop.each -> chk
    t.body -> loop
    t.fault -> ret
  }
}
""")
        trace = []
        res, _ = run(text, "F", trace=trace)
        self.assertEqual(res, [1])
        self.assertIn(("boom", ("t!fault", "loop/bump")), trace)
        self.assertIn(("ret", ()), trace)

    def test_try_inside_the_loop_body_leaves_the_macro_continuation(self):
        # Required macro test 5, second half: the loop goes on after each caught fault.
        text = module("""
func F() -> (n: i32) {
  local c: i32
  node entry = Entry()
  node boom = Throw(
    .message <- "odd",
  )
  node bump = SetLocal c(
    .value <- inc.result,
  )
  node chk = Branch(
    .cond <- odd.result,
  )
  node cur = GetLocal c()
  node done = Return(
    .n <- cur.value,
  )
  node inc = Add::<i32>(
    .a <- cur.value,
    .b <- 1,
  )
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 5,
  )
  node odd = Eq::<i32>(
    .a <- rem.result,
    .b <- 1,
  )
  node rem = Rem::<i32>(
    .a <- loop.index,
    .b <- 2,
  )
  node t = Try()

  flow {
    chk.then -> boom
    entry -> loop
    loop.done -> done
    loop.each -> t
    t.body -> chk
    t.fault -> bump
  }
}
""")
        trace = []
        res, _ = run(text, "F", trace=trace)
        self.assertEqual(res, [3])     # indices 1, 3 and 5 threw and were caught
        self.assertIn(("bump", ("loop/bump",)), trace)

    def test_nested_try_rethrow_reaches_the_outer_handler(self):
        text = module("""
func F() -> (msg: string) {
  node entry = Entry()
  node again = Throw(
    .message <- inner.message,
    .code <- 2,
  )
  node boom = Throw(
    .message <- "first",
    .code <- 1,
  )
  node inner = Try()
  node outer = Try()
  node ret = Return(
    .msg <- outer.message,
  )

  flow {
    entry -> outer
    inner.body -> boom
    inner.fault -> again
    outer.body -> inner
    outer.fault -> ret
  }
}
""", macros=False)
        self.assertEqual(run(text, "F")[0], ["first"])

    def test_fuel_exhaustion_is_not_catchable(self):
        text = module("""
func Spin() {
  node entry = Entry()
  node again = Sequence()
  node t = Try()

  flow {
    again.then0 -> again
    entry -> t
    t.body -> again
  }
}
""", macros=False)
        _, r = build(text)
        vm = VM(fuel=500)
        with self.assertRaises(WiretError) as cm:
            vm.call(vm.load(r.wbc), "Spin", [])
        self.assertEqual(cm.exception.status, "WR_ERR_FUEL")

    def test_throw_ends_a_chain_without_w0302(self):
        text = module("""
func F(x: i32) -> (r: i32) {
  node entry = Entry()
  node boom = Throw(
    .message <- "negative",
  )
  node chk = Branch(
    .cond <- neg.result,
  )
  node neg = Lt::<i32>(
    .a <- entry.x,
    .b <- 0,
  )
  node ret = Return(
    .r <- entry.x,
  )

  flow {
    chk.then -> boom
    chk.else -> ret
    entry -> chk
  }
}
""", macros=False)
        _, r = build(text)
        self.assertNotIn("W0302", [d.code for d in r.diags])

    def test_e0412_body_reached_from_outside(self):
        text = module("""
func F(x: bool) {
  node entry = Entry()
  node chk = Branch(
    .cond <- entry.x,
  )
  node log = Call host.Log(
    .message <- "shared",
  )
  node t = Try()

  flow {
    chk.then -> t
    chk.else -> log
    entry -> chk
    t.body -> log
  }
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_e0412_body_loops_back_to_its_try(self):
        text = module("""
func F() {
  flow {
    entry -> t
    log -> t
    t.body -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "again",
  )
  node t = Try()
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_e0412_exit_inside_a_try_body(self):
        text = module("""
macro Guard(in: exec) -> (each: exec) {
  flow {
    entry -> t
    t.body -> out
  }

  node entry = Entry()
  node out = Exit each()
  node t = Try()
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_loops_and_joins_inside_the_body_are_allowed(self):
        text = module("""
func F() {
  node entry = Entry()
  node a = Call host.Log(
    .message <- "a",
  )
  node b = Call host.Log(
    .message <- "b",
  )
  node chk = Branch()
  node join = Call host.Log(
    .message <- "join",
  )
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 2,
  )
  node t = Try()

  flow {
    a -> join
    b -> join
    chk.then -> a
    chk.else -> b
    entry -> t
    join -> loop
    t.body -> chk
  }
}
""")
        self.assertNotIn("E0412", codes(text))

    def test_bytecode_and_verifier(self):
        _, r = build(module(SAFE_DIV, macros=False))
        text = disassemble(r.wbc)
        self.assertIn("try.push", text)
        self.assertIn("; t.$fault", text)

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception

        def try_push_on_i32_local(m):      # local 0 is the i32 parameter a
            m.bodies[-1].code = bytes([0x0C, 0x80, 0x80, 0x80, 0x80, 0x00, 0x00,
                                       0x20, 0x00, 0x05])
        def throw_an_i32(m):
            m.bodies[-1].code = bytes([0x20, 0x00, 0x0E])
        for fn in (try_push_on_i32_local, throw_an_i32):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn).status, "WR_ERR_VERIFY")

    def test_fuzzed_try_modules_never_crash_the_loader(self):
        _, r = build(module(self.THROWER, macros=False))
        rng = random.Random(4120)
        data = bytes(r.wbc)
        for _ in range(800):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            vm = VM(output=lambda _s: None, fuel=10_000)
            try:
                mod = vm.load(bytes(d))
                if "Check" in mod.exports:
                    vm.call(mod, "Check", [30])
            except WiretError:
                pass


FIBERS = """
event Beep(gap: f64) {
  flow {
    a -> d
    d -> b
    entry -> a
  }

  node a = Call host.Log(
    .message <- "before",
  )
  node b = Call host.Log(
    .message <- "after",
  )
  node d = Delay(
    .seconds <- entry.gap,
  )
  node entry = Entry()
}

event Listen(s: std.Signal, name: string) {
  flow {
    entry -> w
    w -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- entry.name,
  )
  node w = Await(
    .signal <- entry.s,
  )
}

event Steps() {
  flow {
    a -> y
    entry -> a
    y -> b
  }

  node a = Call host.Log(
    .message <- "step 1",
  )
  node b = Call host.Log(
    .message <- "step 2",
  )
  node entry = Entry()
  node y = Yield()
}
"""


def fiber_vm(text):
    _, r = build(text)
    out = []
    vm = VM(output=out.append)
    return vm, vm.load(r.wbc), out


class FiberTests(unittest.TestCase):
    """Latent nodes, fibers and the scheduler (sections 4.5, 4.10 and 6.8)."""

    def test_latent_module_round_trips_and_checks(self):
        text = module(FIBERS, macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])

    def test_delay_waits_for_virtual_time(self):
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        fb = vm.start(mod, "Beep", [1.0])
        self.assertEqual((fb.status, out), ("READY", []))
        vm.advance(0.0)
        self.assertEqual((fb.status, fb.waiting, out), ("SUSPENDED", "time", ["before"]))
        vm.advance(0.5)
        self.assertEqual(out, ["before"])
        vm.advance(0.5)
        self.assertEqual((fb.status, out), ("DONE", ["before", "after"]))
        self.assertEqual(vm.fibers, [])

    def test_wake_order_is_wake_time_then_creation_order(self):
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        late = vm.start(mod, "Beep", [2.0], now=True)
        first = vm.start(mod, "Beep", [1.0], now=True)
        second = vm.start(mod, "Beep", [1.0], now=True)
        ran = vm.advance(5.0)
        self.assertEqual([fb.id for fb in ran], [first.id, second.id, late.id])

    def test_yield_resumes_on_the_next_advance_only(self):
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        vm.start(mod, "Steps", [])
        vm.advance(0.0)
        self.assertEqual(out, ["step 1"])
        vm.advance(0.0)
        self.assertEqual(out, ["step 1", "step 2"])

    def test_signal_wakes_waiters_in_the_order_they_began_waiting(self):
        from wiret.natives import Signal
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        s = Signal()
        vm.start(mod, "Listen", [s, "b"], now=True)
        vm.start(mod, "Listen", [s, "a"], now=True)
        vm.advance(10.0)
        self.assertEqual(out, [])
        vm.fire(s)
        self.assertEqual(out, [])           # woken fibers run on the next advance
        vm.advance(0.0)
        self.assertEqual(out, ["b", "a"])
        late = vm.start(mod, "Listen", [s, "c"], now=True)
        vm.advance(0.0)
        self.assertEqual(late.status, "SUSPENDED")    # a fire is not remembered

    def test_suspension_keeps_frames_and_continuations(self):
        text = module("""
func Wait(seconds: f64) -> (waited: f64) @latent {
  node d = Delay(
    .seconds <- entry.seconds,
  )
  node entry = Entry()
  node ret = Return(
    .waited <- entry.seconds,
  )

  flow {
    d -> ret
    entry -> d
  }
}

event Count(n: i32) {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- entry.n,
  )
  node msg = Convert::<i32, string>(
    .value <- loop.index,
  )
  node say = Call host.Log(
    .message <- msg.result,
  )
  node w = Call Wait(
    .seconds <- 1.0,
  )

  flow {
    entry -> loop
    loop.each -> w
    w -> say
  }
}
""")
        vm, mod, out = fiber_vm(text)
        trace = []
        fb = vm.start(mod, "Count", [3], now=True)
        self.assertEqual(len(fb.frames), 1)            # suspended inside Wait
        self.assertEqual(fb.cont, [])                  # Wait's own stack
        self.assertEqual(len(fb.frames[0][4]), 1)      # Count's pending loop/bump
        for t in range(3):
            vm.advance(1.0)
        self.assertEqual((fb.status, out), ("DONE", ["1", "2", "3"]))

    def test_a_fault_in_a_fiber_goes_to_on_fault_and_others_run_on(self):
        text = module("""
event Bad() {
  flow {
    entry -> y
    y -> boom
  }

  node boom = Throw(
    .message <- "bad",
    .code <- 9,
  )
  node entry = Entry()
  node y = Yield()
}
""" + FIBERS, macros=False)
        vm, mod, out = fiber_vm(text)
        faulted = []
        vm.on_fault = faulted.append
        bad = vm.start(mod, "Bad", [], now=True)
        good = vm.start(mod, "Steps", [], now=True)
        vm.advance(0.0)
        self.assertEqual(faulted, [bad])
        self.assertEqual((bad.status, bad.error.message, bad.error.code), ("FAULTED", "bad", 9))
        self.assertEqual((good.status, out), ("DONE", ["step 1", "step 2"]))

    def test_await_on_a_null_signal_is_a_catchable_fault(self):
        text = module("""
event E() {
  flow {
    entry -> t
    t.body -> w
    t.fault -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- t.message,
  )
  node t = Try()
  node w = Await()
}
""", macros=False)
        vm, mod, out = fiber_vm(text)
        fb = vm.start(mod, "E", [], now=True)
        self.assertEqual((fb.status, out), ("DONE", ["Await on a null signal"]))

    def test_signals_made_and_fired_in_wiret(self):
        text = module("""
var bell: std.Signal

event Ring() {
  node entry = Entry()
  node fire = Call std.signal.Fire(
    .signal <- get.value,
  )
  node get = GetVar bell()

  flow {
    entry -> fire
  }
}

event Wait() {
  node aw = Await(
    .signal <- mk.signal,
  )
  node entry = Entry()
  node log = Call host.Log(
    .message <- "rang",
  )
  node mk = Call std.signal.New()
  node keep = SetVar bell(
    .value <- mk.signal,
  )

  flow {
    aw -> log
    entry -> mk
    keep -> aw
    mk -> keep
  }
}
""", macros=False)
        vm, mod, out = fiber_vm(text)
        w = vm.start(mod, "Wait", [], now=True)
        vm.start(mod, "Ring", [], now=True)
        self.assertEqual(out, [])
        vm.advance(0.0)
        self.assertEqual((w.status, out), ("DONE", ["rang"]))

    def test_kill_ends_a_waiting_fiber(self):
        from wiret.natives import Signal
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        s = Signal()
        fb = vm.start(mod, "Listen", [s, "x"], now=True)
        vm.kill(fb)
        vm.fire(s)
        vm.advance(0.0)
        self.assertEqual((fb.status, out), ("FAULTED", []))

    def test_call_refuses_a_latent_function(self):
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        with self.assertRaises(WiretError) as cm:
            vm.call(mod, "Beep", [1.0])
        self.assertEqual(cm.exception.status, "WR_ERR_API")

    def test_run_function_skips_idle_time(self):
        from wiret.runner import run_function
        from wiret.natives import Signal
        vm, mod, out = fiber_vm(module(FIBERS, macros=False))
        self.assertEqual(run_function(vm, mod, "Beep", [5.0]), [])
        self.assertEqual((vm.time, out), (5.0, ["before", "after"]))
        with self.assertRaises(WiretError) as cm:
            run_function(vm, mod, "Listen", [Signal(), "x"])
        self.assertEqual(cm.exception.status, "WR_YIELD")

    def test_e0201_non_latent_graphs_cannot_wait(self):
        text = module("""
func Sleeper() {
  node d = Delay(
    .seconds <- 1.0,
  )
  node entry = Entry()

  flow {
    entry -> d
  }
}

func Waits() @latent {
  node d = Delay(
    .seconds <- 1.0,
  )
  node entry = Entry()

  flow {
    entry -> d
  }
}

func CallsLatent() {
  node c = Call Waits()
  node entry = Entry()

  flow {
    entry -> c
  }
}

event Ev() {
  node entry = Entry()
}

func CallsEvent() {
  node c = Call Ev()
  node entry = Entry()

  flow {
    entry -> c
  }
}

macro Pause(in: exec) -> (then: exec) {
  node d = Yield()
  node entry = Entry()
  node out = Exit then()

  flow {
    d -> out
    entry -> d
  }
}

func ExpandsLatent() {
  node entry = Entry()
  node p = Macro Pause()

  flow {
    entry -> p
  }
}
""", macros=False)
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(sorted(diags), [("CallsEvent", "E0201"), ("CallsLatent", "E0201"),
                                         ("ExpandsLatent", "E0201"), ("Sleeper", "E0201")])

    def test_e0302_pure_functions_cannot_be_latent(self):
        text = module("""
func A() @latent @pure {
  node entry = Entry()
}

func B() -> (x: i32) @pure {
  flow {
    d -> ret
    entry -> d
  }

  node d = Yield()
  node entry = Entry()
  node ret = Return(
    .x <- 1,
  )
}
""", macros=False)
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(sorted(diags), [("A", "E0302"), ("B", "E0302")])

    def test_signals_cannot_be_fields_or_container_items(self):
        text = module("""
struct Holder {
  s: std.Signal
}

func F(a: array::<std.Signal>) {
  node entry = Entry()
}
""", macros=False)
        self.assertEqual(codes(text), ["E0501"])

    def test_verifier_rules_for_suspend(self):
        _, r = build(module(FIBERS, macros=False))

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def bad_kind(m):
            m.bodies[0].code = bytes([0x0D, 0x03, 0x05])
        def extra_operand(m):         # an i32 left under the suspend
            m.bodies[0].code = bytes([0x20, 0x00, 0x0D, 0x00, 0x05])
        def timer_without_f64(m):
            m.bodies[0].code = bytes([0x20, 0x00, 0x0D, 0x01, 0x05])
        for fn in (bad_kind, extra_operand, timer_without_f64):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn), "WR_ERR_VERIFY")

    def test_fuzzed_latent_modules_never_crash(self):
        _, r = build(module(FIBERS, macros=False))
        rng = random.Random(4500)
        data = bytes(r.wbc)
        for _ in range(600):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            vm = VM(output=lambda _s: None, fuel=10_000)
            try:
                mod = vm.load(bytes(d))
                if "Beep" in mod.exports:
                    vm.start(mod, "Beep", [1.0], now=True)
                    vm.advance(2.0)
            except WiretError:
                pass


CLASSES = """
class Boss : Player {
  rage: i32 = 3

  func Describe() -> (text: string) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .text <- "boss",
    )
  }
}

class Player {
  health: i32 = 100
  name: string = "hero"

  func Describe() -> (text: string) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .text <- "player",
    )
  }

  func TakeDamage(amount: i32) -> (died: bool) {
    local new_hp: i32

    flow {
      chk.then -> ret_dead
      chk.else -> ret_alive
      entry -> set_new
      set_new -> store
      store -> chk
    }

    node chk = Branch(
      .cond <- Le::<i32>(
        .a <- hp,
        .b <- 0,
      ),
    )
    node entry = Entry()
    node hp = GetLocal new_hp()
    node ret_alive = Return(
      .died <- false,
    )
    node ret_dead = Return(
      .died <- true,
    )
    node set_new = SetLocal new_hp(
      .value <- Sub::<i32>(
        .a <- GetField Player.health(
          .obj <- entry.self,
        ),
        .b <- entry.amount,
      ),
    )
    node store = SetField Player.health(
      .obj <- entry.self,
      .value <- hp,
    )
  }
}

func Make(boss: bool) -> (p: Player) {
  local who: Player

  flow {
    b -> set_b
    entry -> pick
    pick.then -> b
    pick.else -> pl
    pl -> set_p
    set_b -> ret
    set_p -> ret
  }

  node b = New Boss()
  node entry = Entry()
  node pick = Branch(
    .cond <- entry.boss,
  )
  node pl = New Player()
  node ret = Return(
    .p <- GetLocal who(),
  )
  node set_b = SetLocal who(
    .value <- b,
  )
  node set_p = SetLocal who(
    .value <- pl,
  )
}
"""


def classes_text(extra=""):
    return module(CLASSES + extra, macros=False)


class ClassTests(unittest.TestCase):
    """Classes (sections 2.2, 3.1, 3.3, 5.3 and 5.6): fields, methods, inheritance, virtual
    dispatch, Cast, IsValid, identity, and null faults."""

    def test_round_trip_and_clean_check(self):
        text = classes_text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])

    def test_bare_members_are_read_and_written_qualified(self):
        # inside a method the reader accepts a member of its class by its bare name; the
        # canonical form always qualifies it, and the program is the same
        for full, bare in (("GetField Player.health", "GetField health"),
                           ("SetField Player.health", "SetField health")):
            text = classes_text()
            self.assertIn(full, text)
            loose = text.replace(full, bare)
            self.assertEqual(print_module(parse(loose)), text)
            self.assertEqual(instruction_bytes(build(loose)[1].wbc),
                             instruction_bytes(build(text)[1].wbc))
        text = delegates_text()
        loose = text.replace("Broadcast Player.OnHit", "Broadcast OnHit")
        self.assertNotEqual(loose, text)
        self.assertEqual(print_module(parse(loose)), text)

    def test_a_note_on_a_method_round_trips_once(self):
        text = module("""
class A {
  #[note("one note")]
  func F() {
    node entry = Entry()
  }
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)

    def test_methods_are_items_named_by_class(self):
        m = parse(classes_text())
        names = [g.name for g in m.graphs()]
        self.assertIn("Player.TakeDamage", names)
        self.assertEqual(m.graph("Boss.Describe").owner, "Boss")

    def test_fields_methods_and_virtual_dispatch(self):
        text = classes_text("""
func Run(boss: bool) -> (said: string, died: bool, hp: i32, name: string) {
  flow {
    desc -> hit
    entry -> mk
    hit -> ret
    mk -> desc
  }

  node desc = Call Player.Describe(
    .self <- mk.p,
  )
  node entry = Entry()
  node hit = Call Player.TakeDamage(
    .self <- mk.p,
    .amount <- 150,
  )
  node hp = GetField Player.health(
    .obj <- mk.p,
  )
  node mk = Call Make(
    .boss <- entry.boss,
  )
  node nm = GetField Player.name(
    .obj <- mk.p,
  )
  node ret = Return(
    .said <- desc.text,
    .died <- hit.died,
    .hp <- hp.value,
    .name <- nm.value,
  )
}
""")
        self.assertEqual(run(text, "Run", 0)[0], ["player", 1, -50, "hero"])
        self.assertEqual(run(text, "Run", 1)[0], ["boss", 1, -50, "hero"])

    def test_cast_isvalid_and_identity(self):
        text = classes_text("""
func Probe(boss: bool) -> (ok: bool, rage: i32, valid: bool, same: bool, other: bool) {
  node as_boss = Cast Boss(
    .obj <- mk.p,
  )
  node entry = Entry()
  node mk = Call Make(
    .boss <- entry.boss,
  )
  node mk2 = Call Make(
    .boss <- entry.boss,
  )
  node other = Eq::<Player>(
    .a <- mk.p,
    .b <- mk2.p,
  )
  node rage = GetField Boss.rage(
    .obj <- as_boss.result,
  )
  node ret = Return(
    .ok <- as_boss.ok,
    .rage <- rage.value,
    .valid <- valid.result,
    .same <- same.result,
    .other <- other.result,
  )
  node same = Eq::<Player>(
    .a <- mk.p,
    .b <- mk.p,
  )
  node valid = IsValid(
    .obj <- mk.p,
  )

  flow {
    entry -> mk
    mk -> mk2
    mk2 -> ret
  }
}
""")
        self.assertEqual(run(text, "Probe", 1)[0], [1, 3, 1, 1, 0])
        with self.assertRaises(WiretError) as cm:          # Cast fails: result is null
            run(text, "Probe", 0)
        e = cm.exception
        self.assertEqual((e.code, e.traceback[-1]), (-3, ("t.Probe", "rage")))

    def test_null_reference_faults_are_catchable(self):
        text = classes_text("""
func Safe() -> (code: i32) {
  flow {
    entry -> t
    set -> ok
    t.body -> set
    t.fault -> caught
  }

  node caught = Return(
    .code <- t.code,
  )
  node entry = Entry()
  node ok = Return(
    .code <- 0,
  )
  node set = SetField Player.health(
    .obj <- null,
    .value <- 1,
  )
  node t = Try()
}
""")
        self.assertEqual(run(text, "Safe")[0], [-3])

    def test_objects_are_shared_references(self):
        text = classes_text("""
func Alias() -> (hp: i32) {
  flow {
    a -> set
    entry -> a
    set -> ret
  }

  node a = New Player()
  node arr = MakeArray::<Player>(
    .item0 <- a.result,
  ) @count(1)
  node entry = Entry()
  node first = ArrayGet::<Player>(
    .array <- arr.result,
    .index <- 0,
  )
  node hp = GetField Player.health(
    .obj <- a.result,
  )
  node ret = Return(
    .hp <- hp.value,
  )
  node set = SetField Player.health(
    .obj <- first.item,
    .value <- 7,
  )
}
""")
        self.assertEqual(run(text, "Alias")[0], [7])

    def test_host_api_new_and_call_method(self):
        _, r = build(classes_text())
        vm = VM(output=lambda s: None)
        mod = vm.load(r.wbc)
        boss = vm.new(mod, "Boss")
        self.assertEqual((boss.get("health"), boss.get("rage")), (100, 3))
        self.assertEqual(vm.call_method(mod, boss, "Describe", []), ["boss"])
        self.assertEqual(vm.call_method(mod, boss, "TakeDamage", [40]), [0])
        self.assertEqual(boss.get("health"), 60)

    def test_run_function_gives_a_method_a_new_object(self):
        from wiret.runner import run_function
        _, r = build(classes_text())
        vm = VM(output=lambda s: None)
        self.assertEqual(run_function(vm, vm.load(r.wbc), "Player.TakeDamage", [30]), [0])

    def test_subclass_flows_into_base_pins_but_not_back(self):
        text = classes_text("""
func Up() -> (p: Player) {
  node b = New Boss()
  node entry = Entry()
  node ret = Return(
    .p <- b.result,
  )

  flow {
    b -> ret
    entry -> b
  }
}

func Down() -> (b: Boss) {
  node entry = Entry()
  node p = New Player()
  node ret = Return(
    .b <- p.result,
  )

  flow {
    entry -> p
    p -> ret
  }
}
""")
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(diags, [("Down", "E0110")])

    def test_e0150_bad_overrides(self):
        text = module("""
class A {
  func F(x: i32) {
    node entry = Entry()
  }

  func G() @final {
    node entry = Entry()
  }
}

class B : A {
  func F(x: f32) {
    node entry = Entry()
  }

  func G() {
    node entry = Entry()
  }
}
""", macros=False)
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("B.F", "E0150"), ("B.G", "E0150")])

    def test_final_methods_are_called_directly(self):
        text = module("""
class A {
  func Id() -> (x: i32) @final {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .x <- 1,
    )
  }
}

func F() -> (x: i32) {
  flow {
    a -> c
    c -> ret
    entry -> a
  }

  node a = New A()
  node c = Call A.Id(
    .self <- a,
  )
  node entry = Entry()
  node ret = Return(
    .x <- c,
  )
}
""", macros=False)
        _, r = build(text)
        listing = disassemble(r.wbc)
        self.assertIn("call t.A.Id", listing)
        self.assertNotIn("call_virtual", listing)
        self.assertEqual(run(text, "F")[0], [1])

    def test_e0151_and_duplicate_fields(self):
        text = module("""
class A : B {
  x: i32
}

class B : A {
  y: i32
}

class C : Missing {
}

class D : E {
  x: i32
}

class E {
  x: i32
}
""", macros=False)
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("A", "E0151"), ("B", "E0151"), ("C", "E0151"), ("D", "E0102")])

    def test_purity_rules_for_objects(self):
        text = classes_text("""
func P(p: Player) -> (hp: i32) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node hp = GetField Player.health(
    .obj <- entry.p,
  )
  node ret = Return(
    .hp <- hp.value,
  )
}
""")
        self.assertIn("E0304", codes(text))

    def test_flow_view_reorders_methods(self):
        text = classes_text()
        view = view_flow(parse(text))
        self.assertIn("  func TakeDamage(amount: i32) -> (died: bool) {\n    local new_hp: i32\n\n"
                      "    flow {\n      entry -> set_new\n      set_new -> store\n", view)
        self.assertIn("    }\n\n    node entry = Entry()\n    node set_new = SetLocal new_hp(\n",
                      view)

    def test_verifier_rejects_bad_class_code(self):
        _, r = build(classes_text())

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        cls = next(i for i, t in enumerate(wbc.decode_module(r.wbc).types)
                   if isinstance(t, wbc.ClassType) and t.super is None)

        def cyclic(m):
            e = m.types[cls]
            m.types[cls] = wbc.ClassType(cls, e.fields, e.vtable)
        def bad_field(m):                     # class.get with no such field
            m.bodies[-1].code = bytes([0x25, cls, 0xD4, cls, 0x7F, 0x10, 0x05])
        def string_as_object(m):
            m.bodies[-1].code = bytes([0x24, 0x00, 0xD4, cls, 0x00, 0x10, 0x05])
        for fn in (cyclic, bad_field, string_as_object):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn), "WR_ERR_VERIFY")

    def test_the_section_2_6_example_compiles_and_runs(self):
        spec = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "reference",
                            "02-text-syntax.md")
        with open(spec, encoding="utf-8") as f:
            sec = f.read().split("### 2.6 A complete example", 1)[1]
        code = sec.split("```\n", 1)[1].split("```", 1)[0]
        _, r = build(code)
        out = []
        vm = VM(output=out.append)
        mod = vm.load(r.wbc)
        p = vm.new(mod, "Player")
        self.assertEqual(vm.call_method(mod, p, "TakeDamage", [150]), [1])
        self.assertEqual((p.get("health"), out), (-50, ["Player died"]))
        fb = vm.start(mod, "Player.Respawn", [p], now=True)
        vm.advance(2.0)
        self.assertEqual((fb.status, p.get("health")), ("DONE", 100))
        self.assertEqual(vm.call(mod, "Fib", [10]), [55])

    def test_fuzzed_class_modules_never_crash(self):
        _, r = build(classes_text())
        rng = random.Random(5150)
        data = bytes(r.wbc)
        for _ in range(800):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            vm = VM(output=lambda _s: None, fuel=10_000)
            try:
                mod = vm.load(bytes(d))
                if "Make" in mod.exports:
                    vm.call(mod, "Make", [1])
            except WiretError:
                pass


IFACE = """
interface Damageable {
  func Hit(amount: i32) -> (left: i32)
  func Name() -> (name: string)
}

class Barrel impl Damageable {
  hp: i32 = 10

  func Hit(amount: i32) -> (left: i32) {
    local hp_left: i32

    flow {
      entry -> keep
      keep -> set
      set -> ret
    }

    node entry = Entry()
    node keep = SetLocal hp_left(
      .value <- Sub::<i32>(
        .a <- GetField Barrel.hp(
          .obj <- entry.self,
        ),
        .b <- entry.amount,
      ),
    )
    node now = GetLocal hp_left()
    node ret = Return(
      .left <- now,
    )
    node set = SetField Barrel.hp(
      .obj <- entry.self,
      .value <- now,
    )
  }

  func Name() -> (name: string) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .name <- "barrel",
    )
  }
}

class BigBarrel : Barrel {
  func Name() -> (name: string) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .name <- "big barrel",
    )
  }
}

class Door impl Damageable {
  func Hit(amount: i32) -> (left: i32) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .left <- 99,
    )
  }

  func Name() -> (name: string) {
    flow {
      entry -> ret
    }

    node entry = Entry()
    node ret = Return(
      .name <- "door",
    )
  }
}

func Smash(which: i32) -> (name: string, left: i32, is_d: bool) {
  local t: Damageable

  flow {
    b -> sb
    chk.then -> b
    chk.else -> d
    d -> sd
    entry -> chk
    hit -> nm
    nm -> ret
    sb -> hit
    sd -> hit
  }

  node b = New BigBarrel()
  node chk = Branch(
    .cond <- Eq::<i32>(
      .a <- entry.which,
      .b <- 0,
    ),
  )
  node d = New Door()
  node entry = Entry()
  node get = GetLocal t()
  node hit = Call Damageable.Hit(
    .self <- get,
    .amount <- 4,
  )
  node nm = Call Damageable.Name(
    .self <- get,
  )
  node ret = Return(
    .name <- nm,
    .left <- hit,
    .is_d <- Cast Door(
      .obj <- get,
    ).ok,
  )
  node sb = SetLocal t(
    .value <- b,
  )
  node sd = SetLocal t(
    .value <- d,
  )
}
"""


def iface_text(extra=""):
    return module(IFACE + extra, macros=False)


class InterfaceTests(unittest.TestCase):
    """Interfaces (sections 2.2, 3.3, 5.3 and 5.6): `impl`, calls through an interface,
    subtyping, Cast, E0151, E0152, and the verifier's interface tables."""

    def test_round_trip_and_check(self):
        text = iface_text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c.startswith("E")], [])

    def test_calls_dispatch_through_the_interface(self):
        text = iface_text()
        self.assertEqual(run(text, "Smash", 0)[0], ["big barrel", 6, 0])   # Hit is Barrel's
        self.assertEqual(run(text, "Smash", 1)[0], ["door", 99, 1])
        _, r = build(text)
        self.assertIn("call_interface", disassemble(r.wbc))

    def test_subtyping_and_cast(self):
        text = iface_text("""
class Rock {
}

func Up() -> (d: Damageable) {
  node entry = Entry()
  node n = New Door()
  node ret = Return(
    .d <- n.result,
  )

  flow {
    entry -> n
    n -> ret
  }
}

func Down(d: Damageable) -> (door: Door) {
  node entry = Entry()
  node ret = Return(
    .door <- entry.d,
  )

  flow {
    entry -> ret
  }
}

func NotOne() -> (d: Damageable) {
  node entry = Entry()
  node n = New Rock()
  node ret = Return(
    .d <- n.result,
  )

  flow {
    entry -> n
    n -> ret
  }
}

func Probe() -> (rock_ok: bool, door_ok: bool) {
  node door = New Door()
  node entry = Entry()
  node is_door = Cast Damageable(
    .obj <- door.result,
  )
  node is_rock = Cast Damageable(
    .obj <- rock.result,
  )
  node ret = Return(
    .rock_ok <- is_rock.ok,
    .door_ok <- is_door.ok,
  )
  node rock = New Rock()

  flow {
    door -> rock
    entry -> door
    rock -> ret
  }
}
""")
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("Down", "E0110"), ("NotOne", "E0110")])
        ok = parse(text)
        ok.items = [it for it in ok.items if getattr(it, "name", "") not in ("Down", "NotOne")]
        self.assertEqual(run(print_module(ok), "Probe")[0], [0, 1])

    def test_e0152_missing_or_mismatched_methods(self):
        text = module("""
interface Named {
  func Name() -> (name: string)
  func Rank() -> (rank: i32)
}

class A impl Named {
  func Name() -> (name: i32) {
    node entry = Entry()
  }
}

class B impl Named {
  func Rank() -> (rank: i32) {
    node entry = Entry()
  }

  event Name() {
    node entry = Entry()
  }
}
""", macros=False)
        diags = sorted((d.graph, d.code, d.pin) for d in check(parse(text))
                       if d.code.startswith("E"))
        self.assertEqual(diags, [("A", "E0152", "Name"), ("A", "E0152", "Rank"),
                                 ("B", "E0152", "Name")])

    def test_e0151_impl_of_something_else_and_interface_rules(self):
        text = module("""
interface I {
  func F()
  func F()
  func W() @latent
}

class A {
}

class B impl A, Missing {
}
""", macros=False)
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("B", "E0151"), ("B", "E0151"), ("I", "E0102"),
                                 ("I", "E0501")])

    def test_an_object_used_as_a_class_and_as_an_interface(self):
        # New's result goes into a Damageable pin first (sorted by id) and then into a Door
        # field write; the slot holding it must keep the producer's type, Door
        text = iface_text("""
func Both() -> (left: i32) {
  flow {
    a_use -> ret
    door -> a_use
    entry -> door
  }

  node a_use = Call Damageable.Hit(
    .self <- door.result,
    .amount <- 1,
  )
  node door = New Door()
  node entry = Entry()
  node ret = Return(
    .left <- a_use.left,
  )
  node z_cast = Cast Door(
    .obj <- door.result,
  )
}
""")
        self.assertEqual(run(text, "Both")[0], [99])

    def test_null_receiver_faults(self):
        text = iface_text("""
func F() -> (code: i32) {
  flow {
    c -> ok
    entry -> t
    t.body -> c
    t.fault -> caught
  }

  node c = Call Damageable.Name(
    .self <- null,
  )
  node caught = Return(
    .code <- t.code,
  )
  node entry = Entry()
  node ok = Return(
    .code <- 0,
  )
  node t = Try()
}
""")
        self.assertEqual(run(text, "F")[0], [-3])

    def test_ids_and_merge_know_classes_and_interfaces(self):
        from wiret.ids import assign_ids
        from wiret.merge import merge_texts
        m = parse(iface_text())
        assign_ids(m, rng=random.Random(3))
        out = print_module(m)
        self.assertIn('interface Damageable @id("if_', out)
        self.assertIn('class Door impl Damageable @id("cls_', out)
        self.assertIn('func Name() -> (name: string) @id("im_', out)
        base = iface_text()
        ours = base.replace("  func Name() -> (name: string)\n}",
                            "  func Name() -> (name: string)\n  func Heal()\n}", 1)
        theirs = base.replace("class Door impl Damageable {", "class Door impl Damageable {\n"
                              "  open: bool", 1)
        r = merge_texts(base, ours, theirs)
        self.assertEqual(r.conflicts, [])
        self.assertIn("  func Heal()\n}", r.text)
        self.assertIn("  open: bool\n", r.text)

    def test_verifier_checks_interface_tables(self):
        _, r = build(iface_text())

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def find(m, name):
            return next(i for i, t in enumerate(m.types) if isinstance(t, wbc.ClassType)
                        and t.interfaces and len(t.vtable) == 2 and t.super is None
                        and len(t.fields) == (1 if name == "Barrel" else 0))

        def short_table(m):
            t = find(m, "Door")
            e = m.types[t]
            i, impl = e.interfaces[0]
            m.types[t] = wbc.ClassType(e.super, e.fields, e.vtable, ((i, impl[:1]),))
        def swapped_methods(m):          # Hit and Name have different signatures
            t = find(m, "Door")
            e = m.types[t]
            i, impl = e.interfaces[0]
            m.types[t] = wbc.ClassType(e.super, e.fields, e.vtable, ((i, impl[::-1]),))
        def dropped_by_subclass(m):
            t = next(i for i, x in enumerate(m.types)
                     if isinstance(x, wbc.ClassType) and x.super is not None)
            e = m.types[t]
            m.types[t] = wbc.ClassType(e.super, e.fields, e.vtable, ())
        for fn in (short_table, swapped_methods, dropped_by_subclass):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn), "WR_ERR_VERIFY")

    def test_fuzzed_interface_modules_never_crash(self):
        _, r = build(iface_text())
        rng = random.Random(6262)
        data = bytes(r.wbc)
        for _ in range(800):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            vm = VM(output=lambda _s: None, fuel=10_000)
            try:
                mod = vm.load(bytes(d))
                if "Smash" in mod.exports:
                    vm.call(mod, "Smash", [0])
            except WiretError:
                pass


DELEGATES = """
class Counter {
  hits: i32

  func Add(amount: i32) {
    flow {
      entry -> set
    }

    node entry = Entry()
    node set = SetField Counter.hits(
      .obj <- entry.self,
      .value <- Add::<i32>(
        .a <- GetField Counter.hits(
          .obj <- entry.self,
        ),
        .b <- entry.amount,
      ),
    )
  }

  event Later(amount: i32) {
    flow {
      entry -> y
      y -> log
    }

    node entry = Entry()
    node log = Call host.Log(
      .message <- "later",
    )
    node y = Yield()
  }
}

class Player {
  dispatcher OnHit(amount: i32)

  func Hit(amount: i32) {
    flow {
      entry -> b
    }

    node b = Broadcast Player.OnHit(
      .obj <- entry.self,
      .amount <- entry.amount,
    )
    node entry = Entry()
  }
}

func Boom(amount: i32) {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- Convert::<i32, string>(
      .value <- Div::<i32>(
        .a <- 1,
        .b <- 0,
      ),
    ),
  )
}

func Run() -> (hits: i32, twice: i32) {
  flow {
    b1 -> b2
    b2 -> b3
    b3 -> b4
    b4 -> h1
    c -> p
    entry -> c
    h1 -> ub
    h2 -> inv
    inv -> ret
    p -> b1
    ub -> h2
  }

  node add = CreateDelegate Counter.Add(
    .target <- c,
  )
  node b1 = Bind Player.OnHit(
    .obj <- p,
    .handler <- add,
  )
  node b2 = Bind Player.OnHit(
    .obj <- p,
    .handler <- CreateDelegate Boom(),
  )
  node b3 = Bind Player.OnHit(
    .obj <- p,
    .handler <- CreateDelegate Counter.Later(
      .target <- c,
    ),
  )
  node b4 = Bind Player.OnHit(
    .obj <- p,
    .handler <- add,
  )
  node c = New Counter()
  node entry = Entry()
  node h1 = Call Player.Hit(
    .self <- p,
    .amount <- 5,
  )
  node h2 = Call Player.Hit(
    .self <- p,
    .amount <- 7,
  )
  node inv = Invoke::<delegate::<(i32) -> (i32)>>(
    .delegate <- CreateDelegate Twice(),
    .arg0 <- 21,
  )
  node p = New Player()
  node ret = Return(
    .hits <- GetField Counter.hits(
      .obj <- c,
    ),
    .twice <- inv,
  )
  node ub = Unbind Player.OnHit(
    .obj <- p,
    .handler <- add,
  )
}

func Twice(x: i32) -> (y: i32) = Mul::<i32>(
  .a <- x,
  .b <- 2,
)
"""


def delegates_text(extra=""):
    return module(DELEGATES + extra, macros=False)


class DelegateTests(unittest.TestCase):
    """Delegates and dispatchers (sections 2.2, 3.1, 3.3, 5.3 and 5.6)."""

    def run_it(self, text=None):
        _, r = build(text or delegates_text())
        out = []
        vm = VM(output=out.append)
        mod = vm.load(r.wbc)
        return vm, mod, out, vm.call(mod, "Run", [])

    def test_round_trip_and_check(self):
        text = delegates_text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c.startswith("E")], [])

    def test_bind_broadcast_unbind_and_invoke(self):
        vm, mod, out, res = self.run_it()
        # Add ran on the first Hit only (bound once although Bind ran twice, then unbound);
        # Twice(21) through Invoke
        self.assertEqual(res, [5, 42])

    def test_a_faulting_handler_is_reported_and_the_rest_run(self):
        vm, mod, out, res = self.run_it()
        self.assertEqual([e.message for e in vm.handler_faults],
                         ["integer divide by zero"] * 2)
        self.assertEqual(res[0], 5)            # Add, bound before Boom, still ran

    def test_an_event_handler_starts_on_its_own_fiber(self):
        vm, mod, out, res = self.run_it()
        self.assertEqual([f.name for f in vm.fibers], ["t.Counter.Later"] * 2)
        self.assertEqual(out, [])
        vm.advance(0.0)                         # each yields once
        vm.advance(0.0)
        self.assertEqual(out, ["later", "later"])

    def test_a_method_delegate_calls_the_override(self):
        text = delegates_text("""
class Loud : Counter {
  func Add(amount: i32) {
    flow {
      entry -> log
    }

    node entry = Entry()
    node log = Call host.Log(
      .message <- "loud",
    )
  }
}

func Over() {
  flow {
    entry -> l
    l -> inv
  }

  node d = CreateDelegate Counter.Add(
    .target <- l,
  )
  node entry = Entry()
  node inv = Invoke::<delegate::<(i32)>>(
    .delegate <- d.result,
    .arg0 <- 1,
  )
  node l = New Loud()
}
""")
        _, r = build(text)
        out = []
        vm = VM(output=out.append)
        vm.call(vm.load(r.wbc), "Over", [])
        self.assertEqual(out, ["loud"])

    def test_null_delegate_and_null_object_fault(self):
        text = delegates_text("""
func NullInvoke() -> (code: i32) {
  flow {
    entry -> t
    inv -> ok
    t.body -> inv
    t.fault -> caught
  }

  node caught = Return(
    .code <- t.code,
  )
  node entry = Entry()
  node inv = Invoke::<delegate::<(i32) -> (i32)>>(
    .delegate <- null,
  )
  node ok = Return(
    .code <- 0,
  )
  node t = Try()
}
""")
        self.assertEqual(run(text, "NullInvoke")[0], [-3])

    def test_host_delegate_and_broadcast(self):
        _, r = build(delegates_text())
        vm = VM(output=lambda s: None)
        mod = vm.load(r.wbc)
        p, c = vm.new(mod, "Player"), vm.new(mod, "Counter")
        p.get("OnHit").handlers.append(vm.delegate(mod, "Counter.Add", c))
        vm.broadcast(mod, p, "OnHit", [3])
        vm.broadcast(mod, p, "OnHit", [4])
        self.assertEqual(c.get("hits"), 7)
        self.assertEqual(vm.call(mod, "Twice", [5]), [10])

    def test_type_rules(self):
        text = delegates_text("""
func Bad() {
  node d = CreateDelegate Twice()
  node entry = Entry()
  node eq = Eq::<delegate::<(i32) -> (i32)>>(
    .a <- d.result,
    .b <- d.result,
  )
  node p = New Player()
  node wrong = Bind Player.OnHit(
    .obj <- p.result,
    .handler <- d.result,
  )

  flow {
    entry -> p
    p -> wrong
  }
}

func Waits() @latent {
  node d = Delay(
    .seconds <- 1.0,
  )
  node entry = Entry()

  flow {
    entry -> d
  }
}

func BindsLatent() {
  node d = CreateDelegate Waits()
  node entry = Entry()
}

func Native() {
  node d = CreateDelegate host.Log()
  node entry = Entry()
}

struct Holder {
  d: dispatcher::<(i32)>
}
""")
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("Bad", "E0110"), ("Bad", "E0110"), ("BindsLatent", "E0501"),
                                 ("Holder", "E0501"), ("Native", "E0501")])

    def test_dispatcher_members_and_purity(self):
        text = delegates_text("""
class Twin {
  hit: i32
  dispatcher hit(x: i32)
}

func P(p: Player) @pure {
  flow {
    entry -> b
  }

  node b = Broadcast Player.OnHit(
    .obj <- entry.p,
    .amount <- 1,
  )
  node entry = Entry()
}
""")
        c = codes(text)
        self.assertIn("E0102", c)
        self.assertIn("E0302", c)

    def test_delegate_types_written_with_empty_results_are_the_short_form(self):
        m = parse(module("""
func F(d: delegate::<(i32) -> ()>) {
  node entry = Entry()
}
""", macros=False))
        self.assertEqual(m.graph("F").params[0].type, "delegate::<(i32)>")

    def test_ids_name_dispatchers(self):
        from wiret.ids import assign_ids
        m = parse(delegates_text())
        assign_ids(m, rng=random.Random(4))
        self.assertIn('dispatcher OnHit(amount: i32) @id("dsp_', print_module(m))

    def test_verifier_rules(self):
        _, r = build(delegates_text())

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def bad_flags(m):
            m.bodies[-1].code = bytes([0xF4, 0x00, 0x04, 0x10, 0x05])
        def receiver_without_bind(m):        # flag 2 needs flag 1
            m.bodies[-1].code = bytes([0xF4, 0x00, 0x02, 0x10, 0x05])
        def bind_an_i32(m):
            t = next(i for i, x in enumerate(m.types) if isinstance(x, wbc.DispatcherType))
            m.bodies[-1].code = bytes([0x25, 0, 0x20, 0x00, 0xF5, t, 0x05])
        for fn in (bad_flags, receiver_without_bind, bind_an_i32):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn), "WR_ERR_VERIFY")

    def test_fuzzed_delegate_modules_never_crash(self):
        _, r = build(delegates_text())
        rng = random.Random(7070)
        data = bytes(r.wbc)
        for _ in range(800):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            vm = VM(output=lambda _s: None, fuel=20_000)
            try:
                mod = vm.load(bytes(d))
                if "Run" in mod.exports:
                    vm.call(mod, "Run", [])
                    vm.advance(0.0)
            except WiretError:
                pass


COW = """
class Bag {
  items: array::<i32>
}

func Build(n: i32) -> (len: i32) {
  local acc: array::<i32>
  node add = ArrayAdd::<i32> acc(
    .item <- loop.index,
  )
  node entry = Entry()
  node get = GetLocal acc()
  node len = ArrayLength::<i32>(
    .array <- get.value,
  )
  node loop = Macro ForRange(
    .first <- 1,
    .last <- entry.n,
  )
  node ret = Return(
    .len <- len.length,
  )

  flow {
    entry -> loop
    loop.done -> ret
    loop.each -> add
  }
}

func Bump(a: array::<i32>) -> (len: i32) {
  local mine: array::<i32>
  node add = ArrayAdd::<i32> mine(
    .item <- 9,
  )
  node entry = Entry()
  node get = GetLocal mine()
  node keep = SetLocal mine(
    .value <- entry.a,
  )
  node len = ArrayLength::<i32>(
    .array <- get.value,
  )
  node ret = Return(
    .len <- len.length,
  )

  flow {
    add -> ret
    entry -> keep
    keep -> add
  }
}

func Mutate(x: array::<i32>) -> (y: array::<i32>) {
  local mine: array::<i32>
  node add = ArrayAdd::<i32> mine(
    .item <- 7,
  )
  node entry = Entry()
  node get = GetLocal mine()
  node keep = SetLocal mine(
    .value <- entry.x,
  )
  node ret = Return(
    .y <- get.value,
  )

  flow {
    add -> ret
    entry -> keep
    keep -> add
  }
}

func Alias() -> (a: array::<i32>, b: array::<i32>, c: array::<i32>, d: array::<i32>) {
  local a: array::<i32>
  local b: array::<i32>
  node add_a = ArrayAdd::<i32> a(
    .item <- 1,
  )
  node add_a2 = ArrayAdd::<i32> a(
    .item <- 2,
  )
  node bag = New Bag()
  node bag_items = GetField Bag.items(
    .obj <- bag.result,
  )
  node call = Call Mutate(
    .x <- get_a.value,
  )
  node copy_b = SetLocal b(
    .value <- get_a.value,
  )
  node entry = Entry()
  node get_a = GetLocal a()
  node get_b = GetLocal b()
  node put = SetField Bag.items(
    .obj <- bag.result,
    .value <- get_a.value,
  )
  node ret = Return(
    .a <- get_a.value,
    .b <- get_b.value,
    .c <- bag_items.value,
    .d <- call.y,
  )

  flow {
    add_a -> copy_b
    add_a2 -> call
    bag -> put
    call -> ret
    copy_b -> bag
    entry -> add_a
    put -> add_a2
  }
}

func Snapshot() -> (seen: i32, after: i32) {
  local a: array::<i32>
  local n: i32
  node a1 = ArrayAdd::<i32> a(
    .item <- 1,
  )
  node a2 = ArrayAdd::<i32> a(
    .item <- 2,
  )
  node cnt = GetLocal n()
  node entry = Entry()
  node get_a = GetLocal a()
  node grow = ArrayAdd::<i32> a(
    .item <- 0,
  )
  node inc = Add::<i32>(
    .a <- cnt.value,
    .b <- 1,
  )
  node len = ArrayLength::<i32>(
    .array <- get_a.value,
  )
  node loop = Macro std.flow.ForEach::<i32>(
    .array <- get_a.value,
  )
  node ret = Return(
    .seen <- cnt.value,
    .after <- len.length,
  )
  node set_n = SetLocal n(
    .value <- inc.result,
  )

  flow {
    a1 -> a2
    a2 -> loop
    entry -> a1
    grow -> set_n
    loop.done -> ret
    loop.each -> grow
  }
}
"""


class CopyOnWriteTests(unittest.TestCase):
    """Containers are values, implemented copy-on-write (section 4.9)."""

    def fuel_for(self, text, func, *args):
        _, r = build(text)
        vm = VM(output=lambda s: None)
        res = vm.call(vm.load(r.wbc), func, list(args))
        return res, vm.fuel_limit - vm.fuel

    def test_append_loop_has_constant_cost_per_item(self):
        text = module(COW)
        r1, f1 = self.fuel_for(text, "Build", 1000)
        r4, f4 = self.fuel_for(text, "Build", 4000)
        self.assertEqual((r1, r4), ([1000], [4000]))
        self.assertLess(f4, 4.5 * f1)          # eager copies would make it about 16 times

    def test_values_stay_independent(self):
        text = module(COW)
        res = run(text, "Alias")[0]
        # a: changed twice; b: copied after the first change; c: the bag got a after the first
        # change; d: Mutate's own change, which the caller's a never sees
        self.assertEqual(res, [(1, 2), (1,), (1,), (1, 2, 7)])

    def test_callee_change_is_not_seen_by_the_caller(self):
        text = module(COW)
        _, r = build(text)
        vm = VM(output=lambda s: None)
        mod = vm.load(r.wbc)
        arg = (1, 2)
        self.assertEqual(vm.call(mod, "Bump", [arg]), [3])
        self.assertEqual(arg, (1, 2))

    def test_foreach_iterates_the_array_as_it_was(self):
        text = module(COW)
        self.assertEqual(run(text, "Snapshot")[0], [2, 4])

    def test_shares_where_values_escape_and_not_for_reads(self):
        text = module(COW)
        _, r = build(text)
        listing = disassemble(r.wbc)
        build_fn = listing.split("func t.Build")[1].split("\nfunc ")[0]
        self.assertNotIn("ref.share", build_fn)   # only an append and a length
        alias = listing.split("func t.Alias")[1].split("\nfunc ")[0]
        self.assertIn("ref.share", alias)

    def test_verifier_rejects_sharing_a_number(self):
        _, r = build(module(COW))
        m = wbc.decode_module(r.wbc)
        m.bodies[0].code = bytes([0x20, 0x00, 0x2B, 0x10, 0x05])
        with self.assertRaises(WiretError) as cm:
            VM().load(wbc.encode_module(m))
        self.assertEqual(cm.exception.status, "WR_ERR_VERIFY")


CAPS = """
extern func host.Beep() @capability("audio.play")
extern func host.Log(message: string) @capability("console.write")

func Hello() {
  node beep = Call host.Beep()
  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )

  flow {
    entry -> log
    log -> beep
  }
}
"""


class CapabilityTests(unittest.TestCase):
    """Capabilities (sections 2.4, 5.4, 6.5 and 7.3)."""

    def caps_module(self, body=CAPS):
        return "wiret 1\nmodule t\n" + body

    def beep_vm(self, capabilities=None):
        from wiret.natives import NativeSpec
        vm = VM(output=lambda s: None, capabilities=capabilities)
        vm.register("host.Beep", NativeSpec([], [], "impure", lambda _vm: (),
                                            capability="audio.play"))
        return vm

    def test_wr_caps_lists_what_the_module_declares(self):
        from wiret.vm import module_capabilities
        _, r = build(self.caps_module())
        self.assertEqual(module_capabilities(r.wbc), ["audio.play", "console.write"])
        self.assertIn("capability audio.play", disassemble(r.wbc))

    def test_a_sandbox_grants_nothing(self):
        _, r = build(self.caps_module())
        vm = self.beep_vm(capabilities=[])
        with self.assertRaises(WiretError) as cm:
            vm.load(r.wbc)
        self.assertEqual(cm.exception.status, "WR_ERR_LINK")
        self.assertIn("'audio.play'", cm.exception.message)
        vm.grant("audio.play")
        vm.grant("console.write")
        mod = vm.load(r.wbc)
        self.assertEqual(mod.capabilities, ["audio.play", "console.write"])

    def test_the_reference_host_grants_what_its_natives_need(self):
        _, r = build(self.caps_module())
        vm = self.beep_vm()            # grants console.write, not the newly registered one
        with self.assertRaises(WiretError) as cm:
            vm.load(r.wbc)
        self.assertIn("'audio.play'", cm.exception.message)
        vm.grant("audio.play")
        vm.call(vm.load(r.wbc), "Hello", [])

    def test_leaving_the_attribute_off_does_not_get_around_a_grant(self):
        text = module("""
func Hello() {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )
}
""", macros=False)                     # host.Log declared without @capability
        _, r = build(text)
        with self.assertRaises(WiretError) as cm:
            VM(capabilities=[]).load(r.wbc)
        self.assertIn("import host.Log needs capability 'console.write'", cm.exception.message)

    def test_e0104_misplaced_or_malformed(self):
        text = self.caps_module("""
extern func host.A() @capability
extern func host.B() @capability(3)
extern func host.C() @capability("x", "y")

func F() @capability("x") {
  node entry = Entry()
}
""")
        diags = [d for d in check(parse(text)) if d.code == "E0104"]
        self.assertEqual(len(diags), 4)

    def test_e0160_when_the_project_does_not_allow_it(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "t.wiret")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.caps_module())
            from wiret.ids import find_project
            m = parse(self.caps_module())
            with open(os.path.join(d, "wiret.toml"), "w", encoding="utf-8") as f:
                f.write('[project]\nname = "t"\n')
            self.assertEqual([x for x in check(m, project=find_project(path))
                              if x.code == "E0160"], [])         # no table: no check
            with open(os.path.join(d, "wiret.toml"), "w", encoding="utf-8") as f:
                f.write('[project]\nname = "t"\n\n[capabilities]\nallow = ["console.write"]\n')
            bad = [x for x in check(m, project=find_project(path)) if x.code == "E0160"]
            self.assertEqual([(x.graph, x.data["capability"]) for x in bad],
                             [("host.Beep", "audio.play")])
            r = compile_module(m, None, project=find_project(path))
            self.assertFalse(r.ok)
        finally:
            shutil.rmtree(d)

    def test_manifest_allow_list_without_tomllib(self):
        from wiret.ids import read_allowed_capabilities
        text = ('[project]\nname = "x"  # a comment\n\n[capabilities]\n'
                'allow = ["console.write", "audio.play"]\n')
        self.assertEqual(read_allowed_capabilities(text), {"console.write", "audio.play"})
        self.assertIsNone(read_allowed_capabilities('[project]\nname = "x"\n'))
        import builtins
        real = builtins.__import__

        def no_tomllib(name, *args, **kw):
            if name == "tomllib":
                raise ImportError
            return real(name, *args, **kw)
        builtins.__import__ = no_tomllib
        try:
            self.assertEqual(read_allowed_capabilities(text), {"console.write", "audio.play"})
            self.assertIsNone(read_allowed_capabilities('[project]\nname = "x"\n'))
        finally:
            builtins.__import__ = real

    def test_cli_sandbox_and_grant(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "t.wiret")
            with open(path, "w", encoding="utf-8") as f:
                f.write(module("""
func Hello() {
  flow {
    entry -> log
  }

  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi",
  )
}
""", macros=False))
            wiretc = os.path.join(os.path.dirname(HERE), "wiretc.py")
            refused = subprocess.run([sys.executable, wiretc, "run", "--sandbox", path, "Hello"],
                                     capture_output=True, text=True)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("console.write", refused.stderr)
            ok = subprocess.run([sys.executable, wiretc, "run", "--sandbox", "--grant",
                                 "console.write", path, "Hello"], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("hi", ok.stdout)
        finally:
            shutil.rmtree(d)


GAPS = """
class Shouter : Ticker {
  func Tick() -> (n: i32) {
    flow {
      entry -> parent
      parent -> ret
    }

    node entry = Entry()
    node parent = CallParent Tick()
    node ret = Return(
      .n <- Mul::<i32>(
        .a <- parent,
        .b <- 10,
      ),
    )
  }
}

class Ticker {
  items: array::<i32>

  func Greet() {
    flow {
      entry -> once
      once -> hi
    }

    node entry = Entry()
    node hi = Call host.Log(
      .message <- "hello",
    )
    node once = Macro std.flow.DoOnce()
  }

  func Keep(x: i32) {
    flow {
      entry -> add
    }

    node add = ArrayAdd::<i32> Ticker.items(
      .obj <- entry.self,
      .item <- entry.x,
    )
    node entry = Entry()
  }

  func Tick() -> (n: i32) {
    state count: i32

    flow {
      entry -> set
      set -> ret
    }

    node entry = Entry()
    node ret = Return(
      .n <- GetState count(),
    )
    node set = SetState count(
      .value <- Add::<i32>(
        .a <- GetState count(),
        .b <- 1,
      ),
    )
  }
}

func Fill(t: Ticker) -> (before: array::<i32>, after: array::<i32>) {
  local snap: array::<i32>

  flow {
    add -> ret
    entry -> keep
    keep -> take
    take -> add
  }

  node add = ArrayAdd::<i32> Ticker.items(
    .obj <- entry.t,
    .item <- 2,
  )
  node entry = Entry()
  node get = GetField Ticker.items(
    .obj <- entry.t,
  ) @live
  node keep = Call Ticker.Keep(
    .self <- entry.t,
    .x <- 1,
  )
  node ret = Return(
    .before <- GetLocal snap(),
    .after <- get,
  )
  node take = SetLocal snap(
    .value <- get,
  )
}
"""


def gaps_text(extra=""):
    return module(GAPS + extra, macros=False)


class ClassGapTests(unittest.TestCase):
    """State on objects, container mutators on fields, and CallParent."""

    def vm_for(self, text=None):
        _, r = build(text or gaps_text())
        out = []
        vm = VM(output=out.append)
        return vm, vm.load(r.wbc), out

    def test_round_trip_and_check(self):
        text = gaps_text()
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual([c for c in codes(text) if c.startswith("E")], [])

    def test_state_in_a_method_lives_on_each_object(self):
        vm, mod, out = self.vm_for()
        a, b = vm.new(mod, "Ticker"), vm.new(mod, "Ticker")
        self.assertEqual([vm.call(mod, "Ticker.Tick", [a])[0] for _ in range(3)], [1, 2, 3])
        self.assertEqual(vm.call(mod, "Ticker.Tick", [b]), [1])
        self.assertEqual((a.get("Tick.count"), b.get("Tick.count")), (3, 1))

    def test_macro_state_in_a_method_is_per_object(self):
        vm, mod, out = self.vm_for()
        a, b = vm.new(mod, "Ticker"), vm.new(mod, "Ticker")
        for o in (a, a, b, a, b):
            vm.call(mod, "Ticker.Greet", [o])
        self.assertEqual(out, ["hello", "hello"])     # once per object

    def test_mutators_change_a_field_in_place_with_value_semantics(self):
        vm, mod, out = self.vm_for()
        t = vm.new(mod, "Ticker")
        # Keep appends 1 through the bare field name; the snapshot taken next keeps (1,)
        # while the qualified ArrayAdd appends 2 to the field
        self.assertEqual(vm.call(mod, "Fill", [t]), [(1,), (1, 2)])

    def test_a_null_object_place_faults(self):
        vm, mod, out = self.vm_for()
        with self.assertRaises(WiretError) as cm:
            vm.call(mod, "Fill", [None])
        self.assertEqual(cm.exception.code, -3)

    def test_call_parent_runs_the_base_version_on_self(self):
        vm, mod, out = self.vm_for()
        s = vm.new(mod, "Shouter")
        self.assertEqual(vm.call_method(mod, s, "Tick", []), [10])
        self.assertEqual(vm.call_method(mod, s, "Tick", []), [20])
        self.assertEqual(s.get("Tick.count"), 2)   # the base method's state, on this object
        _, r = build(gaps_text())
        shout = disassemble(r.wbc).split("func t.Shouter.Tick")[1].split("\nfunc ")[0]
        self.assertIn("call t.Ticker.Tick", shout)
        self.assertNotIn("call_virtual", shout)

    def test_call_parent_needs_an_override(self):
        text = gaps_text("""
func Loose() {
  node entry = Entry()
  node p = CallParent Tick()
}

class Lonely {
  func Tick() -> (n: i32) {
    node entry = Entry()
    node p = CallParent Tick()
  }
}
""")
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("Lonely.Tick", "E0501"), ("Loose", "E0501")])

    def test_pure_functions_cannot_change_fields(self):
        text = gaps_text("""
func P(t: Ticker) @pure {
  node add = ArrayAdd::<i32> Ticker.items(
    .obj <- entry.t,
    .item <- 1,
  )
  node entry = Entry()

  flow {
    entry -> add
  }
}
""")
        self.assertIn("E0302", codes(text))

    def test_parent_event_needs_a_latent_caller(self):
        text = module("""
class A {
  event Go() {
    node entry = Entry()
  }
}

class B : A {
  event Go() {
    flow {
      entry -> p
    }

    node entry = Entry()
    node p = CallParent Go()
  }
}
""", macros=False)
        self.assertEqual([c for c in codes(text) if c.startswith("E")], [])


DET = """
event Countdown() {
  node entry = Entry()
  node go = Call host.Log(
    .message <- "Go!",
  )
  node loop = Macro ForRange(
    .first <- 1,
    .last <- 3,
  )
  node say = Call host.Log(
    .message <- txt.result,
  )
  node txt = Convert::<i32, string>(
    .value <- loop.index,
  )
  node wait = Delay(
    .seconds <- 0.5,
  )

  flow {
    entry -> loop
    loop.done -> go
    loop.each -> say
    say -> wait
  }
}

func Maths(x: f64) -> (s: f64, p: f64, mn: f64, mx: f64, nan_eq: bool) {
  node entry = Entry()
  node max = Max::<f64>(
    .a <- 0.0,
    .b <- neg_zero.result,
  )
  node min = Min::<f64>(
    .a <- 0.0,
    .b <- neg_zero.result,
  )
  node nan = Div::<f64>(
    .a <- 0.0,
    .b <- 0.0,
  )
  node nan_eq = Eq::<f64>(
    .a <- nan.result,
    .b <- nan.result,
  )
  node neg_zero = Neg::<f64>(
    .value <- 0.0,
  )
  node pow = Call std.math.Pow(
    .a <- entry.x,
    .b <- 0.5,
  )
  node ret = Return(
    .s <- sin.result,
    .p <- pow.result,
    .mn <- min.result,
    .mx <- max.result,
    .nan_eq <- nan_eq.result,
  )
  node sin = Call std.math.Sin(
    .x <- entry.x,
  )

  flow {
    entry -> ret
  }
}
"""


class DeterministicTests(unittest.TestCase):
    """Deterministic mode (section 4.10): float rules, bundled std.math, the input log and
    replay."""

    GOLDEN = [("sin", (1.0,), "0x1.aed548f090ceep-1"), ("cos", (1.0,), "0x1.14a280fb5068cp-1"),
              ("tan", (0.5,), "0x1.17b4f5bf3474ap-1"), ("exp", (1.0,), "0x1.5bf0a8b145769p+1"),
              ("log", (10.0,), "0x1.26bb1bbb55516p+1"), ("pow", (2.0, 0.5), "0x1.6a09e667f3bcdp+0"),
              ("atan2", (1.0, 2.0), "0x1.dac670561bb4fp-2"),
              ("sin", (1e22,), "-0x1.b453ab76bf397p-1")]

    def test_bundled_math_golden_vectors(self):
        from wiret import detmath
        for name, args, want in self.GOLDEN:
            with self.subTest(name=name, args=args):
                got = getattr(detmath, name)(*args)
                self.assertEqual(got.hex(), want)
                self.assertLessEqual(abs(got - getattr(math, name)(*args)),
                                     math.ulp(got))      # and within an ulp of libm

    def test_bundled_math_special_values_match_c99(self):
        from wiret import detmath
        same = (lambda a, b: (math.isnan(a) and math.isnan(b))
                or (a == b and math.copysign(1, a) == math.copysign(1, b)))
        vals = [0.0, -0.0, 1.0, -1.0, 2.0, -2.0, 0.5, -3.0, math.inf, -math.inf, math.nan]
        for x in vals:
            for y in vals:
                with self.subTest(x=x, y=y):
                    self.assertTrue(same(detmath.atan2(x, y), math.atan2(x, y)))
                    try:
                        want = math.pow(x, y)
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    self.assertTrue(same(detmath.pow(x, y), want))

    def test_integer_to_f32_rounds_once(self):
        from wiret.vm import _int_to_f32
        from wiret.natives import _f32
        n = 2 ** 62 + 2 ** 38 + 1      # just above an f32 tie; through f64 it lands on it
        self.assertEqual(_int_to_f32(n), 2.0 ** 62 + 2.0 ** 39)
        self.assertEqual(_f32(float(n)), 2.0 ** 62)          # the double rounding avoided
        self.assertEqual(_int_to_f32(-n), -(2.0 ** 62 + 2.0 ** 39))
        self.assertEqual(_int_to_f32(2 ** 24 + 1), 2.0 ** 24)  # a tie goes to even

    def test_nan_bits_are_canonical(self):
        from wiret.vm import NUMERIC
        payload = struct.unpack("<d", struct.pack("<Q", 0xFFF0000000000123))[0]
        to_i64 = NUMERIC[wbc.OPS["i64.reinterpret_f64"][0]][1]
        to_i32 = NUMERIC[wbc.OPS["i32.reinterpret_f32"][0]][1]
        self.assertEqual(to_i64(payload), 0x7FF8000000000000)
        self.assertEqual(to_i32(payload), 0x7FC00000)
        self.assertEqual(to_i64(1.0), 0x3FF0000000000000)

    def test_deterministic_vm_uses_bundled_math_and_float_rules(self):
        _, r = build(module(DET))
        vm = VM(deterministic=True, output=lambda s: None)
        s, p, mn, mx, nan_eq = vm.call(vm.load(r.wbc), "Maths", [1.0])
        self.assertEqual(s.hex(), "0x1.aed548f090ceep-1")
        self.assertEqual(p, 1.0)
        self.assertEqual((math.copysign(1, mn), math.copysign(1, mx)), (-1.0, 1.0))  # -0 < +0
        self.assertEqual(nan_eq, 0)

    def test_nondeterministic_natives_are_refused(self):
        from wiret.natives import NativeSpec
        clock = NativeSpec([], [("t", "f64")], "impure", lambda _vm: (0.0,), deterministic=False)
        VM().register("host.Clock", clock)                  # fine outside the mode
        with self.assertRaises(WiretError) as cm:
            VM(deterministic=True).register("host.Clock", clock)
        self.assertEqual(cm.exception.status, "WR_ERR_LINK")

    def test_record_and_replay_a_run_with_fibers_objects_and_signals(self):
        from wiret.vm import replay
        text = module(DET) + """
class Box {
  n: i32
  dispatcher Changed(n: i32)

  func Set(n: i32) {
    node b = Broadcast Changed(
      .obj <- entry.self,
      .n <- entry.n,
    )
    node entry = Entry()
    node s = SetField n(
      .obj <- entry.self,
      .value <- entry.n,
    )

    flow {
      entry -> s
      s -> b
    }
  }
}

event Wait(s: std.Signal) {
  node entry = Entry()
  node log = Call host.Log(
    .message <- "woken",
  )
  node w = Await(
    .signal <- entry.s,
  )

  flow {
    entry -> w
    w -> log
  }
}
"""
        _, r = build(text)
        out = []
        vm = VM(deterministic=True, output=out.append)
        mod = vm.load(r.wbc)
        vm.start(mod, "Countdown", [], now=True)
        sig = vm.signal()
        vm.start(mod, "Wait", [sig])
        box = vm.new(mod, "Box")
        vm.call_method(mod, box, "Set", [7])
        vm.advance(0.5)
        vm.fire(sig)
        vm.advance(1.0)
        vm.call(mod, "Maths", [2.0])
        with self.assertRaises(WiretError):
            vm.call(mod, "Maths", [1.0, 2.0])              # a fault is logged too
        log = json.loads(json.dumps(vm.input_log))           # the log is plain JSON
        again = replay(r.wbc, log, output=lambda s: None)
        self.assertEqual(again.input_log, log)
        self.assertEqual(sum((e["output"] for e in log), []), out)

    def test_replay_finds_the_first_difference(self):
        from wiret.vm import ReplayMismatch, replay
        _, r = build(module(DET))
        vm = VM(deterministic=True, output=lambda s: None)
        vm.call(vm.load(r.wbc), "Maths", [3.0])
        log = json.loads(json.dumps(vm.input_log))
        log[1]["out"]["a"][0] = {"f": (0.5).hex()}
        with self.assertRaises(ReplayMismatch) as cm:
            replay(r.wbc, log, output=lambda s: None)
        self.assertEqual((cm.exception.index, cm.exception.what), (1, "out"))
        other = build(module(DET.replace("0.5", "0.25")))[1].wbc
        with self.assertRaises(ReplayMismatch) as cm:
            replay(other, vm.input_log)
        self.assertEqual(cm.exception.what, "module")

    def test_values_from_outside_the_api_cannot_be_logged(self):
        from wiret.natives import Signal
        _, r = build(module(DET) + """
event Wait(s: std.Signal) {
  flow {
    entry -> w
  }

  node entry = Entry()
  node w = Await(
    .signal <- entry.s,
  )
}
""")
        vm = VM(deterministic=True, output=lambda s: None)
        mod = vm.load(r.wbc)
        with self.assertRaises(WiretError) as cm:
            vm.start(mod, "Wait", [Signal()])               # not from vm.signal()
        self.assertEqual(cm.exception.status, "WR_ERR_API")

    def test_an_interrupt_makes_the_run_unreplayable(self):
        vm = VM(deterministic=True)
        self.assertTrue(vm.stats["replayable"])
        vm.interrupt()
        self.assertFalse(vm.stats["replayable"])

    def test_cli_record_and_replay(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "t.wiret")
            with open(src, "w", encoding="utf-8") as f:
                f.write(module(DET))
            log = os.path.join(d, "log.json")
            wiretc = os.path.join(os.path.dirname(HERE), "wiretc.py")
            rec = subprocess.run([sys.executable, wiretc, "run", "--deterministic", "--record",
                                  log, src, "Countdown"], capture_output=True, text=True)
            self.assertEqual(rec.returncode, 0, rec.stderr)
            rep = subprocess.run([sys.executable, wiretc, "replay", src, log],
                                 capture_output=True, text=True)
            self.assertEqual(rep.returncode, 0, rep.stderr)
            self.assertIn("same results", rep.stdout)
        finally:
            shutil.rmtree(d)


class BytecodeTests(unittest.TestCase):
    def test_disassembly_names_nodes(self):
        _, r = build(demo())
        text = disassemble(r.wbc)
        self.assertIn(".loop/seq:", text)
        self.assertIn("cont.push .loop/bump", text)
        self.assertIn("call game.demo.Fib", text)

    def test_embedded_source_round_trips(self):
        import zlib
        text = demo()
        _, r = build(text)
        m = wbc.decode_module(r.wbc)
        self.assertTrue(m.flags & wbc.FLAG_HAS_SOURCE)
        self.assertEqual(zlib.decompress(m.custom("wr.graph")).decode(), text)

    def test_verifier_rejects_bad_modules(self):
        _, r = build(demo())
        good = wbc.decode_module(r.wbc)

        def mutate(fn):
            m = wbc.decode_module(r.wbc)
            fn(m)
            with self.assertRaises(WiretError) as cm:
                VM().load(wbc.encode_module(m))
            return cm.exception.status

        def stack_mismatch(m):   # i32.add on a string
            b = m.bodies[0]
            b.code = bytes([0x24, 0x00, 0x24, 0x00, 0x3B, 0x10, 0x05])
        def bad_branch(m):
            m.bodies[0].code = bytes([0x02, 0x7F, 0x7F, 0x7F, 0x7F, 0x0F, 0x05])
        def bad_local(m):
            m.bodies[0].code = bytes([0x12, 0x7F, 0x10, 0x05])
        def falls_off(m):
            m.bodies[0].code = bytes([0x01])
        def suspend(m):
            m.bodies[0].code = bytes([0x0D, 0x00, 0x05])
        for fn in (stack_mismatch, bad_branch, bad_local, falls_off, suspend):
            with self.subTest(fn.__name__):
                self.assertEqual(mutate(fn), "WR_ERR_VERIFY")
        self.assertTrue(good.bodies)

    def test_fuzzed_modules_never_crash_the_loader(self):
        _, r = build(demo())
        rng = random.Random(1234)
        data = bytearray(r.wbc)
        for _ in range(1500):
            d = bytearray(data)
            for _ in range(rng.randint(1, 4)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            if rng.random() < 0.2:
                d = d[:rng.randrange(len(d))]
            try:
                VM().load(bytes(d))
            except WiretError:
                pass

    def test_link_error_for_missing_native(self):
        text = module("""
extern func host.Missing(x: i32)

func F() {
  node entry = Entry()
  node c = Call host.Missing(
    .x <- 1,
  )

  flow {
    entry -> c
  }
}
""", macros=False)
        _, r = build(text)
        with self.assertRaises(WiretError) as cm:
            VM().load(r.wbc)
        self.assertEqual(cm.exception.status, "WR_ERR_LINK")


LESSONS = os.path.join(os.path.dirname(HERE), "lessons")


def lesson(name: str) -> str:
    with open(os.path.join(LESSONS, name), encoding="utf-8") as f:
        return f.read()


class StdFlowTests(unittest.TestCase):
    def test_library_is_canonical_and_clean(self):
        from wiret.registry import STD_FLOW_PATH
        with open(STD_FLOW_PATH, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(print_module(parse(text)), text)
        self.assertFalse([d for d in check(parse(text)) if d.severity == "error"])

    def test_macros(self):
        text = module("""
func Main() {
  node entry = Entry()
  node rep = Macro std.flow.Repeat(
    .times <- 3,
  )
  node flip = Macro std.flow.FlipFlop()
  node log_a = Call host.Log(
    .message <- "A",
  )
  node log_b = Call host.Log(
    .message <- "B",
  )
  node five = Macro std.flow.ForRange(
    .first <- 1,
    .last <- 5,
  )
  node limited = Macro std.flow.DoN(
    .n <- 2,
  )
  node n_text = Convert::<i32, string>(
    .value <- limited.counter,
  )
  node log_n = Call host.Log(
    .message <- n_text.result,
  )

  flow {
    entry -> rep
    rep.body -> flip
    rep.done -> five
    flip.a -> log_a
    flip.b -> log_b
    five.each -> limited
    limited.out -> log_n
  }
}
""", macros=False)
        self.assertEqual(run(text, "Main")[1], ["B", "A", "B", "1", "2"])


from wiret.runner import run_function  # noqa: E402


class LessonTests(unittest.TestCase):
    EXPECTED = {
        "01_hello.wiret": ["Hello!", "Programs run one step at a time.",
                           "The white arrows decide the order."],
        "02_variables.wiret": ["Your score is 15"],
        "03_decisions.wiret": ["12 is a child.", "30 is an adult.", "18 is an adult."],
        "04_loops.wiret": [f"Counting: {i}" for i in range(1, 6)] + ["Total: 15"],
        "05_functions.wiret": [f"{i} squared is {i * i}" for i in range(1, 6)],
        "06_fizzbuzz.wiret": ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz",
                              "11", "Fizz", "13", "14", "FizzBuzz"],
        "07_arrays.wiret": ["Item 0 is 12", "Item 1 is 30", "Item 2 is 7", "Item 3 is 25",
                            "4 scores, total 74"],
        "08_structs.wiret": ["Rex is happy.", "Rex is hungry."],
        "09_maps.wiret": ["apple: 2", "pear: 1", "kiwi: 1", "3 different fruits"],
        "10_errors.wiret": ["Each gets 3", "Oops: integer divide by zero",
                            "Oops: An age can't be negative", "Still running!"],
        "11_waiting.wiret": ["3...", "2...", "1...", "Go!"],
        "12_objects.wiret": ["Rex makes a sound. Woof!", "Tom says Meow.",
                             "An animal makes a sound."],
        "13_interfaces.wiret": ["Rectangle: area 12", "Square: area 25", "Triangle: area 6"],
        "14_events.wiret": ["Click number 1", "Click number 2", "The counter heard 3 clicks"],
    }

    def test_reset_all_removes_only_lesson_copies(self):
        from wiret.editor import remove_lesson_copies
        d = tempfile.mkdtemp()
        try:
            for name in ("01_hello.wiret", "12_objects.wiret", "mine.wiret"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write("x")
            names = sorted(f for f in os.listdir(LESSONS) if f.endswith(".wiret"))
            self.assertEqual(remove_lesson_copies(names, d), 2)
            self.assertEqual(os.listdir(d), ["mine.wiret"])
        finally:
            shutil.rmtree(d)

    def test_code_font_is_monospace(self):
        import tkinter as tk
        from tkinter import font as tkfont
        from wiret.editor import pick_mono
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display for Tk")
        try:
            root.withdraw()
            family, size = pick_mono(root)
            f = tkfont.Font(root=root, family=family, size=size)
            self.assertEqual(f.measure("iiii"), f.measure("WWWW"))
        finally:
            root.destroy()

    def test_lessons(self):
        names = sorted(f for f in os.listdir(LESSONS) if f.endswith(".wiret"))
        self.assertEqual(names, sorted(self.EXPECTED))
        for name in names:
            with self.subTest(name):
                text = lesson(name)
                m = parse(text)
                self.assertEqual(print_module(m), text, "not canonical")
                self.assertEqual([str(d) for d in check(m)], [])
                _, r = build(text)
                out = []
                vm = VM(output=out.append)
                run_function(vm, vm.load(r.wbc), "Main", [])   # Main may be an event
                self.assertEqual(out, self.EXPECTED[name])
                for g in m.graphs():
                    self.assertTrue(notes(g.meta), f"{g.name} has no intro")
                    placed = {p.id for p in g.places}
                    self.assertEqual(placed, {n.id for n in g.nodes}, f"{g.name} layout")


class DebuggerTests(unittest.TestCase):
    def test_ready_points_show_fresh_inputs(self):
        m = parse(demo())
        r = compile_module(m, debug=True)
        seen = []

        def hook(f, node, pending, depth, snapshot, phase):
            if phase == "ready" and f.endswith("SumTo") and node == "add":
                v = snapshot()[-1].pin_values()
                seen.append((v[("add.value.a", "value")], v[("loop", "index")],
                             v[("add.value", "result")]))
        vm = VM(hook=hook)
        self.assertEqual(vm.call(vm.load(r.wbc), "SumTo", [3]), [6])
        self.assertEqual(seen, [(0, 1, 1), (1, 2, 3), (3, 3, 6)])

    def test_call_stack_and_locals(self):
        r = compile_module(parse(lesson("05_functions.wiret")), debug=True)
        stacks = []

        def hook(f, node, pending, depth, snapshot, phase):
            if phase == "ready" and f.endswith("Square") and node == "ret":
                frames = snapshot()
                stacks.append(([fr.func.name.split(".")[-1] for fr in frames],
                               frames[-1].named_locals()["x"]))
        vm = VM(hook=hook, output=lambda s: None)
        vm.call(vm.load(r.wbc), "Main", [])
        self.assertEqual(stacks[0], (["Main", "Square"], 1))
        self.assertEqual([x for _, x in stacks], [1, 2, 3, 4, 5])

    def test_debug_build_runs_the_same(self):
        for debug in (False, True):
            m = parse(lesson("06_fizzbuzz.wiret"))
            r = compile_module(m, debug=debug)
            out = []
            vm = VM(output=out.append)
            vm.call(vm.load(r.wbc), "Main", [])
            self.assertEqual(out, LessonTests.EXPECTED["06_fizzbuzz.wiret"])


class ExplainTests(unittest.TestCase):
    def test_every_diagnostic_has_a_plain_explanation(self):
        from wiret.explain import explain
        for code, body in DiagnosticTests.CASES.items():
            with self.subTest(code=code):
                text = module(f"\nfunc F() -> (y: i32) {{\n  {body}\n}}\n", macros=False)
                m = parse(text)
                diags = compile_module(m).diags if code == "W0302" else check(m)
                d = next(d for d in diags if d.code == code)
                friendly = explain(d)
                self.assertNotEqual(friendly, d.message)
                self.assertNotIn(code, friendly)

    def test_type_mismatch_names_both_types(self):
        from wiret.explain import explain
        text = module("""
func F() {
  node entry = Entry()
  node n = Add::<i32>(
    .a <- 1,
    .b <- 2,
  )
  node log = Call host.Log(
    .message <- n.result,
  )

  flow {
    entry -> log
  }
}
""", macros=False)
        d = next(d for d in check(parse(text)) if d.code == "E0110")
        self.assertIn("text (string)", explain(d))
        self.assertIn("whole number (i32)", explain(d))
        self.assertIn("Convert", explain(d))

    def test_runtime_errors(self):
        from wiret.explain import explain_runtime
        self.assertIn("divide by zero", explain_runtime("WR_ERR_FAULT", "integer divide by zero"))
        self.assertIn("loop never", explain_runtime("WR_ERR_FUEL", "fuel exhausted"))
        self.assertIn("Sequence", explain_runtime("WR_ERR_FAULT", "continuation stack overflow"))
        self.assertIn("base case", explain_runtime("WR_ERR_FAULT", "stack overflow"))


class PaletteTests(unittest.TestCase):
    def setUp(self):
        from wiret.registry import ModuleIndex
        self.m = parse(demo())
        self.g = self.m.graph("Main")
        self.idx = ModuleIndex(self.m)

    def test_search_finds_beginner_words(self):
        from wiret import palette
        items = palette.items(self.g, self.idx)
        self.assertEqual(len(items), len({i.label for i in items}))
        top = lambda q: palette.rank(items, q)[0]
        self.assertEqual(top("if").kind, "Branch")
        self.assertEqual(top("print").symbol, "host.Log")
        self.assertEqual(top("loop").symbol, "std.flow.ForRange")
        self.assertEqual(top("add").label, "Add::<i32>")

    def test_wire_drop_filters_and_ranks(self):
        from wiret import palette
        items = palette.items(self.g, self.idx)
        fits = [i for i in items if palette.compatible(i, self.g, self.idx, "out", "i32")]
        self.assertTrue(all(palette.compatible(i, self.g, self.idx, "out", "i32") for i in fits))
        self.assertNotIn("Call host.Log", [i.label for i in fits])
        self.assertEqual(palette.rank(fits, "text")[0].label, "Convert::<i32, string> (to text)")
        execs = [i for i in items if palette.compatible(i, self.g, self.idx, "out", "exec")]
        self.assertIn("Branch", [i.kind for i in execs])
        self.assertNotIn("Add", [i.kind for i in execs])



class WebApiTests(unittest.TestCase):
    """wiret.webapi, the JSON calls the browser version makes through Pyodide."""

    def test_runs_every_lesson(self):
        from wiret import webapi
        for name in sorted(n for n in os.listdir(LESSONS) if n.endswith(".wiret")):
            with self.subTest(lesson=name):
                with open(os.path.join(LESSONS, name), encoding="utf-8") as f:
                    r = json.loads(webapi.run(f.read()))
                self.assertTrue(r["ok"], r)
                self.assertTrue(r["output"])

    def test_reports_parse_and_check_errors(self):
        from wiret import webapi
        r = json.loads(webapi.run("wiret 1\nmodule x\nfunc Main( {"))
        self.assertFalse(r["ok"])
        self.assertEqual((r["diags"][0]["code"], r["diags"][0]["line"]), ("parse", 3))
        r = json.loads(webapi.run("wiret 1\nmodule x\nfunc Main() {\n  node e = Entry()\n"
                                  "  node n = Nope\n  flow { e -> n }\n}\n"))
        self.assertFalse(r["ok"])
        self.assertTrue(any(d["severity"] == "error" for d in r["diags"]))

    def test_bundle_leaves_out_tkinter(self):
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
        try:
            import build_web
        finally:
            sys.path.pop(0)
        names = {arc for _, arc in build_web.files()}
        self.assertIn("wiret/webapi.py", names)
        self.assertIn("wiret/std/flow.wiret", names)
        self.assertIn("lessons/01_hello.wiret", names)
        self.assertFalse(names & {"wiret/editor.py", "wiret/graphview.py", "wiret/palettepopup.py"})
        self.assertIn("wiret/palette.py", names)
        self.assertIn("wiret/debugstate.py", names)

    def test_site_holds_only_what_the_page_serves(self):
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
        try:
            import build_web
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                build_web.main(["--site", tmp])
            self.assertEqual(sorted(os.listdir(tmp)),
                             ["debugger.js", "graphview.js", "index.html", "syntax.js", "wiret_bundle.zip"])
            with zipfile.ZipFile(os.path.join(tmp, "wiret_bundle.zip")) as z:
                self.assertIn("wiret/webapi.py", z.namelist())
        # every file the page loads is in the site
        with open(os.path.join(os.path.dirname(HERE), "web", "index.html"), encoding="utf-8") as f:
            page = f.read()
        for name in re.findall(r'from "\./([^"]+)"|fetch\("([^"]+)"\)', page):
            self.assertIn(next(n for n in name if n), build_web.SITE_FILES + [build_web.BUNDLE])

    def test_site_is_stamped_with_one_build_id(self):
        """The published page, its script URLs and its bundle all carry the same build id, so a
        browser cannot pair a new page with a script or bundle cached from an older deploy."""
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
        try:
            import build_web
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                build_web.main(["--site", tmp])
            with open(os.path.join(tmp, "index.html"), encoding="utf-8") as f:
                page = f.read()
            with zipfile.ZipFile(os.path.join(tmp, "wiret_bundle.zip")) as z:
                bundle_build = z.read("BUILD").decode().strip()
        build = re.search(r'const BUILD = "([0-9a-f]{12})";', page).group(1)
        self.assertEqual(bundle_build, build)
        self.assertEqual(build, build_web.build_id())
        refs = re.findall(r'from "\./([^"?]+)\?v=(\w+)"|fetch\("([^"?]+)\?v=(\w+)"\)', page)
        self.assertEqual(sorted(a or c for a, _, c, _ in refs),
                         sorted([n for n in build_web.SITE_FILES if n.endswith(".js")] + [build_web.BUNDLE]))
        self.assertEqual({b or d for _, b, _, d in refs}, {build})
        self.assertNotRegex(page, r'from "\./[^"?]+"|fetch\("[^"?]+"\)')    # nothing left unversioned
        # the page in web/ itself stays "dev", which skips the check
        with open(os.path.join(os.path.dirname(HERE), "web", "index.html"), encoding="utf-8") as f:
            self.assertIn('const BUILD = "dev";', f.read())
        # a page that changed shape is refused, rather than published half-stamped
        with self.assertRaises(SystemExit):
            build_web.stamp(page.replace('const BUILD = "', 'const BUILD_ID = "'), build)

    def test_check_maps_nodes_to_lines(self):
        from wiret import webapi
        text = lesson("05_functions.wiret")
        r = json.loads(webapi.check(text))
        self.assertEqual(r["diags"], [])
        lines = text.split("\n")
        for g, nodes in r["nodes"].items():
            for nid, info in nodes.items():
                if "." in nid:            # an inline node: the line of the input it feeds
                    pin = nid.rsplit(".", 1)[1]
                    self.assertRegex(lines[info["line"] - 1], rf"^\s*\.{pin} <- {info['what']}\b")
                else:
                    self.assertRegex(lines[info["line"] - 1], rf"^\s*node {nid} = ")
        self.assertEqual(r["nodes"]["Square"]["ret"]["what"], "Return")

    def test_debug_run_records_frames_and_values(self):
        from wiret import webapi
        text = lesson("05_functions.wiret")
        r = json.loads(webapi.debug_run(text))
        self.assertTrue(r["ok"])
        self.assertEqual(r["output"], json.loads(webapi.run(text))["output"])
        self.assertFalse(r["truncated"])
        rets = [s for s in r["steps"] if (s["graph"], s["node"], s["phase"]) == ("Square", "ret", "ready")]
        self.assertEqual(len(rets), 5)
        frames = [[r["frame_table"][i] for i in s["frames"]] for s in rets]
        self.assertEqual([(f["graph"], f["node"]) for f in frames[0]],
                         [("Main", "say.message.b.value"), ("Square", "ret")])
        self.assertEqual([f[-1]["vars"] for f in frames][:2],
                         [[["x", "parameter", "i32", "1"]], [["x", "parameter", "i32", "2"]]])
        self.assertEqual([s["depth"] for s in rets], [1] * 5)
        self.assertEqual(r["counts"]["Square"]["ret"], 5)
        # the output a step had seen grows as the run goes on
        self.assertEqual([s["out"] for s in rets], [0, 1, 2, 3, 4])

    def test_debug_run_fault_and_truncation(self):
        from wiret import webapi
        text = (lesson("02_variables.wiret").replace(".value <- Add::<i32>(", ".value <- Div::<i32>(")
                .replace(".b <- 5", ".b <- 0"))
        r = json.loads(webapi.debug_run(text))
        self.assertFalse(r["ok"])
        self.assertEqual(r["fault"], {"graph": "Main", "node": "bonus.value"})
        self.assertIn("divide by zero", r["explain"])
        r = json.loads(webapi.debug_run(lesson("06_fizzbuzz.wiret"), max_steps=10))
        self.assertTrue(r["ok"] and r["truncated"])
        self.assertEqual(len(r["steps"]), 10)
        self.assertEqual(len(r["output"]), 15)              # the run itself went on to the end
        self.assertEqual(sum(r["counts"]["Main"].values()) > 10, True)

    def test_check_describes_graphs_for_drawing(self):
        from wiret import webapi
        r = json.loads(webapi.check(lesson("04_loops.wiret")))
        (main,) = r["graphs"]
        nodes = {n["id"]: n for n in main["nodes"]}
        self.assertEqual((nodes["count"]["x"], nodes["count"]["y"]), (200, 0))
        self.assertEqual([p["label"] for p in nodes["count"]["ins"]],
                         ["", "break", "first = 1", "last = 5"])
        self.assertEqual([p["name"] for p in nodes["count"]["outs"]], ["each", "done", "index"])
        self.assertTrue(nodes["count"]["outs"][0]["exec"] and nodes["count"]["outs"][0]["filled"])
        self.assertIn({"exec": True, "from": ["count", "each"], "to": ["say", "in"], "color": "#f0f0f0"},
                      main["wires"])
        self.assertIn({"exec": False, "from": ["keep.value", "result"], "to": ["keep", "value"], "color": "#1abc9c"},
                      main["wires"])
        self.assertTrue(nodes["keep.value"]["pure"])
        self.assertEqual(nodes["entry"]["header"], "#a93226")
        self.assertTrue(any(n["on"] is None and "Loops" in n["text"] for n in main["notes"]))
        r = json.loads(webapi.check(lesson("05_functions.wiret")))
        squared = next(n for g in r["graphs"] if g["name"] == "Main" for n in g["nodes"]
                       if n["id"] == "say.message.b.value")
        self.assertEqual(squared["opens"], "Square")

    def test_check_marks_problem_nodes_and_lays_out_new_ones(self):
        from wiret import webapi
        text = lesson("02_variables.wiret").replace(".b <- 5", '.b <- "x"')
        text = text.replace("  node show = Call host.Log(", "  node extra = Add::<i32>()\n  node show = Call host.Log(")
        r = json.loads(webapi.check(text))
        nodes = {n["id"]: n for n in r["graphs"][0]["nodes"]}
        self.assertEqual(nodes["bonus.value"]["diag"], "error")
        self.assertIsNone(nodes["start"]["diag"])
        # a node without a place line is laid out automatically, and stays put on the next check
        first = (nodes["extra"]["x"], nodes["extra"]["y"])
        again = {n["id"]: n for n in json.loads(webapi.check(text + "\n"))["graphs"][0]["nodes"]}
        self.assertEqual((again["extra"]["x"], again["extra"]["y"]), first)

    def edit(self, source, graph, **req):
        from wiret import webapi
        return json.loads(webapi.edit(source, graph, json.dumps(req)))

    def test_edit_values(self):
        from wiret import webapi
        text = lesson("02_variables.wiret")
        r = self.edit(text, "Main", op="literal", node="bonus.value", pin="b", text="100")
        self.assertTrue(r["ok"])
        self.assertIn(".b <- 100", r["text"])
        self.assertEqual(r["text"], print_module(parse(r["text"])))          # canonical
        self.assertEqual(self.edit(text, "Main", op="literal", node="bonus.value", pin="b", text="1.5"),
                         {"ok": False, "message": "1.5 is not a valid i32"})
        r = self.edit(text, "Main", op="literal", node="bonus.value", pin="b", text="")
        self.assertNotIn(".b <-", r["text"].split("node bonus")[1].split("node entry")[0])
        self.assertEqual(json.loads(webapi.literal_prompt(text, "Main", "bonus.value", "b")),
                         {"type": "i32", "current": "5", "hint": ""})
        # a string needs no quotes
        r = self.edit(text, "Main", op="literal", node="show.message", pin="a", text='Score: "big"')
        self.assertIn('.a <- "Score: \\"big\\""', r["text"])
        # an enum member needs no type name, and must be a member
        pets = lesson("08_structs.wiret")
        g = next(g["name"] for g in json.loads(webapi.check(pets))["graphs"]
                 if any(n["id"] == "save.value" for n in g["nodes"]))
        self.assertIn("Happy, Hungry, Sleepy", json.loads(webapi.literal_prompt(pets, g, "save.value", "value"))["hint"])
        self.assertIn(".value <- Mood::Sleepy", self.edit(pets, g, op="literal", node="save.value", pin="value", text="Sleepy")["text"])
        self.assertIn("not a member of Mood", self.edit(pets, g, op="literal", node="save.value", pin="value", text="Bored")["message"])
        self.assertIn("has no typed value", self.edit(pets, g, op="literal", node="save.value", pin="obj", text="1")["message"])
        # a bool flips
        r = self.edit(lesson("03_decisions.wiret"), "CheckAge", op="disconnect", node="decide", dir="in", pin="cond")
        r = self.edit(r["text"], "CheckAge", op="toggle", node="decide", pin="cond")
        self.assertIn(".cond <- true", r["text"])
        r = self.edit(r["text"], "CheckAge", op="toggle", node="decide", pin="cond")
        self.assertEqual(r["message"], "Set decide.cond = false")
        self.assertNotIn(".cond <-", r["text"])          # false is cond's default, so it is not written
        self.assertIn(".cond <- true", self.edit(r["text"], "CheckAge", op="toggle", node="decide", pin="cond")["text"])

    def test_edit_wires(self):
        text = lesson("02_variables.wiret")
        # an i32 into a string input: a visible Convert node goes in between, and is selected
        now = "show.message.b.value"
        r = self.edit(text, "Main", op="connect", a=["show", "in", "message"], b=[now, "out", "value"],
                      geoms={now: [440, 420, 120], "show": [980, 0, 150]})
        conv = r["select"]
        self.assertTrue(r["ok"])
        self.assertEqual(conv, "show.message")                 # written inline in show.message
        self.assertIn("    .message <- Convert::<i32, string>(\n"
                      "      .value <- show_message_b_value,\n    ),\n", r["text"])
        self.assertIn(f"{conv} at (710, 250)", r["text"])       # x: (440 + 120 + 980) / 2 - 60
        refused = {
            "Connect an output pin to an input pin.": (["bonus.value", "out", "result"], [now, "out", "value"]),
            "A node cannot be wired to itself.": (["bonus.value", "out", "result"], ["bonus.value", "in", "a"]),
            "Exec pins connect only to exec pins (E0120).": (["start", "out", "then"], ["bonus.value", "in", "a"]),
        }
        for message, (a, b) in refused.items():
            self.assertEqual(self.edit(text, "Main", op="connect", a=a, b=b), {"ok": False, "message": message})
        r = self.edit(text, "Main", op="connect", a=["start", "out", "then"], b=["show", "in", "in"])
        self.assertIn("start -> show", r["text"])
        self.assertNotIn("start -> bonus", r["text"])
        r = self.edit(r["text"], "Main", op="disconnect", node="start", dir="out", pin="then")
        self.assertNotIn("start ->", r["text"])
        # dropped on a node: the first free input of the same type
        old = "bonus.value.a"
        self.assertEqual(self.edit(text, "Main", op="connect_to_node", a=[old, "out", "value"], node="bonus.value"),
                         {"ok": False, "message": ""})                    # both inputs are taken
        freed = self.edit(text, "Main", op="literal", node="bonus.value", pin="b", text="")["text"]
        r = self.edit(freed, "Main", op="connect_to_node", a=[old, "out", "value"], node="bonus.value")
        self.assertEqual(r["message"], "Bound bonus.value.b = bonus.value.a.value")
        # now read twice, the GetLocal is declared under a name of its own
        self.assertIn("      .a <- bonus_value_a,\n      .b <- bonus_value_a,\n", r["text"])
        r = self.edit(text, "Main", op="disconnect", node="bonus.value", dir="out", pin="result")
        self.assertIn("  node bonus = SetLocal score()\n", r["text"])
        self.assertIn("  node bonus_value = Add::<i32>(\n", r["text"])

    def test_edit_move_delete_and_comments(self):
        text = lesson("02_variables.wiret")
        r = self.edit(text, "Main", op="move", moves=[["entry", 10.6, -20.2]])
        self.assertIn("entry at (11, -20)", r["text"])
        r = self.edit(text, "Main", op="delete", node="show.message.b")
        self.assertEqual(r["message"], "Deleted show.message.b and 1 wire(s): "
                                       "show.message.b.result -> show.message.b")
        self.assertIn('detached: "show.message.b"', r["text"])        # its note is kept
        self.assertEqual(self.edit(text + "garbage(", "Main", op="move", moves=[]),
                         {"ok": False, "message": "Fix the parse error in the source before editing the graph."})
        # a node without a place line gets one where it was drawn
        unplaced = text.replace("    entry at (0, 0)\n", "")
        r = self.edit(unplaced, "Main", op="move", moves=[["start", 200, 0]])
        self.assertRegex(r["text"], r"entry at \(-?\d+, -?\d+\)")
        # a // comment directly above a statement is kept through an edit
        kept = text.replace("  node entry = Entry()\n", "  // the start\n  node entry = Entry()\n")
        r = self.edit(kept, "Main", op="move", moves=[["entry", 1, 1]])
        self.assertIn("  // the start\n  node entry = Entry()\n", r["text"])
        # one attached to nothing cannot be kept: ask first, then convert it to a note
        commented = text.replace("func Main() {", "func Main() {\n  // keep me\n")
        self.assertEqual(self.edit(commented, "Main", op="move", moves=[["entry", 1, 1]]),
                         {"ok": False, "comments": 1})
        r = self.edit(commented, "Main", op="move", moves=[["entry", 1, 1]], comments="convert")
        self.assertIn('#[note("keep me")]', r["text"])

    def test_canvas_edits_match_the_desktop(self):
        """The desktop editor makes its canvas edits through canvasedit too."""
        import inspect
        from wiret import editor
        for method in ("connect", "connect_to_node", "disconnect", "edit_literal"):
            self.assertIn("canvasedit.", inspect.getsource(getattr(editor.EditorApp, method)))

    def test_palette_search_and_add(self):
        from wiret import palette, webapi
        from wiret.registry import ModuleIndex
        text = lesson("02_variables.wiret")
        r = json.loads(webapi.palette(text, "Main", "mul"))
        self.assertEqual(r["items"][0]["label"], "Mul::<i32>")
        self.assertEqual(r["items"][0]["description"], "Multiplies: a × b.")
        # the same ranking as the desktop palette
        m = parse(text)
        idx = ModuleIndex(m)
        desktop = [it.label for it in palette.rank(palette.items(m.graph("Main"), idx), "mul")]
        self.assertEqual([it["label"] for it in r["items"]], desktop[:200])
        self.assertEqual(r["total"], len(palette.items(m.graph("Main"), idx)))
        # from a dragged pin: only what fits it
        r = json.loads(webapi.palette(text, "Main", "", json.dumps(["show", "in", "message"])))
        self.assertEqual(r["title"], "Add a node for show.message (text (string))")
        self.assertIn("Call std.string.Concat", [it["label"] for it in r["items"]])
        self.assertNotIn("Mul::<i32>", [it["label"] for it in r["items"]])
        self.assertEqual(webapi.palette(text, "Main", "", json.dumps(["show", "in", "nope"])), "null")
        self.assertEqual(webapi.palette(text + "(", "Main"), "null")
        # adding: at the point given, and wired to the dragged pin (a producer goes to its left)
        r = self.edit(text, "Main", op="add", kind="Mul", symbol=None, targs=["i32"], x=10, y=20)
        self.assertEqual(r["message"], f"Added {r['select']}")
        self.assertIn(f"node {r['select']} = Mul::<i32>", r["text"])
        self.assertIn(f"{r['select']} at (10, 20)", r["text"])
        r = self.edit(text, "Main", op="add", kind="Call", symbol="std.string.Concat", targs=[],
                      x=500, y=300, context=["show", "in", "message"])
        new = r["select"]
        self.assertEqual(new, "show.message")
        self.assertEqual(r["message"], f"Bound show.message = {new}.result")
        self.assertIn(f"{new} at (300, 300)", r["text"])
        r = self.edit(text, "Main", op="add", kind="Branch", symbol=None, targs=[], x=300, y=200,
                      context=["start", "out", "then"])
        self.assertIn(f"start -> {r['select']}", r["text"])

    def test_graph_nodes_carry_descriptions(self):
        from wiret import webapi
        nodes = {n["id"]: n for n in json.loads(webapi.check(lesson("02_variables.wiret")))["graphs"][0]["nodes"]}
        self.assertEqual(nodes["bonus.value"]["description"], "Adds two numbers: a + b.")

    def menu(self, source, graph, **target):
        from wiret import webapi
        return json.loads(webapi.menu(source, graph, json.dumps(target)))

    @staticmethod
    def labels(entries):
        return ["---" if e.get("sep") else f"[{e['label']}]" if e.get("header") else e["label"]
                for e in entries]

    def test_menus_follow_the_desktop(self):
        pets = lesson("08_structs.wiret")
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="save.value", dir="in", pin="value")),
                         ["[Set 'value' to]", "Mood::Happy", "Mood::Hungry", "Mood::Sleepy", "Disconnect",
                          "---", "[save.value  (WithField)]", "Breakpoint  (F9)", "Label…",
                          "Colour…", "Add note…", "Disable (@disabled)", "---", "Delete node"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="save.value", dir="in", pin="obj"))[:2],
                         ["Make a Pet for 'obj'", "Disconnect"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="start.value", dir="out", pin="result"))[:2],
                         ["Break 'result' into fields", "Disconnect"])
        name = self.menu(pets, "Main", kind="pin", node="start.value", dir="in", pin="name")[0]
        self.assertEqual(name, {"label": "Set literal for 'name'…", "client": "editPin", "node": "start.value",
                                "pin": "name"})
        self.assertIn("Rename id…", self.labels(self.menu(pets, "Main", kind="node", node="save")))
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="canvas", x=5, y=6)),
                         ["Search nodes…   (Tab)", "---", "Add box here…", "Add graph note…", "Add local…"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="wire", wire="d|save|value")), ["Delete wire"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="note", note="save.value|0")), ["Edit note…", "Delete note"])
        entry = self.menu(pets, "Main", kind="node", node="entry")
        self.assertNotIn("Disable (@disabled)", self.labels(entry))
        self.assertEqual(entry[-1]["confirm"], "Delete the graph's Entry node?")
        calls = self.labels(self.menu(lesson("05_functions.wiret"), "Main", kind="node", node="say.message.b.value"))
        self.assertIn("Open Square", calls)
        self.assertEqual(self.menu(pets, "Main", kind="node", node="gone"), [])
        self.assertEqual(self.menu(pets + "(", "Main", kind="canvas"), [])

    def test_menu_actions(self):
        import re
        pets = lesson("08_structs.wiret")
        # each entry's action, with the text the page asked for, is an edit request
        def run(target, label, text=None, source=pets, **extra):
            e = next(e for e in self.menu(source, "Main", **target) if e.get("label") == label)
            req = {**e["action"], **extra}
            if text is not None:
                req["text"] = text
            return self.edit(source, "Main", **req)
        node = {"kind": "node", "node": "start.value"}
        self.assertIn(".value <- Mood::Sleepy", run({"kind": "pin", "node": "save.value", "dir": "in", "pin": "value"}, "Mood::Sleepy")["text"])
        r = run({"kind": "pin", "node": "save.value", "dir": "in", "pin": "obj"}, "Make a Pet for 'obj'", geoms={"save.value": [300, 0, 150]})
        self.assertEqual(r["select"], "save.value.obj")
        self.assertIn("      .obj <- MakeStruct Pet(),\n", r["text"])
        self.assertIn(f"{r['select']} at (80, 0)", r["text"])
        r = run({"kind": "pin", "node": "start.value", "dir": "out", "pin": "result"}, "Break 'result' into fields", geoms={"start.value": [0, 160, 120]})
        self.assertIn(f"{r['select']} at (180, 160)", r["text"])
        r = run({"kind": "node", "node": "save"}, "Rename id…", "store")
        self.assertEqual((r["message"], r["select"]), ("Renamed save to store", "store"))
        self.assertEqual(run({"kind": "node", "node": "save"}, "Rename id…", "2x"),
                         {"ok": False, "message": "Not a valid identifier."})
        self.assertIn("Rename", self.edit(pets, "Main", op="rename", node="start.value", text="build")["message"] + "Rename")
        self.assertFalse(self.edit(pets, "Main", op="rename", node="start.value", text="build")["ok"])
        self.assertIn('[label = "Feed"]', run(node, "Label…", "Feed")["text"])
        self.assertIn('color = "#C0392B"', run(node, "Colour…", "#c0392b")["text"])
        self.assertEqual(run(node, "Colour…", "red")["message"], "Use the form #RRGGBB.")
        # a semantic attribute makes the node a declared one
        self.assertIn('  node start_value = MakeStruct Pet(\n    .name <- "Rex",\n  ) @disabled\n',
                      run(node, "Disable (@disabled)")["text"])
        self.assertIn('#[note("Hi")]\n    start.value at (', run(node, "Add note…", "Hi")["text"])
        r = run({"kind": "canvas", "x": 10, "y": 20}, "Add box here…", "Pets", member="start.value")
        self.assertRegex(r["text"], r'box box_\w+ "Pets" at \(10, 20\) size \(360, 220\) \[members = \[start\.value\]\]')
        bid = re.search(r"box (box_\w+)", r["text"]).group(1)
        box = {"kind": "box", "box": bid}
        self.assertIn("size (500, 300)", run(box, "Resize…", "500, 300", source=r["text"])["text"])
        self.assertEqual(run(box, "Resize…", "big", source=r["text"])["message"], "Enter the width and height, as in 360, 220.")
        self.assertIn(f'box {bid} "Cats"', run(box, "Rename title…", "Cats", source=r["text"])["text"])
        self.assertIn("[members = [entry, start.value]]",
                      run(box, "Edit members…", "entry, start.value", source=r["text"])["text"])
        self.assertIn("local count: i32", run({"kind": "canvas"}, "Add local…", "count: i32")["text"])
        self.assertIn("Use a valid name", run({"kind": "canvas"}, "Add local…", "x: Nope")["message"])
        self.assertIn('#[note("Short")]', run({"kind": "note", "note": "save.value|0"}, "Edit note…", "Short")["text"])
        self.assertNotIn("WithField makes a copy", run({"kind": "note", "note": "save.value|0"}, "Delete note")["text"])

    def test_menu_counts_and_cases(self):
        text = """wiret 1
module m

extern func host.Log(message: string)

enum Mode {
  Idle
  Chase
}

func Main() {
  node entry = Entry()
  node seq = Sequence()
  node sw = Switch::<Mode>()
  flow {
    entry -> seq
  }
}
"""
        seq = self.menu(text, "Main", kind="node", node="seq")
        e = next(e for e in seq if e["label"] == "Set output count (@count)…")
        self.assertEqual(e["ask"], {"label": "Number of outputs:", "value": "2"})
        r = self.edit(text, "Main", **{**e["action"], "text": "3"})
        self.assertIn("node seq = Sequence() @count(3)", r["text"])
        self.assertEqual(self.edit(text, "Main", **{**e["action"], "text": "99"})["message"],
                         "Enter a whole number from 1 to 64.")
        e = next(e for e in self.menu(text, "Main", kind="node", node="sw") if e["label"] == "Set cases (@cases)…")
        self.assertEqual(e["ask"]["label"], "Mode members, comma separated (one of: Idle, Chase):")
        self.assertIn("@cases(Mode::Idle, Mode::Chase)", self.edit(text, "Main", **{**e["action"], "text": "Idle, Chase"})["text"])

    def test_web_highlighting_matches_desktop(self):
        """web/syntax.js colours every line as the desktop editor does (wiret/syntax.py)."""
        import shutil
        from wiret import syntax, webapi
        node = shutil.which("node")
        if node is None:
            self.skipTest("needs Node.js to run web/syntax.js")
        self.assertEqual(json.loads(webapi.syntax()), json.loads(json.dumps(syntax.rules())))
        lines = []
        for name in sorted(os.listdir(LESSONS)):
            if name.endswith(".wiret"):
                lines += lesson(name).split("\n")
        lines += demo().split("\n")
        lines += ['  .a <- "say \\"hi\\" // not a comment"', "  // a comment with \"quotes\" and 12",
                  "  .b <- -3.5e2", "node n = Add::<i32>() @pure", '#[note("x")]', "  .s <- \"unfinished",
                  "var x: i32 = 0x1F", "]"]
        expect = [[list(s) for s in syntax.spans(line)] for line in lines]
        self.assertGreater(sum(map(len, expect)), 1500)
        js = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { makeHighlighter } = await import(pathToFileURL(process.argv[1]).href);
const { rules, lines } = JSON.parse(readFileSync(process.argv[2], "utf8"));
const hl = makeHighlighter(rules);
process.stdout.write(JSON.stringify({ spans: lines.map(hl.spans), html: hl.html(lines.slice(-8).join("\n")) }));
"""
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "lines.json")
            with open(data, "w", encoding="utf-8") as f:
                json.dump({"rules": syntax.rules(), "lines": lines}, f)
            module = os.path.join(os.path.dirname(HERE), "web", "syntax.js")
            p = subprocess.run([node, "--input-type=module", "-e", js, module, data],
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout)
        for line, want, have in zip(lines, expect, got["spans"]):
            self.assertEqual(have, want, line)
        # the HTML escapes the text and keeps every character
        html = got["html"]
        self.assertIn('<span class="t-str">"say \\"hi\\" // not a comment"</span>', html)
        self.assertIn('<span class="t-attr">@pure</span>', html)
        self.assertEqual(re.sub(r"<[^>]+>", "", html).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"),
                         "\n".join(lines[-8:]))

    def test_web_stepping_matches_desktop(self):
        """web/debugger.js, stepping through a recording, pauses where the desktop editor's
        hook (DebugState.decide, driven live by the VM) pauses, for random breakpoints and
        random sequences of Step, Over, Run and Animate."""
        import random
        import shutil
        from wiret import webapi
        from wiret.debugstate import DebugState
        from wiret.runner import run_function
        node = shutil.which("node")
        if node is None:
            self.skipTest("needs Node.js to run web/debugger.js")

        class Done(Exception):
            pass

        def desktop(text, script, breakpoints):
            m = parse(text)
            r = compile_module(m, text, debug=True)
            prefix, names = m.name + ".", {g.name for g in m.graphs()}
            dbg, cmds, log = DebugState(script[0]), list(script[1:]), []

            def hook(fname, node_id, _pending, depth, _snapshot, phase):
                g = fname[len(prefix):] if fname.startswith(prefix) else fname
                top = node_id.split("/")[0].split("!")[0]
                act = dbg.decide(g, node_id, depth, phase, breakpoints, names)
                if act == "animate":
                    log.append(["anim", g, top, depth])
                elif act == "pause":
                    dbg.depth = depth
                    log.append(["pause", g, top, depth, phase == "ready"])
                    if not cmds:
                        raise Done()
                    dbg.mode = cmds.pop(0)
            vm = VM(output=lambda s: None, hook=hook)
            try:
                run_function(vm, vm.load(r.wbc), "Main", [])
            except Done:
                return log
            except WiretError:
                pass
            return log + [["end"]]

        rng = random.Random(1)
        cases = []
        files = sorted(n for n in os.listdir(LESSONS) if n.endswith(".wiret"))
        for name in files:
            text = lesson(name)
            trace = json.loads(webapi.debug_run(text))
            keys = [(g, n) for g, ns in trace["nodes"].items() for n in ns]
            for _ in range(6):
                bps = set(rng.sample(keys, min(len(keys), rng.choice([0, 1, 2, 4]))))
                script = [rng.choice(["run", "step", "over", "animate"])] + [
                    rng.choice(["run", "step", "step", "over", "over", "animate"])
                    for _ in range(rng.randint(3, 30))]
                cases.append({"name": name, "bps": sorted(map(list, bps)), "script": script,
                              "trace": trace, "expect": desktop(text, script, bps)})
        js = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { Session } = await import(pathToFileURL(process.argv[1]).href);
const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const got = cases.map((c) => {
  const s = new Session(c.trace, new Set(c.bps.map(([g, n]) => `${g}\t${n}`)));
  const cmds = [...c.script]; let mode = cmds.shift(); const log = [];
  for (;;) {
    const r = s.advance(mode);
    if (!r) { log.push(["end"]); break; }
    const st = s.current;
    if (!r.paused) { log.push(["anim", st.graph, st.node, st.depth]); continue; }
    log.push(["pause", st.graph, st.node, st.depth, st.phase === "ready"]);
    if (!cmds.length) break;
    mode = cmds.shift();
  }
  return log;
});
process.stdout.write(JSON.stringify(got));
"""
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "cases.json")
            with open(data, "w", encoding="utf-8") as f:
                json.dump(cases, f)
            module = os.path.join(os.path.dirname(HERE), "web", "debugger.js")
            p = subprocess.run([node, "--input-type=module", "-e", js, module, data],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout)
        pauses = 0
        for c, g in zip(cases, got):
            with self.subTest(lesson=c["name"], breakpoints=c["bps"], script=c["script"]):
                self.assertEqual(g, c["expect"])
            pauses += sum(1 for e in g if e[0] == "pause")
        self.assertGreater(pauses, 200)


# -- Lane types (Draft 0.13, section 3.1.1) --------------------------------------------------
LANES = """
const Up: vec3 = (0, 1, 0)
var spawn: transform = ((0, 2, 0), (0, 0, 0, 1), (2, 2, 2))

struct Body {
  pos: vec3 = (1, 2, 3)
  turn: quat
}

class Mover {
  at: vec3 = (5, 0, 0)
}

func Step(p: vec3, v: vec3, dt: f32) -> (r: vec3) @pure = Add::<vec3>(
  .a <- p,
  .b <- Scale::<vec3>(
    .v <- v,
    .s <- dt,
  ),
)

func Arith(a: vec2, b: vec2) -> (sub: vec2, mul: vec2, div: vec2, min: vec2, max: vec2, neg: vec2, abs: vec2) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .sub <- Sub::<vec2>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .mul <- Mul::<vec2>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .div <- Div::<vec2>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .min <- Min::<vec2>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .max <- Max::<vec2>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .neg <- Neg::<vec2>(
      .value <- entry.a,
    ),
    .abs <- Abs::<vec2>(
      .value <- entry.b,
    ),
  )
}

func VecLib(a: vec3, b: vec3) -> (dot: f32, cross: vec3, len: f32, dist: f32, norm: vec3, lerp: vec3, refl: vec3) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .dot <- Call std.vec.Dot::<vec3>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .cross <- Call std.vec.Cross(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .len <- Call std.vec.Length::<vec3>(
      .v <- entry.a,
    ),
    .dist <- Call std.vec.Distance::<vec3>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .norm <- Call std.vec.Normalize::<vec3>(
      .v <- entry.a,
    ),
    .lerp <- Call std.vec.Lerp::<vec3>(
      .a <- entry.a,
      .b <- entry.b,
      .t <- 0.25,
    ),
    .refl <- Call std.vec.Reflect::<vec3>(
      .v <- entry.a,
      .n <- GetVar Up(),
    ),
  )
}

func PerpDot(a: vec2, b: vec2) -> (r: f32) @pure = Call std.vec.PerpDot(
  .a <- a,
  .b <- b,
)

func Turn(axis: vec3, angle: f32, v: vec3) -> (r: vec3) = Call std.quat.Rotate(
  .q <- Call std.quat.FromAxisAngle(
    .axis <- axis,
    .angle <- angle,
  ),
  .v <- v,
)

func Compose(a: quat, b: quat, v: vec3) -> (r: vec3) @pure = Call std.quat.Rotate(
  .q <- Mul::<quat>(
    .a <- a,
    .b <- b,
  ),
  .v <- v,
)

func Slerp(a: quat, b: quat, t: f32) -> (r: quat) = Call std.quat.Slerp(
  .a <- a,
  .b <- b,
  .t <- t,
)

func Angle(a: quat, b: quat) -> (r: f32) = Call std.quat.Angle(
  .a <- a,
  .b <- b,
)

func QuatLib(q: quat) -> (conj: quat, inv: quat, norm: quat) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .conj <- Call std.quat.Conjugate(
      .q <- entry.q,
    ),
    .inv <- Call std.quat.Inverse(
      .q <- entry.q,
    ),
    .norm <- Call std.quat.Normalize(
      .q <- entry.q,
    ),
  )
}

func Place(p: vec3) -> (r: vec3) = Call std.transform.Apply(
  .t <- GetVar spawn(),
  .p <- p,
)

func TLib(a: transform, b: transform, p: vec3) -> (both: vec3, back: vec3, dir: vec3) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .both <- Call std.transform.Apply(
      .t <- Mul::<transform>(
        .a <- entry.a,
        .b <- entry.b,
      ),
      .p <- entry.p,
    ),
    .back <- Call std.transform.Apply(
      .t <- Call std.transform.Inverse(
        .t <- entry.a,
      ),
      .p <- Call std.transform.Apply(
        .t <- entry.a,
        .p <- entry.p,
      ),
    ),
    .dir <- Call std.transform.ApplyVector(
      .t <- entry.a,
      .v <- entry.p,
    ),
  )
}

func Fields(v: vec3, t: transform) -> (y: f32, moved: vec3, rot: quat, x: f32, z: f32) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node parts = BreakStruct vec3(
    .obj <- entry.v,
  )
  node ret = Return(
    .y <- GetField vec3.y(
      .obj <- entry.v,
    ),
    .moved <- WithField vec3.z(
      .obj <- entry.v,
      .value <- 9,
    ),
    .rot <- GetField transform.rotation(
      .obj <- entry.t,
    ),
    .x <- parts.x,
    .z <- parts.z,
  )
}

func Same(a: vec3, b: vec3) -> (eq: bool, ne: bool) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .eq <- Eq::<vec3>(
      .a <- entry.a,
      .b <- entry.b,
    ),
    .ne <- Ne::<vec3>(
      .a <- entry.a,
      .b <- entry.b,
    ),
  )
}

func Defaults() -> (body: Body, t: transform, q: quat, at: vec3) {
  flow {
    entry -> mk
    mk -> ret
  }

  node entry = Entry()
  node mk = New Mover()
  node ret = Return(
    .body <- MakeStruct Body(),
    .t <- MakeStruct transform(
      .translation <- (1, 0, 0),
    ),
    .q <- MapFind::<string, quat>(
      .key <- "none",
    ).value,
    .at <- GetField Mover.at(
      .obj <- mk.result,
    ),
  )
}

func Converts(v: vec3) -> (flat: vec2, up: vec3, text: string) @pure {
  flow {
    entry -> ret
  }

  node entry = Entry()
  node ret = Return(
    .flat <- Convert::<vec3, vec2>(
      .value <- entry.v,
    ),
    .up <- Convert::<vec2, vec3>(
      .value <- (7, 8),
    ),
    .text <- Format "at {v}"(
      .v <- entry.v,
    ),
  )
}

func Keyed(v: vec3) -> (n: i32) {
  local seen: map::<vec3, i32>

  flow {
    entry -> put
    put -> ret
  }

  node entry = Entry()
  node put = MapSet::<vec3, i32> seen(
    .key <- (1, 2, 3),
    .value <- 42,
  )
  node ret = Return(
    .n <- MapFind::<vec3, i32>(
      .map <- GetLocal seen(),
      .key <- entry.v,
    ).value,
  )
}

func Pick(c: bool) -> (r: vec3) @pure = Select::<vec3>(
  .cond <- c,
  .a <- GetVar Up(),
  .b <- (0, -1, 0),
)
"""


class LaneTypeTests(unittest.TestCase):
    """`vec2`, `vec3`, `quat` and `transform` (Draft 0.13, sections 3.1.1, 5.3 and 5.6)."""

    @classmethod
    def setUpClass(cls):
        cls.text = module(LANES, macros=False)
        _, cls.r = build(cls.text)

    def call(self, func, *args, **vm_args):
        vm = VM(output=lambda s: None, **vm_args)
        return vm.call(vm.load(self.r.wbc), func, list(args))

    def close(self, got, want, eps=1e-6):
        if isinstance(want, (tuple, list)):
            self.assertEqual(len(got), len(want))
            for g, w in zip(got, want):
                self.close(g, w, eps)
        else:
            self.assertAlmostEqual(got, want, delta=eps)

    def test_round_trip(self):
        m = parse(self.text)
        self.assertEqual(print_module(parse(print_module(m))), print_module(m))
        self.assertIn("var spawn: transform = ((0, 2, 0), (0, 0, 0, 1), (2, 2, 2))",
                      print_module(m))

    def test_component_wise_arithmetic(self):
        self.assertEqual(self.call("Step", (1, 2, 3), (1, 0, -2), 0.5), [(1.5, 2.0, 2.0)])
        sub, mul, div, mn, mx, neg, ab = self.call("Arith", (1, -2), (4, 0))
        self.assertEqual((sub, mul, mn, mx, neg, ab),
                         ((-3.0, -2.0), (4.0, -0.0), (1.0, -2.0), (4.0, 0.0), (-1.0, 2.0),
                          (4.0, 0.0)))
        self.assertEqual(div[0], 0.25)
        self.assertEqual(div[1], -math.inf)      # an f32 division by zero, never a fault

    def test_results_are_f32(self):
        r, = self.call("Step", (0.1, 0, 0), (0, 0, 0), 0)
        self.assertEqual(r[0], struct.unpack("<f", struct.pack("<f", 0.1))[0])

    def test_vector_library(self):
        dot, cross, ln, dist, norm, lerp, refl = self.call("VecLib", (3, 4, 0), (0, 0, 2))
        self.assertEqual((dot, cross, ln), (0.0, (8.0, -6.0, 0.0), 5.0))
        self.close(dist, math.sqrt(29))
        self.close(norm, (0.6, 0.8, 0.0))
        self.assertEqual(lerp, (2.25, 3.0, 0.5))
        self.assertEqual(refl, (3.0, -4.0, 0.0))
        self.assertEqual(self.call("VecLib", (0, 0, 0), (0, 0, 0))[4], (0.0, 0.0, 0.0))
        self.assertEqual(self.call("PerpDot", (1, 0), (0, 1)), [1.0])

    def test_rotations(self):
        r, = self.call("Turn", (0, 0, 1), math.pi / 2, (1, 0, 0))
        self.close(r, (0, 1, 0))                 # the right-hand rule about +z
        self.assertEqual(self.call("Turn", (0, 0, 0), 1.0, (1, 2, 3)), [(1.0, 2.0, 3.0)])
        s = math.sqrt(0.5)
        turn_z, tilt_x = (0, 0, s, s), (s, 0, 0, s)
        # Mul::<quat>(a, b) rotates by b, then a
        self.close(self.call("Compose", turn_z, tilt_x, (0, 1, 0))[0], (-0.0, 0.0, 1.0))
        self.close(self.call("Compose", tilt_x, turn_z, (0, 1, 0))[0], (-1.0, 0.0, 0.0))
        half, = self.call("Slerp", (0, 0, 0, 1), turn_z, 0.5)
        self.close(half, (0, 0, math.sin(math.pi / 8), math.cos(math.pi / 8)))
        self.close(self.call("Angle", turn_z, tuple(-x for x in turn_z))[0], 0.0, 1e-3)
        self.close(self.call("Angle", (0, 0, 0, 1), turn_z)[0], math.pi / 2, 1e-5)
        conj, inv, norm = self.call("QuatLib", (0, 0, 0, 2))
        self.assertEqual((conj, inv, norm), ((-0.0, -0.0, -0.0, 2.0), (-0.0, -0.0, -0.0, 0.5),
                                             (0.0, 0.0, 0.0, 1.0)))
        self.assertEqual(self.call("QuatLib", (0, 0, 0, 0))[2], (0.0, 0.0, 0.0, 1.0))

    def test_transforms(self):
        self.assertEqual(self.call("Place", (1, 0, 0)), [(2.0, 2.0, 0.0)])
        s = math.sqrt(0.5)
        a = ((1, 2, 3), (0, 0, s, s), (2, 2, 2))
        b = ((0, 1, 0), (s, 0, 0, s), (1, 3, 1))
        both, back, d = self.call("TLib", a, b, (1, 1, 1))
        b_p = (1.0, 0.0, 3.0)                    # b applied to (1, 1, 1) by hand
        self.close(both, (1 - 2 * b_p[1], 2 + 2 * b_p[0], 3 + 2 * b_p[2]), 1e-5)
        self.close(back, (1, 1, 1), 1e-5)
        self.close(d, (-2, 2, 2), 1e-5)

    def test_struct_nodes(self):
        y, moved, rot, x, z = self.call("Fields", (1, 2, 3), ((0, 0, 0), (0, 0, 1, 0), (1, 1, 1)))
        self.assertEqual((y, moved, rot, x, z), (2.0, (1.0, 2.0, 9.0), (0.0, 0.0, 1.0, 0.0),
                                                 1.0, 3.0))

    def test_equality(self):
        self.assertEqual(self.call("Same", (1, 2, 3), (1, 2, 3)), [1, 0])
        self.assertEqual(self.call("Same", (1, 2, 3), (1, 2, 4)), [0, 1])
        self.assertEqual(self.call("Same", (math.nan, 0, 0), (math.nan, 0, 0)), [0, 1])
        self.assertEqual(self.call("Same", (-0.0, 0, 0), (0.0, 0, 0)), [1, 0])

    def test_defaults_are_identities(self):
        body, t, q, at = self.call("Defaults")
        self.assertEqual(body, ((1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0)))
        self.assertEqual(t, ((1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0)))
        self.assertEqual(q, (0.0, 0.0, 0.0, 1.0))      # a missing key's zero value
        self.assertEqual(at, (5.0, 0.0, 0.0))

    def test_conversions_and_format(self):
        self.assertEqual(self.call("Converts", (1, 2.5, 3)),
                         [(1.0, 2.5), (7.0, 8.0, 0.0), "at (1.0, 2.5, 3.0)"])

    def test_map_keys_and_select(self):
        self.assertEqual(self.call("Keyed", (1, 2, 3)), [42])
        self.assertEqual(self.call("Keyed", (1, 2, 4)), [0])
        self.assertEqual(self.call("Pick", True), [(0.0, 1.0, 0.0)])
        self.assertEqual(self.call("Pick", False), [(0.0, -1.0, 0.0)])

    def test_bytecode_is_unboxed(self):
        m = wbc.decode_module(self.r.wbc)
        self.assertTrue(m.flags & wbc.FLAG_LANES)
        dis = disassemble(self.r.wbc)
        step = dis.split("func t.Step")[1].split("\nfunc ")[0]
        self.assertIn("v3.scale", step)
        self.assertIn("v3.add", step)
        self.assertNotIn("struct.", step)
        self.assertNotIn("call", step)
        lib = dis.split("func t.VecLib")[1].split("\nfunc ")[0]
        for op in ("v3.dot", "v3.cross", "v3.len", "v3.sub", "v3.normalize", "v3.lerp"):
            self.assertIn(op, lib)                 # intrinsics, not native calls
        self.assertNotIn("call", lib)
        self.assertIn("v3.get 1                ; vec3.y", dis)
        w = wbc.Writer()
        wbc.encode_instr(w, "v3.add", ())
        self.assertEqual(bytes(w.b), b"\xfb\x23")  # FB plus the sub-opcode (section 5.6)

    def test_fuel_has_no_allocation(self):
        vm = VM()
        mod = vm.load(self.r.wbc)
        vm.call(mod, "Step", [(1, 2, 3), (1, 1, 1), 2.0])
        # local.get x3, v3.scale, v3.add, return: one unit each
        self.assertEqual(vm.fuel_limit - vm.fuel, 6)

    def test_module_without_the_feature_bit_is_refused(self):
        data = bytearray(self.r.wbc)
        flags = struct.unpack_from("<I", data, 8)[0]
        struct.pack_into("<I", data, 8, flags & ~wbc.FLAG_LANES)
        with self.assertRaises(Exception):
            VM().load(bytes(data))
        m = wbc.decode_module(bytes(data))
        from wiret.verifier import VerifyError, verify
        with self.assertRaises(VerifyError):
            verify(m)

    def test_deterministic_mode(self):
        args = ((1, 1, 0), 1.2345, (0.5, -2, 3))
        a = self.call("Turn", *args)
        b = self.call("Turn", *args, deterministic=True)
        self.close(a, b, 1e-6)
        s = math.sqrt(0.5)
        self.close(self.call("Slerp", (0, 0, 0, 1), (0, 0, s, s), 0.3, deterministic=True),
                   self.call("Slerp", (0, 0, 0, 1), (0, 0, s, s), 0.3), 1e-6)

    def test_diagnostics(self):
        def c(body):
            return codes(module(body, macros=False))
        self.assertEqual(c("const A: vec3 = (0, 1)\n"), ["E0110"])
        self.assertEqual(c("const T: transform = ((0, 2, 0), (0, 0, 0), (1, 1, 1))\n"),
                         ["E0110"])
        self.assertEqual(c("const A: i32 = \"x\"\n"), ["E0110"])
        self.assertEqual(c("struct vec3 {\n  x: f32\n}\n"), ["E0102"])
        for kind in ("Add::<quat>", "Rem::<vec3>", "Lt::<vec3>", "Div::<transform>"):
            with self.subTest(kind=kind):
                self.assertIn("E0110", c(f"func F(a: quat) -> (r: bool) @pure = Eq::<bool>(\n"
                                         f"  .a <- {kind}(\n    .a <- a,\n    .b <- a,\n  ),\n"
                                         f"  .b <- true,\n)\n"))
        self.assertIn("E0110", c("func F(a: quat) -> (r: quat) @pure = Scale::<quat>(\n"
                                 "  .v <- a,\n  .s <- 2,\n)\n"))
        self.assertIn("E0110", c("func F() -> (r: vec3) @pure = Add::<vec3>(\n"
                                 "  .a <- (1, 2),\n  .b <- (1, 2, 3),\n)\n"))
        self.assertIn("E0502", c("func F(a: vec3) -> (r: f32) @pure = Call std.vec.Dot(\n"
                                 "  .a <- a,\n  .b <- a,\n)\n"))
        self.assertIn("E0110", c("func F(a: quat) -> (r: vec3) @pure = Convert::<quat, vec3>(\n"
                                 "  .value <- a,\n)\n"))
        self.assertIn("E0501", c("func F(a: vec3) {\n  flow {\n    entry -> s\n  }\n\n"
                                 "  node entry = Entry()\n  node s = SetField vec3.x(\n"
                                 "    .obj <- a,\n    .value <- 1,\n  )\n}\n"))
        with self.assertRaises(ParseError):
            parse(module('const A: vec3 = (0, "1", 0)\n', macros=False))

    def test_runner_arguments(self):
        from wiret.runner import format_value, lit_value
        from wiret.parser import parse_literal
        self.assertEqual(lit_value(parse_literal("(1, 2, 3)"), "vec3", "p"), (1.0, 2.0, 3.0))
        with self.assertRaises(ValueError):
            lit_value(parse_literal("(1, 2)"), "vec3", "p")
        self.assertEqual(format_value("vec3", (1.0, 2.5, 0.0)), "(1.0, 2.5, 0.0)")


if __name__ == "__main__":
    unittest.main()
