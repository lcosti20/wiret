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
from wiret.ops import convert_comments, delete_node  # noqa: E402
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
  node bump = SetLocal i (value: nxt.result) -> test
  node cmp = Le<i32>(a: cur.value, b: entry.last)
  node cur = GetLocal i
  node each_out = Exit each (index: cur.value)
  node entry = Entry -> init
  node finish = Exit done
  node init = SetLocal i (value: entry.first) -> test
  node nxt = Add<i32>(a: cur.value, b: 1)
  node seq = Sequence { then0 -> each_out, then1 -> bump } @count(2)
  node test = Branch(cond: cmp.result) { then -> seq, else -> finish }
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
  node ret   = Return(y: s.result)
  node entry = Entry { then -> ret }
  node s     = Add<i32>(
     a: entry.x,
     b: 0x10,
  )
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn("node entry = Entry -> ret\n", out)
        self.assertIn("node s = Add<i32>(a: entry.x, b: 16)\n", out)
        self.assertEqual(print_module(parse(out)), out)

    def test_unknown_attributes_and_layout_props_survive(self):
        text = module("""
func F() @x.acme.review("ok", level: 2) {
  node entry = Entry @Hash(1)
  layout {
    entry at (1, 2) [label = "Start", x.acme.pin = [a, b]]
  }
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn('@x.acme.review("ok", level: 2)', out)
        self.assertIn("@Hash(1)", out)
        self.assertIn('x.acme.pin = [a, b]', out)

    def test_long_nodes_wrap(self):
        text = module("""
func F() {
  node entry = Entry -> log
  node log = Call host.Log(message: "a very long message that pushes this node line well past the hundred column limit")
}
""", macros=False)
        out = print_module(parse(text))
        self.assertIn("node log = Call host.Log(\n    message: ", out)
        self.assertEqual(print_module(parse(out)), out)

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
        self.assertIn('on entry "explain the entry"', out)

    def test_parse_errors_have_positions(self):
        with self.assertRaises(ParseError) as cm:
            parse("wiret 1\nmodule t\nfunc F( {\n}\n")
        self.assertEqual(cm.exception.line, 3)


class HashTests(unittest.TestCase):
    def test_reorder_and_layout_removal_do_not_change_semantics(self):
        text = demo()
        m1 = parse(text)
        _, r1 = build(text)
        m2 = parse(text)
        for g in m2.graphs():
            g.nodes.reverse()
            g.places, g.boxes, g.notes = [], [], []
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
  node entry = Entry -> ret
  node ret = Return(y: entry.x)
}
""", macros=False)
        rerouted = module("""
func F(x: i32) -> (y: i32) {
  node bend = Reroute<i32>(in: entry.x)
  node entry = Entry -> hop
  node hop = Reroute<exec> -> ret
  node ret = Return(y: bend.out)
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
  node entry = Entry -> outer
  node outer = Macro ForRange(first: 1, last: entry.n) { each -> inner, done -> ret }
  node inner = Macro ForRange(first: 1, last: outer.index) { each -> bump }
  node cur = GetLocal c
  node inc = Add<i32>(a: cur.value, b: 1)
  node bump = SetLocal c (value: inc.result)
  node total = GetLocal c
  node ret = Return(count: total.value)
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
  node entry = Entry -> seq
  node seq = Sequence { then0 -> a, then1 -> b }
  node a = Exit first
  node b = Exit second
}

func F() {
  node entry = Entry -> tw
  node tw = Macro Twice { first -> log1, second -> log2 }
  node log1 = Call host.Log(message: "one") -> log1b
  node log1b = Call host.Log(message: "one-b")
  node log2 = Call host.Log(message: "two")
}
""")
        self.assertEqual(run(text, "F")[1], ["one", "one-b", "two"])

    def test_early_return_discards_pending_continuations(self):
        text = module("""
func FirstOver(limit: i32) -> (found: i32) {
  node entry = Entry -> loop
  node loop = Macro ForRange(first: 1, last: 100) { each -> chk, done -> none }
  node sq = Mul<i32>(a: loop.index, b: loop.index)
  node over = Gt<i32>(a: sq.result, b: entry.limit)
  node chk = Branch(cond: over.result) { then -> hit }
  node hit = Return(found: loop.index)
  node none = Return(found: -1)
}
""")
        self.assertEqual(run(text, "FirstOver", 50)[0], [8])
        self.assertEqual(run(text, "FirstOver", 100000)[0], [-1])

    def test_unwired_exit_is_a_chain_end(self):
        text = module("""
func F() {
  node entry = Entry -> seq
  node seq = Sequence { then0 -> loop, then1 -> after }
  node loop = Macro ForRange(first: 1, last: 2) { each -> log }
  node log = Call host.Log(message: "body")
  node after = Call host.Log(message: "after")
}
""")
        self.assertEqual(run(text, "F")[1], ["body", "body", "after"])

    def test_join_and_W0310(self):
        text = module("""
func F(c: bool) -> (r: string) {
  node entry = Entry -> br
  node br = Branch(cond: entry.c) { then -> make, else -> join }
  node make = Call Make -> join
  node join = Return(r: make.s)
}

func Make() -> (s: string) {
  node entry = Entry -> ret
  node ret = Return(s: "made")
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
  node entry = Entry -> save
  node cur = GetVar hp
  node save = SetLocal first (value: cur.value) -> hit
  node dmg = Sub<i32>(a: cur.value, b: 3)
  node hit = SetVar hp (value: dmg.result) -> ret
  node got = GetLocal first
  node ret = Return(a: got.value, b: cur.value)
}
""", macros=False)
        self.assertIn("W0320", codes(text))
        self.assertEqual(run(text, "F")[0], [10, 7])

    def test_do_once_state_is_per_expansion(self):
        text = module("""
macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool
  node entry = Entry { in -> check, reset -> clear }
  node flag = GetState fired
  node check = Branch(cond: flag.value) { else -> mark }
  node mark = SetState fired (value: true) -> fire
  node fire = Exit out
  node clear = SetState fired (value: false)
}

func F() {
  node entry = Entry -> loop
  node loop = Macro ForRange(first: 1, last: 3) { each -> seq }
  node seq = Sequence { then0 -> once_a, then1 -> once_b }
  node once_a = Macro DoOnce { out -> log_a }
  node once_b = Macro DoOnce { out -> log_b }
  node log_a = Call host.Log(message: "a")
  node log_b = Call host.Log(message: "b")
}
""")
        self.assertEqual(run(text, "F")[1], ["a", "b"])

    def test_switch_select_and_conversions(self):
        text = module("""
func Name(v: i32) -> (s: string) {
  node entry = Entry -> sw
  node sw = Switch<i32>(value: entry.v) { case0 -> one, case1 -> two, default -> other } @cases(1, 2)
  node one = Return(s: "one")
  node two = Return(s: "two")
  node neg = Lt<i32>(a: entry.v, b: 0)
  node pick = Select<string>(cond: neg.result, a: "negative", b: "many")
  node other = Return(s: pick.result)
}

func Conv(x: f64) -> (i: i32, b: u8, s: string, back: f32) {
  node entry = Entry -> ret
  node i = Convert<f64, i32>(value: entry.x)
  node b = Convert<i32, u8>(value: i.result)
  node s = Convert<f64, string>(value: entry.x)
  node f = Convert<f64, f32>(value: entry.x)
  node ret = Return(i: i.result, b: b.result, s: s.result, back: f.result)
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
  node entry = Entry -> ret
  node q = Div<i32>(a: entry.a, b: entry.b)
  node r = Rem<i32>(a: entry.a, b: entry.b)
  node ret = Return(q: q.result, r: r.result)
}

func Shift(a: i32, n: i32) -> (r: i32) {
  node entry = Entry -> ret
  node s = Shl<i32>(a: entry.a, b: entry.n)
  node ret = Return(r: s.result)
}

func AddU8(a: u8, b: u8) -> (r: u8) {
  node entry = Entry -> ret
  node s = Add<u8>(a: entry.a, b: entry.b)
  node ret = Return(r: s.result)
}

func MinMax(a: i32, b: i32) -> (lo: i32, hi: i32, abs: i32) {
  node entry = Entry -> ret
  node lo = Min<i32>(a: entry.a, b: entry.b)
  node hi = Max<i32>(a: entry.a, b: entry.b)
  node ab = Abs<i32>(value: entry.a)
  node ret = Return(lo: lo.result, hi: hi.result, abs: ab.result)
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
  node entry = Entry -> again
  node again = Sequence { then0 -> again }
}
""", macros=False)
        _, r = build(text)
        vm = VM(fuel=1000)
        with self.assertRaises(WiretError) as cm:
            vm.call(vm.load(r.wbc), "Spin", [])
        self.assertEqual(cm.exception.status, "WR_ERR_FUEL")


