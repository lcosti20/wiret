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

  node bump = SetLocal i(
    .value <- Add#<i32>(
      .a <- cur
      .b <- 1
    )
  )
  node cur = GetLocal i()
  node each_out = Exit each(
    .index <- cur
  )
  node entry = Entry()
  node finish = Exit done()
  node init = SetLocal i(
    .value <- entry.first
  )
  node seq = Sequence#count<2>()
  node test = Branch(
    .cond <- Le#<i32>(
      .a <- cur
      .b <- entry.last
    )
  )

  exec entry
  exec init
  exec test.then -> {
    exec seq.then[0] -> {
      exec each_out
    }.then[1]
    exec bump
    goto test
  }.else -> {
    exec finish
  }
}
"""


def module(body: str, macros=True) -> str:
    return ("""wiret 1
module t

extern func host.Log(message: string)
"""
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
  exec   Entry( )
  exec Return(.y <- Add#<i32>(.a <- x, .b <- 16,),)
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn("func F(x: i32) -> (y: i32) = Add#<i32>(\n  .a <- x\n  .b <- 16\n)\n", out)
        self.assertEqual(print_module(parse(out)), out)

    def test_single_use_nodes_are_written_inline(self):
        text = module("""
func Main() {
  local score: i32

  exec Entry()
  exec Call host.Log{pos=(980, 0)}(
    .message <- Call std.string.Concat{pos=(780, 180)}(
      .a <- "Your score is "
      @note("Log needs text, so Convert turns the number into text.")
      .b <- Convert#<i32, string>{pos=(600, 320)}(
        .value <- GetLocal score{pos=(440, 420)}()
      )
    )
  )
}
""", macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        g = m.graph("Main")
        self.assertEqual(sorted(n.id for n in g.nodes),
                         ["0", "1", "1.message", "1.message.b", "1.message.b.value"])
        self.assertEqual(g.node("1.message.b").binding("value").value.node, "1.message.b.value")
        self.assertEqual(note_text(g.node("1.message.b").meta[0]),
                         "Log needs text, so Convert turns the number into text.")
        self.assertEqual(run(text, "Main"), ([], ["Your score is 0"]))
        # a node read twice is named after what it does, and keeps its position and notes
        g.node("1.message").binding("a").value = PinRef("1.message.b", "result")
        out = print_module(m)
        self.assertIn('  @note("Log needs text, so Convert turns the number into text.")\n'
                      "  node convert = Convert#<i32, string>{pos=(600, 320)}(\n"
                      "    .value <- GetLocal score{pos=(440, 420)}()\n  )\n", out)
        self.assertIn("      .a <- convert\n      .b <- convert\n", out)
        self.assertEqual(print_module(parse(out)), out)

    def test_named_nodes_keep_their_names_and_order(self):
        text = module("""
func F() -> (n: i32) {
  node get = Call G()
  node seq = Sequence#count<2>()

  exec Entry()
  exec get
  exec Return(
    .n <- get
  )

  !exec seq
}

func G() -> (n: i32) = 1
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        # a node that must be named is added after the names already there
        swapped = text.replace("  node get = Call G()\n  node seq = Sequence#count<2>()\n",
                               "  node seq = Sequence#count<2>()\n  node get = Call G()\n")
        self.assertEqual(print_module(parse(swapped)), swapped)

    def test_unknown_metadata_and_attributes_survive(self):
        text = module("""
@x.acme.review("ok", level: 2)
func F() {
  @Hash(1)
  exec Entry{pos=(1, 2), label="Start", x.acme.pin=[a, b]}()
}
""", macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        self.assertEqual([d for d in check(m) if d.code == "E0104"], [])

    def test_decorators_stand_above_their_statement(self):
        text = module("""
@note("second")
@note("first")
@keywords("a", "b")
@pure
@doc("Does F.")
func F() {
  @note("why")
  local x: i32

  @note("a group")
  box {title="G", pos=(0, 0), size=(10, 10)}

  @doc("the start")
  exec Entry()
}
""", macros=False)
        m = parse(text)
        out = print_module(m)
        self.assertIn('@doc("Does F.")\n@keywords("a", "b")\n@note("second")\n'
                      '@note("first")\n@pure\nfunc F() {', out)
        self.assertIn('  @note("why")\n  local x: i32\n', out)
        self.assertIn('  @note("a group")\n  box {title="G", pos=(0, 0), size=(10, 10)}\n', out)
        self.assertIn('  @doc("the start")\n  exec Entry()\n', out)
        self.assertEqual(m.graph("F").node("0").meta[0].name, "doc")
        self.assertEqual(print_module(parse(out)), out)
        self.assertEqual(m.graph("F").meta[0].name, "note")   # the model keeps written order

    def test_decorators_must_touch_their_statement(self):
        for body, hint in (('@note("x")\n\n  local x: i32', "no blank line"),
                           ('exec Entry()\n  @note("x")', "directly above"),
                           ('#[note("x")]\n  exec Entry()', "not #["),
                           ("exec Entry() @pure", "line above"),
                           ("flow {\n  }", "'exec' statements"),
                           ("layout {\n  }", "pos=(x, y)")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)

    def test_promoted_inline_node_skips_taken_and_retired_names(self):
        # an inline node that comes to feed a second input is named after what it does,
        # then _2, _3, ... past live names and names retired in wiret.ids
        from wiret.model import Binding
        text = module("""
func F() {
  node concat = Call host.Log(
    .message <- "taken"
  )

  exec Entry()
  exec Call host.Log(
    .message <- Call std.string.Concat(
      .a <- "a"
      .b <- "b"
    )
  )
  exec concat
  exec Call host.Log()
}
""", macros=False)

        def promoted(retired, graph="F"):
            m = parse(text)
            m.graph("F").node("3").bindings.append(Binding("message",
                                                           PinRef("1.message", "result")))
            m.retired_nodes = {(graph, r) for r in retired}
            out = print_module(m)
            return re.findall(r"node (concat\w*) = Call std.string.Concat", out), out

        self.assertEqual(promoted(())[0], ["concat_2"])     # concat is taken
        names, out = promoted(("concat_2", "concat_3"))
        self.assertEqual(names, ["concat_4"])
        self.assertIn("    .message <- concat_4\n", out)
        self.assertEqual(promoted(("concat_2",), graph="G")[0], ["concat_2"])

    def test_inputs_go_in_parentheses_one_per_line(self):
        text = module("""
func F() {
  exec Entry()
  exec Call host.Log(
    .message <- "hi"
  )
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        # one line, or a comma after each input: read the same
        for form in ('Call host.Log(.message <- "hi")', 'Call host.Log(\n    .message <- "hi",\n  )'):
            one = text.replace('Call host.Log(\n    .message <- "hi"\n  )', form)
            self.assertEqual(print_module(parse(one)), text)

    def test_old_syntax_is_rejected_with_a_hint(self):
        for body, hint in (('exec Call host.Log(message: "hi")', ".pin <- value"),
                           ("exec Add<i32>()", "Add#<i32>"),
                           ("exec Add::<i32>()", "#<"),
                           ("local xs: array::<i32>", "array#<i32>"),
                           ('exec Call host.Log\n    .message <- "hi"', "in parentheses"),
                           ("exec Entry", "'Entry()'"),
                           ('exec Call std.string.Concat(.a <- "hi" .b <- "x")', "expected ','"),
                           ("exec Add#<i32>(.a <- Call host.Log())", "no output"),
                           ('exec Call host.Log() .message <- "hi"', "-> {"),
                           ("exec Sequence() @count(2)", "#count<2>"),
                           ("exec Sequence().then[0](a) -> {\n  }", "'.then[0]|name, ...| -> {"),
                           ("exec Sequence().then[0]|a| ", "write '.then[0]|a| -> {"),
                           ("node entry = Entry()\n  entry -> entry", "expected 'exec'")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  exec Entry()\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)
        for head in ("macro M<T>(in: exec) {\n}", "macro M::<T>(in: exec) {\n}"):
            with self.assertRaises(ParseError) as cm:
                parse(module(f"\n{head}\n", macros=False))
            self.assertIn("#<", cm.exception.msg)

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
  exec Entry{pos=(0, 0)}()
  // first
  exec Call host.Log(
    // what it says
    .message <- Format "{n} items"(
      .n <- 3
    )
  )
}
""", macros=False)
        out = print_module(parse(text))
        self.assertEqual(out, text)
        self.assertNotIn("W0603", {d.code for d in check(parse(text))})
        # not part of the semantic text, so a comment edit does not change the semantic hash
        self.assertEqual(semantic_hash(parse(out)),
                         semantic_hash(parse(out.replace("what it says", "its message"))))
        self.assertNotEqual(layout_hash(parse(out)),
                            layout_hash(parse(out.replace("what it says", "its message"))))
        # a commented node is named, never written inline, so its comment has a place
        m = parse(out)
        m.graph("F").node("1.message").comment = ["the text"]
        self.assertIn("  // the text\n  node format = Format", print_module(m))

    def test_comments_are_reported_and_convertible(self):
        text = module("""
func F() {
  exec Entry()   // explain the entry

  // dangling
}
""", macros=False)
        m = parse(text)
        self.assertIn("W0603", {d.code for d in check(m)})
        self.assertEqual(len(m.comments), 2)
        convert_comments(m)
        out = print_module(m)
        self.assertIn('  @note("explain the entry")\n  exec Entry()\n', out)

    def test_parse_errors_have_positions(self):
        with self.assertRaises(ParseError) as cm:
            parse("wiret 1\nmodule t\nfunc F( {\n}\n")
        self.assertEqual(cm.exception.line, 3)


class ExecSyntaxTests(unittest.TestCase):
    """`exec`, output blocks, flattening, `goto`, `!`, static methods, the implicit `self` and
    parameter defaults (section 2.3)."""

    def test_goto_loops_back_to_a_named_node(self):
        text = module("""
func SayHiThreeTimes() {
  local count: i32 = 0

  node say_hi = Call host.Log(
    .message <- "Hi!"
  )

  exec Entry()
  exec say_hi
  exec SetLocal count(
    .value <- Add#<i32>(
      .a <- GetLocal count()
      .b <- 1
    )
  )
  exec Branch(
    .cond <- Ge#<i32>(
      .a <- GetLocal count()
      .b <- 3
    )
  ).then -> {
    exec Return()
  }.else
  goto say_hi
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "SayHiThreeTimes")[1], ["Hi!"] * 3)
        g = parse(text).graph("SayHiThreeTimes")
        self.assertEqual([n.id for n in g.nodes if n.kind != "Add" and n.kind != "Ge"
                          and n.kind != "GetLocal"], ["say_hi", "0", "2", "3", "3.then.0"])
        # a goto target must be a named node; an unknown one is kept and reported
        bad = text.replace("goto say_hi", "goto nowhere")
        self.assertEqual(print_module(parse(bad)), bad)
        self.assertIn("E0101", codes(bad))

    def test_each_node_has_one_exec_point(self):
        with self.assertRaises(ParseError) as cm:
            parse(module("""
func F() {
  node log = Call host.Log()

  exec Entry()
  exec log
  exec log
}
""", macros=False))
        self.assertIn("goto log", cm.exception.msg)

    def test_a_node_entered_twice_is_named_by_the_printer(self):
        from wiret.model import ExecOut
        text = module("""
func F(c: bool) {
  exec Entry()
  exec Branch(
    .cond <- c
  ).then -> {
    exec Call host.Log(
      .message <- "yes"
    )
  }.else
  exec Call host.Log(
    .message <- "after"
  )
}
""", macros=False)
        m = parse(text)
        g = m.graph("F")
        g.node("1.then.0").execs.append(ExecOut(None, "2"))     # yes -> after
        out = print_module(m)
        self.assertIn("  node log = Call host.Log(\n    .message <- \"after\"\n  )\n", out)
        # it is written where the branch's flattened else enters it, the then block goes to it
        self.assertIn("      .message <- \"yes\"\n    )\n    goto log\n  }.else\n  exec log\n}\n", out)
        self.assertEqual(print_module(parse(out)), out)
        self.assertEqual(run(out, "F", 1)[1], ["yes", "after"])

    def test_unreached_nodes_are_written_after_a_bang(self):
        text = module("""
func F() {
  exec Entry()

  @note("Declared, but its exec input is not wired.")
  !exec Call host.Log(
    .message <- "alone"
  )

  !{
    @note("Wired to each other, but not to Entry.")
    exec Call host.Log(
      .message <- "a"
    )
    exec Call host.Log(
      .message <- "b"
    )
  }

  !Add#<i32>(
    .a <- 1
  )
}
""", macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        g = m.graph("F")
        self.assertEqual(sorted(n.id for n in g.nodes), ["0", "~0", "~1.0", "~1.1", "~2"])
        self.assertEqual(g.node("~1.0").execs[0].target, "~1.1")
        self.assertEqual(run(text, "F")[1], [])
        self.assertIn("W0301", codes(text))
        # @disabled is different: the node is on the path and is skipped
        skipped = module("""
func F() {
  exec Entry()
  @disabled
  exec Call host.Log(
    .message <- "skipped"
  )
  exec Call host.Log(
    .message <- "runs"
  )
}
""", macros=False)
        self.assertEqual(print_module(parse(skipped)), skipped)
        self.assertEqual(run(skipped, "F")[1], ["runs"])

    def test_output_blocks_bind_names_and_the_last_output_can_continue(self):
        text = module("""
func F() -> (n: i32) {
  local total: i32

  exec Entry()
  exec Macro std.flow.ForRange(
    .first <- 1
    .last <- 100
  ).each|index, break| -> {
    exec SetLocal total(
      .value <- Add#<i32>(
        .a <- GetLocal total()
        .b <- index
      )
    )
    exec Branch(
      .cond <- Ge#<i32>(
        .a <- index
        .b <- 4
      )
    ).then -> {
      goto break
    }
  }.done
  exec Return(
    .n <- GetLocal total()
  )
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "F")[0], [10])
        # `.done` written as a block reads the same, and is kept as written
        block = text.replace("  }.done\n  exec Return(\n    .n <- GetLocal total()\n  )\n",
                             "  }.done -> {\n    exec Return(\n      .n <- GetLocal total()\n"
                             "    )\n  }\n")
        self.assertEqual(print_module(parse(block)), block)
        self.assertEqual(semantic_hash(parse(block)), semantic_hash(parse(text)))
        # a name an output block binds is only in that block: outside, it names nothing
        outside = text.replace("    .n <- GetLocal total()\n", "    .n <- index\n")
        self.assertIn("E0101", codes(outside))

    def test_static_methods_implicit_self_and_defaults(self):
        text = module("""
class Counter {
  n: i32

  func Bump(self, by: i32 = 1) {
    exec Entry()
    exec SetField Counter.n(
      .obj <- self
      .value <- Add#<i32>(
        .a <- GetField Counter.n(
          .obj <- self
        )
        .b <- by
      )
    )
  }

  func Make(start: i32 = 5) -> (c: Counter) {
    node c = New Counter()

    exec Entry()
    exec c
    exec SetField Counter.n(
      .obj <- c
      .value <- start
    )
    exec Return(
      .c <- c
    )
  }

  func Twice(self) {
    exec Entry()
    exec Call Counter.Bump()
    exec Call Counter.Bump(
      .by <- 10
    )
  }
}

func Main() -> (n: i32) {
  node c = Call Counter.Make()

  exec Entry()
  exec c
  exec Call Counter.Twice(
    .self <- c
  )
  exec Return(
    .n <- GetField Counter.n(
      .obj <- c
    )
  )
}
""", macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Main")[0], [16])          # 5 + 1 + 10
        self.assertTrue(m.graph("Counter.Make").static)
        self.assertFalse(m.graph("Counter.Bump").static)
        # inside an instance method, a call to a method of its class takes its self
        calls = [n for n in m.graph("Counter.Twice").nodes if n.kind == "Call"]
        self.assertTrue(all(n.binding("self").value == PinRef("0", "self") for n in calls))
        # a static method has no self
        with self.assertRaises(ParseError) as cm:
            parse(module("\nfunc F(self) {\n  exec Entry()\n}\n", macros=False))
        self.assertIn("only a method", cm.exception.msg)

    def test_extern_results_may_be_written_empty(self):
        text = "wiret 1\nmodule t\n\nextern func host.Beep() -> ()\nextern func host.Log(message: string)\n"
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(parse(text).items[0].results, [])
        self.assertIsNone(parse(module("", macros=False)).items[0].results)

    def test_commas_are_optional_after_a_new_line(self):
        a = module("""
func F() -> (x: i32, y: i32) {
  exec Entry()
  exec Return(
    .x <- 1
    .y <- 2
  )
}
""", macros=False)
        b = a.replace(".x <- 1\n", ".x <- 1,\n").replace(".y <- 2\n", ".y <- 2,\n")
        c = a.replace("(\n    .x <- 1\n    .y <- 2\n  )", "(.x <- 1, .y <- 2)")
        for text in (b, c):
            self.assertEqual(print_module(parse(text)), a)
        with self.assertRaises(ParseError):
            parse(a.replace("(\n    .x <- 1\n    .y <- 2\n  )", "(.x <- 1 .y <- 2)"))


TYPE_DECLS = """
const MAX: i32 = 3

@doc("What an enemy is doing.")
@id("en_k3f9")
enum Mode: u8 {
  Idle = 0
  @note("Moving towards the player.")
  @id("m_c") Chase
  Flee = 7
}

struct Empty {}

@doc("A point on the map.")
struct Vec2 {
  y: f32 = 1.5
  @doc("Across.")
  @id("f_x") x: f32
  name: string = "origin"
}

func Main() {
  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi"
  )

  exec entry
  exec log
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
  exec Entry()
}
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
  exec Entry()
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
  @dok("x") Idle
}

struct P {
  @bogus hp: i32 = 100
}
""", macros=False)
        diags = [d for d in check(parse(text)) if d.code == "E0104"]
        self.assertEqual(len(diags), 2)
        self.assertIn("@doc", diags[0].message)
        self.assertIn("'P.hp'", diags[1].message)

    def test_parse_errors(self):
        for src, hint in (("enum E: f32 {\n}\n", "integer type"),
                          ("enum E: Mode {\n}\n", "integer type"),
                          ("enum E {\n  A = 1u8\n}\n", "plain integer"),
                          ('enum E {\n  A = "x"\n}\n', "plain integer"),
                          ("enum E {\n  A B\n}\n", "end of line"),
                          ("struct S {\n  x\n}\n", "expected :"),
                          ("struct S {\n  x: i32 y: i32\n}\n", "end of line"),
                          ("struct S#<T> {\n}\n", "no type parameters"),
                          ("struct S {\n  @doc(\"x\")\n}\n", "directly above"),
                          ("class C#<T> {\n}\n", "no type parameters"),
                          ("class C {\n  macro M() {\n  }\n}\n", "module level"),
                          ("interface I {\n  x: i32\n}\n", "lists methods"),
                          ("interface I {\n  func F(self) {\n  }\n}\n", "no body"),
                          ("interface I {\n  func F()\n}\n", "(self")):
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
  points: array#<Vec2>
  mode: Mode
}

func Move(p: Vec2, ps: array#<Vec2>) -> (m: Mode) {
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
  b: array#<Nope>
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
  ok_list: array#<i32> = null
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
  children: array#<Tree>
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

@pure
func Spawn() -> (e: Enemy) {
  node entry = Entry()
  node r = Return(
    .e <- MakeStruct Enemy(
      .pos <- MakeStruct Vec2()
      .mode <- Mode::Chase
    )
  )

  exec entry
  exec r
}

func Step(e: Enemy) -> (out: Enemy, fleeing: bool) {
  node chased = WithField Enemy.pos(
    .obj <- entry.e
    .value <- MakeStruct Vec2(
      .x <- Add#<f32>(
        .a <- parts.x
        .b <- 1
      )
      .y <- parts.y
    )
  )
  node entry = Entry()
  node mode = GetField Enemy.mode(
    .obj <- entry.e
  )
  node parts = BreakStruct Vec2(
    .obj <- GetField Enemy.pos(
      .obj <- entry.e
    )
  )
  node r1 = Return(
    .out <- chased
    .fleeing <- Eq#<Mode>(
      .a <- mode
      .b <- Mode::Flee
    )
  )
  node r2 = Return(
    .out <- entry.e
    .fleeing <- Lt#<Mode>(
      .a <- mode
      .b <- Mode::Flee
    )
  )
  node sw = Switch#<Mode>#cases<2>(
    .value <- Select#<Mode>(
      .cond <- Eq#<Enemy>(
        .a <- entry.e
        .b <- chased
      )
      .a <- Mode::Idle
      .b <- Convert#<u8, Mode>(
        .value <- Convert#<Mode, u8>(
          .value <- mode
        )
      )
    )
  )

  exec entry
  exec sw.case[0] Mode::Idle -> {
    exec r1
  }.case[1] Mode::Chase -> {
    goto r1
  }.default -> {
    exec r2
  }
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
        self.assertEqual(g.node("sw").binding("case[1]").value, Lit("enum", "Mode.Chase"))
        enemy = next(it for it in m.items if it.name == "Enemy")
        self.assertEqual(enemy.field("mode").default.kind, "enum")
        # MakeStruct inputs default to the field's declared default, else to the zero value
        spawn = parse(text.replace("      .mode <- Mode::Chase\n",
                                   "      .mode <- Mode::Idle\n      .hp <- 10\n"))
        self.assertEqual(print_module(spawn), text.replace("      .mode <- Mode::Chase\n", ""))

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
  node f = MakeStruct Vec2#<i32>()
  node g = MakeStruct Enemy.pos()
  node h = BreakStruct()
  node i = SetField Enemy.hp()
  node j = GetField Enemy.hp(
    .obj <- entry.v,
  )
