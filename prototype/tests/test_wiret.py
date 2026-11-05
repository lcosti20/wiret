"""Prototype test suite (spec sections 1.6 Tier 0 and 7.4).

Run from `prototype/`:  python3 -m unittest discover tests
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wiret import wbc  # noqa: E402
from wiret.checker import check  # noqa: E402
from wiret.compiler import compile_module  # noqa: E402
from wiret.disasm import disassemble  # noqa: E402
from wiret.flow import view_flow  # noqa: E402
from wiret.model import note_detached, note_text, notes  # noqa: E402
from wiret.ops import add_note, convert_comments, delete_box, delete_node  # noqa: E402
from wiret.parser import ParseError, parse  # noqa: E402
from wiret.printer import layout_hash, print_module, semantic_hash  # noqa: E402
from wiret.vm import VM, WiretError  # noqa: E402

DEMO = os.path.join(os.path.dirname(HERE), "examples", "demo.wiret")


def demo() -> str:
    with open(DEMO, encoding="utf-8") as f:
        return f.read()

FOR_RANGE = """
macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32
  node bump = SetLocal i
    .value <- nxt.result
  node cmp = Le::<i32>
    .a <- cur.value
    .b <- entry.last
  node cur = GetLocal i
  node each_out = Exit each
    .index <- cur.value
  node entry = Entry
  node finish = Exit done
  node init = SetLocal i
    .value <- entry.first
  node nxt = Add::<i32>
    .a <- cur.value
    .b <- 1
  node seq = Sequence @count(2)
  node test = Branch
    .cond <- cmp.result

  flow {
    bump -> test
    entry -> init
    init -> test
    seq.then0 -> each_out
    seq.then1 -> bump
    test.then -> seq
    test.else -> finish
  }
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
  node ret   = Return
      .y   <-   s.result
  node entry = Entry
  node s     = Add::<i32>

    .b <- 0x10
  .a <- entry.x

  flow {
    entry.then -> ret
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn("node entry = Entry\n", out)
        self.assertIn("  flow {\n    entry -> ret\n  }\n", out)
        self.assertIn("  node s = Add::<i32>\n    .a <- entry.x\n    .b <- 16\n", out)
        self.assertEqual(print_module(parse(out)), out)

    def test_unknown_metadata_and_layout_props_survive(self):
        text = module("""
#[x.acme.review("ok", level: 2)]
func F() {
  #[Hash(1)]
  node entry = Entry
  layout {
    entry at (1, 2) [label = "Start", x.acme.pin = [a, b]]
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn('#[x.acme.review("ok", level: 2)]\nfunc F() {', out)
        self.assertIn("  #[Hash(1)]\n  node entry = Entry", out)
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
  #[doc("the start")]
  node entry = Entry
  layout {
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
        self.assertIn('  #[doc("the start")]\n  node entry = Entry\n', out)
        self.assertIn('    #[note("a group")]\n    box g "G"', out)
        self.assertEqual(print_module(parse(out)), out)
        self.assertEqual(m.graph("F").meta[0].name, "note")   # the model keeps written order

    def test_metadata_must_touch_its_statement(self):
        for body, hint in (('#[note("x")]\n\n  node entry = Entry', "no blank line"),
                           ('node entry = Entry\n  #[note("x")]', "directly above"),
                           ('node entry = Entry\n  flow {\n    #[note("x")]\n    entry -> entry\n  }',
                            "flow wires"),
                           ('node entry = Entry\n  layout {\n    #[note("x")]\n    entry at (0, 0)\n  }',
                            "'box' line"),
                           ('#[note("x")] node entry = Entry', "next line")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)

    def test_markup_block_is_rejected_with_a_hint(self):
        with self.assertRaises(ParseError) as cm:
            parse(module("\nfunc F() {\n  node entry = Entry\n  markup {\n"
                         '    attribute a = Note(message: "x")\n  }\n}\n', macros=False))
        self.assertIn('#[note(', cm.exception.msg)

    def test_at_doc_is_e0104_with_a_hint(self):
        text = module('\nfunc F() @doc("x") {\n  node entry = Entry @x.acme.review\n}\n',
                      macros=False)
        diags = [d for d in check(parse(text)) if d.code == "E0104"]
        self.assertEqual(len(diags), 2)
        self.assertIn("#[doc(", diags[0].message)
        self.assertEqual(diags[1].node, "entry")

    def test_inputs_go_on_their_own_lines(self):
        text = module("""
func F() {
  node entry = Entry
  node log = Call host.Log
    .message <- "hi"

  flow {
    entry -> log
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn('  node log = Call host.Log\n    .message <- "hi"\n', out)
        self.assertEqual(out, text)

    def test_old_syntax_is_rejected_with_a_hint(self):
        for body, hint in (('node log = Call host.Log(message: "hi")', ".pin <- value"),
                           ("node a = Add<i32>", "Add::<i32>"),
                           ("local xs: array<i32>", "array::<i32>"),
                           ('node log = Call host.Log .message <- "hi"', "end of line")):
            with self.subTest(body):
                with self.assertRaises(ParseError) as cm:
                    parse(module(f"\nfunc F() {{\n  {body}\n}}\n", macros=False))
                self.assertIn(hint, cm.exception.msg)
        with self.assertRaises(ParseError) as cm:
            parse(module("\nmacro M<T>(in: exec) {\n}\n", macros=False))
        self.assertIn("::<", cm.exception.msg)

    def test_comments_are_reported_and_convertible(self):
        text = module("""
func F() {
  // explain the entry
  node entry = Entry
}
""", macros=False)
        m = parse(text)
        self.assertIn("W0603", {d.code for d in check(m)})
        convert_comments(m)
        out = print_module(m)
        self.assertIn('  #[note("explain the entry")]\n  node entry = Entry', out)

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
  node entry = Entry
  node log = Call host.Log
    .message <- "hi"

  flow {
    entry -> log
  }
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
  node entry = Entry
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
  node entry = Entry
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
                          ("class C {\n}\n", "Tier 2"),
                          ("interface I {\n}\n", "Tier 2")):
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
  node entry = Entry
}
"""
        self.assertEqual(self.found(body), [])
        # They check, but cannot be lowered yet: compiling says so instead of crashing.
        r = compile_module(parse(module(body, macros=False)))
        self.assertFalse(r.ok)
        self.assertEqual({d.graph for d in r.diags if d.code == "E0501"}, {"mode", "Move"})
        self.assertTrue(all("cannot compile struct and enum" in d.message for d in r.diags))

    def test_unknown_types(self):
        diags = self.diags("""
struct S {
  a: Vector
  b: array::<Nope>
  c: t.S
  d: exec
}

func F(x: Missing) {
  node entry = Entry
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
        diags += compile_module(parse(module("\nstruct V {}\n\nvar v: V\n", macros=False))).diags
        self.assertEqual(len(diags), 10)
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
  mode: Mode = Mode.Idle
  hp: i32 = 10
}

struct Vec2 {
  x: f32
  y: f32 = 1.5
}

func Spawn() -> (e: Enemy) @pure {
  node entry = Entry
  node origin = MakeStruct Vec2
  node r = Return
    .e <- spawn.result
  node spawn = MakeStruct Enemy
    .pos <- origin.result
    .mode <- Mode.Chase

  flow {
    entry -> r
  }
}

func Step(e: Enemy) -> (out: Enemy, fleeing: bool) {
  node back = Convert::<u8, Mode>
    .value <- code.result
  node chased = WithField Enemy.pos
    .obj <- entry.e
    .value <- moved.result
  node code = Convert::<Mode, u8>
    .value <- mode.value
  node entry = Entry
  node is_flee = Eq::<Mode>
    .a <- mode.value
    .b <- Mode.Flee
  node later = Lt::<Mode>
    .a <- mode.value
    .b <- Mode.Flee
  node mode = GetField Enemy.mode
    .obj <- entry.e
  node moved = MakeStruct Vec2
    .x <- nx.result
    .y <- parts.y
  node nx = Add::<f32>
    .a <- parts.x
    .b <- 1
  node parts = BreakStruct Vec2
    .obj <- pos.value
  node pick = Select::<Mode>
    .cond <- same.result
    .a <- Mode.Idle
    .b <- back.result
  node pos = GetField Enemy.pos
    .obj <- entry.e
  node r1 = Return
    .out <- chased.result
    .fleeing <- is_flee.result
  node r2 = Return
    .out <- entry.e
    .fleeing <- later.result
  node same = Eq::<Enemy>
    .a <- entry.e
    .b <- chased.result
  node sw = Switch::<Mode> @cases(Mode.Idle, Mode.Chase)
    .value <- pick.result

  flow {
    entry -> sw
    sw.case0 -> r1
    sw.case1 -> r1
    sw.default -> r2
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
                          "  node entry = Entry\n" + nodes + "}\n")

    def test_program_checks_and_round_trips(self):
        text = module(STRUCT_NODES, macros=False)
        m = parse(text)
        self.assertEqual(print_module(m), text)
        self.assertEqual(codes(text), [])
        g = m.graph("Step")
        self.assertEqual(g.node("is_flee").binding("b").value.kind, "enum")
        self.assertEqual(g.node("sw").attr("cases").args[1][1].kind, "enum")
        enemy = next(it for it in m.items if it.name == "Enemy")
        self.assertEqual(enemy.field("mode").default.kind, "enum")
        # MakeStruct inputs default to the field's declared default, else to the zero value
        spawn = parse(text.replace("    .mode <- Mode.Chase\n",
                                   "    .mode <- Mode.Idle\n    .hp <- 10\n"))
        self.assertEqual(print_module(spawn), text.replace("    .mode <- Mode.Chase\n", ""))

    def test_pins(self):
        from wiret.registry import ModuleIndex, signature
        m = parse(module(STRUCT_NODES, macros=False))
        idx, g = ModuleIndex(m), m.graph("Step")

        def pins(nid):
            s = signature(g.node(nid), g, idx)
            return ([(p.name, p.type) for p in s.inputs], [(p.name, p.type) for p in s.outputs],
                    s.purity)

        self.assertEqual(pins("parts"), ([("obj", "Vec2")], [("x", "f32"), ("y", "f32")], "pure"))
        self.assertEqual(pins("moved"), ([("x", "f32"), ("y", "f32")], [("result", "Vec2")],
                                         "pure"))
        self.assertEqual(pins("mode"), ([("obj", "Enemy")], [("value", "Mode")], "pure"))
        self.assertEqual(pins("chased"), ([("obj", "Enemy"), ("value", "Vec2")],
                                          [("result", "Enemy")], "pure"))

    def test_struct_node_errors(self):
        self.assertEqual(self.graph_errors("""
  node a = GetField Enemy
  node b = GetField Nope.x
  node c = GetField Mode.Idle
  node d = GetField Enemy.zz
  node f = MakeStruct Vec2::<i32>
  node g = MakeStruct Enemy.pos
  node h = BreakStruct
  node i = SetField Enemy.hp
  node j = GetField Enemy.hp
    .obj <- entry.v
"""), [("E0110", "j", "obj")] + [("E0501", x, "") for x in "abcdfghi"])

    def test_enum_values(self):
        self.assertEqual(self.graph_errors("""
  node a = Eq::<Mode>
    .a <- entry.m
    .b <- Mode.Run
  node b = Eq::<i32>
    .a <- 1
    .b <- Mode.Idle
  node c = Eq::<Mode>
    .a <- entry.m
    .b <- 1
  node d = Eq::<Mode>
    .a <- entry.m
    .b <- Mood.Idle
""", decls="\nvar ok: Mode = Mode.Chase\n\nvar bad: Mode = Mode.Zip\n"),
            [("E0101", "d", "b"), ("E0110", "b", "b"), ("E0110", "c", "b"),
             ("E0501", "a", "b"), ("E0501", "bad", "bad")])
        self.assertEqual(self.found("""
enum A {
  X
}

enum B {
  Y
}

struct S {
  a: A = A.Nope
  b: A = B.Y
}

func F(p: A = B.Y) {
  local l: A = A.X
  node entry = Entry
}
"""), [("E0110", "F", "p"), ("E0110", "S", "b"), ("E0501", "S", "a")])

    def test_enum_aware_kinds(self):
        self.assertEqual(self.graph_errors("""
  node lt = Lt::<Mode>
    .a <- entry.m
    .b <- Mode.Idle
  node sel = Select::<Vec2>
    .a <- entry.v
    .b <- entry.v
  node eq = Eq::<Vec2>
    .a <- entry.v
    .b <- entry.v
  node to_int = Convert::<Mode, u8>
    .value <- entry.m
  node bad_lt = Lt::<Vec2>
    .a <- entry.v
    .b <- entry.v
  node bad_add = Add::<Mode>
    .a <- entry.m
    .b <- entry.m
  node bad_conv = Convert::<Mode, i32>
    .value <- entry.m
  node bad_text = Convert::<Mode, string>
    .value <- entry.m
  node bad_struct = Convert::<Vec2, i32>
    .value <- entry.v
"""), [("E0110", x, "") for x in ("bad_add", "bad_conv", "bad_lt", "bad_struct", "bad_text")])

    def test_switch_cases(self):
        self.assertEqual(self.graph_errors("""
  node a = Switch::<Mode> @cases(Mode.Idle, 3, Mode.Nope)
    .value <- entry.m
  node b = Switch::<i32> @cases(1, "two")
    .value <- 0
  node c = Switch::<u8> @cases(300)
    .value <- 0
  node Mode = Branch
"""), [("E0102", "Mode", ""), ("E0110", "a", "case1"), ("E0110", "b", "case1"),
       ("E0110", "c", "case0"), ("E0501", "a", "case2")])

    def test_enum_value_literals(self):
        from wiret.parser import parse_literal
        lit = parse_literal("Mode.Chase")
        self.assertEqual((lit.kind, lit.value), ("enum", "Mode.Chase"))
        with self.assertRaises(ParseError) as cm:
            parse_literal("a.b.c")
        self.assertIn("Enum.Member", cm.exception.msg)

    def test_compiling_reports_instead_of_crashing(self):
        text = module("""
struct Vec2 {
  x: f32
}

func Main() {
  node entry = Entry
  node v = MakeStruct Vec2
    .x <- 2
  node x = GetField Vec2.x
    .obj <- v.result
  node text = Convert::<f32, string>
    .value <- x.value
  node log = Call host.Log
    .message <- text.result

  flow {
    entry -> log
  }
}
""", macros=False)
        self.assertEqual(codes(text), [])
        r = compile_module(parse(text))
        self.assertFalse(r.ok)
        self.assertEqual([(d.code, d.graph) for d in r.diags], [("E0501", "Main")])

    def test_palette_and_explanations(self):
        from wiret import palette
        from wiret.explain import explain
        from wiret.registry import ModuleIndex
        m = parse(module(STRUCT_NODES, macros=False))
        self.assertTrue(palette.items(m.graph("Step"), ModuleIndex(m)))
        types = STRUCT_NODES.split("\nfunc Spawn")[0]
        text = module(types + """
var bad: Mode = Mode.Zip

func G(e: Enemy, v: Vec2, m: Mode, p: Mode = Other.X) {
  node entry = Entry
  node a = GetField Enemy
  node b = GetField Nope.x
  node c = GetField Mode.Idle
  node d = GetField Enemy.zz
  node f = MakeStruct Vec2::<i32>
  node g = MakeStruct Enemy.pos
  node i = SetField Enemy.hp
  node j = Eq::<i32>
    .a <- 1
    .b <- Mode.Idle
  node k = Switch::<Mode> @cases(Mode.Idle, 3)
    .value <- entry.m
  node Mode = Branch
}
""", macros=False)
        diags = [d for d in check(parse(text)) if d.severity == "error"]
        self.assertEqual(len(diags), 12)   # with node Mode present, j.b is a wire to it
        for d in diags:
            with self.subTest(d=str(d)):
                friendly = explain(d)
                self.assertNotEqual(friendly, d.message)
                self.assertNotIn(d.code, friendly)
                self.assertNotIn("None", friendly)


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
func F(x: i32) -> (y: i32) {
  node entry = Entry
  node ret = Return
    .y <- entry.x

  flow {
    entry -> ret
  }
}
""", macros=False)
        rerouted = module("""
func F(x: i32) -> (y: i32) {
  node bend = Reroute::<i32>
    .in <- entry.x
  node entry = Entry
  node hop = Reroute::<exec>
  node ret = Return
    .y <- bend.out

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
  node entry = Entry
  node outer = Macro ForRange
    .first <- 1
    .last <- entry.n
  node inner = Macro ForRange
    .first <- 1
    .last <- outer.index
  node cur = GetLocal c
  node inc = Add::<i32>
    .a <- cur.value
    .b <- 1
  node bump = SetLocal c
    .value <- inc.result
  node total = GetLocal c
  node ret = Return
    .count <- total.value

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
  node entry = Entry
  node seq = Sequence
  node a = Exit first
  node b = Exit second

  flow {
    entry -> seq
    seq.then0 -> a
    seq.then1 -> b
  }
}

func F() {
  node entry = Entry
  node tw = Macro Twice
  node log1 = Call host.Log
    .message <- "one"
  node log1b = Call host.Log
    .message <- "one-b"
  node log2 = Call host.Log
    .message <- "two"

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
  node entry = Entry
  node loop = Macro ForRange
    .first <- 1
    .last <- 100
  node sq = Mul::<i32>
    .a <- loop.index
    .b <- loop.index
  node over = Gt::<i32>
    .a <- sq.result
    .b <- entry.limit
  node chk = Branch
    .cond <- over.result
  node hit = Return
    .found <- loop.index
  node none = Return
    .found <- -1

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
  node entry = Entry
  node seq = Sequence
  node loop = Macro ForRange
    .first <- 1
    .last <- 2
  node log = Call host.Log
    .message <- "body"
  node after = Call host.Log
    .message <- "after"

  flow {
    entry -> seq
    seq.then0 -> loop
    seq.then1 -> after
    loop.each -> log
  }
}
""")
        self.assertEqual(run(text, "F")[1], ["body", "body", "after"])

    def test_join_and_W0310(self):
        text = module("""
func F(c: bool) -> (r: string) {
  node entry = Entry
  node br = Branch
    .cond <- entry.c
  node make = Call Make
  node join = Return
    .r <- make.s

  flow {
    entry -> br
    br.then -> make
    br.else -> join
    make -> join
  }
}

func Make() -> (s: string) {
  node entry = Entry
  node ret = Return
    .s <- "made"

  flow {
    entry -> ret
  }
}
""", macros=False)
        self.assertIn("W0310", codes(text))
        self.assertEqual(run(text, "F", 1)[0], ["made"])
        self.assertEqual(run(text, "F", 0)[0], [""])

    def test_pure_nodes_are_reevaluated_per_evaluation_point(self):
        text = module("""
var hp: i32 = 10

func F() -> (a: i32, b: i32) {
  local first: i32
  node entry = Entry
  node cur = GetVar hp
  node save = SetLocal first
    .value <- cur.value
  node dmg = Sub::<i32>
    .a <- cur.value
    .b <- 3
  node hit = SetVar hp
    .value <- dmg.result
  node got = GetLocal first
  node ret = Return
    .a <- got.value
    .b <- cur.value

  flow {
    entry -> save
    save -> hit
    hit -> ret
  }
}
""", macros=False)
        self.assertIn("W0320", codes(text))
        self.assertEqual(run(text, "F")[0], [10, 7])

    def test_do_once_state_is_per_expansion(self):
        text = module("""
macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool
  node entry = Entry
  node flag = GetState fired
  node check = Branch
    .cond <- flag.value
  node mark = SetState fired
    .value <- true
  node fire = Exit out
  node clear = SetState fired
    .value <- false

  flow {
    entry.in -> check
    entry.reset -> clear
    check.else -> mark
    mark -> fire
  }
}

func F() {
  node entry = Entry
  node loop = Macro ForRange
    .first <- 1
    .last <- 3
  node seq = Sequence
  node once_a = Macro DoOnce
  node once_b = Macro DoOnce
  node log_a = Call host.Log
    .message <- "a"
  node log_b = Call host.Log
    .message <- "b"

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
  node entry = Entry
  node sw = Switch::<i32> @cases(1, 2)
    .value <- entry.v
  node one = Return
    .s <- "one"
  node two = Return
    .s <- "two"
  node neg = Lt::<i32>
    .a <- entry.v
    .b <- 0
  node pick = Select::<string>
    .cond <- neg.result
    .a <- "negative"
    .b <- "many"
  node other = Return
    .s <- pick.result

  flow {
    entry -> sw
    sw.case0 -> one
    sw.case1 -> two
    sw.default -> other
  }
}

func Conv(x: f64) -> (i: i32, b: u8, s: string, back: f32) {
  node entry = Entry
  node i = Convert::<f64, i32>
    .value <- entry.x
  node b = Convert::<i32, u8>
    .value <- i.result
  node s = Convert::<f64, string>
    .value <- entry.x
  node f = Convert::<f64, f32>
    .value <- entry.x
  node ret = Return
    .i <- i.result
    .b <- b.result
    .s <- s.result
    .back <- f.result

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


class ArithmeticEdgeCases(unittest.TestCase):
    TEXT = module("""
func Div(a: i32, b: i32) -> (q: i32, r: i32) {
  node entry = Entry
  node q = Div::<i32>
    .a <- entry.a
    .b <- entry.b
  node r = Rem::<i32>
    .a <- entry.a
    .b <- entry.b
  node ret = Return
    .q <- q.result
    .r <- r.result

  flow {
    entry -> ret
  }
}

func Shift(a: i32, n: i32) -> (r: i32) {
  node entry = Entry
  node s = Shl::<i32>
    .a <- entry.a
    .b <- entry.n
  node ret = Return
    .r <- s.result

  flow {
    entry -> ret
  }
}

func AddU8(a: u8, b: u8) -> (r: u8) {
  node entry = Entry
  node s = Add::<u8>
    .a <- entry.a
    .b <- entry.b
  node ret = Return
    .r <- s.result

  flow {
    entry -> ret
  }
}

func MinMax(a: i32, b: i32) -> (lo: i32, hi: i32, abs: i32) {
  node entry = Entry
  node lo = Min::<i32>
    .a <- entry.a
    .b <- entry.b
  node hi = Max::<i32>
    .a <- entry.a
    .b <- entry.b
  node ab = Abs::<i32>
    .value <- entry.a
  node ret = Return
    .lo <- lo.result
    .hi <- hi.result
    .abs <- ab.result

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
  node entry = Entry
  node again = Sequence

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
  node add = ArrayAdd::<i32> nums
    .item <- 30
  node cur = GetLocal nums
  node entry = Entry
  node fin = GetLocal total
  node init = SetLocal nums
    .value <- mk.result
  node keep = SetLocal total
    .value <- plus.result
  node loop = Macro std.flow.ForEach::<i32>
    .array <- cur.value
  node mk = MakeArray::<i32> @count(3)
    .item0 <- 10
    .item1 <- 20
    .item2 <- 5
  node name = ArrayAdd::<string> names
    .item <- "Ada"
  node names_now = GetVar names
  node old = GetLocal total
  node plus = Add::<i32>
    .a <- old.value
    .b <- loop.item
  node r = Return
    .r <- fin.value
  node say = Call host.Log
    .message <- who.item
  node set = ArraySet::<i32> nums
    .index <- entry.at
    .item <- 7
  node who = ArrayGet::<string>
    .array <- names_now.value
    .index <- 0

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
                self.assertEqual(cm.exception.traceback[-1], ("t.Main", "who"))   # not `say`

    def test_mutator_type_must_match_place(self):
        text = module(self.BODY.replace("ArrayAdd::<i32> nums", "ArrayAdd::<f64> nums"),
                      macros=False)
        self.assertIn("E0110", codes(text))


class DiagnosticTests(unittest.TestCase):
    """One failing graph per implemented diagnostic code (section 7.4)."""

    CASES = {
        "E0101": "node entry = Entry\n  flow {\n    entry -> nowhere\n  }",
        "E0102": "node entry = Entry\n  node entry = Return",
        "E0103": "node entry = Entry\n  node r = Return\n    .bogus <- 1\n"
                 "  flow {\n    entry -> r\n  }",
        "E0110": "node entry = Entry\n  node r = Return\n    .y <- \"text\"\n"
                 "  flow {\n    entry -> r\n  }",
        "E0111": "node entry = Entry\n  node r = Return\n    .y <- 1\n    .y <- 2\n"
                 "  flow {\n    entry -> r\n  }",
        "E0120": "node entry = Entry\n  node r = Return\n    .in <- 1\n    .y <- 2\n"
                 "  flow {\n    entry -> r\n  }",
        "E0121": "node entry = Entry\n  node r = Return\n    .y <- 1\n"
                 "  flow {\n    entry.then -> r\n    entry.then -> r\n  }",
        "E0130": "node entry = Entry\n  node c = ArrayClear::<i32>\n  node r = Return\n    .y <- 1\n"
                 "  flow {\n    entry -> c\n    c -> r\n  }",
        "E0301": "node entry = Entry\n  node a = Add::<i32>\n    .a <- b.result\n    .b <- 1\n"
                 "  node b = Add::<i32>\n    .a <- a.result\n    .b <- 1\n"
                 "  node r = Return\n    .y <- a.result\n"
                 "  flow {\n    entry -> r\n  }",
        "E0501": "node entry = Entry\n  node w = Frobnicate\n  node r = Return\n    .y <- 1\n"
                 "  flow {\n    entry -> r\n  }",
        "E0502": "node entry = Entry\n  node a = Add\n    .a <- 1\n    .b <- 2\n"
                 "  node r = Return\n    .y <- 1\n"
                 "  flow {\n    entry -> r\n  }",
        "W0201": "node entry = Entry\n  node r = Return\n  flow {\n    entry -> r\n  }",
        "W0301": "node entry = Entry\n  node r = Return\n    .y <- 1\n  node lost = Return\n"
                 "    .y <- 2\n  flow {\n    entry -> r\n  }",
        "W0302": "node entry = Entry",
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
  node entry = Entry
}
""", macros=False)
        e0302 = base + """
func P() -> (y: i32) @pure {
  node entry = Entry
  node w = SetVar g
    .value <- 1
  node r = Return
    .y <- 1

  flow {
    entry -> w
    w -> r
  }
}
"""
        e0304 = base + """
func P() -> (y: i32) @pure {
  node entry = Entry
  node v = GetVar g
  node r = Return
    .y <- v.value

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
  node entry = Entry
  node again = Macro Loop
  node done = Exit out

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
  node entry = Entry
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
        removed = delete_node(g, "fib_text")
        self.assertTrue(removed)
        self.assertTrue(any(note_detached(a) == "fib_text" for a in notes(g.meta)))
        self.assertIn("W0604", {d.code for d in check(m)})
        out = print_module(m)
        self.assertIn('detached: "fib_text")]', out)
        self.assertEqual(print_module(parse(out)), out)

    def test_delete_box_keeps_notes(self):
        text = module("""
func F() {
  node entry = Entry
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
                self.assertTrue(nxt.startswith(("#[", "node ", "func ", "event ", "macro ")), nxt)


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
  node entry = Entry
  node c = Call host.Missing
    .x <- 1

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
  node entry = Entry
  node rep = Macro std.flow.Repeat
    .times <- 3
  node flip = Macro std.flow.FlipFlop
  node log_a = Call host.Log
    .message <- "A"
  node log_b = Call host.Log
    .message <- "B"
  node five = Macro std.flow.ForRange
    .first <- 1
    .last <- 5
  node limited = Macro std.flow.DoN
    .n <- 2
  node n_text = Convert::<i32, string>
    .value <- limited.counter
  node log_n = Call host.Log
    .message <- n_text.result

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
    }

    def test_lessons(self):
        names = sorted(f for f in os.listdir(LESSONS) if f.endswith(".wiret"))
        self.assertEqual(names, sorted(self.EXPECTED))
        for name in names:
            with self.subTest(name):
                text = lesson(name)
                m = parse(text)
                self.assertEqual(print_module(m), text, "not canonical")
                self.assertEqual([str(d) for d in check(m)], [])
                self.assertEqual(run(text, "Main")[1], self.EXPECTED[name])
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
                seen.append((v[("cur", "value")], v[("loop", "index")], v[("sum", "result")]))
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
  node entry = Entry
  node n = Add::<i32>
    .a <- 1
    .b <- 2
  node log = Call host.Log
    .message <- n.result

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


if __name__ == "__main__":
    unittest.main()