class ArrayTests(unittest.TestCase):
    BODY = """
var names: array<string>

func Main(at: i32) -> (r: i32) {
  local nums: array<i32>
  local total: i32
  node add = ArrayAdd<i32> nums (item: 30) -> set
  node cur = GetLocal nums
  node entry = Entry -> init
  node fin = GetLocal total
  node init = SetLocal nums (value: mk.result) -> add
  node keep = SetLocal total (value: plus.result)
  node loop = Macro std.flow.ForEach<i32>(array: cur.value) { each -> keep, done -> name }
  node mk = MakeArray<i32>(item0: 10, item1: 20, item2: 5) @count(3)
  node name = ArrayAdd<string> names (item: "Ada") -> say
  node names_now = GetVar names
  node old = GetLocal total
  node plus = Add<i32>(a: old.value, b: loop.item)
  node r = Return(r: fin.value)
  node say = Call host.Log(message: who.item) -> r
  node set = ArraySet<i32> nums (index: entry.at, item: 7) -> loop
  node who = ArrayGet<string>(array: names_now.value, index: 0)
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
        text = module(self.BODY.replace("index: 0)", "index: 5)"), macros=False)
        for debug in (False, True):
            with self.subTest(debug=debug):
                vm = VM(output=lambda s: None)
                with self.assertRaises(WiretError) as cm:
                    vm.call(vm.load(compile_module(parse(text), text, debug=debug).wbc), "Main", [0])
                self.assertEqual(cm.exception.traceback[-1], ("t.Main", "who"))   # not `say`

    def test_mutator_type_must_match_place(self):
        text = module(self.BODY.replace("ArrayAdd<i32> nums", "ArrayAdd<f64> nums"),
                      macros=False)
        self.assertIn("E0110", codes(text))


class DiagnosticTests(unittest.TestCase):
    """One failing graph per implemented diagnostic code (section 7.4)."""

    CASES = {
        "E0101": "node entry = Entry -> nowhere",
        "E0102": "node entry = Entry\n  node entry = Return",
        "E0103": "node entry = Entry -> r\n  node r = Return(bogus: 1)",
        "E0110": "node entry = Entry -> r\n  node r = Return(y: \"text\")",
        "E0111": "node entry = Entry -> r\n  node r = Return(y: 1, y: 2)",
        "E0120": "node entry = Entry -> r\n  node r = Return(in: 1, y: 2)",
        "E0121": "node entry = Entry { then -> r, then -> r }\n  node r = Return(y: 1)",
        "E0130": "node entry = Entry -> c\n  node c = ArrayClear<i32> -> r\n  node r = Return(y: 1)",
        "E0301": "node entry = Entry -> r\n  node a = Add<i32>(a: b.result, b: 1)\n"
                 "  node b = Add<i32>(a: a.result, b: 1)\n  node r = Return(y: a.result)",
        "E0501": "node entry = Entry -> r\n  node w = Frobnicate\n  node r = Return(y: 1)",
        "E0502": "node entry = Entry -> r\n  node a = Add(a: 1, b: 2)\n  node r = Return(y: 1)",
        "W0201": "node entry = Entry -> r\n  node r = Return",
        "W0301": "node entry = Entry -> r\n  node r = Return(y: 1)\n  node lost = Return(y: 2)",
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
  node entry = Entry -> w
  node w = SetVar g (value: 1) -> r
  node r = Return(y: 1)
}
"""
        e0304 = base + """
func P() -> (y: i32) @pure {
  node entry = Entry -> r
  node v = GetVar g
  node r = Return(y: v.value)
}
"""
        self.assertIn("E0302", codes(e0302))
        self.assertIn("E0304", codes(e0304))

    def test_macro_recursion(self):
        text = module("""
macro Loop(in: exec) -> (out: exec) {
  node entry = Entry -> again
  node again = Macro Loop { out -> done }
  node done = Exit out
}
""", macros=False)
        self.assertIn("E0401", codes(text))

    def test_layout_and_note_warnings(self):
        text = module("""
func F() {
  node entry = Entry
  notes {
    note lost on gone "orphan"
  }
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
        self.assertTrue(any(n.on == "fib_text" for n in g.notes))
        self.assertIn("W0604", {d.code for d in check(m)})


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
  node entry = Entry -> c
  node c = Call host.Missing(x: 1)
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
  node entry = Entry -> rep
  node rep = Macro std.flow.Repeat(times: 3) { body -> flip, done -> five }
  node flip = Macro std.flow.FlipFlop { a -> log_a, b -> log_b }
  node log_a = Call host.Log(message: "A")
  node log_b = Call host.Log(message: "B")
  node five = Macro std.flow.ForRange(first: 1, last: 5) { each -> limited }
  node limited = Macro std.flow.DoN(n: 2) { out -> log_n }
  node n_text = Convert<i32, string>(value: limited.counter)
  node log_n = Call host.Log(message: n_text.result)
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
                    self.assertTrue(any(n.on is None for n in g.notes), f"{g.name} has no intro")
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
  node entry = Entry -> log
  node n = Add<i32>(a: 1, b: 2)
  node log = Call host.Log(message: n.result)
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
        self.assertEqual(top("add").label, "Add<i32>")

    def test_wire_drop_filters_and_ranks(self):
        from wiret import palette
        items = palette.items(self.g, self.idx)
        fits = [i for i in items if palette.compatible(i, self.g, self.idx, "out", "i32")]
        self.assertTrue(all(palette.compatible(i, self.g, self.idx, "out", "i32") for i in fits))
        self.assertNotIn("Call host.Log", [i.label for i in fits])
        self.assertEqual(palette.rank(fits, "text")[0].label, "Convert<i32, string> (to text)")
        execs = [i for i in items if palette.compatible(i, self.g, self.idx, "out", "exec")]
        self.assertIn("Branch", [i.kind for i in execs])
        self.assertNotIn("Add", [i.kind for i in execs])


if __name__ == "__main__":
    unittest.main()