"""), [("E0110", "j", "obj")] + [("E0501", x, "") for x in "abcdfghi"])

    def test_enum_values(self):
        self.assertEqual(self.graph_errors("""
  node a = Eq#<Mode>(
    .a <- entry.m,
    .b <- Mode::Run,
  )
  node b = Eq#<i32>(
    .a <- 1,
    .b <- Mode::Idle,
  )
  node c = Eq#<Mode>(
    .a <- entry.m,
    .b <- 1,
  )
  node d = Eq#<Mode>(
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
  node lt = Lt#<Mode>(
    .a <- entry.m,
    .b <- Mode::Idle,
  )
  node sel = Select#<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node eq = Eq#<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node to_int = Convert#<Mode, u8>(
    .value <- entry.m,
  )
  node bad_lt = Lt#<Vec2>(
    .a <- entry.v,
    .b <- entry.v,
  )
  node bad_add = Add#<Mode>(
    .a <- entry.m,
    .b <- entry.m,
  )
  node bad_conv = Convert#<Mode, i32>(
    .value <- entry.m,
  )
  node bad_text = Convert#<Mode, string>(
    .value <- entry.m,
  )
  node bad_struct = Convert#<Vec2, i32>(
    .value <- entry.v,
  )
"""), [("E0110", x, "") for x in ("bad_add", "bad_conv", "bad_lt", "bad_struct", "bad_text")])

    def test_switch_cases(self):
        self.assertEqual(self.graph_errors("""
  node a = Switch#<Mode>#cases<3>(
    .value <- entry.m,
  )
  node b = Switch#<i32>#cases<2>(
    .value <- 0,
  )
  node c = Switch#<u8>#cases<1>(
    .value <- 0,
  )
  node Mode = Branch()

  exec entry
  exec a.case[0] Mode::Idle -> {}.case[1] 3 -> {}.case[2] Mode::Nope -> {}
  !exec b.case[0] 1 -> {}.case[1] "two" -> {}
  !exec c.case[0] 300 -> {}
"""), [("E0110", "a", "case[1]"), ("E0110", "b", "case[1]"),       # a node may be called Mode
       ("E0110", "c", "case[0]"), ("E0501", "a", "case[2]")])

    def test_switch_case_values_follow_their_outputs(self):
        # the old form, case values in #cases, says where they go now
        diags = check(parse(module("""
enum Mode {
  Idle
}

func G(m: Mode) {
  exec Entry()
  exec Switch#<Mode>#cases<Mode::Idle>(
    .value <- m
  )
}
""", macros=False)))
        d = next(d for d in diags if d.code == "E0502")
        self.assertIn("'.case[0] Mode::Idle -> { ... }'", d.message)
        # a value on an output that takes none, and a case with no value
        text = module("""
func G(v: i32) {
  exec Entry()
  exec Branch(
    .cond <- true
  ).true 3 -> {}
  !exec Switch#<i32>#cases<1>(
    .value <- v
  ).case[0] -> {}
}
""", macros=False)
        diags = check(parse(text))
        self.assertIn(("E0103", "true"), [(d.code, d.pin) for d in diags])
        w = next(d for d in diags if d.code == "W0201")
        self.assertEqual(w.pin, "case[0]")
        self.assertIn("never taken", w.message)

    def test_indexed_outputs_are_written_with_brackets(self):
        text = module("""
func G() {
  exec Entry()
  exec Sequence#count<2>().then0 -> {
    exec Call host.Log(
      .message <- "hi"
    )
  }
}
""", macros=False)
        d = next(d for d in check(parse(text)) if d.code == "E0103")
        self.assertIn("'then[0]'", d.message)
        with self.assertRaises(ParseError) as cm:
            parse(text.replace(".then0", ".then[x]"))
        self.assertIn("'case[0]'", cm.exception.msg)

    def test_case_rows_line_up_and_default_is_set_apart(self):
        """A case's value sits on its output's row; a line divides the cases from default,
        and the Add pin button comes last (viewmodel.pin_rows, both canvases)."""
        from wiret.registry import ModuleIndex, signature
        from wiret.viewmodel import pin_rows
        m = parse(lesson("08_structs.wiret"))
        g = m.graph("Show")
        n = next(n for n in g.nodes if n.kind == "Switch")
        r = pin_rows(n, signature(n, g, ModuleIndex(m)))
        rows = [(p and p.name, o and o.name) for p, o, _ in r["rows"]]
        self.assertEqual(rows, [("in", None), ("value", None), ("case[0]", "case[0]"),
                                ("case[1]", "case[1]"), (None, "default")])
        ys = [y for _, _, y in r["rows"]]
        self.assertLess(ys[3], r["rule"])
        self.assertLess(r["rule"], ys[4])
        self.assertLess(ys[4], r["add"])
        self.assertLess(r["add"], r["height"])
        # a node with no indexed outputs has neither
        b = next(x for x in g.nodes if x.kind == "BreakStruct")
        plain = pin_rows(b, signature(b, g, ModuleIndex(m)))
        self.assertIsNone(plain["rule"])
        self.assertIsNone(plain["add"])
        # what the web canvas gets: the rows, the line, and a remove button on each case
        from wiret.checker import GraphInfo
        from wiret.viewmodel import graph_json
        idx = ModuleIndex(m)
        web = next(x for x in graph_json(g, GraphInfo(g, idx), idx)["nodes"] if x["id"] == n.id)
        self.assertEqual([r[:2] for r in web["rows"]], [list(r) for r in rows])
        self.assertEqual((web["rule"], web["addPin"]), (r["rule"], r["add"]))
        self.assertEqual({o["name"]: o["removable"] for o in web["outs"]},
                         {"case[0]": True, "case[1]": True, "default": False})
        self.assertEqual([p["label"] for p in web["ins"]][2:], ["", ""])

    def test_switch_case_values_may_be_wired(self):
        """A case's value is an input: a literal, or a wire from a node or a parameter, read
        when the Switch runs (section 3.3)."""
        text = module("""
func Pick(v: i32, lim: i32) -> (r: string) {
  exec Entry()
  exec Switch#<i32>#cases<3>(
    .value <- v
  ).case[0] lim -> {
    exec Return(
      .r <- "lim"
    )
  }.case[1] Add#<i32>(
    .a <- lim
    .b <- 1
  ) -> {
    exec Return(
      .r <- "lim+1"
    )
  }.case[2] 0 -> {}.default -> {
    exec Return(
      .r <- "other"
    )
  }
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Pick", 5, 5)[0], ["lim"])
        self.assertEqual(run(text, "Pick", 6, 5)[0], ["lim+1"])
        self.assertEqual(run(text, "Pick", 7, 5)[0], ["other"])
        self.assertEqual(run(text, "Pick", 0, 5)[0], [""])     # case[2]: nothing wired

    def test_bindings_between_bars_on_named_nodes(self):
        """A named node's block may bind its outputs by name too, as a shorthand for
        `loop.index` (section 2.3)."""
        text = module("""
func Main() {
  node loop = Macro ForRange(
    .first <- 0
    .last <- 2
  )

  exec Entry()
  exec loop.each|index| -> {
    exec Call host.Log(
      .message <- Convert#<i32,string>(
        .value <- index
      )
    )
  }
}
""")
        self.assertEqual(codes(text), [])
        self.assertEqual(run(text, "Main")[1], ["0", "1", "2"])

    def test_enum_value_literals(self):
        from wiret.parser import parse_literal
        lit = parse_literal("Mode::Chase")
        self.assertEqual((lit.kind, lit.value), ("enum", "Mode.Chase"))

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
    .x <- 2
  )
  node x = GetField Vec2.x(
    .obj <- v
  )
  node text = Convert#<f32, string>(
    .value <- x
  )
  node log = Call host.Log(
    .message <- text
  )

  exec entry
  exec log
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

func G(e: Enemy, v: Vec2, m: Mode, p: Mode = Other::X) {
  node entry = Entry()
  node a = GetField Enemy()
  node b = GetField Nope.x()
  node c = GetField Mode.Idle()
  node d = GetField Enemy.zz()
  node f = MakeStruct Vec2#<i32>()
  node g = MakeStruct Enemy.pos()
  node i = SetField Enemy.hp()
  node j = Eq#<i32>(
    .a <- 1,
    .b <- Mode::Idle,
  )
  node k = Switch#<Mode>#cases<2>(
    .value <- entry.m,
  )
  node Mode = Branch()

  !exec k.case[0] Mode::Idle -> {}.case[1] 3 -> {}
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
  points: array#<Vec2>
}

struct Tree {
  label: string
  children: array#<Tree>
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
    .local_e <- le
    .global_e <- ge
    .m <- gm
    .s <- st
    .made <- mk
  )
  node st = GetVar START()

  exec entry
  exec r
}

func Equal(a: Enemy, b: Enemy) -> (eq: bool, ne: bool) {
  node entry = Entry()
  node eq = Eq#<Enemy>(
    .a <- entry.a
    .b <- entry.b
  )
  node ne = Ne#<Enemy>(
    .a <- entry.a
    .b <- entry.b
  )
  node r = Return(
    .eq <- eq
    .ne <- ne
  )

  exec entry
  exec r
}

func Far() -> (w: Wide, back: i64) {
  node entry = Entry()
  node to_int = Convert#<Wide, i64>(
    .value <- Wide::Far
  )
  node r = Return(
    .w <- Wide::Far
    .back <- to_int
  )

  exec entry
  exec r
}

func Leaf(name: string) -> (t: Tree) {
  node entry = Entry()
  node r = Return(
    .t <- tree
  )
  node tree = MakeStruct Tree(
    .label <- entry.name
  )

  exec entry
  exec r
}

func Pick(m: Mode) -> (word: string) {
  node chase = Return(
    .word <- "chase"
  )
  node entry = Entry()
  node other = Return(
    .word <- "other"
  )
  node sw = Switch#<Mode>#cases<2>(
    .value <- entry.m
  )
  node wait = Return(
    .word <- "wait"
  )

  exec entry
  exec sw.case[0] Mode::Idle -> {
    exec wait
  }.case[1] Mode::Chase -> {
    exec chase
  }.default -> {
    exec other
  }
}

func Points(n: i32) -> (path: Path, last_x: f32, count: i32) {
  local pts: array#<Vec2>

  node add = ArrayAdd#<Vec2> pts(
    .item <- point
  )
  node entry = Entry()
  node get = ArrayGet#<Vec2>(
    .array <- now
    .index <- last
  )
  node last = Sub#<i32>(
    .a <- len
    .b <- 1
  )
  node len = ArrayLength#<Vec2>(
    .array <- now
  )
  node loop = Macro std.flow.ForRange(
    .first <- 0
    .last <- entry.n
  )
  node now = GetLocal pts()
  node path = MakeStruct Path(
    .points <- now
  )
  node point = MakeStruct Vec2(
    .x <- x
  )
  node r = Return(
    .path <- path
    .last_x <- x_of
    .count <- len
  )
  node x = Convert#<i32, f32>(
    .value <- loop.index
  )
  node x_of = GetField Vec2.x(
    .obj <- get
  )

  exec entry
  exec loop.each -> {
    exec add
  }.done -> {
    exec r
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
        self.assertEqual(self.call("Equal", nan, nan), [0, 1])   # as Eq#<f32> on NaN

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
                      "Switch#<Mode>", "Eq#<Enemy>", "Lt#<Mode>", "Select#<Tree>",
                      "MakeArray#<Vec2>", "Convert#<Mode, u8> (to whole number)",
                      "Convert#<u8, Mode> (to a Mode)", "Eq#<Path>", "Ne#<array#<Vec2>>"):
            with self.subTest(label):
                self.assertIn(label, labels)
        for label in ("Lt#<Vec2>", "Add#<Mode>", "Convert#<Mode, i32> (to whole number)"):
            with self.subTest(label):
                self.assertNotIn(label, labels)
        self.assertEqual(labels["Make Vec2"].category, "Structs")
        self.assertEqual(labels["Get Enemy.mode"].description,
                         "Reads the field 'mode' of an Enemy.")

    def test_struct_docs_reach_the_palette(self):
        from wiret import palette
        src = (STRUCT_NODES.replace("struct Vec2 {", '@doc("A point.")\nstruct Vec2 {')
               .replace("  x: f32\n", '  @doc("Across.")\n  x: f32\n'))
        m = parse(module(src, macros=False))
        from wiret.registry import ModuleIndex
        idx = ModuleIndex(m)
        self.assertTrue(palette.describe("MakeStruct", "Vec2", idx).endswith("A point."))
        self.assertTrue(palette.describe("GetField", "Vec2.x", idx).endswith("Across."))

    def test_dropping_a_struct_wire_offers_its_nodes(self):
        from wiret import palette
        fits = {it.label for it in palette.items(self.g, self.idx)
                if palette.compatible(it, self.g, self.idx, "out", "Vec2") is not None}
        for label in ("Break Vec2", "Get Vec2.x", "With Vec2.x (changed copy)", "Eq#<Vec2>"):
            self.assertIn(label, fits)
        self.assertNotIn("Break Enemy", fits)
        into = {it.label for it in palette.items(self.g, self.idx)
                if palette.compatible(it, self.g, self.idx, "in", "Mode") is not None}
        self.assertIn("Get Enemy.mode", into)

    def test_pin_colours(self):
        from wiret.viewmodel import type_color
        self.assertEqual(type_color("array#<i32>"), "#f0a830")
        self.assertNotEqual(type_color("Vec2", self.idx), type_color("Vec2"))
        self.assertNotEqual(type_color("Mode", self.idx), type_color("Vec2", self.idx))


CONTAINERS = """
var seen: set#<i32>

struct Cell {
  x: i32
  y: i32
}

struct Grid {
  cells: map#<Cell, string>
}

func Count(words: array#<string>) -> (counts: map#<string, i32>, n: i32, first: string, firstn: i32) {
  local m: map#<string, i32>

  node add = MapSet#<string, i32> m(
    .key <- w.item
    .value <- plus
  )
  node cur = GetLocal m()
  node entry = Entry()
  node find = MapFind#<string, i32>(
    .map <- cur
    .key <- w.item
  )
  node k0 = MapKeyAt#<string, i32>(
    .map <- cur
    .index <- 0
  )
  node len = MapLength#<string, i32>(
    .map <- cur
  )
  node plus = Add#<i32>(
    .a <- find.value
    .b <- 1
  )
  node r = Return(
    .counts <- cur
    .n <- len
    .first <- k0
    .firstn <- v0
  )
  node v0 = MapValueAt#<string, i32>(
    .map <- cur
    .index <- 0
  )
  node w = Macro std.flow.ForEach#<string>(
    .array <- entry.words
  )

  exec entry
  exec w.each -> {
    exec add
  }.done -> {
    exec r
  }
}

func Describe(m: map#<string, i32>) -> (text: string) {
  local acc: string

  node add = SetLocal acc(
    .value <- line
  )
  node entry = Entry()
  node eq = Call std.string.Concat(
    .a <- loop.key
    .b <- "="
  )
  node kv = Call std.string.Concat(
    .a <- eq
    .b <- num
  )
  node line = Call std.string.Concat(
    .a <- old
    .b <- kv
  )
  node loop = Macro std.flow.ForEachMap#<string, i32>(
    .map <- entry.m
  )
  node num = Convert#<i32, string>(
    .value <- loop.value
  )
  node old = GetLocal acc()
  node r = Return(
    .text <- old
  )

  exec entry
  exec loop.each -> {
    exec add
  }.done -> {
    exec r
  }
}

func Missing(m: map#<string, i32>, key: string) -> (value: i32, found: bool, removed: bool, left: i32) {
  local copy: map#<string, i32>

  node entry = Entry()
  node find = MapFind#<string, i32>(
    .map <- entry.m
    .key <- entry.key
  )
  node keep = SetLocal copy(
    .value <- entry.m
  )
  node left = MapLength#<string, i32>(
    .map <- now
  )
  node now = GetLocal copy()
  node r = Return(
    .value <- find.value
    .found <- find.found
    .removed <- rm
    .left <- left
  )
  node rm = MapRemove#<string, i32> copy(
    .key <- entry.key
  )

  exec entry
  exec keep
  exec rm
  exec r
}

func Nans() -> (size: i32) {
  local s: set#<f64>

  node a = SetAdd#<f64> s(
    .item <- nan
  )
  node b = SetAdd#<f64> s(
    .item <- nan
  )
  node entry = Entry()
  node nan = Div#<f64>(
    .a <- 0.0
    .b <- 0.0
  )
  node now = GetLocal s()
  node r = Return(
    .size <- size
  )
  node size = SetLength#<f64>(
    .set <- now
  )

  exec entry
  exec a
  exec b
  exec r
}

func OutOfRange(m: map#<string, i32>) -> (k: string) {
  node at = MapKeyAt#<string, i32>(
    .map <- entry.m
    .index <- 5
  )
  node entry = Entry()
  node r = Return(
    .k <- at
  )

  exec entry
  exec r
}

func Place(g: Grid, x: i32, y: i32) -> (g2: Grid, what: string, found: bool) {
  local cells: map#<Cell, string>

  node at = MakeStruct Cell(
    .x <- entry.x
    .y <- entry.y
  )
  node entry = Entry()
  node find = MapFind#<Cell, string>(
    .map <- now
    .key <- at
  )
  node get = GetField Grid.cells(
    .obj <- entry.g
  )
  node load = SetLocal cells(
    .value <- get
  )
  node now = GetLocal cells()
  node put = MapSet#<Cell, string> cells(
    .key <- at
    .value <- "tree"
  )
  node r = Return(
    .g2 <- out
    .what <- find.value
    .found <- find.found
  )
  node out = WithField Grid.cells(
    .obj <- entry.g
    .value <- now
  )

  exec entry
  exec load
  exec put
  exec r
}

func Remember(x: i32) -> (added: bool, size: i32, has: bool, removed: bool) {
  node add = SetAdd#<i32> seen(
    .item <- entry.x
  )
  node entry = Entry()
  node has = SetHas#<i32>(
    .set <- now
    .item <- entry.x
  )
  node now = GetVar seen()
  node r = Return(
    .added <- add
    .size <- size
    .has <- has
    .removed <- rm
  )
  node rm = SetRemove#<i32> seen(
    .item <- 999
  )
  node size = SetLength#<i32>(
    .set <- now
  )

  exec entry
  exec add
  exec rm
  exec r
}
"""


class ContainerTests(unittest.TestCase):
    """set#<T> and map#<K, V>: insertion-ordered value types (sections 3.1, 3.3, 5.6)."""

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
        self.assertIn("MapSet#<string, i32> m", self.text)

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
var s: set#<i32>

struct Tree {
  label: string
  kids: array#<Tree>
}

@pure
func F(a: map#<array#<i32>, i32>, b: set#<Tree>, c: map#<string, Tree>) -> (y: i32) {
  local m: map#<string, i32>

  node entry = Entry()
  node f1 = MapFind#<i32>(
    .key <- 1
  )
  node m1 = MapSet#<string, i32>(
    .key <- "a"
    .value <- 1
  )
  node m2 = MapSet#<string, f32> m(
    .key <- "a"
  )
  node s1 = SetAdd#<i32> s(
    .item <- 1
  )
  node s2 = SetHas#<Tree>()

  exec entry

  !exec f1

  !exec m1

  !exec m2

  !exec s1

  !exec s2
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
        for label in ("MapFind#<string, i32>", "MapSet m", "MapRemove m", "SetAdd seen",
                      "SetHas#<i32>", "MapFind#<Cell, string>",
                      "Macro std.flow.ForEachMap#<string, i32>"):
            with self.subTest(label):
                self.assertIn(label, labels)
        self.assertFalse(any("ForEachMap#<i32, i32>" in x for x in labels))


