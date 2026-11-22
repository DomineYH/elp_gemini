"""1:1 창이 열려 있으면 오류 문구는 창 안 줄에, 재시도 상자는 창 안 입력줄 위에 (#411).

요청 → 실패 → 화면이 bindInput·say·run·api·showRetry를 거치므로 스크립트 블록 전체를
node에서 가짜 DOM으로 돌린다 (트리아지 하니스 t411/dm_harness.py에서 옮김).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("app/templates/user/simulation.html")
LIMIT = "상한에 도달했습니다. 수업을 종료하고 피드백을 받으세요."
Q429 = "AI 사용량이 잠시 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
Q503 = "AI 모델이 혼잡합니다. 잠시 후 다시 시도해 주세요."
FINISHED = "이미 끝난 시뮬레이션입니다."
EMPTY = "내용을 입력해 주세요."
SAY = "say:채원아, 다시 말해 볼래?→1"

_node = pytest.mark.skipif(shutil.which("node") is None, reason="node 필요")

_JS = r"""
const PAGE = __PAGE__, SEED = __SEED__;
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r)); };

function makeEnv(queue) {  // 스크립트가 실행되자마자 init()이 GET을 보내므로 응답을 먼저 넣는다
    const env = { calls: [], queue, intervals: new Map(), nextTimer: 1 };
    const els = {};
    const mk = (id, tag) => {
        const cls = new Set();
        let text = "";
        const e = {
            id, tag, children: [], value: "", disabled: false, className: "", title: "", style: {},
            listeners: {}, onclick: null, beforeId: null, scrollTop: 0,
            classList: {
                add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c),
                toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)),
            },
            get textContent() { return text + e.children.map(c => c.textContent).join(""); },
            set textContent(v) { text = String(v); e.children = []; },
            setAttribute() {},
            append(...n) { e.children.push(...n.map(wrap)); },
            prepend(...n) { e.children.unshift(...n.map(wrap)); },
            replaceChildren(...n) { text = ""; e.children = n.map(wrap); },
            before(node) { node.beforeId = e.id; },
            addEventListener(t, f) { (e.listeners[t] ??= []).push(f); },
            dispatch(t, ev = {}) {
                (e.listeners[t] || []).forEach(f => f({ preventDefault() {}, stopPropagation() {}, target: e, ...ev }));
            },
            requestSubmit() { e.dispatch("submit"); },
            focus() { if (!e.disabled) document.activeElement = e; },
            blur() { document.activeElement = document.body; },
            contains: x => !!x && ["dmInput", "dmSubmit", "dmClose"].includes(x.id),
            querySelector: () => els.dmSubmit,
        };
        return e;
    };
    const wrap = n => (typeof n === "string" ? { textContent: n, children: [], className: "" } : n);
    for (const [id, s] of Object.entries(SEED)) {
        els[id] = mk(id);
        if (s.hidden) els[id].classList.add("hidden");
        els[id].disabled = s.disabled;
        if (s.text) els[id].textContent = s.text;
    }
    els.dmSubmit = mk("dmSubmit");  // 1:1 제출 버튼은 id가 없다
    els.retryBox.beforeId = "tForm";
    // 안내 줄에 글이 들거나 상자가 창 안에 보이면 대화 영역이 줄어 바닥이 내려간 것과 같다
    Object.defineProperty(els.dmFeed, "scrollHeight", { get: () => 1000 + 40 * els.dmFeed.children.length +
        (els.dmTurnNote.textContent ? 19 : 0) +
        (!els.retryBox.classList.contains("hidden") && els.retryBox.beforeId === "dmForm" ? 62 : 0) });
    const document = {
        body: { id: "body" }, activeElement: null, listeners: {},
        getElementById: id => els[id] || null,
        createElement: tag => mk("", tag),
        addEventListener(t, f) { (document.listeners[t] ??= []).push(f); },
    };
    document.activeElement = document.body;
    env.$ = id => els[id];
    env.document = document;
    env.fetch = (url, init) => {
        env.calls.push({ method: init.method, url, body: init.body ? JSON.parse(init.body) : undefined });
        const next = env.queue.shift();
        if (!next) throw new Error("대역에 준비되지 않은 요청: " + init.method + " " + url);
        return next();
    };
    env.setInterval = (fn, ms) => { const id = env.nextTimer++; env.intervals.set(id, fn); return id; };
    env.clearInterval = id => env.intervals.delete(id);
    env.seconds = n => { for (let i = 0; i < n; i++) [...env.intervals.values()].forEach(f => f()); };
    new Function("document", "fetch", "matchMedia", "setInterval", "clearInterval", "setTimeout", "confirm", "window", PAGE)(
        document, env.fetch, () => ({ matches: false }), env.setInterval, env.clearInterval,
        fn => fn(), () => true, { location: {} });
    return env;
}