IDS_SRC = """wiret 1
module game.ids

struct Vec2 {
  x: f32
}

func Add1(v: i32) -> (r: i32, s: i32) {
  local tmp: i32

  node entry = Entry()
  node plus = Add#<i32>(
    .a <- entry.v
    .b <- 1
  )
  node ret = Return(
    .r <- plus
    .s <- plus
  )

  exec entry
  exec ret
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
struct Path {
  name: string
  points: array#<Vec2>
}

struct Vec2 {
  x: f64
  y: f64
}
""" + "".join(f"""
func {name}(a: {ty}, b: {ty}) -> (eq: bool, ne: bool) {{
  exec Entry()
  exec Return(
    .eq <- Eq#<{ty}>(
      .a <- a
      .b <- b
    )
    .ne <- Ne#<{ty}>(
      .a <- a
      .b <- b
    )
  )
}}
""" for name, ty in (("Arrays", "array#<f64>"), ("Nested", "array#<array#<i32>>"),
                     ("Maps", "map#<string, i32>"), ("Sets", "set#<i32>"),
                     ("FloatSets", "set#<f64>"), ("FloatMaps", "map#<f64, f64>"),
                     ("Paths", "Path"), ("PathMaps", "map#<string, Path>")))


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
        self.assertRegex(text, r'@id\("mod_\w+"\)\nmodule game.ids\n')
        self.assertRegex(text, r'\(@id\("p_\w+"\) v: i32\)')

    def test_retired_between(self):
        from wiret.ids import Retired, retired_between
        old = parse(IDS_SRC)
        new = parse(IDS_SRC.replace("  local tmp: i32\n", "").replace("plus", "sum"))
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

@pure
func Double(v: i32) -> (r: i32) {
  node entry = Entry()
  node ret = Return(
    .r <- twice
  )
  node twice = Add#<i32>(
    .a <- entry.v
    .b <- entry.v
  )

  exec entry
  exec ret
}

func Main(m: Mode) -> (out: i32, len: f32, word: string) {
  local acc: i32

  node call = Call Double(
    .v <- 21
  )
  node entry = Entry()
  node get = GetLocal acc()
  node len = GetField Vec2.x(
    .obj <- make
  )
  node make = MakeStruct Vec2(
    .x <- 3.5
  )
  node parts = BreakStruct Vec2(
    .obj <- make
  )
  node r_idle = Return(
    .out <- get
    .len <- parts.x
    .word <- "idle"
  )
  node r_run = Return(
    .out <- get
    .len <- len
    .word <- "run"
  )
  node save = SetLocal acc(
    .value <- call
  )
  node sw = Switch#<Mode>#cases<1>(
    .value <- entry.m
  )

  exec entry
  exec save
  exec sw.case[0] Mode::Idle -> {
    exec r_idle
  }.default -> {
    exec r_run
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
            {"op": "set_meta", "graph": "Main", "node": "log", "meta": '@note("Says hi.")'},
            {"op": "set_attr", "graph": "Main", "node": "sw", "attr": "#cases<2>"},
            {"op": "bind", "graph": "Main", "node": "sw", "pin": "case[1]", "value": "Mode::Run"},
            {"op": "wire_exec", "graph": "Main", "from": "sw.case[1]", "to": "r_run"},
            {"op": "place", "graph": "Main", "node": "log", "props": {"label": '"Greet"'}},
        ])
        self.assertTrue(r.ok, r.error)
        self.assertEqual([d.code for d in r.diagnostics], [])
        self.assertEqual(print_module(parse(r.text)), r.text)
        self.assertIn('  @note("Says hi.")\n  node log = Call host.Log{pos=(100, 50), label="Greet"}(\n'
                      '    .message <- "hello"\n  )\n', r.text)
        self.assertIn("  exec entry\n  exec log\n  exec save\n", r.text)
        self.assertIn("node sw = Switch#<Mode>#cases<2>(", r.text)
        self.assertIn("exec sw.case[0] Mode::Idle -> {\n    exec r_idle\n  }.case[1] Mode::Run -> {\n"
                      "    exec r_run\n  }", r.text)
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
                    {"op": "set_attr", "graph": "Main", "node": "sw", "attr": "@cases(1)"},
                    {"op": "set_meta", "graph": "Main", "node": "sw", "meta": "@pure"},
                    {"op": "rename", "graph": "Main", "node": "sw", "to": "1.x"},
                    {"op": "bind", "graph": "Main", "node": "save", "pin": "value", "value": "a b"},
                    {"op": "wire_exec", "graph": "Main", "from": "sw", "to": "save"}):
            with self.subTest(bad):
                self.assertFalse(self.edit([bad]).ok)

    def test_delete_node(self):
        r = self.edit([{"op": "delete_node", "graph": "Main", "node": "make"}])
        self.assertFalse(r.ok)
        self.assertIn("cascade", r.error["message"])
        r = self.edit([{"op": "set_meta", "graph": "Main", "node": "make", "meta": '@note("n")'},
                       {"op": "delete_node", "graph": "Main", "node": "make", "cascade": True}])
        self.assertTrue(r.ok, r.error)
        self.assertEqual(sorted(r.removed), ["make.result -> len.obj", "make.result -> parts.obj"])
        self.assertIn('@note("n", detached: "make")', r.text)
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
                    {"op": "bind", "graph": "Double", "node": "twice", "pin": "b", "value": "1"}]}, f)
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
        self.assertIn("  node call = Call Twice(\n", text)
        text = self.renamed("param", "v", "n")
        self.assertIn("    .a <- entry.n\n    .b <- entry.n\n", text)
        self.assertIn("    .n <- 21\n", text)
        text = self.renamed("result", "r", "doubled")
        self.assertRegex(text, r'-> \(@id\("\w+"\) doubled: i32')
        text = self.renamed("local", "acc", "total")
        self.assertIn("node get = GetLocal total()\n", text)
        self.assertIn("node save = SetLocal total(\n", text)

    def test_struct_and_field(self):
        text = self.renamed("field", "x", "across")
        self.assertIn("  node len = GetField Vec2.across(\n", text)
        self.assertIn("    .across <- 3.5\n", text)
        self.assertIn("    .len <- parts.across\n", text)
        text = self.renamed("struct", "Vec2", "Point")
        self.assertIn("node make = MakeStruct Point(\n", text)
        self.assertIn("  node len = GetField Point.across(\n", text)
        self.assertIn("struct Point", text)

    def test_enum_and_member(self):
        text = self.renamed("member", "Idle", "Resting")
        self.assertIn("exec sw.case[0] Mode::Resting -> {", text)
        text = self.renamed("enum", "Mode", "State")
        self.assertRegex(text, r'func Main\(@id\("\w+"\) m: State')
        self.assertIn("node sw = Switch#<State>#cases<1>(\n", text)
        self.assertIn("exec sw.case[0] State::Resting -> {", text)

    def test_macro_exec_pins(self):
        from wiret.ids import assign_ids, elements
        from wiret.rename import rename
        src = module("""
macro Twice(go: exec, skip: exec) -> (out: exec) {
  node entry = Entry()
  node leave = Exit out()
  node log = Call host.Log(
    .message <- "tick"
  )
  node seq = Sequence#count<2>()

  exec entry.go -> {
    exec seq.then[0] -> {
      exec log
      exec leave
    }.then[1]
    goto log
  }.skip -> {
    goto leave
  }
}

func Main() {
  node after = Call host.Log(
    .message <- "done"
  )
  node entry = Entry()
  node t = Macro Twice()

  exec entry
  exec t
  exec after
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
        # Entry's exec outputs are blocks; `exec t` enters t at its first exec input
        for line in ("exec entry.start -> {", "  exec t\n  exec after\n",
                     "node leave = Exit finished()"):
            self.assertIn(line, text)
        self.assertRegex(text, r'-> \(@id\("\w+"\) finished: exec')

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
        self.assertRegex(r.text, r'  @id\("\w+"\) Go\n')


MERGE_BASE = """wiret 1
module t

extern func host.Log(message: string)

func Double(v: i32) -> (r: i32, s: i32) {
  node twice = Add#<i32>(
    .a <- v
    .b <- v
  )

  exec Entry()
  exec Return(
    .r <- twice
    .s <- twice
  )
}

func Main() {
  box {title="Group", pos=(0, 0), size=(300, 100)}

  @note("Says hello.")
  node a = Call host.Log{pos=(100, 0)}(
    .message <- "a"
  )
  node b = Call host.Log{pos=(200, 0)}(
    .message <- "b"
  )

  exec Entry{pos=(0, 0)}()
  exec a
  exec b
}
"""

CALL_D = ("  node d = Call Double(\n    .v <- 2\n  )\n", "  exec b\n  exec d\n")


def sub(text, old, new):
    assert old in text, old
    return text.replace(old, new)


def with_call_d(text):
    """`text` with a node d that calls Double, run after b."""
    text = sub(text, "\n\n  exec Entry{pos=(0, 0)}()", "\n" + CALL_D[0].rstrip("\n")
               + "\n\n  exec Entry{pos=(0, 0)}()")
    return sub(text, "  exec b\n", CALL_D[1])


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
        ours = sub(MERGE_BASE, "    .b <- v\n", "    .b <- 3\n")
        theirs = sub(MERGE_BASE, "node twice = Add#<i32>(", "node twice = Mul#<i32>(")
        r = self.merge(ours, theirs)
        self.assertTrue(r.clean)
        self.assertIn("  node twice = Mul#<i32>(\n    .a <- v\n    .b <- 3\n  )\n", r.text)

    def test_anonymous_nodes_merge_by_position(self):
        r = self.merge(sub(MERGE_BASE, "    .r <- twice\n", "    .r <- 1\n"),
                       sub(MERGE_BASE, "    .s <- twice\n", "    .s <- 2\n"))
        self.assertTrue(r.clean)
        self.assertIn("  exec Return(\n    .r <- 1\n    .s <- 2\n  )\n", r.text)

    def test_conflicting_binding_is_one_line_each(self):
        r = self.merge(sub(MERGE_BASE, '.message <- "a"', '.message <- "ours"'),
                       sub(MERGE_BASE, '.message <- "a"', '.message <- "theirs"'))
        self.assertFalse(r.clean)
        self.assertEqual([c.where for c in r.conflicts], ["Main.a.message"])
        self.assertIn('<<<<<<< ours (Main.a.message)\n    .message <- "ours"\n=======\n'
                      '    .message <- "theirs"\n>>>>>>> theirs\n', r.text)

    def test_delete_against_change_is_a_conflict(self):
        ours = (MERGE_BASE.replace('  node b = Call host.Log{pos=(200, 0)}(\n    .message <- "b"\n'
                                   '  )\n', "").replace("  exec b\n", ""))
        r = self.merge(ours, sub(MERGE_BASE, '.message <- "b"', '.message <- "B"'))
        self.assertEqual([c.what for c in r.conflicts],
                         ["node deleted in ours, changed in the other"])
        self.assertIn("<<<<<<< ours (Main.b)\n", r.text)
        self.assertIn('  node b = Call host.Log{pos=(200, 0)}(\n    .message <- "B"\n  )\n', r.text)
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
        r = self.merge(ours, with_call_d(base), base)
        self.assertTrue(r.clean, [c.what for c in r.conflicts])
        self.assertIn("func Twice(", r.text)
        self.assertIn("node d = Call Twice(\n", r.text)
        self.assertEqual([d.code for d in check(parse(r.text)) if d.severity == "error"], [])
        # without @ids the rename is a deletion plus an addition, and theirs' call breaks
        r = self.merge(MERGE_BASE.replace("func Double(", "func Twice("), with_call_d(MERGE_BASE))
        self.assertTrue(r.semantic or r.conflicts)

    def test_renamed_parameter_reaches_new_call_sites(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(2))
        base = print_module(m)
        ours = re.sub(r'\) v: i32\)', ") n: i32)", base)
        ours = sub(sub(ours, "    .a <- v\n", "    .a <- n\n"), "    .b <- v\n", "    .b <- n\n")
        r = self.merge(ours, with_call_d(base), base)
        self.assertTrue(r.clean)
        self.assertIn("  node d = Call Double(\n    .n <- 2\n  )\n", r.text)

    def test_ids_assigned_on_one_side_are_not_a_rename(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(3))
        r = self.merge(print_module(m), sub(MERGE_BASE, '.message <- "a"', '.message <- "A"'))
        self.assertTrue(r.clean)
        self.assertIn('.message <- "A"', r.text)
        self.assertEqual(r.text.count("@id("), print_module(m).count("@id("))

    def test_layout_never_blocks(self):
        r = self.merge(sub(MERGE_BASE, "{pos=(100, 0)}", "{pos=(111, 0)}"),
                       sub(MERGE_BASE, "{pos=(100, 0)}", "{pos=(122, 0)}"))
        self.assertTrue(r.clean)
        self.assertIn("{pos=(122, 0)}", r.text)
        self.assertEqual(len(r.notices), 1)
        r = self.merge(sub(MERGE_BASE, "{pos=(100, 0)}", "{pos=(111, 0)}"),
                       sub(MERGE_BASE, '.message <- "a"', '.message <- "A"'))
        self.assertTrue(r.clean)
        self.assertIn("{pos=(111, 0)}", r.text)
        self.assertIn('"A"', r.text)

    def test_box_properties_merge_separately(self):
        r = self.merge(sub(MERGE_BASE, 'title="Group"', 'title="Ours"'),
                       sub(MERGE_BASE, "size=(300, 100)", "size=(320, 100)"))
        self.assertTrue(r.clean)
        self.assertIn('  box {title="Ours", pos=(0, 0), size=(320, 100)}\n', r.text)

    def test_notes(self):
        r = self.merge(sub(MERGE_BASE, "  node b = ", '  @note("ours")\n  node b = '),
                       sub(MERGE_BASE, "  node b = ", '  @note("theirs")\n  node b = '))
        self.assertTrue(r.clean)
        self.assertIn('  @note("ours")\n  @note("theirs")\n  node b = ', r.text)
        r = self.merge(sub(MERGE_BASE, "Says hello.", "Ours."),
                       sub(MERGE_BASE, "Says hello.", "Theirs."))
        self.assertEqual([c.what for c in r.conflicts],
                         ["a note was replaced differently on both sides"])
        self.assertIn('<<<<<<< ours (Main.a note)\n  @note("Ours.")\n=======\n'
                      '  @note("Theirs.")\n>>>>>>> theirs\n', r.text)
        r = self.merge(sub(MERGE_BASE, '  @note("Says hello.")\n', ""),
                       sub(MERGE_BASE, '.message <- "b"', '.message <- "B"'))
        self.assertTrue(r.clean)
        self.assertNotIn("Says hello.", r.text)

    def test_semantic_conflicts_are_reported(self):
        ours = (MERGE_BASE.replace("  node twice = Add#<i32>(\n    .a <- v\n    .b <- v\n  )\n\n", "")
                .replace("    .r <- twice\n    .s <- twice\n", "    .r <- 0\n    .s <- 0\n"))
        theirs = sub(MERGE_BASE, "  node twice = Add",
                     "  node half = Div#<i32>(\n    .a <- twice\n    .b <- 2\n  )\n"
                     "  node twice = Add")
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
                f.write(sub(MERGE_BASE, "    .b <- v\n", "    .b <- 3\n"))
            sh("commit", "-q", "-am", "theirs")
            sh("checkout", "-q", "main")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sub(MERGE_BASE, "node twice = Add#<i32>(", "node twice = Mul#<i32>("))
            sh("commit", "-q", "-am", "ours")
            sh("merge", "-q", "--no-edit", "other")
            merged = read(path)
            self.assertIn("  node twice = Mul#<i32>(\n    .a <- v\n    .b <- 3\n  )\n", merged)
            # the textconv changes what git diff shows, not what is stored
            shown = sh("diff", "HEAD~1", "HEAD", "--", "g.wiret").stdout
            raw = sh("diff", "--no-textconv", "HEAD~1", "HEAD", "--", "g.wiret").stdout
            self.assertIn(".b <- 3", shown)
            self.assertIn(".b <- 3", raw)


class DiffTests(unittest.TestCase):
    """wiretc diff (section 7): behaviour first, then metadata, then layout."""

    def diff(self, a, b):
        from wiret.diff import semantic_diff
        return semantic_diff(parse(a), parse(b))

    def test_no_change(self):
        self.assertEqual(self.diff(MERGE_BASE, MERGE_BASE), "")

    def test_nodes_in_flow_order(self):
        b = sub(MERGE_BASE, '.message <- "b"', '.message <- "B"')
        b = sub(b, "  exec b\n", '  exec b\n  exec Call host.Log(\n    .message <- "c"\n  )\n')
        b = sub(b, "    .r <- twice\n    .s <- twice\n", "    .r <- 1\n    .s <- 1\n")
        b = sub(b, "  node twice = Add#<i32>(\n    .a <- v\n    .b <- v\n  )\n\n", "")
        self.assertEqual(self.diff(MERGE_BASE, b), """func Double
  ~ node 1: .r: twice.result -> 1; .s: twice.result -> 1
  - node twice = Add
func Main
  ~ node b: .message: "b" -> "B"; exec then: (none) -> 3
  + node 3 = Call host.Log(
        .message <- "c"
      )
""")

    def test_declarations(self):
        from wiret.ids import assign_ids
        m = parse(MERGE_BASE)
        assign_ids(m, random.Random(9))
        a = print_module(m)
        b = re.sub(r"func Double\((@id\(\"\w+\"\)) v: i32", r"func Twice(\1 n: i32", a)
        b = b.replace("    .a <- v\n    .b <- v\n", "    .a <- n\n    .b <- n\n")
        b = re.sub(r"(@id\(\"ext_\w+\"\)\nextern)", r"var count: i32\n\n\1", b)
        out = self.diff(a, b)
        self.assertIn("func Double -> Twice (renamed)\n  ~ param v -> n\n", out)
        self.assertIn("+ var count\n", out)

    def test_metadata_and_layout_are_separate(self):
        b = sub(MERGE_BASE, "Says hello.", "Says hi.")
        b = sub(b, "{pos=(100, 0)}", "{pos=(150, 0)}")
        b = sub(b, "size=(300, 100)", "size=(320, 100)")
        self.assertEqual(self.diff(MERGE_BASE, b), """metadata (does not change behaviour):
  Main.a: - @note("Says hello.")
  Main.a: + @note("Says hi.")

layout only:
  Main.a: (100, 0) -> (150, 0)
  Main: box 'Group' changed
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
            self.assertIn('-    .message <- "a"\n+    .message <- "A"\n', out.getvalue())


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
        m.graph("Main").place("2").x += 40            # the Log after SetVar, by position
        self.assertEqual(semantic_hash(m), before)

    def test_rewire_changes_semantic_hash(self):
        m = parse(demo())
        before = semantic_hash(m)
        m.graph("Main").node("2").bindings[0].value.value = "changed"
        self.assertNotEqual(semantic_hash(m), before)

    def test_reroute_is_erased(self):
        plain = module("""
func F(x: i32) -> (y: i32) {
  node entry = Entry()
  node ret = Return(
    .y <- entry.x
  )

  exec entry
  exec ret
}
""", macros=False)
        rerouted = module("""
func F(x: i32) -> (y: i32) {
  node bend = Reroute#<i32>(
    .in <- entry.x
  )
  node entry = Entry()
  node hop = Reroute#<exec>()
  node ret = Return(
    .y <- bend
  )

  exec entry
  exec hop
  exec ret
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
        # node ids are execution positions: the loop is "1", the node in its `each` block
        # "1.each.0"; inside the macro, "test" is a named node and the rest are positions
        seq, each, bump = "1/test.then.0", "1/test.then.0.then[0].0", "1/test.then.1"
        expected = [
            ("0", ()), ("1!in", ()), ("1/1", ()), ("1/test", ()),
            (seq, ()), (each, (bump,)), ("1.each.0", (bump,)),
            (bump, ()), ("1/test", ()), (seq, ()),
            (each, (bump,)), ("1.each.0", (bump,)), (bump, ()),
            ("1/test", ()), ("1/test.else.0", ()), ("1.done.0", ())]
        self.assertEqual(trace, expected)

    def test_nested_loops(self):
        text = module("""
func Grid(n: i32) -> (count: i32) {
  local c: i32

  node entry = Entry()
  node outer = Macro ForRange(
    .first <- 1
    .last <- entry.n
  )
  node inner = Macro ForRange(
    .first <- 1
    .last <- outer.index
  )
  node cur = GetLocal c()
  node inc = Add#<i32>(
    .a <- cur
    .b <- 1
  )
  node bump = SetLocal c(
    .value <- inc
  )
  node total = GetLocal c()
  node ret = Return(
    .count <- total
  )

  exec entry
  exec outer.each -> {
    exec inner.each -> {
      exec bump
    }
  }.done -> {
    exec ret
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

  exec entry
  exec seq.then[0] -> {
    exec a
  }.then[1]
  exec b
}

func F() {
  node entry = Entry()
  node tw = Macro Twice()
  node log1 = Call host.Log(
    .message <- "one"
  )
  node log1b = Call host.Log(
    .message <- "one-b"
  )
  node log2 = Call host.Log(
    .message <- "two"
  )

  exec entry
  exec tw.first -> {
    exec log1
    exec log1b
  }.second -> {
    exec log2
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["one", "one-b", "two"])

    def test_early_return_discards_pending_continuations(self):
        text = module("""
func FirstOver(limit: i32) -> (found: i32) {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1
    .last <- 100
  )
  node sq = Mul#<i32>(
    .a <- loop.index
    .b <- loop.index
  )
  node over = Gt#<i32>(
    .a <- sq
    .b <- entry.limit
  )
  node chk = Branch(
    .cond <- over
  )
  node hit = Return(
    .found <- loop.index
  )
  node none = Return(
    .found <- -1
  )

  exec entry
  exec loop.each -> {
    exec chk.then -> {
      exec hit
    }
  }.done -> {
    exec none
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
    .first <- 1
    .last <- 2
  )
  node log = Call host.Log(
    .message <- "body"
  )
  node after = Call host.Log(
    .message <- "after"
  )

  exec entry
  exec seq.then[0] -> {
    exec loop.each -> {
      exec log
    }
  }.then[1]
  exec after
}
""")
        self.assertEqual(run(text, "F")[1], ["body", "body", "after"])

    def test_join_and_E0310(self):
        text = module("""
func F(c: bool) -> (r: string) {
  node entry = Entry()
  node br = Branch(
    .cond <- entry.c
  )
  node make = Call Make()
  node join = Return(
    .r <- make
  )

  exec entry
  exec br.then -> {
    exec make
    exec join
  }.else -> {
    goto join
  }
}

func Make() -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- "made"
  )

  exec entry
  exec ret
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
    .cond <- entry.c
  )
  node make = Call Make()
  node keep = SetLocal s(
    .value <- make
  )
  node none = SetLocal s(
    .value <- ""
  )
  node join = Return(
    .r <- GetLocal s()
  )

  exec entry
  exec br.then -> {
    exec make
    exec keep
    exec join
  }.else -> {
    exec none
    goto join
  }
}

func Make() -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- "made"
  )

  exec entry
  exec ret
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
    .value <- cur
  )
  node dmg = Sub#<i32>(
    .a <- cur
    .b <- 3
  )
  node hit = SetVar hp(
    .value <- dmg
  )
  node got = GetLocal first()
  node ret = Return(
    .a <- got
    .b <- cur
  )

  exec entry
  exec save
  exec hit
  exec ret
}
""", macros=False)
        # read at save, then at ret after hit wrote it: an error unless that is meant
        self.assertIn("E0320", codes(text))
        live = sub(text, "  node cur = GetVar hp()\n", "  @live\n  node cur = GetVar hp()\n")
        self.assertNotIn("E0320", codes(live))
        self.assertEqual(run(live, "F")[0], [10, 7])
        # @live on a node that reads it also excuses it, but not on an impure node
        dmg = sub(text, "  node dmg = ", "  @live\n  node dmg = ")
        self.assertIn("E0320", codes(dmg))       # cur still reaches save and ret directly
        bad = sub(text, "  node hit = ", "  @live\n  node hit = ")
        self.assertIn("E0104", codes(bad))

    def test_reads_on_exclusive_paths_are_not_e0320(self):
        text = module("""
var hp: i32 = 10

func F(c: bool) -> (a: i32) {
  node chk = Branch(
    .cond <- entry.c
  )
  node cur = GetVar hp()
  node entry = Entry()
  node r1 = Return(
    .a <- cur
  )
  node r2 = Return(
    .a <- Add#<i32>(
      .a <- cur
      .b <- 1
    )
  )

  exec entry
  exec chk.then -> {
    exec r1
  }.else -> {
    exec r2
  }
}
""", macros=False)
        self.assertNotIn("E0320", codes(text))
        # a loop body and the code after the loop do run one after the other
        loop = module("""
var hp: i32 = 10

func F() -> (a: i32) {
  node bump = SetVar hp(
    .value <- cur
  )
  node cur = GetVar hp()
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1
    .last <- 3
  )
  node ret = Return(
    .a <- cur
  )

  exec entry
  exec loop.each -> {
    exec bump
  }.done -> {
    exec ret
  }
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
    .cond <- flag
  )
  node mark = SetState fired(
    .value <- true
  )
  node fire = Exit out()
  node clear = SetState fired(
    .value <- false
  )

  exec entry.in -> {
    exec check.else -> {
      exec mark
      exec fire
    }
  }.reset -> {
    exec clear
  }
}

func F() {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1
    .last <- 3
  )
  node seq = Sequence()
  node once_a = Macro DoOnce()
  node once_b = Macro DoOnce()
  node log_a = Call host.Log(
    .message <- "a"
  )
  node log_b = Call host.Log(
    .message <- "b"
  )

  exec entry
  exec loop.each -> {
    exec seq.then[0] -> {
      exec once_a
      exec log_a
    }.then[1]
    exec once_b
    exec log_b
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["a", "b"])

    def test_switch_select_and_conversions(self):
        text = module("""
func Conv(x: f64) -> (i: i32, b: u8, s: string, back: f32) {
  node entry = Entry()
  node i = Convert#<f64, i32>(
    .value <- entry.x
  )
  node b = Convert#<i32, u8>(
    .value <- i
  )
  node s = Convert#<f64, string>(
    .value <- entry.x
  )
  node f = Convert#<f64, f32>(
    .value <- entry.x
  )
  node ret = Return(
    .i <- i
    .b <- b
    .s <- s
    .back <- f
  )

  exec entry
  exec ret
}

func Name(v: i32) -> (s: string) {
  node entry = Entry()
  node sw = Switch#<i32>#cases<2>(
    .value <- entry.v
  )
  node one = Return(
    .s <- "one"
  )
  node two = Return(
    .s <- "two"
  )
  node neg = Lt#<i32>(
    .a <- entry.v
    .b <- 0
  )
  node pick = Select#<string>(
    .cond <- neg
    .a <- "negative"
    .b <- "many"
  )
  node other = Return(
    .s <- pick
  )

  exec entry
  exec sw.case[0] 1 -> {
    exec one
  }.case[1] 2 -> {
    exec two
  }.default -> {
    exec other
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
  items: array#<i32>

  func Pick(self, i: i32) {
    state last: i32

    node entry = Entry()
    node save = SetState last(
      .value <- Select#<i32>(
        .cond <- Lt#<i32>(
          .a <- entry.i
          .b <- 0
        )
        .a <- -1
        .b <- ArrayGet#<i32>(
          .array <- GetField Box.items(
            .obj <- entry.self
          )
          .index <- entry.i
        )
      )
    )
    node log = Call host.Log(
      .message <- Convert#<i32, string>(
        .value <- GetState last()
      )
    )

    exec entry
    exec save
    exec log
  }
}

func Guard(i: i32) -> (r: i32) {
  node entry = Entry()
  node arr = MakeArray#<i32>#count<2>(
    .item0 <- 10
    .item1 <- 20
  )
  node ok = And(
    .a <- Ge#<i32>(
      .a <- entry.i
      .b <- 0
    )
    .b <- Lt#<i32>(
      .a <- entry.i
      .b <- ArrayLength#<i32>(
        .array <- arr
      )
    )
  )
  node ret = Return(
    .r <- Add#<i32>(
      .a <- 1000
      .b <- Select#<i32>(
        .cond <- ok
        .a <- ArrayGet#<i32>(
          .array <- arr
          .index <- entry.i
        )
        .b <- Select#<i32>(
          .cond <- Or(
            .a <- ok
            .b <- Eq#<i32>(
              .a <- Div#<i32>(
                .a <- 1
                .b <- entry.i
              )
              .b <- 0
            )
          )
          .a <- 1
          .b <- -1
        )
      )
    )
  )

  exec entry
  exec ret
}

func Main() {
  node entry = Entry()
  node b = New Box()
  node add = ArrayAdd#<i32> Box.items(
    .obj <- b
    .item <- 42
  )
  node low = Call Box.Pick(
    .self <- b
    .i <- -5
  )
  node high = Call Box.Pick(
    .self <- b
    .i <- 0
  )

  exec entry
  exec b
  exec add
  exec low
  exec high
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
func F(c: bool) -> (r: i32) {
  node entry = Entry()
  node ret = Return(
    .r <- Select#<i32>(
      .cond <- entry.c
      .a <- Div#<i32>(
        .a <- 1
        .b <- 0
      )
      .b <- 7
    )
  )

  exec entry
  exec ret
}
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

@pure
func Both(v: i32) -> (lo: i32, hi: i32) {
  exec Entry()
  exec Return(
    .lo <- v
    .hi <- Mul#<i32>(
      .a <- v
      .b <- 2
    )
  )
}

@pure
func Clamp01(v: f32) -> (result: f32) = Min#<f32>(
  .a <- Max#<f32>(
    .a <- v
    .b <- 0.0
  )
  .b <- 1.0
)

func Main() {
  local items: array#<i32>

  exec Entry()
  exec Call host.Log(
    .message <- Format "{n} items, {f} clamped, {ok}, {big}, {name}"(
      .n <- ArrayLength#<i32>(
        .array <- GetLocal items()
      )
      .f <- Call Clamp01(
        .v <- 2.5
      )
      .ok <- Lt#<i32>(
        .a <- 1
        .b <- 2
      )
      .big <- 3000000000u32
      .name <- "done"
    )
  )
  exec Call host.Log(
    .message <- Format "lo {lo}, hi {hi}, x {x}, {{literal}} {lo}"(
      .lo <- Call Both(
        .v <- 3
      ).lo
      .hi <- Call Both(
        .v <- 4
      ).hi
      .x <- BreakStruct Vec2(
        .obj <- MakeStruct Vec2(
          .x <- 0.5
        )
      ).x
    )
  )
}
"""


class ReadabilityTests(unittest.TestCase):
    """An inline node's one output is implied, Format builds text, a function can be written
    `= value`, and `//` comments are kept."""

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
        f = m.graph("Main").node("1.message.f")
        self.assertEqual(m.graph("Main").node("1.message").binding("f").value,
                         PinRef("1.message.f", "result"))
        self.assertEqual(f.kind, "Call")
        # `.lo` can be left out of the text only when the node has one data output
        bad = self.text().replace("      ).lo\n", "      )\n")
        with self.assertRaises(ParseError) as cm:
            parse(bad)
        self.assertIn("several outputs (lo, hi)", cm.exception.msg)
        self.assertIn("'Call(...).lo'", cm.exception.msg)
        # written out, `.result` reads the same and is printed the short way
        long = self.text().replace("        .v <- 2.5\n      )", "        .v <- 2.5\n      ).result")
        self.assertNotEqual(long, self.text())
        self.assertEqual(print_module(parse(long)), self.text())

    def test_a_named_node_s_one_output_is_implied_too(self):
        text = module("""
struct Vec2 {
  x: f32
  y: f32
}

func F(n: i32) -> (r: i32, x: f32, y: f32) {
  local acc: i32

  node cur = GetLocal acc()
  node parts = BreakStruct Vec2(
    .obj <- MakeStruct Vec2(
      .x <- 1.5
    )
  )

  exec Entry()
  exec Macro std.flow.ForRange(
    .first <- 1
    .last <- n
  ).each|index| -> {
    exec SetLocal acc(
      .value <- Add#<i32>(
        .a <- cur
        .b <- index
      )
    )
  }.done -> {
    exec Return(
      .r <- cur
      .x <- parts.x
      .y <- parts.y
    )
  }
}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
        self.assertEqual(run(text, "F", 4)[0], [10, 1.5, 0.0])
        g = parse(text).graph("F")
        self.assertEqual(g.node("1.done.0").binding("r").value, PinRef("cur", "value"))
        # written out, the one output reads the same and is printed the short way
        self.assertEqual(print_module(parse(text.replace("      .r <- cur\n",
                                                         "      .r <- cur.value\n"))), text)
        # several outputs: the one read must be named
        with self.assertRaises(ParseError) as cm:
            parse(text.replace("      .x <- parts.x\n", "      .x <- parts\n"))
        self.assertIn("'parts' has several outputs (x, y)", cm.exception.msg)
        self.assertIn("'parts.x'", cm.exception.msg)
        # a name that is no node or parameter is kept as written and reported
        gone = print_module(parse(text.replace("      .r <- cur\n", "      .r <- old\n")))
        self.assertIn("      .r <- old\n", gone)
        self.assertEqual(print_module(parse(gone)), gone)
        found = [d for d in check(parse(gone)) if d.code == "E0101"]
        self.assertEqual([(d.node, d.pin) for d in found], [("1.done.0", "r")])


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
func F(xs: array#<i32>) -> (s: string) = Format "{xs}"(
  .xs <- xs,
)
""")
        self.assertTrue(any(c == "E0110" and "'xs' is array#<i32>" in m for c, m in found), found)
        # an unbound placeholder is empty text; doubled braces are braces
        text = module("""
func F() -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- Format "[{gap}] {{x}}"()
  )

  exec entry
  exec ret
}
""", macros=False)
        self.assertEqual(run(text, "F")[0], ["[] {x}"])

    def test_format_with_a_lazy_input_verifies(self):
        # the Select branches, so the template's text must not be on the operand stack yet
        text = module("""
func F(c: bool) -> (s: string) {
  node entry = Entry()
  node ret = Return(
    .s <- Format "got {v}!"(
      .v <- Select#<i32>(
        .cond <- entry.c
        .a <- Div#<i32>(
          .a <- 1
          .b <- 0
        )
        .b <- -1
      )
    )
  )

  exec entry
  exec ret
}
""", macros=False)
        self.assertEqual(run(text, "F", 0)[0], ["got -1!"])
        r = compile_module(parse(text), text, debug=True)
        self.assertTrue(r.ok, [str(d) for d in r.diags])

    def test_expression_body(self):
        text = self.text()
        m = parse(text)
        g = m.graph("Clamp01")
        self.assertEqual(sorted(n.id for n in g.nodes), ["0", "1", "1.result", "1.result.a"])
        self.assertEqual(g.node("1.result.a").binding("a").value, PinRef("0", "v"))
        # once it has a position (the editor placed it), it is written as a graph
        g.places.append(Place("1", 300, 0))
        out = print_module(m)
        self.assertIn("@pure\nfunc Clamp01(v: f32) -> (result: f32) {\n  exec Entry()\n"
                      "  exec Return{pos=(300, 0)}(\n", out)
        self.assertIn("      .a <- v\n", out)
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

  node entry = Entry()
  node get = GetLocal n()
  node say = Call host.Log(
    .message <- Format "n is {n}"()
  )

  exec entry
  exec say
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
        base = self.text().replace("  exec Entry()\n", "  // starts here\n  exec Entry()\n")
        ours = base.replace("// starts here", "// begins here")
        theirs = base.replace('.name <- "done"', '.name <- "finished"').replace(
            "    .message <- Format \"{n}", "    // the summary\n    .message <- Format \"{n}")
        r = merge_texts(base, ours, theirs)
        self.assertTrue(r.clean, [c.what for c in r.conflicts])
        self.assertIn("  // begins here\n  exec Entry()\n", r.text)
        self.assertIn("    // the summary\n    .message <- Format \"{n}", r.text)
        self.assertIn('.name <- "finished"', r.text)


LEAVE = """
func Nest() -> (n: i32) {
  local count: i32

  node add = SetLocal count(
    .value <- Add#<i32>(
      .a <- GetLocal count()
      .b <- 1
    )
  )
  node chk = Branch(
    .cond <- And(
      .a <- Eq#<i32>(
        .a <- outer.index
        .b <- 2
      )
      .b <- Eq#<i32>(
        .a <- inner.index
        .b <- 2
      )
    )
  )
  node entry = Entry()
  node inner = Macro std.flow.ForRange(
    .first <- 1
    .last <- 3
  )
  node outer = Macro std.flow.ForRange(
    .first <- 1
    .last <- 3
  )
  node ret = Return(
    .n <- GetLocal count()
  )
  node seq = Sequence#count<2>()

  exec entry
  exec outer.each -> {
    exec inner.each -> {
      exec seq.then[0] -> {
        exec chk.then -> {
          goto outer.break
        }
      }.then[1]
      exec add
    }
  }.done -> {
    exec ret
  }
}

func Never() -> (n: i32) {
  node entry = Entry()
  node loop = Macro std.flow.ForRange(
    .first <- 1
    .last <- 3
  )
  node ret = Return(
    .n <- 7
  )

  exec entry
  goto loop.break

  !{
    exec loop.done -> {
      exec ret
    }
  }
}

func SumUntil(stop: i32) -> (total: i32) {
  local acc: i32

  node add = SetLocal acc(
    .value <- Add#<i32>(
      .a <- GetLocal acc()
      .b <- loop.index
    )
  )
  node chk = Branch(
    .cond <- Eq#<i32>(
      .a <- loop.index
      .b <- entry.stop
    )
  )
  node entry = Entry()
  node loop = Macro std.flow.ForRange(
    .first <- 1
    .last <- 10
  )
  node ret = Return(
    .total <- GetLocal acc()
  )

  exec entry
  exec loop.each -> {
    exec chk.then -> {
      goto loop.break
    }.else -> {
      exec add
    }
  }.done -> {
    exec ret
  }
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
  node entry = Entry()
  node out = Leave done()

  exec entry
  exec out
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

  func Total(self) -> (size: i32) {
    node entry = Entry()
    node ret = Return(
      .size <- GetField Box.state(
        .obj <- entry.self
      )
    )

    exec entry
    exec ret
  }
}