const resp = (status, body, headers = {}) => () => Promise.resolve({
    ok: status >= 200 && status < 300, status,
    headers: { get: k => headers[k] ?? null },
    json: async () => body,
});
const err = (status, code, message, headers) => resp(status, { detail: { code, message } }, headers);
const deferred = () => { let go; const p = new Promise(r => (go = r)); const f = () => p; f.settle = r => go(r()); return f; };

const AGREE = { agreed_persona_ids: [], pledged_persona_ids: [], understanding: { 1: 40, 2: 55 }, count: 0, total: 2, all_agreed: false };
function state(used = 10, entered = true) {
    return {
        session: { status: "running", current_phase_idx: 0, teacher_turns_max: 40, teacher_turns_used: used },
        phases: [{ idx: 0, name: "도입", teacher_prompt: "발문", minutes: 5 }, { idx: 1, name: "전개", teacher_prompt: "발문2" }],
        personas: [1, 2].map(id => ({ id, display_name: id === 1 ? "채원" : "지호", color_key: "c" + id,
            adapted_level: "부분 도달", adapted_profile: { behavior_summary: "" } })),
        utterances: !entered ? [] : [
            { id: 1, seq: 1, phase_idx: 0, speaker_type: "teacher", target_persona_id: null, content: "발문", structured: { source: "plan" } },
            { id: 2, seq: 2, phase_idx: 0, speaker_type: "student", persona_id: 1, content: "네", structured: { utterance: "네" }, failed: false },
            { id: 3, seq: 3, phase_idx: 0, speaker_type: "student", persona_id: 2, content: "네", structured: { utterance: "네" }, failed: false },
        ],
        agreement: AGREE,
    };
}
const turn = (content, target, used) => resp(200, {
    utterances: [
        { id: 10, seq: 10, phase_idx: 0, speaker_type: "teacher", target_persona_id: target, content, structured: { source: "user" } },
        { id: 11, seq: 11, phase_idx: 0, speaker_type: "student", persona_id: target ?? 1, content: "알겠어요",
          structured: { utterance: "알겠어요" }, failed: false },
    ],
    agreement: AGREE, teacher_turns_used: used, failed_persona_ids: [],
});

function snap(env) {
    const $ = env.$, box = $("retryBox"), btn = $("retryBtn"), feed = $("dmFeed");
    return {
        open: !$("dmModal").classList.contains("hidden"),
        simStatus: $("simStatus").textContent,
        turnNote: $("turnNote").textContent,
        dmTurnNote: $("dmTurnNote").textContent,
        box: box.classList.contains("hidden") ? "hidden" :
            btn.textContent + (btn.disabled ? " off" : " on") + " @" + box.beforeId +
            (box.classList.contains("px-3") ? " px-3" : ""),
        dmInput: $("dmInput").value,
        atBottom: feed.scrollTop === feed.scrollHeight,
        POST: env.calls.filter(c => c.method === "POST").map(c => c.url.split("/").pop() +
            (c.body && c.body.content ? ":" + c.body.content + "→" + c.body.target_persona_id : "")),
    };
}

async function boot(st = state()) {
    const env = makeEnv([resp(200, st)]);
    await flush();
    return env;
}
const openSeat = (env, i = 0) => env.$("seats").children[i].dispatch("click");
async function submit(env, form, text, ...answers) {
    env.queue.push(...answers);
    env.$(form === "dmForm" ? "dmInput" : "tInput").value = text;
    env.$(form).dispatch("submit");
    await flush();
}
const dmSubmit = (env, text, ...a) => submit(env, "dmForm", text, ...a);
const RA = { "Retry-After": "30" };
const TEXT = "채원아, 다시 말해 볼래?";
const out = {};
const CLOSE = {
    button: env => env.$("dmClose").dispatch("click"),
    escape: env => env.document.listeners.keydown.forEach(f => f({ key: "Escape" })),
    backdrop: env => env.$("dmModal").dispatch("click", { target: env.$("dmModal") }),
};