func Main(node: i32) -> (size: i32) {
  local flow: i32
  local state: Mode

  box {title="Group", pos=(0, 0), size=(400, 100)}

  node Mode = Branch(
    .cond <- Eq#<Mode>(
      .a <- GetLocal state()
      .b <- Mode::Idle
    )
  )
  node at = SetLocal flow{pos=(100, 0)}(
    .value <- entry.node
  )
  node box = SetLocal state{pos=(200, 0)}(
    .value <- Mode::Idle
  )
  node entry = Entry{pos=(0, 0)}()
  node local = Call host.Log(
    .message <- Format "{size} {flow}"(
      .size <- GetField layout.size(
        .obj <- MakeStruct layout(
          .size <- 5
        )
      )
      .flow <- GetLocal flow()
    )
  )
  node size = Return{pos=(300, 0)}(
    .size <- GetLocal flow()
  )

  exec entry
  exec at
  exec box
  exec Mode.then -> {
    exec local
    exec size
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
        self.assertEqual([b.title for b in g.boxes], ["Group"])
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
        self.assertEqual(kw("  node at = SetLocal flow("), ["node"])
        self.assertEqual(kw("  exec box"), ["exec"])
        self.assertEqual(kw("  goto node"), ["goto"])
        self.assertEqual(kw("  !exec Entry()"), ["exec"])
        self.assertEqual(kw('  box {title="x"}'), ["box"])
        self.assertEqual(kw("    .box <- exec"), [])


class SaturationTests(unittest.TestCase):
    """Float to integer conversion saturates to the target type's range (section 3.2)."""

    def test_narrow_types_saturate(self):
        types = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
        results = ", ".join(f"{t}_: {t}" for t in types)
        binds = "".join(f"    .{t}_ <- Convert#<f64, {t}>(\n      .value <- x\n    )\n"
                        for t in types)
        text = module(f"""
@pure
func Sat(x: f64) -> ({results}) {{
  exec Entry()
  exec Return(
{binds}  )
}}
""", macros=False)
        self.assertEqual(print_module(parse(text)), text)
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
@export
var counter: i32 = 0

var hidden: i32 = 0

@export
enum Color: u8 {
  Red
  Green
}

struct Inner {
  v: i32
}

@export
struct Point {
  x: i32
  y: i32
}

@export
interface Named {
  func Name(self) -> (name: string)
}

@export
class Box {
  size: i32 = 1

  @export
  func Grow(self, by: i32) -> (size: i32) {
    node entry = Entry()
    node ret = Return(
      .size <- entry.by
    )

    exec entry
    exec ret
  }

  func Shrink(self, by: i32) -> (size: i32) {
    node entry = Entry()
    node ret = Return(
      .size <- entry.by
    )

    exec entry
    exec ret
  }
}

func Priv(x: i32) -> (y: i32) {
  node entry = Entry()
  node ret = Return(
    .y <- entry.x
  )

  exec entry
  exec ret
}

@export
func Pub(x: i32) -> (y: i32) {
  node call = Call Priv(
    .x <- entry.x
  )
  node entry = Entry()
  node ret = Return(
    .y <- call
  )

  exec entry
  exec call
  exec ret
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
        unmarked = EXPORTS.replace("@export\nenum Color: u8 {", "enum Color: u8 {")
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
    The text is written in the order it runs, so the example is canonical as it stands, and
    `wiretc view --flow` prints it unchanged."""

    def example(self):
        spec = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "reference",
                            "02-text-syntax.md")
        with open(spec, encoding="utf-8", newline="") as f:
            sec = f.read().split("### 2.6 A complete example", 1)[1]
        return sec.split("```\n", 1)[1].split("```", 1)[0]

    def test_section_2_6_round_trips_byte_for_byte(self):
        from wiret.flow import view_flow
        text = self.example()
        self.assertEqual(print_module(parse(text)), text)              # fmt(x) == x
        self.assertEqual(view_flow(parse(text)), text)
        self.assertEqual([d.code for d in check(parse(text))], [])

    def test_section_2_6_has_no_alignment_padding(self):
        for line in self.example().splitlines():
            with self.subTest(line=line):
                self.assertNotRegex(line.strip(), r"\S  +(=|at|<-|->) ")


class ArithmeticEdgeCases(unittest.TestCase):
    TEXT = module("""
func AddU8(a: u8, b: u8) -> (r: u8) {
  node entry = Entry()
  node s = Add#<u8>(
    .a <- entry.a
    .b <- entry.b
  )
  node ret = Return(
    .r <- s
  )

  exec entry
  exec ret
}

func Div(a: i32, b: i32) -> (q: i32, r: i32) {
  node entry = Entry()
  node q = Div#<i32>(
    .a <- entry.a
    .b <- entry.b
  )
  node r = Rem#<i32>(
    .a <- entry.a
    .b <- entry.b
  )
  node ret = Return(
    .q <- q
    .r <- r
  )

  exec entry
  exec ret
}

func MinMax(a: i32, b: i32) -> (lo: i32, hi: i32, abs: i32) {
  node entry = Entry()
  node lo = Min#<i32>(
    .a <- entry.a
    .b <- entry.b
  )
  node hi = Max#<i32>(
    .a <- entry.a
    .b <- entry.b
  )
  node ab = Abs#<i32>(
    .value <- entry.a
  )
  node ret = Return(
    .lo <- lo
    .hi <- hi
    .abs <- ab
  )

  exec entry
  exec ret
}

func Shift(a: i32, n: i32) -> (r: i32) {
  node entry = Entry()
  node s = Shl#<i32>(
    .a <- entry.a
    .b <- entry.n
  )
  node ret = Return(
    .r <- s
  )

  exec entry
  exec ret
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

  exec entry
  exec again.then[0]
  goto again
}
""", macros=False)
        _, r = build(text)
        vm = VM(fuel=1000)
        with self.assertRaises(WiretError) as cm:
            vm.call(vm.load(r.wbc), "Spin", [])
        self.assertEqual(cm.exception.status, "WR_ERR_FUEL")


class ArrayTests(unittest.TestCase):
    BODY = """
var names: array#<string>

func Main(at: i32) -> (r: i32) {
  local nums: array#<i32>
  local total: i32

  exec Entry()
  exec SetLocal nums(
    .value <- MakeArray#<i32>#count<3>(
      .item0 <- 10
      .item1 <- 20
      .item2 <- 5
    )
  )
  exec ArrayAdd#<i32> nums(
    .item <- 30
  )
  exec ArraySet#<i32> nums(
    .index <- at
    .item <- 7
  )
  exec Macro std.flow.ForEach#<i32>(
    .array <- GetLocal nums()
  ).each|item| -> {
    exec SetLocal total(
      .value <- Add#<i32>(
        .a <- GetLocal total()
        .b <- item
      )
    )
  }.done
  exec ArrayAdd#<string> names(
    .item <- "Ada"
  )
  exec Call host.Log(
    .message <- ArrayGet#<string>(
      .array <- GetVar names()
      .index <- 0
    )
  )
  exec Return(
    .r <- GetLocal total()
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
        self.assertEqual(cm.exception.traceback[-1], ("t.Main", "3"))      # the ArraySet

    def test_fault_in_pure_node_names_that_node(self):
        text = module(self.BODY.replace(".index <- 0", ".index <- 5"), macros=False)
        for debug in (False, True):
            with self.subTest(debug=debug):
                vm = VM(output=lambda s: None)
                with self.assertRaises(WiretError) as cm:
                    vm.call(vm.load(compile_module(parse(text), text, debug=debug).wbc), "Main", [0])
                self.assertEqual(cm.exception.traceback[-1], ("t.Main", "6.message"))  # not `6`

    def test_mutator_type_must_match_place(self):
        text = module(self.BODY.replace("ArrayAdd#<i32> nums", "ArrayAdd#<f64> nums"),
                      macros=False)
        self.assertIn("E0110", codes(text))


class DiagnosticTests(unittest.TestCase):
    """One failing graph per implemented diagnostic code (section 7.4)."""

    CASES = {
        "E0101": "exec Entry()\n  goto nowhere",
        "E0102": "local x: i32\n  local x: i32\n\n  exec Entry()\n  exec Return(\n    .y <- 1\n  )",
        "E0103": "exec Entry()\n  exec Return(\n    .bogus <- 1\n  )",
        "E0110": "exec Entry()\n  exec Return(\n    .y <- \"text\"\n  )",
        "E0111": "exec Entry()\n  exec Return(\n    .y <- 1\n    .y <- 2\n  )",
        "E0120": "exec Entry()\n  exec Return(\n    .in <- 1\n    .y <- 2\n  )",
        "E0121": "node r = Return(\n    .y <- 1\n  )\n\n  exec Entry().then -> {\n    exec r\n"
                 "  }.then -> {\n    goto r\n  }",
        "E0130": "exec Entry()\n  exec ArrayClear#<i32>()\n  exec Return(\n    .y <- 1\n  )",
        "E0301": "node a = Add#<i32>(\n    .a <- b\n    .b <- 1\n  )\n"
                 "  node b = Add#<i32>(\n    .a <- a\n    .b <- 1\n  )\n\n"
                 "  exec Entry()\n  exec Return(\n    .y <- a\n  )",
        "E0501": "exec Entry()\n  exec Frobnicate()\n  exec Return(\n    .y <- 1\n  )",
        "E0502": "exec Entry()\n  exec Return(\n    .y <- Add(\n      .a <- 1\n      .b <- 2\n"
                 "    )\n  )",
        "W0201": "exec Entry()\n  exec Return()",
        "W0301": "exec Entry()\n  exec Return(\n    .y <- 1\n  )\n\n  !exec Return(\n    .y <- 2\n  )",
        "W0302": "exec Entry()",
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
""", macros=False)
        e0302 = base + """
@pure
func P() -> (y: i32) {
  exec Entry()
  exec SetVar g(
    .value <- 1
  )
  exec Return(
    .y <- 1
  )
}
"""
        e0304 = base + """
@pure
func P() -> (y: i32) {
  exec Entry()
  exec Return(
    .y <- GetVar g()
  )
}
"""
        self.assertIn("E0302", codes(e0302))
        self.assertIn("E0304", codes(e0304))

    def test_macro_recursion(self):
        text = module("""
macro Loop(in: exec) -> (out: exec) {
  exec Entry()
  exec Macro Loop()
  exec Exit out()
}
""", macros=False)
        self.assertIn("E0401", codes(text))

    def test_detached_note_warning(self):
        text = module("""
@note("orphan", detached: "gone")
func F() {
  exec Entry()
}
""", macros=False)
        self.assertIn("W0604", codes(text))

    def test_delete_keeps_notes(self):
        m = parse(demo())
        g = m.graph("Main")
        target = "3.each.0.then.0.message.b"         # the Convert with a note in the demo
        self.assertTrue(notes(g.node(target).meta))
        removed = delete_node(g, target)
        self.assertTrue(removed)
        self.assertTrue(any(note_detached(a) == target for a in notes(g.meta)))
        self.assertIn("W0604", {d.code for d in check(m)})
        out = print_module(m)
        self.assertIn(f'detached: "{target}")', out)
        self.assertEqual(print_module(parse(out)), out)

    def test_delete_box_keeps_notes(self):
        text = module("""
func F() {
  @note("the group")
  box {title="G", pos=(0, 0), size=(10, 10)}

  exec Entry()
}
""", macros=False)
        m = parse(text)
        g = m.graph("F")
        delete_box(g, g.boxes[0].id)
        self.assertEqual([(note_text(a), note_detached(a)) for a in notes(g.meta)],
                         [("the group", "box.0")])

    def test_notes_do_not_change_the_semantic_hash(self):
        m1 = parse(demo())
        m2 = parse(demo())
        g = m2.graph("Main")
        add_note(g, None, "a new graph note")
        add_note(g, g.nodes[0].id, "a new node note")
        self.assertEqual(semantic_hash(m1), semantic_hash(m2))
        self.assertNotEqual(layout_hash(m1), layout_hash(m2))


SAFE_DIV = """
func SafeDiv(a: i32, b: i32) -> (q: i32) {
  node bad = Call host.Log(
    .message <- t.message
  )
  node entry = Entry()
  node fail = Return(
    .q <- t.code
  )
  node ok = Return(
    .q <- Div#<i32>(
      .a <- entry.a
      .b <- entry.b
    )
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec ok
  }.fault
  exec bad
  exec fail
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
    .message <- "after"
  )
  node big = Gt#<i32>(
    .a <- entry.x
    .b <- 10
  )
  node boom = Throw(
    .message <- "too big"
    .code <- 42
  )
  node chk = Branch(
    .cond <- big
  )
  node logit = Call host.Log(
    .message <- t.message
  )
  node ret = Return(
    .r <- t.code
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec chk.then -> {
      exec boom
    }
  }.fault -> {
    exec logit
  }.then
  exec after
  exec ret
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
    .message <- "no"
    .code <- 7
  )

  exec entry
  exec boom
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
  node div = Div#<i32>(
    .a <- 1
    .b <- entry.x
  )
  node log = Call host.Log(
    .message <- "inner done"
  )
  node ret = Return(
    .r <- div
  )
  node seq = Sequence()

  exec entry
  exec seq.then[0] -> {
    exec ret
  }.then[1]
  exec log
}

func Outer(x: i32) -> (r: i32) {
  node entry = Entry()
  node call = Call Inner(
    .x <- entry.x
  )
  node caught = Return(
    .r <- t.code
  )
  node ok = Return(
    .r <- call
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec call
    exec ok
  }.fault
  exec caught
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
    .message <- "stop"
  )
  node bump = SetLocal c(
    .value <- inc
  )
  node chk = Branch(
    .cond <- two
  )
  node cur = GetLocal c()
  node inc = Add#<i32>(
    .a <- cur
    .b <- 1
  )
  node loop = Macro ForRange(
    .first <- 1
    .last <- 5
  )
  node ret = Return(
    .n <- cur
  )
  node t = Try()
  node two = Eq#<i32>(
    .a <- loop.index
    .b <- 2
  )

  exec entry
  exec t.body -> {
    exec loop.each -> {
      exec chk.then -> {
        exec boom
      }.else -> {
        exec bump
      }
    }
  }.fault
  exec ret
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
    .message <- "odd"
  )
  node bump = SetLocal c(
    .value <- inc
  )
  node chk = Branch(
    .cond <- odd
  )
  node cur = GetLocal c()
  node done = Return(
    .n <- cur
  )
  node inc = Add#<i32>(
    .a <- cur
    .b <- 1
  )
  node loop = Macro ForRange(
    .first <- 1
    .last <- 5
  )
  node odd = Eq#<i32>(
    .a <- rem
    .b <- 1
  )
  node rem = Rem#<i32>(
    .a <- loop.index
    .b <- 2
  )
  node t = Try()

  exec entry
  exec loop.done -> {
    exec done
  }.each -> {
    exec t.body -> {
      exec chk.then -> {
        exec boom
      }
    }.fault
    exec bump
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
    .message <- inner.message
    .code <- 2
  )
  node boom = Throw(
    .message <- "first"
    .code <- 1
  )
  node inner = Try()
  node outer = Try()
  node ret = Return(
    .msg <- outer.message
  )

  exec entry
  exec outer.body -> {
    exec inner.body -> {
      exec boom
    }.fault
    exec again
  }.fault
  exec ret
}
""", macros=False)
        self.assertEqual(run(text, "F")[0], ["first"])

    def test_fuel_exhaustion_is_not_catchable(self):
        text = module("""
func Spin() {
  node entry = Entry()
  node again = Sequence()
  node t = Try()

  exec entry
  exec t.body
  exec again.then[0]
  goto again
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
    .message <- "negative"
  )
  node chk = Branch(
    .cond <- neg
  )
  node neg = Lt#<i32>(
    .a <- entry.x
    .b <- 0
  )
  node ret = Return(
    .r <- entry.x
  )

  exec entry
  exec chk.then -> {
    exec boom
  }.else -> {
    exec ret
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
    .cond <- entry.x
  )
  node log = Call host.Log(
    .message <- "shared"
  )
  node t = Try()

  exec entry
  exec chk.then -> {
    exec t.body
    exec log
  }.else -> {
    goto log
  }
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_e0412_body_loops_back_to_its_try(self):
        text = module("""
func F() {
  node entry = Entry()
  node log = Call host.Log(
    .message <- "again"
  )
  node t = Try()

  exec entry
  exec t.body
  exec log
  goto t
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_e0412_exit_inside_a_try_body(self):
        text = module("""
macro Guard(in: exec) -> (each: exec) {
  node entry = Entry()
  node out = Exit each()
  node t = Try()

  exec entry
  exec t.body
  exec out
}
""", macros=False)
        self.assertIn("E0412", codes(text))

    def test_loops_and_joins_inside_the_body_are_allowed(self):
        text = module("""
func F() {
  node entry = Entry()
  node a = Call host.Log(
    .message <- "a"
  )
  node b = Call host.Log(
    .message <- "b"
  )
  node chk = Branch()
  node join = Call host.Log(
    .message <- "join"
  )
  node loop = Macro ForRange(
    .first <- 1
    .last <- 2
  )
  node t = Try()

  exec entry
  exec t.body
  exec chk.then -> {
    exec a
    exec join
    exec loop
  }.else -> {
    exec b
    goto join
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
  node a = Call host.Log(
    .message <- "before"
  )
  node b = Call host.Log(
    .message <- "after"
  )
  node d = Delay(
    .seconds <- entry.gap
  )
  node entry = Entry()

  exec entry
  exec a
  exec d
  exec b
}

event Listen(s: std.Signal, name: string) {
  node entry = Entry()
  node log = Call host.Log(
    .message <- entry.name
  )
  node w = Await(
    .signal <- entry.s
  )

  exec entry
  exec w
  exec log
}

event Steps() {
  node a = Call host.Log(
    .message <- "step 1"
  )
  node b = Call host.Log(
    .message <- "step 2"
  )
  node entry = Entry()
  node y = Yield()

  exec entry
  exec a
  exec y
  exec b
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
@latent
func Wait(seconds: f64) -> (waited: f64) {
  node d = Delay(
    .seconds <- entry.seconds
  )
  node entry = Entry()
  node ret = Return(
    .waited <- entry.seconds
  )

  exec entry
  exec d
  exec ret
}

event Count(n: i32) {
  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1
    .last <- entry.n
  )
  node msg = Convert#<i32, string>(
    .value <- loop.index
  )
  node say = Call host.Log(
    .message <- msg
  )
  node w = Call Wait(
    .seconds <- 1.0
  )

  exec entry
  exec loop.each -> {
    exec w
    exec say
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
  node boom = Throw(
    .message <- "bad"
    .code <- 9
  )
  node entry = Entry()
  node y = Yield()

  exec entry
  exec y
  exec boom
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
  node entry = Entry()
  node log = Call host.Log(
    .message <- t.message
  )
  node t = Try()
  node w = Await()

  exec entry
  exec t.body -> {
    exec w
  }.fault
  exec log
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
    .signal <- get
  )
  node get = GetVar bell()

  exec entry
  exec fire
}

event Wait() {
  node aw = Await(
    .signal <- mk
  )
  node entry = Entry()
  node log = Call host.Log(
    .message <- "rang"
  )
  node mk = Call std.signal.New()
  node keep = SetVar bell(
    .value <- mk
  )

  exec entry
  exec mk
  exec keep
  exec aw
  exec log
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
macro Pause(in: exec) -> (then: exec) {
  node d = Yield()
  node entry = Entry()
  node out = Exit then()

  exec entry
  exec d
  exec out
}

func CallsEvent() {
  node c = Call Ev()
  node entry = Entry()

  exec entry
  exec c
}

func CallsLatent() {
  node c = Call Waits()
  node entry = Entry()

  exec entry
  exec c
}

func ExpandsLatent() {
  node entry = Entry()
  node p = Macro Pause()

  exec entry
  exec p
}

func Sleeper() {
  node d = Delay(
    .seconds <- 1.0
  )
  node entry = Entry()

  exec entry
  exec d
}

@latent
func Waits() {
  node d = Delay(
    .seconds <- 1.0
  )
  node entry = Entry()

  exec entry
  exec d
}

event Ev() {
  node entry = Entry()

  exec entry
}
""", macros=False)
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(sorted(diags), [("CallsEvent", "E0201"), ("CallsLatent", "E0201"),
                                         ("ExpandsLatent", "E0201"), ("Sleeper", "E0201")])

    def test_e0302_pure_functions_cannot_be_latent(self):
        text = module("""
@latent
@pure
func A() {
  node entry = Entry()

  exec entry
}

@pure
func B() -> (x: i32) {
  node d = Yield()
  node entry = Entry()
  node ret = Return(
    .x <- 1
  )

  exec entry
  exec d
  exec ret
}
""", macros=False)
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(sorted(diags), [("A", "E0302"), ("B", "E0302")])

    def test_signals_cannot_be_fields_or_container_items(self):
        text = module("""
struct Holder {
  s: std.Signal
}

func F(a: array#<std.Signal>) {
  node entry = Entry()

  exec entry
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

  func Describe(self) -> (text: string) {
    node entry = Entry()
    node ret = Return(
      .text <- "boss"
    )

    exec entry
    exec ret
  }
}

class Player {
  health: i32 = 100
  name: string = "hero"

  func Describe(self) -> (text: string) {
    node entry = Entry()
    node ret = Return(
      .text <- "player"
    )

    exec entry
    exec ret
  }

  func TakeDamage(self, amount: i32) -> (died: bool) {
    local new_hp: i32

    node chk = Branch(
      .cond <- Le#<i32>(
        .a <- hp
        .b <- 0
      )
    )
    node entry = Entry()
    node hp = GetLocal new_hp()
    node ret_alive = Return(
      .died <- false
    )
    node ret_dead = Return(
      .died <- true
    )
    node set_new = SetLocal new_hp(
      .value <- Sub#<i32>(
        .a <- GetField Player.health(
          .obj <- entry.self
        )
        .b <- entry.amount
      )
    )
    node store = SetField Player.health(
      .obj <- entry.self
      .value <- hp
    )

    exec entry
    exec set_new
    exec store
    exec chk.then -> {
      exec ret_dead
    }.else -> {
      exec ret_alive
    }
  }
}

func Make(boss: bool) -> (p: Player) {
  local who: Player

  node b = New Boss()
  node entry = Entry()
  node pick = Branch(
    .cond <- entry.boss
  )
  node pl = New Player()
  node ret = Return(
    .p <- GetLocal who()
  )
  node set_b = SetLocal who(
    .value <- b
  )
  node set_p = SetLocal who(
    .value <- pl
  )

  exec entry
  exec pick.then -> {
    exec b
    exec set_b
    exec ret
  }.else -> {
    exec pl
    exec set_p
    goto ret
  }
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
  @note("one note")
  func F(self) {
    node entry = Entry()

    exec entry
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
  node desc = Call Player.Describe(
    .self <- mk.p
  )
  node entry = Entry()
  node hit = Call Player.TakeDamage(
    .self <- mk.p
    .amount <- 150
  )
  node hp = GetField Player.health(
    .obj <- mk.p
  )
  node mk = Call Make(
    .boss <- entry.boss
  )
  node nm = GetField Player.name(
    .obj <- mk.p
  )
  node ret = Return(
    .said <- desc.text
    .died <- hit.died
    .hp <- hp.value
    .name <- nm.value
  )

  exec entry
  exec mk
  exec desc
  exec hit
  exec ret
}
""")
        self.assertEqual(run(text, "Run", 0)[0], ["player", 1, -50, "hero"])
        self.assertEqual(run(text, "Run", 1)[0], ["boss", 1, -50, "hero"])

    def test_cast_isvalid_and_identity(self):
        text = classes_text("""
func Probe(boss: bool) -> (ok: bool, rage: i32, valid: bool, same: bool, other: bool) {
  node as_boss = Cast Boss(
    .obj <- mk.p
  )
  node entry = Entry()
  node mk = Call Make(
    .boss <- entry.boss
  )
  node mk2 = Call Make(
    .boss <- entry.boss
  )
  node other = Eq#<Player>(
    .a <- mk.p
    .b <- mk2.p
  )
  node rage = GetField Boss.rage(
    .obj <- as_boss.result
  )
  node ret = Return(
    .ok <- as_boss.ok
    .rage <- rage.value
    .valid <- valid
    .same <- same.result
    .other <- other.result
  )
  node same = Eq#<Player>(
    .a <- mk.p
    .b <- mk.p
  )
  node valid = IsValid(
    .obj <- mk.p
  )

  exec entry
  exec mk
  exec mk2
  exec ret
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
  node caught = Return(
    .code <- t.code
  )
  node entry = Entry()
  node ok = Return(
    .code <- 0
  )
  node set = SetField Player.health(
    .obj <- null
    .value <- 1
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec set
    exec ok
  }.fault
  exec caught
}
""")
        self.assertEqual(run(text, "Safe")[0], [-3])

    def test_objects_are_shared_references(self):
        text = classes_text("""
func Alias() -> (hp: i32) {
  node a = New Player()
  node arr = MakeArray#<Player>#count<1>(
    .item0 <- a.result
  )
  node entry = Entry()
  node first = ArrayGet#<Player>(
    .array <- arr.result
    .index <- 0
  )
  node hp = GetField Player.health(
    .obj <- a.result
  )
  node ret = Return(
    .hp <- hp.value
  )
  node set = SetField Player.health(
    .obj <- first.item
    .value <- 7
  )

  exec entry
  exec a
  exec set
  exec ret
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
func Down() -> (b: Boss) {
  node entry = Entry()
  node p = New Player()
  node ret = Return(
    .b <- p.result
  )

  exec entry
  exec p
  exec ret
}

func Up() -> (p: Player) {
  node b = New Boss()
  node entry = Entry()
  node ret = Return(
    .p <- b.result
  )

  exec entry
  exec b
  exec ret
}
""")
        diags = [(d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E")]
        self.assertEqual(diags, [("Down", "E0110")])

    def test_e0150_bad_overrides(self):
        text = module("""
class A {
  func F(self, x: i32) {
    node entry = Entry()

    exec entry
  }

  @final
  func G(self) {
    node entry = Entry()

    exec entry
  }
}

class B : A {
  func F(self, x: f32) {
    node entry = Entry()

    exec entry
  }

  func G(self) {
    node entry = Entry()

    exec entry
  }
}
""", macros=False)
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("B.F", "E0150"), ("B.G", "E0150")])

    def test_final_methods_are_called_directly(self):
        text = module("""
class A {
  @final
  func Id(self) -> (x: i32) {
    node entry = Entry()
    node ret = Return(
      .x <- 1
    )

    exec entry
    exec ret
  }
}

func F() -> (x: i32) {
  node a = New A()
  node c = Call A.Id(
    .self <- a
  )
  node entry = Entry()
  node ret = Return(
    .x <- c
  )

  exec entry
  exec a
  exec c
  exec ret
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

class C : Missing {}

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
@pure
func P(p: Player) -> (hp: i32) {
  node entry = Entry()
  node hp = GetField Player.health(
    .obj <- entry.p
  )
  node ret = Return(
    .hp <- hp.value
  )

  exec entry
  exec ret
}
""")
        self.assertIn("E0304", codes(text))

    def test_flow_view_is_the_text(self):
        # the text is already in the order it runs, so the flow view changes nothing
        text = classes_text()
        self.assertEqual(view_flow(parse(text)), print_module(parse(text)))

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
  func Hit(self, amount: i32) -> (left: i32)
  func Name(self) -> (name: string)
}

class Barrel impl Damageable {
  hp: i32 = 10

  func Hit(self, amount: i32) -> (left: i32) {
    local hp_left: i32

    node entry = Entry()
    node keep = SetLocal hp_left(
      .value <- Sub#<i32>(
        .a <- GetField Barrel.hp(
          .obj <- entry.self
        )
        .b <- entry.amount
      )
    )
    node now = GetLocal hp_left()
    node ret = Return(
      .left <- now
    )
    node set = SetField Barrel.hp(
      .obj <- entry.self
      .value <- now
    )

    exec entry
    exec keep
    exec set
    exec ret
  }

  func Name(self) -> (name: string) {
    node entry = Entry()
    node ret = Return(
      .name <- "barrel"
    )

    exec entry
    exec ret
  }
}

class BigBarrel : Barrel {
  func Name(self) -> (name: string) {
    node entry = Entry()
    node ret = Return(
      .name <- "big barrel"
    )

    exec entry
    exec ret
  }
}

class Door impl Damageable {
  func Hit(self, amount: i32) -> (left: i32) {
    node entry = Entry()
    node ret = Return(
      .left <- 99
    )

    exec entry
    exec ret
  }

  func Name(self) -> (name: string) {
    node entry = Entry()
    node ret = Return(
      .name <- "door"
    )

    exec entry
    exec ret
  }
}

func Smash(which: i32) -> (name: string, left: i32, is_d: bool) {
  local t: Damageable

  node b = New BigBarrel()
  node chk = Branch(
    .cond <- Eq#<i32>(
      .a <- entry.which
      .b <- 0
    )
  )
  node d = New Door()
  node entry = Entry()
  node get = GetLocal t()
  node hit = Call Damageable.Hit(
    .self <- get
    .amount <- 4
  )
  node nm = Call Damageable.Name(
    .self <- get
  )
  node ret = Return(
    .name <- nm
    .left <- hit
    .is_d <- Cast Door(
      .obj <- get
    ).ok
  )
  node sb = SetLocal t(
    .value <- b
  )
  node sd = SetLocal t(
    .value <- d
  )

  exec entry
  exec chk.then -> {
    exec b
    exec sb
    exec hit
    exec nm
    exec ret
  }.else -> {
    exec d
    exec sd
    goto hit
  }
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
class Rock {}

func Down(d: Damageable) -> (door: Door) {
  node entry = Entry()
  node ret = Return(
    .door <- entry.d
  )

  exec entry
  exec ret
}

func NotOne() -> (d: Damageable) {
  node entry = Entry()
  node n = New Rock()
  node ret = Return(
    .d <- n
  )

  exec entry
  exec n
  exec ret
}

func Probe() -> (rock_ok: bool, door_ok: bool) {
  node door = New Door()
  node entry = Entry()
  node is_door = Cast Damageable(
    .obj <- door.result
  )
  node is_rock = Cast Damageable(
    .obj <- rock
  )
  node ret = Return(
    .rock_ok <- is_rock.ok
    .door_ok <- is_door.ok
  )
  node rock = New Rock()

  exec entry
  exec door
  exec rock
  exec ret
}

func Up() -> (d: Damageable) {
  node entry = Entry()
  node n = New Door()
  node ret = Return(
    .d <- n.result
  )

  exec entry
  exec n
  exec ret
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
  func Name(self) -> (name: string)
  func Rank(self) -> (rank: i32)
}

class A impl Named {
  func Name(self) -> (name: i32) {
    node entry = Entry()

    exec entry
  }
}

class B impl Named {
  func Rank(self) -> (rank: i32) {
    node entry = Entry()

    exec entry
  }

  event Name(self) {
    node entry = Entry()

    exec entry
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
  func F(self)
  func F(self)
  @latent
  func W(self)
}

class A {}

class B impl A, Missing {}
""", macros=False)
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("B", "E0151"), ("B", "E0151"), ("I", "E0102"),
                                 ("I", "E0501")])

    def test_an_object_used_as_a_class_and_as_an_interface(self):
        # New's result goes into a Damageable pin first (sorted by id) and then into a Door
        # field write; the slot holding it must keep the producer's type, Door
        text = iface_text("""
func Both() -> (left: i32) {
  node a_use = Call Damageable.Hit(
    .self <- door.result
    .amount <- 1
  )
  node door = New Door()
  node entry = Entry()
  node ret = Return(
    .left <- a_use.left
  )
  node z_cast = Cast Door(
    .obj <- door.result
  )

  exec entry
  exec door
  exec a_use
  exec ret

  !exec z_cast
}
""")
        self.assertEqual(run(text, "Both")[0], [99])

    def test_null_receiver_faults(self):
        text = iface_text("""
func F() -> (code: i32) {
  node c = Call Damageable.Name(
    .self <- null
  )
  node caught = Return(
    .code <- t.code
  )
  node entry = Entry()
  node ok = Return(
    .code <- 0
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec c
    exec ok
  }.fault
  exec caught
}
""")
        self.assertEqual(run(text, "F")[0], [-3])

    def test_ids_and_merge_know_classes_and_interfaces(self):
        from wiret.ids import assign_ids
        from wiret.merge import merge_texts
        m = parse(iface_text())
        assign_ids(m, rng=random.Random(3))
        out = print_module(m)
        self.assertRegex(out, r'@id\("if_\w+"\)\ninterface Damageable \{')
        self.assertRegex(out, r'@id\("cls_\w+"\)\nclass Door impl Damageable \{')
        self.assertRegex(out, r'  @id\("im_\w+"\)\n  func Name\(self\) -> \(')
        base = iface_text()
        ours = base.replace("  func Name(self) -> (name: string)\n}",
                            "  func Name(self) -> (name: string)\n  func Heal(self)\n}", 1)
        theirs = base.replace("class Door impl Damageable {", "class Door impl Damageable {\n"
                              "  open: bool", 1)
        r = merge_texts(base, ours, theirs)
        self.assertEqual(r.conflicts, [])
        self.assertIn("  func Heal(self)\n}", r.text)
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

  func Add(self, amount: i32) {
    node entry = Entry()
    node set = SetField Counter.hits(
      .obj <- entry.self
      .value <- Add#<i32>(
        .a <- GetField Counter.hits(
          .obj <- entry.self
        )
        .b <- entry.amount
      )
    )

    exec entry
    exec set
  }

  event Later(self, amount: i32) {
    node entry = Entry()
    node log = Call host.Log(
      .message <- "later"
    )
    node y = Yield()

    exec entry
    exec y
    exec log
  }
}

class Player {
  dispatcher OnHit(amount: i32)

  func Hit(self, amount: i32) {
    node b = Broadcast Player.OnHit(
      .obj <- entry.self
      .amount <- entry.amount
    )
    node entry = Entry()

    exec entry
    exec b
  }
}

func Boom(amount: i32) {
  node entry = Entry()
  node log = Call host.Log(
    .message <- Convert#<i32, string>(
      .value <- Div#<i32>(
        .a <- 1
        .b <- 0
      )
    )
  )

  exec entry
  exec log
}

func Run() -> (hits: i32, twice: i32) {
  node add = CreateDelegate Counter.Add(
    .target <- c
  )
  node b1 = Bind Player.OnHit(
    .obj <- p
    .handler <- add
  )
  node b2 = Bind Player.OnHit(
    .obj <- p
    .handler <- CreateDelegate Boom()
  )
  node b3 = Bind Player.OnHit(
    .obj <- p
    .handler <- CreateDelegate Counter.Later(
      .target <- c
    )
  )
  node b4 = Bind Player.OnHit(
    .obj <- p
    .handler <- add
  )
  node c = New Counter()
  node entry = Entry()
  node h1 = Call Player.Hit(
    .self <- p
    .amount <- 5
  )
  node h2 = Call Player.Hit(
    .self <- p
    .amount <- 7
  )
  node inv = Invoke#<delegate#<(i32) -> (i32)>>(
    .delegate <- CreateDelegate Twice()
    .arg0 <- 21
  )
  node p = New Player()
  node ret = Return(
    .hits <- GetField Counter.hits(
      .obj <- c
    )
    .twice <- inv
  )
  node ub = Unbind Player.OnHit(
    .obj <- p
    .handler <- add
  )

  exec entry
  exec c
  exec p
  exec b1
  exec b2
  exec b3
  exec b4
  exec h1
  exec ub
  exec h2
  exec inv
  exec ret
}

func Twice(x: i32) -> (y: i32) {
  node entry = Entry()
  node ret = Return(
    .y <- Mul#<i32>(
      .a <- entry.x
      .b <- 2
    )
  )

  exec entry
  exec ret
}
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
  func Add(self, amount: i32) {
    node entry = Entry()
    node log = Call host.Log(
      .message <- "loud"
    )

    exec entry
    exec log
  }
}

func Over() {
  node d = CreateDelegate Counter.Add(
    .target <- l
  )
  node entry = Entry()
  node inv = Invoke#<delegate#<(i32)>>(
    .delegate <- d.result
    .arg0 <- 1
  )
  node l = New Loud()

  exec entry
  exec l
  exec inv
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
  node caught = Return(
    .code <- t.code
  )
  node entry = Entry()
  node inv = Invoke#<delegate#<(i32) -> (i32)>>(
    .delegate <- null
  )
  node ok = Return(
    .code <- 0
  )
  node t = Try()

  exec entry
  exec t.body -> {
    exec inv
    exec ok
  }.fault
  exec caught
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
struct Holder {
  d: dispatcher#<(i32)>
}

func Bad() {
  node d = CreateDelegate Twice()
  node entry = Entry()
  node eq = Eq#<delegate#<(i32) -> (i32)>>(
    .a <- d.result
    .b <- d.result
  )
  node p = New Player()
  node wrong = Bind Player.OnHit(
    .obj <- p.result
    .handler <- d.result
  )

  exec entry
  exec p
  exec wrong

  !exec eq
}

func BindsLatent() {
  node d = CreateDelegate Waits()
  node entry = Entry()

  exec entry

  !exec d
}

func Native() {
  node d = CreateDelegate host.Log()
  node entry = Entry()

  exec entry

  !exec d
}

@latent
func Waits() {
  node d = Delay(
    .seconds <- 1.0
  )
  node entry = Entry()

  exec entry
  exec d
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

@pure
func P(p: Player) {
  node b = Broadcast Player.OnHit(
    .obj <- entry.p
    .amount <- 1
  )
  node entry = Entry()

  exec entry
  exec b
}
""")
        c = codes(text)
        self.assertIn("E0102", c)
        self.assertIn("E0302", c)

    def test_delegate_types_written_with_empty_results_are_the_short_form(self):
        m = parse(module("""
func F(d: delegate#<(i32)>) {
  node entry = Entry()

  exec entry
}
""", macros=False))
        self.assertEqual(m.graph("F").params[0].type, "delegate#<(i32)>")

    def test_ids_name_dispatchers(self):
        from wiret.ids import assign_ids
        m = parse(delegates_text())
        assign_ids(m, rng=random.Random(4))
        self.assertRegex(print_module(m), r'  @id\("dsp_\w+"\)\n  dispatcher OnHit\(')

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
  items: array#<i32>
}

func Alias() -> (a: array#<i32>, b: array#<i32>, c: array#<i32>, d: array#<i32>) {
  local a: array#<i32>
  local b: array#<i32>

  node add_a = ArrayAdd#<i32> a(
    .item <- 1
  )
  node add_a2 = ArrayAdd#<i32> a(
    .item <- 2
  )
  node bag = New Bag()
  node bag_items = GetField Bag.items(
    .obj <- bag
  )
  node call = Call Mutate(
    .x <- get_a
  )
  node copy_b = SetLocal b(
    .value <- get_a
  )
  node entry = Entry()
  node get_a = GetLocal a()
  node get_b = GetLocal b()
  node put = SetField Bag.items(
    .obj <- bag
    .value <- get_a
  )
  node ret = Return(
    .a <- get_a
    .b <- get_b
    .c <- bag_items
    .d <- call
  )

  exec entry
  exec add_a
  exec copy_b
  exec bag
  exec put
  exec add_a2
  exec call
  exec ret
}

func Build(n: i32) -> (len: i32) {
  local acc: array#<i32>

  node add = ArrayAdd#<i32> acc(
    .item <- loop.index
  )
  node entry = Entry()
  node get = GetLocal acc()
  node len = ArrayLength#<i32>(
    .array <- get
  )
  node loop = Macro ForRange(
    .first <- 1
    .last <- entry.n
  )
  node ret = Return(
    .len <- len
  )

  exec entry
  exec loop.done -> {
    exec ret
  }.each -> {
    exec add
  }
}

func Bump(a: array#<i32>) -> (len: i32) {
  local mine: array#<i32>

  node add = ArrayAdd#<i32> mine(
    .item <- 9
  )
  node entry = Entry()
  node get = GetLocal mine()
  node keep = SetLocal mine(
    .value <- entry.a
  )
  node len = ArrayLength#<i32>(
    .array <- get
  )
  node ret = Return(
    .len <- len
  )

  exec entry
  exec keep
  exec add
  exec ret
}

func Mutate(x: array#<i32>) -> (y: array#<i32>) {
  local mine: array#<i32>

  node add = ArrayAdd#<i32> mine(
    .item <- 7
  )
  node entry = Entry()
  node get = GetLocal mine()
  node keep = SetLocal mine(
    .value <- entry.x
  )
  node ret = Return(
    .y <- get
  )

  exec entry
  exec keep
  exec add
  exec ret
}

func Snapshot() -> (seen: i32, after: i32) {
  local a: array#<i32>
  local n: i32

  node a1 = ArrayAdd#<i32> a(
    .item <- 1
  )
  node a2 = ArrayAdd#<i32> a(
    .item <- 2
  )
  node cnt = GetLocal n()
  node entry = Entry()
  node get_a = GetLocal a()
  node grow = ArrayAdd#<i32> a(
    .item <- 0
  )
  node inc = Add#<i32>(
    .a <- cnt
    .b <- 1
  )
  node len = ArrayLength#<i32>(
    .array <- get_a
  )
  node loop = Macro std.flow.ForEach#<i32>(
    .array <- get_a
  )
  node ret = Return(
    .seen <- cnt
    .after <- len
  )
  node set_n = SetLocal n(
    .value <- inc
  )

  exec entry
  exec a1
  exec a2
  exec loop.each -> {
    exec grow
    exec set_n
  }.done -> {
    exec ret
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
@capability("audio.play")
extern func host.Beep()

@capability("console.write")
extern func host.Log(message: string)

func Hello() {
  node beep = Call host.Beep()
  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi"
  )

  exec entry
  exec log
  exec beep
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
  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi"
  )

  exec entry
  exec log
}
""", macros=False)                     # host.Log declared without @capability
        _, r = build(text)
        with self.assertRaises(WiretError) as cm:
            VM(capabilities=[]).load(r.wbc)
        self.assertIn("import host.Log needs capability 'console.write'", cm.exception.message)

    def test_e0104_misplaced_or_malformed(self):
        text = self.caps_module("""
@capability
extern func host.A()

@capability(3)
extern func host.B()

@capability("x", "y")
extern func host.C()

@capability("x")
func F() {
  exec Entry()
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
  node entry = Entry()
  node log = Call host.Log(
    .message <- "hi"
  )

  exec entry
  exec log
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
  func Tick(self) -> (n: i32) {
    node entry = Entry()
    node parent = CallParent Tick()
    node ret = Return(
      .n <- Mul#<i32>(
        .a <- parent
        .b <- 10
      )
    )

    exec entry
    exec parent
    exec ret
  }
}

class Ticker {
  items: array#<i32>

  func Greet(self) {
    node entry = Entry()
    node hi = Call host.Log(
      .message <- "hello"
    )
    node once = Macro std.flow.DoOnce()

    exec entry
    exec once
    exec hi
  }

  func Keep(self, x: i32) {
    node add = ArrayAdd#<i32> Ticker.items(
      .obj <- entry.self
      .item <- entry.x
    )
    node entry = Entry()

    exec entry
    exec add
  }

  func Tick(self) -> (n: i32) {
    state count: i32

    node entry = Entry()
    node ret = Return(
      .n <- GetState count()
    )
    node set = SetState count(
      .value <- Add#<i32>(
        .a <- GetState count()
        .b <- 1
      )
    )

    exec entry
    exec set
    exec ret
  }
}

func Fill(t: Ticker) -> (before: array#<i32>, after: array#<i32>) {
  local snap: array#<i32>

  node add = ArrayAdd#<i32> Ticker.items(
    .obj <- entry.t
    .item <- 2
  )
  node entry = Entry()
  @live
  node get = GetField Ticker.items(
    .obj <- entry.t
  )
  node keep = Call Ticker.Keep(
    .self <- entry.t
    .x <- 1
  )
  node ret = Return(
    .before <- GetLocal snap()
    .after <- get
  )
  node take = SetLocal snap(
    .value <- get
  )

  exec entry
  exec keep
  exec take
  exec add
  exec ret
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
class Lonely {
  func Tick(self) -> (n: i32) {
    node entry = Entry()
    node p = CallParent Tick()

    exec entry

    !exec p
  }
}

func Loose() {
  node entry = Entry()
  node p = CallParent Tick()

  exec entry

  !exec p
}
""")
        diags = sorted((d.graph, d.code) for d in check(parse(text)) if d.code.startswith("E"))
        self.assertEqual(diags, [("Lonely.Tick", "E0501"), ("Loose", "E0501")])

    def test_pure_functions_cannot_change_fields(self):
        text = gaps_text("""
@pure
func P(t: Ticker) {
  node add = ArrayAdd#<i32> Ticker.items(
    .item <- 1
    .obj <- entry.t
  )
  node entry = Entry()

  exec entry
  exec add
}
""")
        self.assertIn("E0302", codes(text))

    def test_parent_event_needs_a_latent_caller(self):
        text = module("""
class A {
  event Go(self) {
    node entry = Entry()

    exec entry
  }
}

class B : A {
  event Go(self) {
    node entry = Entry()
    node p = CallParent Go()

    exec entry
    exec p
  }
}
""", macros=False)
        self.assertEqual([c for c in codes(text) if c.startswith("E")], [])