(async () => {
    let env;
    env = await boot(); openSeat(env);
    await dmSubmit(env, "   ");
    out.blank = snap(env);

    env = await boot(); openSeat(env);
    await dmSubmit(env, TEXT, err(409, "SESSION_FINISHED", __FINISHED__));
    out.finished = snap(env);

    env = await boot(state(37)); openSeat(env);
    await dmSubmit(env, TEXT, err(409, "TURN_LIMIT", __LIMIT__));
    out.limit409 = snap(env);
    await dmSubmit(env, "다시 보낸 글", turn("다시 보낸 글", 1, 38));
    out.limit409_then_ok = snap(env);

    env = await boot(state(37)); openSeat(env);
    await dmSubmit(env, TEXT, err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
    out.r429 = snap(env);
    env.seconds(30);
    out.r429_30s = snap(env);
    env.queue.push(turn(TEXT, 1, 38));
    env.$("retryBtn").onclick(); await flush();
    out.r429_retry = snap(env);

    for (const [how, close] of Object.entries(CLOSE)) {
        env = await boot(state(37)); openSeat(env);
        await dmSubmit(env, TEXT, err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
        close(env);
        env.seconds(1);
        out["close_" + how] = snap(env);
    }

    env = await boot();
    await submit(env, "tForm", "여러분, 시작해 볼까요?", err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
    out.closed429 = snap(env);
    openSeat(env);
    out.closed429_open = snap(env);

    const enter = deferred();
    env = makeEnv([resp(200, state(0, false)), enter]);
    await flush();
    openSeat(env);
    out.enter_wait = snap(env);
    enter.settle(err(503, "MODEL_OVERLOADED", __Q503__, RA)); await flush();
    out.enter503 = snap(env);

    env = await boot(); openSeat(env);
    await dmSubmit(env, TEXT, () => Promise.reject(new TypeError("Failed to fetch")));
    out.reject = snap(env);

    env = await boot();
    await submit(env, "tForm", "   ");
    out.closed_blank = snap(env);
    env = await boot();
    await submit(env, "tForm", TEXT, err(409, "SESSION_FINISHED", __FINISHED__));
    out.closed409 = snap(env);
    env = await boot();
    await submit(env, "tForm", TEXT, () => Promise.reject(new TypeError("Failed to fetch")));
    out.closed_reject = snap(env);

    env = makeEnv([err(404, "SESSION_NOT_FOUND", "시뮬레이션 세션을 찾을 수 없습니다.")]);
    await flush();
    out.init404 = snap(env);

    console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _page() -> tuple[str, str]:
    src = TEMPLATE.read_text(encoding="utf-8")
    html, script = src.split("{% block scripts %}")
    m = re.search(
        r"<script>\n(\(\(\) => \{.*\}\)\(\);)\n</script>", script, re.S
    )
    assert m, "스크립트 블록을 찾지 못함"
    return html, m.group(1).replace("{{ sid }}", "1")


def _seed(html: str) -> dict:
    """템플릿의 id 요소: hidden 클래스, disabled 속성, 단순 글자."""
    out = {}
    for tag in re.finditer(
        r'<\w+\s[^>]*?\bid="(\w+)"[^>]*>([^<]*)', html, re.S
    ):
        attrs = tag.group(0)
        cls = re.search(r'class="([^"]*)"', attrs)
        bare = re.sub(r'"[^"]*"', "", attrs.split(">")[0])
        out[tag.group(1)] = {
            "hidden": bool(cls and "hidden" in cls.group(1).split()),
            "disabled": bool(re.search(r"\sdisabled\b", bare)),
            "text": tag.group(2).strip() if "{" not in tag.group(2) else "",
        }
    return out


@pytest.fixture(scope="module")
def out() -> dict:
    html, page = _page()
    js = _JS.replace("__PAGE__", json.dumps(page)).replace(
        "__SEED__", json.dumps(_seed(html))
    )
    for name, text in [
        ("FINISHED", FINISHED),
        ("LIMIT", LIMIT),
        ("Q429", Q429),
        ("Q503", Q503),
    ]:
        js = js.replace(f"__{name}__", json.dumps(text))
    res = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout)


@_node
def test_blank_input_in_window_shows_notice_inside(out):
    s = out["blank"]
    assert (s["dmTurnNote"], s["simStatus"]) == (EMPTY, "")
    assert s["POST"] == [] and s["dmInput"] == "   "


@_node
def test_409_in_window_shows_server_message_inside(out):
    s = out["finished"]
    assert (s["dmTurnNote"], s["simStatus"], s["box"]) == (
        FINISHED,
        "",
        "hidden",
    )


@_node
def test_error_comes_before_turns_left_then_clears(out):
    # 이 탭은 남은 3회지만 오류 문구가 먼저다
    assert (out["limit409"]["dmTurnNote"], out["limit409"]["turnNote"]) == (
        LIMIT,
        "",
    )
    assert out["limit409_then_ok"]["dmTurnNote"] == "남은 발화 2회"


@_node
def test_429_in_window_moves_retry_box_inside(out):
    assert out["r429"]["dmTurnNote"] == Q429
    assert out["r429"]["box"] == "다시 시도 (30초) off @dmForm px-3"
    assert out["r429_30s"]["box"] == "다시 시도 on @dmForm px-3"


@_node
def test_retry_inside_window_resends_same_body(out):
    s = out["r429_retry"]
    assert s["POST"] == [SAY, SAY]
    assert s["box"] == "hidden" and s["dmTurnNote"] in ("", "남은 발화 2회")


@_node
@pytest.mark.parametrize("how", ["button", "escape", "backdrop"])
def test_close_window_moves_retry_box_back(out, how):
    s = out["close_" + how]
    assert not s["open"]
    assert (s["simStatus"], s["dmTurnNote"]) == (Q429, "")
    # 초 세기는 이어진다(30 → 29초)
    assert s["box"] == "다시 시도 (29초) off @tForm"


@_node
def test_open_window_after_main_screen_429_brings_box_inside(out):
    assert out["closed429"]["box"] == "다시 시도 (30초) off @tForm"
    s = out["closed429_open"]
    assert (s["dmTurnNote"], s["simStatus"]) == (Q429, "")
    assert s["box"] == "다시 시도 (30초) off @dmForm px-3"


@_node
def test_window_opened_while_entering_shows_503_inside(out):
    s = out["enter503"]
    assert s["dmTurnNote"] == Q503 and "@dmForm px-3" in s["box"]


@_node
def test_fetch_rejection_message_inside_window(out):
    assert out["reject"]["dmTurnNote"] == "Failed to fetch"


@_node
@pytest.mark.parametrize(
    ("key", "text", "box"),
    [
        ("closed_blank", EMPTY, "hidden"),
        ("closed409", FINISHED, "hidden"),
        ("closed_reject", "Failed to fetch", "hidden"),
        ("closed429", Q429, "다시 시도 (30초) off @tForm"),
    ],
)
def test_closed_window_errors_stay_on_main_screen(out, key, text, box):
    s = out[key]
    assert (s["simStatus"], s["dmTurnNote"], s["box"]) == (text, "", box)


@_node
def test_init_get_failure_writes_main_status(out):
    assert out["init404"]["simStatus"] == "시뮬레이션 세션을 찾을 수 없습니다."


@_node
def test_one_filled_line_and_feed_at_bottom_in_every_state(out):
    for name, s in out.items():
        if s["dmTurnNote"]:
            assert not (s["simStatus"] or s["turnNote"]), name
        if s["open"]:
            assert "@tForm" not in s["box"], name
            # 안내 줄이나 상자가 생겨 대화 영역이 줄어도 마지막 말풍선이 보인다
            assert s["atBottom"], name
        else:
            assert not s["dmTurnNote"] and "@dmForm" not in s["box"], name


def test_template_keeps_single_retry_box_before_tform():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert html.count('id="retryBox"') == 1
    assert re.search(
        r'id="retryBox".*?</div>\s*</div>\s*<form id="tForm"', html, re.S
    )
    assert (
        '<div id="retryBox" class="hidden container mx-auto max-w-3xl mb-2 flex'
        ' justify-end" role="alert">' in html
    )
    assert '<p id="simStatus" class="note mt-3" role="status"></p>' in html
    assert (
        '<button type="button" id="retryBtn" class="text-sm font-semibold px-4 py-2'
        " rounded-lg bg-amber-500 hover:bg-amber-600 disabled:bg-gray-400"
        ' disabled:cursor-not-allowed text-white shrink-0">다시 시도</button>'
        in html
    )