DET = """
func Maths(x: f64) -> (s: f64, p: f64, mn: f64, mx: f64, nan_eq: bool) {
  node entry = Entry()
  node max = Max#<f64>(
    .a <- 0.0
    .b <- neg_zero
  )
  node min = Min#<f64>(
    .a <- 0.0
    .b <- neg_zero
  )
  node nan = Div#<f64>(
    .a <- 0.0
    .b <- 0.0
  )
  node nan_eq = Eq#<f64>(
    .a <- nan
    .b <- nan
  )
  node neg_zero = Neg#<f64>(
    .value <- 0.0
  )
  node pow = Call std.math.Pow(
    .a <- entry.x
    .b <- 0.5
  )
  node ret = Return(
    .s <- sin
    .p <- pow
    .mn <- min
    .mx <- max
    .nan_eq <- nan_eq
  )
  node sin = Call std.math.Sin(
    .x <- entry.x
  )

  exec entry
  exec ret
}

event Countdown() {
  node entry = Entry()
  node go = Call host.Log(
    .message <- "Go!"
  )
  node loop = Macro ForRange(
    .first <- 1
    .last <- 3
  )
  node say = Call host.Log(
    .message <- txt
  )
  node txt = Convert#<i32, string>(
    .value <- loop.index
  )
  node wait = Delay(
    .seconds <- 0.5
  )

  exec entry
  exec loop.done -> {
    exec go
  }.each -> {
    exec say
    exec wait
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

  func Set(self, n: i32) {
    exec Entry()
    exec SetField n(
      .obj <- self
      .value <- n
    )
    exec Broadcast Changed(
      .obj <- self
      .n <- n
    )
  }
}

event Wait(s: std.Signal) {
  exec Entry()
  exec Await(
    .signal <- s
  )
  exec Call host.Log(
    .message <- "woken"
  )
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
  exec Entry()
  exec Await(
    .signal <- s
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
        self.assertIn(".1/test.then.0:", text)
        self.assertIn("cont.push .1/test.then.1", text)
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
    .x <- 1
  )

  exec entry
  exec c
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
    .times <- 3
  )
  node flip = Macro std.flow.FlipFlop()
  node log_a = Call host.Log(
    .message <- "A"
  )
  node log_b = Call host.Log(
    .message <- "B"
  )
  node five = Macro std.flow.ForRange(
    .first <- 1
    .last <- 5
  )
  node limited = Macro std.flow.DoN(
    .n <- 2
  )
  node n_text = Convert#<i32, string>(
    .value <- limited.counter
  )
  node log_n = Call host.Log(
    .message <- n_text
  )

  exec entry
  exec rep.body -> {
    exec flip.a -> {
      exec log_a
    }.b -> {
      exec log_b
    }
  }.done -> {
    exec five.each -> {
      exec limited
      exec log_n
    }
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
            if phase == "ready" and f.endswith("SumTo") and node == "1.each.0":
                v = snapshot()[-1].pin_values()
                seen.append((v[("1.each.0.value.a", "value")], v[("1", "index")],
                             v[("1.each.0.value", "result")]))
        vm = VM(hook=hook)
        self.assertEqual(vm.call(vm.load(r.wbc), "SumTo", [3]), [6])
        self.assertEqual(seen, [(0, 1, 1), (1, 2, 3), (3, 3, 6)])

    def test_call_stack_and_locals(self):
        r = compile_module(parse(lesson("05_functions.wiret")), debug=True)
        stacks = []

        def hook(f, node, pending, depth, snapshot, phase):
            if phase == "ready" and f.endswith("Square") and node == "1":
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
  node n = Add#<i32>(
    .a <- 1
    .b <- 2
  )
  node log = Call host.Log(
    .message <- n
  )

  exec entry
  exec log
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
        self.assertEqual(top("add").label, "Add#<i32>")

    def test_wire_drop_filters_and_ranks(self):
        from wiret import palette
        items = palette.items(self.g, self.idx)
        fits = [i for i in items if palette.compatible(i, self.g, self.idx, "out", "i32")]
        self.assertTrue(all(palette.compatible(i, self.g, self.idx, "out", "i32") for i in fits))
        self.assertNotIn("Call host.Log", [i.label for i in fits])
        self.assertEqual(palette.rank(fits, "text")[0].label, "Convert#<i32, string> (to text)")
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
                line = lines[info["line"] - 1]
                if nid.rsplit(".", 1)[-1].isidentifier() and "." in nid:
                    pin = nid.rsplit(".", 1)[1]           # inline: the line of the input it feeds
                    self.assertRegex(line, rf"^\s*\.{pin} <- {info['what']}\b")
                else:                                     # an exec statement
                    self.assertRegex(line, rf"^\s*exec {info['what']}\b")
        self.assertEqual(r["nodes"]["Square"]["1"]["what"], "Return")

    def test_debug_run_records_frames_and_values(self):
        from wiret import webapi
        text = lesson("05_functions.wiret")
        r = json.loads(webapi.debug_run(text))
        self.assertTrue(r["ok"])
        self.assertEqual(r["output"], json.loads(webapi.run(text))["output"])
        self.assertFalse(r["truncated"])
        rets = [s for s in r["steps"] if (s["graph"], s["node"], s["phase"]) == ("Square", "1", "ready")]
        self.assertEqual(len(rets), 5)
        frames = [[r["frame_table"][i] for i in s["frames"]] for s in rets]
        self.assertEqual([(f["graph"], f["node"]) for f in frames[0]],
                         [("Main", "1.each.0.message.b.value"), ("Square", "1")])
        self.assertEqual([f[-1]["vars"] for f in frames][:2],
                         [[["x", "parameter", "i32", "1"]], [["x", "parameter", "i32", "2"]]])
        self.assertEqual([s["depth"] for s in rets], [1] * 5)
        self.assertEqual(r["counts"]["Square"]["1"], 5)
        # the output a step had seen grows as the run goes on
        self.assertEqual([s["out"] for s in rets], [0, 1, 2, 3, 4])

    def test_debug_run_fault_and_truncation(self):
        from wiret import webapi
        text = (lesson("02_variables.wiret").replace(".value <- Add#<i32>", ".value <- Div#<i32>")
                .replace(".b <- 5", ".b <- 0"))
        r = json.loads(webapi.debug_run(text))
        self.assertFalse(r["ok"])
        self.assertEqual(r["fault"], {"graph": "Main", "node": "2.value"})
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
        self.assertEqual((nodes["1"]["x"], nodes["1"]["y"]), (200, 0))
        self.assertEqual([p["label"] for p in nodes["1"]["ins"]],
                         ["", "break", "first = 1", "last = 5"])
        self.assertEqual([p["name"] for p in nodes["1"]["outs"]], ["each", "done", "index"])
        self.assertTrue(nodes["1"]["outs"][0]["exec"] and nodes["1"]["outs"][0]["filled"])
        self.assertIn({"exec": True, "from": ["1", "each"], "to": ["1.each.0", "in"], "color": "#f0f0f0"},
                      main["wires"])
        self.assertIn({"exec": False, "from": ["1.each.1.value", "result"], "to": ["1.each.1", "value"],
                       "color": "#1abc9c"}, main["wires"])
        self.assertTrue(nodes["1.each.1.value"]["pure"])
        self.assertEqual(nodes["0"]["header"], "#a93226")
        self.assertTrue(any(n["on"] is None and "Loops" in n["text"] for n in main["notes"]))
        r = json.loads(webapi.check(lesson("05_functions.wiret")))
        squared = next(n for g in r["graphs"] if g["name"] == "Main" for n in g["nodes"]
                       if n["id"] == "1.each.0.message.b.value")
        self.assertEqual(squared["opens"], "Square")

    def test_check_marks_problem_nodes_and_lays_out_new_ones(self):
        from wiret import webapi
        text = lesson("02_variables.wiret").replace(".b <- 5", '.b <- "x"')
        text = text.rstrip("}\n") + "\n\n  !Add#<i32>()\n}\n"
        r = json.loads(webapi.check(text))
        nodes = {n["id"]: n for n in r["graphs"][0]["nodes"]}
        self.assertEqual(nodes["2.value"]["diag"], "error")
        self.assertIsNone(nodes["1"]["diag"])
        # a node without a position is laid out automatically, and stays put on the next check
        first = (nodes["~0"]["x"], nodes["~0"]["y"])
        again = {n["id"]: n for n in json.loads(webapi.check(text + "\n"))["graphs"][0]["nodes"]}
        self.assertEqual((again["~0"]["x"], again["~0"]["y"]), first)

    def edit(self, source, graph, **req):
        from wiret import webapi
        return json.loads(webapi.edit(source, graph, json.dumps(req)))

    def test_edit_values(self):
        from wiret import webapi
        text = lesson("02_variables.wiret")
        r = self.edit(text, "Main", op="literal", node="2.value", pin="b", text="100")
        self.assertTrue(r["ok"])
        self.assertIn(".b <- 100", r["text"])
        self.assertEqual(r["text"], print_module(parse(r["text"])))          # canonical
        self.assertEqual(self.edit(text, "Main", op="literal", node="2.value", pin="b", text="1.5"),
                         {"ok": False, "message": "1.5 is not a valid i32"})
        r = self.edit(text, "Main", op="literal", node="2.value", pin="b", text="")
        self.assertNotIn(".b <-", r["text"].split("Add#<i32>")[1].split("exec Call")[0])
        self.assertEqual(json.loads(webapi.literal_prompt(text, "Main", "2.value", "b")),
                         {"type": "i32", "current": "5", "hint": ""})
        # a string needs no quotes
        r = self.edit(text, "Main", op="literal", node="3.message", pin="a", text='Score: "big"')
        self.assertIn('.a <- "Score: \\"big\\""', r["text"])
        # an enum member needs no type name, and must be a member
        pets = lesson("08_structs.wiret")
        self.assertIn("Happy, Hungry, Sleepy", json.loads(webapi.literal_prompt(pets, "Main", "3.value", "value"))["hint"])
        self.assertIn(".value <- Mood::Sleepy", self.edit(pets, "Main", op="literal", node="3.value", pin="value", text="Sleepy")["text"])
        self.assertIn("not a member of Mood", self.edit(pets, "Main", op="literal", node="3.value", pin="value", text="Bored")["message"])
        self.assertIn("has no typed value", self.edit(pets, "Main", op="literal", node="3.value", pin="obj", text="1")["message"])
        # a bool flips
        r = self.edit(lesson("03_decisions.wiret"), "CheckAge", op="disconnect", node="1", dir="in", pin="cond")
        r = self.edit(r["text"], "CheckAge", op="toggle", node="1", pin="cond")
        self.assertIn(".cond <- true", r["text"])
        r = self.edit(r["text"], "CheckAge", op="toggle", node="1", pin="cond")
        self.assertEqual(r["message"], "Set 1.cond = false")
        self.assertNotIn(".cond <-", r["text"])          # false is cond's default, so it is not written
        self.assertIn(".cond <- true", self.edit(r["text"], "CheckAge", op="toggle", node="1", pin="cond")["text"])

    def test_edit_values_verbatim(self):
        """A canvas text field sends the string as typed: spaces and quotes kept, never parsed."""
        text = lesson("02_variables.wiret")
        r = self.edit(text, "Main", op="literal", node="3.message", pin="a", text=' "hi" ',
                      verbatim=True)
        self.assertIn('.a <- " \\"hi\\" "', r["text"])
        r = self.edit(text, "Main", op="literal", node="3.message", pin="a", text="", verbatim=True)
        self.assertNotIn('.a <- "Your score', r["text"])          # empty: removed from the source
        # a wired input takes no value
        r = self.edit(text, "Main", op="literal", node="3.message", pin="b", text="x", verbatim=True)
        self.assertFalse(r["ok"])
        self.assertIn("is wired", r["message"])

    def test_input_editors(self):
        """The form control each unwired input shows on the canvas (graph_json ins[].editor)."""
        from wiret import webapi

        def editors(text, graph):
            g = next(x for x in json.loads(webapi.check(text))["graphs"] if x["name"] == graph)
            return {(n["id"], p["name"]): p.get("editor") for n in g["nodes"] for p in n["ins"]}

        ins = editors(lesson("02_variables.wiret"), "Main")
        self.assertEqual(ins[("2.value", "b")], {"kind": "int", "value": "5", "placeholder": None,
                                                 "min": -2**31, "max": 2**31 - 1})
        self.assertIsNone(ins[("2.value", "a")])                    # wired: no field
        self.assertEqual(ins[("3.message", "a")]["kind"], "text")
        self.assertEqual(ins[("3.message", "a")]["value"], "Your score is ")   # no quotes
        self.assertIsNone(ins[("3", "in")])                         # exec: no field
        mood = editors(lesson("08_structs.wiret"), "Main")[("3.value", "value")]
        self.assertEqual(mood["kind"], "enum")
        self.assertIn("Sleepy", mood["options"])

    def test_edit_wires(self):
        text = lesson("02_variables.wiret")
        # an i32 into a string input: a visible Convert node goes in between, and is selected
        now = "3.message.b.value"
        r = self.edit(text, "Main", op="connect", a=["3", "in", "message"], b=[now, "out", "value"],
                      geoms={now: [440, 420, 120], "3": [980, 0, 150]})
        self.assertTrue(r["ok"])
        self.assertEqual(r["select"], "3.message")             # written inline in 3.message
        # x: (440 + 120 + 980) / 2 - 60; the GetLocal, now read twice, gets a name
        self.assertIn("    .message <- Convert#<i32, string>{pos=(710, 250)}(\n"
                      "      .value <- score\n    )\n", r["text"])
        self.assertIn("  node score = GetLocal score{pos=(440, 420)}()\n", r["text"])
        # the Concat it replaced is wired to nothing, so it is kept after a `!`
        self.assertIn("  !Call std.string.Concat{pos=(780, 180)}(\n", r["text"])
        refused = {
            "Connect an output pin to an input pin.": (["2.value", "out", "result"], [now, "out", "value"]),
            "A node cannot be wired to itself.": (["2.value", "out", "result"], ["2.value", "in", "a"]),
            "Exec pins connect only to exec pins (E0120).": (["1", "out", "then"], ["2.value", "in", "a"]),
        }
        for message, (a, b) in refused.items():
            self.assertEqual(self.edit(text, "Main", op="connect", a=a, b=b), {"ok": False, "message": message})
        # the second SetLocal is skipped: it moves into a `!{ }` block that still goes on to
        # the Log, which is entered from two places now and so is named
        r = self.edit(text, "Main", op="connect", a=["1", "out", "then"], b=["3", "in", "in"])
        self.assertIn("  exec SetLocal score{pos=(200, 0)}(\n    .value <- 10\n  )\n  exec log\n",
                      r["text"])
        self.assertIn("  !{\n    exec SetLocal score{pos=(560, 0)}(\n", r["text"])
        self.assertIn("    goto log\n  }\n", r["text"])
        self.assertEqual(run(r["text"], "Main")[1], ["Your score is 10"])
        r = self.edit(r["text"], "Main", op="disconnect", node="1", dir="out", pin="then")
        self.assertIn("    )\n    exec log\n  }\n", r["text"])      # a name, once given, stays
        # dropped on a node: the first free input of the same type
        old = "2.value.a"
        self.assertEqual(self.edit(text, "Main", op="connect_to_node", a=[old, "out", "value"], node="2.value"),
                         {"ok": False, "message": ""})                    # both inputs are taken
        freed = self.edit(text, "Main", op="literal", node="2.value", pin="b", text="")["text"]
        r = self.edit(freed, "Main", op="connect_to_node", a=[old, "out", "value"], node="2.value")
        self.assertEqual(r["message"], "Bound 2.value.b = 2.value.a.value")
        # now read twice, the GetLocal is named
        self.assertIn("      .a <- score\n      .b <- score\n", r["text"])
        r = self.edit(text, "Main", op="disconnect", node="2.value", dir="out", pin="result")
        self.assertIn("  exec SetLocal score{pos=(560, 0)}()\n", r["text"])
        self.assertIn("  !Add#<i32>{pos=(360, 160)}(\n", r["text"])

    def test_edit_move_delete_and_comments(self):
        text = lesson("02_variables.wiret")
        r = self.edit(text, "Main", op="move", moves=[["0", 10.6, -20.2]])
        self.assertIn("exec Entry{pos=(11, -20)}()", r["text"])
        r = self.edit(text, "Main", op="delete", node="3.message.b")
        self.assertEqual(r["message"], "Deleted 3.message.b and 1 wire(s): "
                                       "3.message.b.result -> 3.message.b")
        self.assertIn('detached: "3.message.b"', r["text"])        # its note is kept
        self.assertIn("  !GetLocal score{pos=(440, 420)}()\n", r["text"])
        self.assertEqual(self.edit(text + "garbage(", "Main", op="move", moves=[]),
                         {"ok": False, "message": "Fix the parse error in the source before editing the graph."})
        # a node without a position gets one where it was drawn
        unplaced = text.replace("exec Entry{pos=(0, 0)}()", "exec Entry()")
        r = self.edit(unplaced, "Main", op="move", moves=[["1", 200, 0]])
        self.assertRegex(r["text"], r"exec Entry\{pos=\(-?\d+, -?\d+\)\}\(\)")
        # a // comment directly above a statement is kept through an edit
        kept = text.replace("  exec Entry{", "  // the start\n  exec Entry{")
        r = self.edit(kept, "Main", op="move", moves=[["0", 1, 1]])
        self.assertIn("  // the start\n  exec Entry{pos=(1, 1)}()\n", r["text"])
        # one attached to nothing cannot be kept: ask first, then convert it to a note
        commented = text.replace("func Main() {", "func Main() {\n  // keep me\n")
        self.assertEqual(self.edit(commented, "Main", op="move", moves=[["0", 1, 1]]),
                         {"ok": False, "comments": 1})
        r = self.edit(commented, "Main", op="move", moves=[["0", 1, 1]], comments="convert")
        self.assertIn('@note("keep me")', r["text"])

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
        self.assertEqual(r["items"][0]["label"], "Mul#<i32>")
        self.assertEqual(r["items"][0]["description"], "Multiplies: a × b.")
        # the same ranking as the desktop palette
        m = parse(text)
        idx = ModuleIndex(m)
        desktop = [it.label for it in palette.rank(palette.items(m.graph("Main"), idx), "mul")]
        self.assertEqual([it["label"] for it in r["items"]], desktop[:200])
        self.assertEqual(r["total"], len(palette.items(m.graph("Main"), idx)))
        # from a dragged pin: only what fits it
        r = json.loads(webapi.palette(text, "Main", "", json.dumps(["3", "in", "message"])))
        self.assertEqual(r["title"], "Add a node for 3.message (text (string))")
        self.assertIn("Call std.string.Concat", [it["label"] for it in r["items"]])
        self.assertNotIn("Mul#<i32>", [it["label"] for it in r["items"]])
        self.assertEqual(webapi.palette(text, "Main", "", json.dumps(["3", "in", "nope"])), "null")
        self.assertEqual(webapi.palette(text + "(", "Main"), "null")
        # adding: at the point given, wired to nothing yet, so after a `!`
        r = self.edit(text, "Main", op="add", kind="Mul", symbol=None, targs=["i32"], x=10, y=20)
        self.assertEqual((r["message"], r["select"]), ("Added ~0", "~0"))
        self.assertIn("  !Mul#<i32>{pos=(10, 20)}()\n", r["text"])
        # wired to the dragged pin (a producer goes to its left)
        r = self.edit(text, "Main", op="add", kind="Call", symbol="std.string.Concat", targs=[],
                      x=500, y=300, context=["3", "in", "message"])
        self.assertEqual(r["select"], "3.message")
        self.assertIn("    .message <- Call std.string.Concat{pos=(300, 300)}()\n", r["text"])
        r = self.edit(text, "Main", op="add", kind="Branch", symbol=None, targs=[], x=300, y=200,
                      context=["1", "out", "then"])
        self.assertEqual(r["select"], "2")
        self.assertIn("  exec Branch{pos=(300, 200)}()\n", r["text"])

    def test_graph_nodes_carry_descriptions(self):
        from wiret import webapi
        nodes = {n["id"]: n for n in json.loads(webapi.check(lesson("02_variables.wiret")))["graphs"][0]["nodes"]}
        self.assertEqual(nodes["2.value"]["description"], "Adds two numbers: a + b.")

    def menu(self, source, graph, **target):
        from wiret import webapi
        return json.loads(webapi.menu(source, graph, json.dumps(target)))

    @staticmethod
    def labels(entries):
        return ["---" if e.get("sep") else f"[{e['label']}]" if e.get("header") else e["label"]
                for e in entries]

    def test_menus_follow_the_desktop(self):
        pets = lesson("08_structs.wiret")
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="3.value", dir="in", pin="value")),
                         ["[Set 'value' to]", "Mood::Happy", "Mood::Hungry", "Mood::Sleepy", "Disconnect",
                          "---", "[3.value  (WithField)]", "Breakpoint  (F9)", "Name…", "Label…",
                          "Colour…", "Add note…", "Disable (@disabled)", "---", "Delete node"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="3.value", dir="in", pin="obj"))[:2],
                         ["Make a Pet for 'obj'", "Disconnect"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="pin", node="1.value", dir="out", pin="result"))[:2],
                         ["Break 'result' into fields", "Disconnect"])
        name = self.menu(pets, "Main", kind="pin", node="1.value", dir="in", pin="name")[0]
        self.assertEqual(name, {"label": "Set literal for 'name'…", "client": "editPin", "node": "1.value",
                                "pin": "name"})
        self.assertIn("Name…", self.labels(self.menu(pets, "Main", kind="node", node="3")))
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="canvas", x=5, y=6)),
                         ["Search nodes…   (Tab)", "---", "Add box here…", "Add graph note…", "Add local…"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="wire", wire="d|3|value")), ["Delete wire"])
        self.assertEqual(self.labels(self.menu(pets, "Main", kind="note", note="3.value|0")), ["Edit note…", "Delete note"])
        entry = self.menu(pets, "Main", kind="node", node="0")
        self.assertNotIn("Disable (@disabled)", self.labels(entry))
        self.assertEqual(entry[-1]["confirm"], "Delete the graph's Entry node?")
        calls = self.labels(self.menu(lesson("05_functions.wiret"), "Main", kind="node",
                                      node="1.each.0.message.b.value"))
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
        node = {"kind": "node", "node": "1.value"}
        self.assertIn(".value <- Mood::Sleepy", run({"kind": "pin", "node": "3.value", "dir": "in", "pin": "value"}, "Mood::Sleepy")["text"])
        r = run({"kind": "pin", "node": "3.value", "dir": "in", "pin": "obj"}, "Make a Pet for 'obj'", geoms={"3.value": [300, 0, 150]})
        self.assertEqual(r["select"], "3.value.obj")
        self.assertIn("      .obj <- MakeStruct Pet{pos=(80, 0)}()\n", r["text"])
        r = run({"kind": "pin", "node": "1.value", "dir": "out", "pin": "result"}, "Break 'result' into fields", geoms={"1.value": [0, 160, 120]})
        self.assertIn("BreakStruct Pet{pos=(180, 160)}(", r["text"])
        # naming a node declares it at the top of the function, after the names already there
        r = run({"kind": "node", "node": "3"}, "Name…", "store")
        self.assertEqual((r["message"], r["select"]), ("Renamed 3 to store", "store"))
        self.assertIn("  node store = SetLocal pet{pos=(640, 0)}(\n", r["text"])
        self.assertIn("  exec store\n", r["text"])
        self.assertEqual(run({"kind": "node", "node": "3"}, "Name…", "2x"),
                         {"ok": False, "message": "Not a valid name."})
        self.assertIn('label="Feed"', run(node, "Label…", "Feed")["text"])
        self.assertIn('color="#C0392B"', run(node, "Colour…", "#c0392b")["text"])
        self.assertEqual(run(node, "Colour…", "red")["message"], "Use the form #RRGGBB.")
        # a semantic decorator stands above the node, which stays where it is written
        self.assertIn('    @disabled\n    .value <- MakeStruct Pet{pos=(-105, 81)}(\n',
                      run(node, "Disable (@disabled)")["text"])
        self.assertIn('    @note("Hi")\n    .value <- MakeStruct Pet', run(node, "Add note…", "Hi")["text"])
        r = run({"kind": "canvas", "x": 10, "y": 20}, "Add box here…", "Pets")
        self.assertIn('  box {title="Pets", pos=(10, 20), size=(360, 220)}\n', r["text"])
        box = {"kind": "box", "box": "box.0"}
        self.assertIn("size=(500, 300)", run(box, "Resize…", "500, 300", source=r["text"])["text"])
        self.assertEqual(run(box, "Resize…", "big", source=r["text"])["message"], "Enter the width and height, as in 360, 220.")
        self.assertIn('box {title="Cats"', run(box, "Rename title…", "Cats", source=r["text"])["text"])
        self.assertIn("local count: i32", run({"kind": "canvas"}, "Add local…", "count: i32")["text"])
        self.assertIn("Use a valid name", run({"kind": "canvas"}, "Add local…", "x: Nope")["message"])
        self.assertIn('@note("Short")', run({"kind": "note", "note": "3.value|0"}, "Edit note…", "Short")["text"])
        self.assertNotIn("WithField makes a copy", run({"kind": "note", "note": "3.value|0"}, "Delete note")["text"])

    def test_menu_counts_and_cases(self):
        text = """wiret 1
module m

extern func host.Log(message: string)

enum Mode {
  Idle
  Chase
}

func Main() {
  exec Entry()
  exec Sequence()

  !exec Switch#<Mode>()
}
"""
        seq = self.menu(text, "Main", kind="node", node="1")
        e = next(e for e in seq if e["label"] == "Set output count (#count)…")
        self.assertEqual(e["ask"], {"label": "Number of outputs:", "value": "2"})
        r = self.edit(text, "Main", **{**e["action"], "text": "3"})
        self.assertIn("  exec Sequence#count<3>{pos=(250, 0)}()\n", r["text"])
        self.assertEqual(self.edit(text, "Main", **{**e["action"], "text": "99"})["message"],
                         "Enter a whole number from 1 to 64.")
        # "+ Add pin" on a Switch: a case with the first member no case has yet
        e = next(e for e in self.menu(text, "Main", kind="node", node="~0") if e["label"] == "Add pin")
        r = self.edit(text, "Main", **e["action"])
        self.assertIn("!exec Switch#<Mode>#cases<1>{pos=", r["text"])
        self.assertIn(").case[0] Mode::Idle -> {}\n", r["text"])
        r = self.edit(r["text"], "Main", op="add_pin", node="~0")
        self.assertIn(").case[0] Mode::Idle -> {}.case[1] Mode::Chase -> {}\n", r["text"])
        # every member taken: the new case has no value yet, and says so
        r = self.edit(r["text"], "Main", op="add_pin", node="~0")
        self.assertIn(".case[2] -> {}\n", r["text"])
        # Remove pin on case[0]: the later cases move down, keeping their values
        pins = self.menu(r["text"], "Main", kind="pin", node="~0", dir="out", pin="case[0]")
        e = next(e for e in pins if e.get("label") == "Remove pin 'case[0]'")
        r = self.edit(r["text"], "Main", **e["action"])
        self.assertIn("!exec Switch#<Mode>#cases<2>{pos=", r["text"])
        self.assertIn(").case[0] Mode::Chase -> {}.case[1] -> {}\n", r["text"])
        self.assertFalse(any(e.get("label", "").startswith("Remove pin") for e in
                             self.menu(r["text"], "Main", kind="pin", node="~0", dir="out",
                                       pin="default")))
        # and on a Sequence: one more `then`
        r = self.edit(text, "Main", op="add_pin", node="1")
        self.assertIn("  exec Sequence#count<3>{pos=(250, 0)}()\n", r["text"])


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
        lines += ["  goto exec", '@note("x")',
                  '  .a <- "say \\"hi\\" // not a comment"', "  // a comment with \"quotes\" and 12",
                  "  .b <- -3.5e2", "  exec Sequence#count<2>()", "@pure", "  .s <- \"unfinished",
                  "var x: i32 = 0x1F", "  !exec box"]
        expect = [[list(s) for s in syntax.spans(line)] for line in lines]
        self.assertGreater(sum(map(len, expect)), 1000)
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

func Angle(a: quat, b: quat) -> (r: f32) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.quat.Angle(
      .a <- entry.a
      .b <- entry.b
    )
  )

  exec entry
  exec ret
}

@pure
func Arith(a: vec2, b: vec2) -> (sub: vec2, mul: vec2, div: vec2, min: vec2, max: vec2, neg: vec2, abs: vec2) {
  node entry = Entry()
  node ret = Return(
    .sub <- Sub#<vec2>(
      .a <- entry.a
      .b <- entry.b
    )
    .mul <- Mul#<vec2>(
      .a <- entry.a
      .b <- entry.b
    )
    .div <- Div#<vec2>(
      .a <- entry.a
      .b <- entry.b
    )
    .min <- Min#<vec2>(
      .a <- entry.a
      .b <- entry.b
    )
    .max <- Max#<vec2>(
      .a <- entry.a
      .b <- entry.b
    )
    .neg <- Neg#<vec2>(
      .value <- entry.a
    )
    .abs <- Abs#<vec2>(
      .value <- entry.b
    )
  )

  exec entry
  exec ret
}

@pure
func Compose(a: quat, b: quat, v: vec3) -> (r: vec3) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.quat.Rotate(
      .q <- Mul#<quat>(
        .a <- entry.a
        .b <- entry.b
      )
      .v <- entry.v
    )
  )

  exec entry
  exec ret
}

@pure
func Converts(v: vec3) -> (flat: vec2, up: vec3, text: string) {
  node entry = Entry()
  node ret = Return(
    .flat <- Convert#<vec3, vec2>(
      .value <- entry.v
    )
    .up <- Convert#<vec2, vec3>(
      .value <- (7, 8)
    )
    .text <- Format "at {v}"(
      .v <- entry.v
    )
  )

  exec entry
  exec ret
}

func Defaults() -> (body: Body, t: transform, q: quat, at: vec3) {
  node entry = Entry()
  node mk = New Mover()
  node ret = Return(
    .body <- MakeStruct Body()
    .t <- MakeStruct transform(
      .translation <- (1, 0, 0)
    )
    .q <- MapFind#<string, quat>(
      .key <- "none"
    ).value
    .at <- GetField Mover.at(
      .obj <- mk
    )
  )

  exec entry
  exec mk
  exec ret
}

@pure
func Fields(v: vec3, t: transform) -> (y: f32, moved: vec3, rot: quat, x: f32, z: f32) {
  node entry = Entry()
  node parts = BreakStruct vec3(
    .obj <- entry.v
  )
  node ret = Return(
    .y <- GetField vec3.y(
      .obj <- entry.v
    )
    .moved <- WithField vec3.z(
      .obj <- entry.v
      .value <- 9
    )
    .rot <- GetField transform.rotation(
      .obj <- entry.t
    )
    .x <- parts.x
    .z <- parts.z
  )

  exec entry
  exec ret
}

func Keyed(v: vec3) -> (n: i32) {
  local seen: map#<vec3, i32>

  node entry = Entry()
  node put = MapSet#<vec3, i32> seen(
    .key <- (1, 2, 3)
    .value <- 42
  )
  node ret = Return(
    .n <- MapFind#<vec3, i32>(
      .map <- GetLocal seen()
      .key <- entry.v
    ).value
  )

  exec entry
  exec put
  exec ret
}

@pure
func PerpDot(a: vec2, b: vec2) -> (r: f32) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.vec.PerpDot(
      .a <- entry.a
      .b <- entry.b
    )
  )

  exec entry
  exec ret
}

@pure
func Pick(c: bool) -> (r: vec3) {
  node entry = Entry()
  node ret = Return(
    .r <- Select#<vec3>(
      .cond <- entry.c
      .a <- GetVar Up()
      .b <- (0, -1, 0)
    )
  )

  exec entry
  exec ret
}

func Place(p: vec3) -> (r: vec3) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.transform.Apply(
      .t <- GetVar spawn()
      .p <- entry.p
    )
  )

  exec entry
  exec ret
}

@pure
func QuatLib(q: quat) -> (conj: quat, inv: quat, norm: quat) {
  node entry = Entry()
  node ret = Return(
    .conj <- Call std.quat.Conjugate(
      .q <- entry.q
    )
    .inv <- Call std.quat.Inverse(
      .q <- entry.q
    )
    .norm <- Call std.quat.Normalize(
      .q <- entry.q
    )
  )

  exec entry
  exec ret
}

@pure
func Same(a: vec3, b: vec3) -> (eq: bool, ne: bool) {
  node entry = Entry()
  node ret = Return(
    .eq <- Eq#<vec3>(
      .a <- entry.a
      .b <- entry.b
    )
    .ne <- Ne#<vec3>(
      .a <- entry.a
      .b <- entry.b
    )
  )

  exec entry
  exec ret
}

func Slerp(a: quat, b: quat, t: f32) -> (r: quat) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.quat.Slerp(
      .a <- entry.a
      .b <- entry.b
      .t <- entry.t
    )
  )

  exec entry
  exec ret
}

@pure
func Step(p: vec3, v: vec3, dt: f32) -> (r: vec3) {
  node entry = Entry()
  node ret = Return(
    .r <- Add#<vec3>(
      .a <- entry.p
      .b <- Scale#<vec3>(
        .v <- entry.v
        .s <- entry.dt
      )
    )
  )

  exec entry
  exec ret
}

@pure
func TLib(a: transform, b: transform, p: vec3) -> (both: vec3, back: vec3, dir: vec3) {
  node entry = Entry()
  node ret = Return(
    .both <- Call std.transform.Apply(
      .t <- Mul#<transform>(
        .a <- entry.a
        .b <- entry.b
      )
      .p <- entry.p
    )
    .back <- Call std.transform.Apply(
      .t <- Call std.transform.Inverse(
        .t <- entry.a
      )
      .p <- Call std.transform.Apply(
        .t <- entry.a
        .p <- entry.p
      )
    )
    .dir <- Call std.transform.ApplyVector(
      .t <- entry.a
      .v <- entry.p
    )
  )

  exec entry
  exec ret
}

func Turn(axis: vec3, angle: f32, v: vec3) -> (r: vec3) {
  node entry = Entry()
  node ret = Return(
    .r <- Call std.quat.Rotate(
      .q <- Call std.quat.FromAxisAngle(
        .axis <- entry.axis
        .angle <- entry.angle
      )
      .v <- entry.v
    )
  )

  exec entry
  exec ret
}

@pure
func VecLib(a: vec3, b: vec3) -> (dot: f32, cross: vec3, len: f32, dist: f32, norm: vec3, lerp: vec3, refl: vec3) {
  node entry = Entry()
  node ret = Return(
    .dot <- Call std.vec.Dot#<vec3>(
      .a <- entry.a
      .b <- entry.b
    )
    .cross <- Call std.vec.Cross(
      .a <- entry.a
      .b <- entry.b
    )
    .len <- Call std.vec.Length#<vec3>(
      .v <- entry.a
    )
    .dist <- Call std.vec.Distance#<vec3>(
      .a <- entry.a
      .b <- entry.b
    )
    .norm <- Call std.vec.Normalize#<vec3>(
      .v <- entry.a
    )
    .lerp <- Call std.vec.Lerp#<vec3>(
      .a <- entry.a
      .b <- entry.b
      .t <- 0.25
    )
    .refl <- Call std.vec.Reflect#<vec3>(
      .v <- entry.a
      .n <- GetVar Up()
    )
  )

  exec entry
  exec ret
}
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
        # Mul#<quat>(a, b) rotates by b, then a
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
        for kind in ("Add#<quat>", "Rem#<vec3>", "Lt#<vec3>", "Div#<transform>"):
            with self.subTest(kind=kind):
                self.assertIn("E0110", c(f"@pure\nfunc F(a: quat) -> (r: bool) = Eq#<bool>(\n"
                                         f"  .a <- {kind}(\n    .a <- a,\n    .b <- a,\n  ),\n"
                                         f"  .b <- true,\n)\n"))
        self.assertIn("E0110", c("@pure\nfunc F(a: quat) -> (r: quat) = Scale#<quat>(\n"
                                 "  .v <- a,\n  .s <- 2,\n)\n"))
        self.assertIn("E0110", c("@pure\nfunc F() -> (r: vec3) = Add#<vec3>(\n"
                                 "  .a <- (1, 2),\n  .b <- (1, 2, 3),\n)\n"))
        self.assertIn("E0502", c("@pure\nfunc F(a: vec3) -> (r: f32) = Call std.vec.Dot(\n"
                                 "  .a <- a,\n  .b <- a,\n)\n"))
        self.assertIn("E0110", c("@pure\nfunc F(a: quat) -> (r: vec3) = Convert#<quat, vec3>(\n"
                                 "  .value <- a,\n)\n"))
        self.assertIn("E0501", c("func F(a: vec3) {\n  exec Entry()\n  exec SetField vec3.x(\n"
                                 "    .obj <- a\n    .value <- 1\n  )\n}\n"))
        with self.assertRaises(ParseError):
            parse(module('const A: vec3 = (0, "1", 0)\n', macros=False))

    def test_runner_arguments(self):
        from wiret.runner import format_value, lit_value
        from wiret.parser import parse_literal
        self.assertEqual(lit_value(parse_literal("(1, 2, 3)"), "vec3", "p"), (1.0, 2.0, 3.0))
        with self.assertRaises(ValueError):
            lit_value(parse_literal("(1, 2)"), "vec3", "p")
        self.assertEqual(format_value("vec3", (1.0, 2.5, 0.0)), "(1.0, 2.5, 0.0)")


class TextChangesTests(unittest.TestCase):
    """What the Source pane flashes after a graph edit (wiret/textchanges.py)."""

    def setUp(self):
        from wiret.textchanges import changes
        self.changes = changes
        self.text = "func Main() {\n  exec Entry{pos=(0, 0)}()\n  exec Call host.Log{pos=(200, 0)}(\n" \
                    "    .message <- \"Hi\"\n  )\n}\n"

    def test_changed_number_is_shown_whole(self):
        new = self.text.replace("(200, 0)", "(220, 40)")
        self.assertEqual(self.changes(self.text, new), {"lines": [3], "spans": [[3, 26, 33]]})

    def test_inserted_line_is_marked_without_its_indent(self):
        new = self.text.replace('"Hi"\n', '"Hi"\n    .level <- 2\n')
        self.assertEqual(self.changes(self.text, new), {"lines": [5], "spans": [[5, 4, 15]]})

    def test_deleted_lines_mark_where_they_were(self):
        new = self.text.replace('    .message <- "Hi"\n', "")
        self.assertEqual(self.changes(self.text, new), {"lines": [4], "spans": []})

    def test_no_change(self):
        self.assertEqual(self.changes(self.text, self.text), {"lines": [], "spans": []})


if __name__ == "__main__":
    unittest.main()
