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
CSS = Path("app/static/css/tailwind.css")
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

// gets: GET 응답 대기열. 주지 않으면 queue를 함께 쓴다(409 뒤 다시 받기를 POST와 따로 답하려고, #416)
function makeEnv(queue, gets = queue) {  // 스크립트가 실행되자마자 init()이 GET을 보내므로 응답을 먼저 넣는다
    const env = { calls: [], queue, gets, intervals: new Map(), nextTimer: 1, moves: 0, log: [], location: {} };
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
            set textContent(v) {
                text = String(v); e.children = [];
                if (id === "dmTurnNote") env.log.push("note:" + text);
            },
            setAttribute() {},
            append(...n) { e.children.push(...n.map(wrap)); },
            prepend(...n) { e.children.unshift(...n.map(wrap)); },
            replaceChildren(...n) { text = ""; e.children = n.map(wrap); },
            before(node) {
                node.beforeId = e.id; env.moves++;
                env.log.push("move:" + e.id + (node.classList.contains("hidden") ? ":hidden" : ":shown"));
            },
            get nextElementSibling() { return e.beforeId ? els[e.beforeId] : null; },
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
    // 1:1 창의 패널: 낮은 화면에서 내용이 넘치면 패널이 스크롤된다 (#411)
    els.dmModal.firstElementChild = { scrollTop: 0, scrollHeight: 300 };
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
        const next = (init.method === "GET" ? env.gets : env.queue).shift();
        if (!next) throw new Error("대역에 준비되지 않은 요청: " + init.method + " " + url);
        return next(env.calls[env.calls.length - 1]);  // 요청을 보고 답하는 대역용 (#420)
    };
    env.setInterval = (fn, ms) => { const id = env.nextTimer++; env.intervals.set(id, fn); return id; };
    env.clearInterval = id => env.intervals.delete(id);
    env.seconds = n => { for (let i = 0; i < n; i++) [...env.intervals.values()].forEach(f => f()); };
    new Function("document", "fetch", "matchMedia", "setInterval", "clearInterval", "setTimeout", "confirm", "window", PAGE)(
        document, env.fetch, () => ({ matches: false }), env.setInterval, env.clearInterval,
        fn => fn(), () => true, { location: env.location });
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
        panelAtBottom: $("dmModal").firstElementChild.scrollTop === $("dmModal").firstElementChild.scrollHeight,
        bodies: env.calls.filter(c => c.method === "POST").map(c => c.body ?? null),
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

    // 채원(A)에게 한 1:1 말이 429 → 창을 닫고 지호(B) 창을 엶 → 다시 A 창 (#411 2차)
    env = await boot(state(37)); openSeat(env);
    await dmSubmit(env, TEXT, err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
    CLOSE.button(env); env.seconds(1); openSeat(env, 1);
    out.away_say = snap(env);
    CLOSE.button(env); openSeat(env, 0);
    out.away_back = snap(env);
    env.seconds(29);
    env.queue.push(turn(TEXT, 1, 38));
    env.$("retryBtn").onclick(); await flush();
    out.away_retry = snap(env);

    // A 창에서 보낸 말을 기다리는 동안 B 창으로 옮겼고 그 요청이 429
    env = await boot(); openSeat(env);
    const pendingSay = deferred();
    await dmSubmit(env, TEXT, pendingSay);
    CLOSE.button(env); openSeat(env, 1);
    pendingSay.settle(err(429, "RESOURCE_EXHAUSTED", __Q429__, RA)); await flush();
    out.away_wait = snap(env);
    // 그 B 창에서 빈 입력: 안내는 B 창 안에, 상자는 본 화면에 그대로
    await dmSubmit(env, "   ");
    out.away_blank = snap(env);

    // 좌석의 A '다시 생성'이 429 → B 창을 엶 → 다시 A 창
    const st = state();
    st.utterances[1] = { ...st.utterances[1], content: "", structured: null, failed: true };
    env = await boot(st);
    const findBtn = n => n.tag === "button" ? n : (n.children || []).map(findBtn).find(Boolean);
    env.queue.push(err(503, "MODEL_OVERLOADED", __Q503__, RA));
    findBtn(env.$("seats").children[0]).dispatch("click"); await flush();
    openSeat(env, 1);
    out.away_regen = snap(env);
    CLOSE.button(env); openSeat(env, 0);
    out.away_regen_back = snap(env);

    // 모두를 기다린 요청(장면 넘기기)이 503 → 어느 창이든 창 안
    env = await boot();
    env.queue.push(err(503, "MODEL_OVERLOADED", __Q503__, RA));
    env.$("skipBtn").dispatch("click"); await flush();
    openSeat(env, 1);
    out.skip503_open = snap(env);

    // 상자는 자리가 바뀔 때만 옮긴다: 창 안에 보이는 동안 다시 그려도 끼워 넣지 않는다
    const moves = env.moves;
    await dmSubmit(env, "   "); await dmSubmit(env, "   ");
    out.moves = { ...snap(env), again: env.moves - moves };

    // 중간 쓰기 순서: A 몫 429가 B 창에서 끝날 때, 그리고 B 창에서 새 요청이 시작될 때 (#411 3차)
    env = await boot(); openSeat(env);
    const slow = deferred();
    await dmSubmit(env, TEXT, slow);
    CLOSE.button(env); openSeat(env, 1);
    env.log.length = 0;
    slow.settle(err(429, "RESOURCE_EXHAUSTED", __Q429__, RA)); await flush();
    out.order_fail = { ...snap(env), log: [...env.log] };
    env.log.length = 0;
    await dmSubmit(env, "지호야, 너는 어때?", turn("지호야, 너는 어때?", 2, 11));
    out.order_next = { ...snap(env), log: [...env.log] };

    // ===== 409 뒤 상태를 한 번 다시 받아 그린다 (#416) =====
    const T = (id, phase, content) => ({ id, seq: id, phase_idx: phase, speaker_type: "teacher",
        target_persona_id: null, content, structured: { source: "user" } });
    const S = (id, phase, persona, content) => ({ id, seq: id, phase_idx: phase, speaker_type: "student",
        persona_id: persona, content, structured: { utterance: content }, failed: false });
    const FIN = () => {
        const s = state(12);
        s.session.status = "finished";
        s.utterances.push(T(10, 0, "다른 탭 발화"), S(11, 0, 1, "네"), S(12, 0, 2, "네"));
        return s;
    };
    const ENTER1 = [T(21, 1, "발문2"), S(22, 1, 1, "장면2 네"), S(23, 1, 2, "장면2 네")];
    const SCENE2 = (entered = true) => {
        const s = state();
        s.session.current_phase_idx = 1;
        if (entered) s.utterances.push(...ENTER1);
        return s;
    };
    const ALL = { ...AGREE, agreed_persona_ids: [1, 2], understanding: { 1: 85, 2: 90 }, count: 2, all_agreed: true };
    const netfail = () => Promise.reject(new TypeError("Failed to fetch"));
    // 200 헤더 뒤 본문이 끊김: api()는 본문 읽기 실패를 {}로 바꾼다
    const badbody = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null },
        json: () => Promise.reject(new SyntaxError("Unexpected end of JSON input")) });
    const CONFLICT = "동시에 요청이 처리되었습니다. 다시 시도해 주세요.";
    const NOT_ENTERED = "아직 현재 장면에 들어가지 않았습니다.";
    const IDS = ["tInput", "tSend", "hintBtn", "skipBtn", "nextBtn", "endBtn", "dmInput", "dmSubmit"];
    const view = env => ({
        ...snap(env),
        GET: env.calls.filter(c => c.method === "GET").length,
        urls: env.calls.map(c => c.method + " " + c.url),
        eyebrow: env.$("phaseEyebrow").textContent,
        tForm: !env.$("tForm").classList.contains("hidden"),
        finishedNote: !env.$("finishedNote").classList.contains("hidden"),
        off: Object.fromEntries(IDS.map(id => [id, env.$(id).disabled])),
        seats: env.$("seats").children.map(c => c.textContent),
        href: env.location.href ?? null,
    });
    // 꺼진 버튼·숨은 입력줄은 누를 수 없다(브라우저와 같게)
    const press = async (env, id) => { if (!env.$(id).disabled) env.$(id).dispatch("click"); await flush(); };
    const canType = (env, form) => !env.$(form === "dmForm" ? "dmInput" : "tInput").disabled &&
        !env.$(form).classList.contains("hidden");
    // 첫 로딩은 st, 요청 하나가 answer, 그 뒤 GET은 fresh
    async function stale(st, open, act, answer, fresh) {
        const e = makeEnv([], [resp(200, st)]);
        await flush();
        if (open) openSeat(e);
        e.queue.push(answer);
        if (fresh) e.gets.push(fresh);
        await act(e); await flush();
        return e;
    }
    const sayT = e => submit(e, "tForm", "보낸 글");
    const sayDM = e => dmSubmit(e, "보낸 글");
    const FIN409 = () => err(409, "SESSION_FINISHED", __FINISHED__);

    env = await stale(state(), false, sayT, FIN409(), resp(200, FIN()));
    out.s416_fin = view(env);
    if (canType(env, "tForm")) await submit(env, "tForm", "또 보낸 글");
    out.s416_fin_again = view(env);

    env = await stale(state(), true, sayDM, FIN409(), resp(200, FIN()));
    out.s416_fin_dm = view(env);
    CLOSE.button(env); openSeat(env);
    out.s416_fin_dm_reopen = view(env);

    env = await stale(state(37), false, sayT, err(409, "TURN_LIMIT", __LIMIT__), resp(200, state(40)));
    out.s416_limit = view(env);

    const other = state(11);
    other.utterances.push(T(10, 0, "다른 탭 발화"), S(11, 0, 1, "네 선생님"), S(12, 0, 2, "네 선생님"));
    env = await stale(state(), false, sayT, err(409, "CONFLICT_RETRY", CONFLICT), resp(200, other));
    out.s416_conflict = view(env);
    // 409 문구는 다음 요청이 시작될 때 지워진다
    const later = deferred();
    await submit(env, "tForm", "다시 보낸 글", later);
    out.s416_conflict_next = view(env);
    later.settle(turn("다시 보낸 글", null, 12)); await flush();

    env = await stale(state(), false, sayT, err(409, "PHASE_NOT_ENTERED", NOT_ENTERED), resp(200, SCENE2(false)));
    out.s416_not_entered = view(env);
    env.queue.push(resp(200, { utterances: ENTER1, agreement: AGREE, teacher_turns_used: 10, failed_persona_ids: [] }));
    if (!env.$("retryBox").classList.contains("hidden")) { env.$("retryBtn").onclick(); await flush(); }
    out.s416_not_entered_retry = view(env);

    env = await stale(state(), true, sayDM, err(409, "PHASE_NOT_ENTERED", NOT_ENTERED), resp(200, SCENE2(false)));
    out.s416_not_entered_dm = view(env);

    env = makeEnv([err(409, "PHASE_NOT_CURRENT", "현재 장면이 아닙니다.")], [resp(200, state(10, false)), resp(200, SCENE2())]);
    await flush();
    out.s416_enter409 = view(env);

    const agreed = state();
    agreed.agreement = ALL;
    env = await stale(agreed, false, e => press(e, "nextBtn"),
        err(409, "NOT_ALL_AGREED", "아직 모든 학생이 다음 장면에 동의하지 않았습니다."), resp(200, SCENE2()));
    out.s416_next409 = view(env);
    env = await stale(state(), false, e => press(e, "skipBtn"), FIN409(), resp(200, FIN()));
    out.s416_skip409 = view(env);
    env = await stale(state(), false, e => press(e, "endBtn"), FIN409(), resp(200, FIN()));
    out.s416_end409 = view(env);

    const broken = state();
    broken.utterances[1] = { ...broken.utterances[1], content: "", structured: null, failed: true };
    const fixed = state();
    fixed.utterances[1] = { ...fixed.utterances[1], content: "다른 탭에서 고친 반응", structured: { utterance: "다른 탭에서 고친 반응" } };
    const findBtn416 = n => n.tag === "button" ? n : (n.children || []).map(findBtn416).find(Boolean);
    env = await stale(broken, false, async e => { findBtn416(e.$("seats").children[0]).dispatch("click"); await flush(); },
        err(409, "NOTHING_TO_REGENERATE", "다시 생성할 학생 반응이 없습니다."), resp(200, fixed));
    out.s416_regen409 = view(env);

    // 다시 받기가 실패하면 낡은 상태로 둔다
    for (const [name, answer] of [["net", netfail],
        ["500", resp(500, { detail: "x" })],
        ["404", err(404, "SESSION_NOT_FOUND", "시뮬레이션 세션을 찾을 수 없습니다.")], ["badbody", badbody]]) {
        env = makeEnv([], [resp(200, state())]);
        await flush();
        out["s416_refail_" + name + "_before"] = view(env);
        env.queue.push(FIN409()); env.gets.push(answer);
        await sayT(env);
        out["s416_refail_" + name] = view(env);
    }

    // 첫 로딩의 자동 진입이 409이고 다시 받기도 실패: 재시도 상자도 띄우지 않는다
    for (const [name, answer] of [["net", netfail],
        ["500", resp(500, { detail: "x" })],
        ["404", err(404, "SESSION_NOT_FOUND", "시뮬레이션 세션을 찾을 수 없습니다.")], ["badbody", badbody]]) {
        env = makeEnv([err(409, "PHASE_NOT_CURRENT", "현재 장면이 아닙니다.")], [resp(200, state(10, false)), answer]);
        await flush();
        out["s416_enter_refail_" + name] = view(env);
    }

    // 409가 아니면 다시 받지 않는다(GET 응답을 준비하지 않았으므로 GET이 가면 GET 수에 보인다)
    for (const [name, answer] of [["429", err(429, "RESOURCE_EXHAUSTED", __Q429__, RA)],
        ["503", err(503, "MODEL_OVERLOADED", __Q503__, RA)], ["net", netfail],
        ["500", resp(500, { detail: "x" })], ["200", turn("보낸 글", null, 11)]]) {
        env = makeEnv([], [resp(200, state())]);
        await flush();
        await submit(env, "tForm", "보낸 글", answer);
        out["s416_noget_" + name] = view(env);
    }

    // 이 탭에서 수업 종료 200은 그대로 대화록으로 간다
    env = makeEnv([], [resp(200, state())]);
    await flush();
    env.queue.push(resp(200, { status: "finished" }));
    await press(env, "endBtn");
    out.s416_end200 = view(env);

    // ===== 실패하면 보낸 글을 보낸 입력칸에 되돌린다 (#415) =====
    const v415 = env => ({ ...view(env), tInput: env.$("tInput").value });
    async function boot415(st = state()) {
        const e = makeEnv([], [resp(200, st)]);
        await flush();
        return e;
    }
    const FAILS415 = {
        SESSION_FINISHED: FIN409, TURN_LIMIT: () => err(409, "TURN_LIMIT", __LIMIT__),
        CONFLICT_RETRY: () => err(409, "CONFLICT_RETRY", CONFLICT),
        PHASE_NOT_ENTERED: () => err(409, "PHASE_NOT_ENTERED", NOT_ENTERED),
        net: () => netfail, 500: () => resp(500, { detail: "x" }), 502: () => resp(502, "HTML"),
        401: () => resp(401, { detail: "로그인이 필요합니다." }),
        429: () => err(429, "RESOURCE_EXHAUSTED", __Q429__, RA), 503: () => err(503, "MODEL_OVERLOADED", __Q503__, RA),
    };
    for (const form of ["tForm", "dmForm"]) {
        for (const [name, answer] of Object.entries(FAILS415)) {
            env = await boot415();
            if (form === "dmForm") openSeat(env);
            env.gets.push(resp(200, state()));  // 409 뒤 다시 받기: 상태는 그대로
            await submit(env, form, "보낸 글", answer());
            out[`s415_${form}_${name}`] = v415(env);
        }
        const wait = deferred();
        env = await boot415();
        if (form === "dmForm") openSeat(env);
        await submit(env, form, "보낸 글", wait);
        out[`s415_${form}_wait`] = v415(env);
        wait.settle(turn("보낸 글", form === "dmForm" ? 1 : null, 11)); await flush();
        out[`s415_${form}_200`] = v415(env);
    }

    // 409 뒤 입력칸이 꺼짐(끝난 세션·상한, #416): 꺼진 칸에 글이 보인다
    env = await stale(state(), false, sayT, FIN409(), resp(200, FIN()));
    out.s415_fin_t = v415(env);
    env = await stale(state(), true, sayDM, FIN409(), resp(200, FIN()));
    out.s415_fin_dm = v415(env);
    env = await stale(state(37), false, sayT, err(409, "TURN_LIMIT", __LIMIT__), resp(200, state(40)));
    out.s415_limit_t = v415(env);
    env = await stale(state(37), true, sayDM, err(409, "TURN_LIMIT", __LIMIT__), resp(200, state(40)));
    out.s415_limit_dm = v415(env);

    // 409 뒤 다른 탭에서 장면이 넘어가 있음: 켜진 칸의 글을 그대로 다시 보낸다
    env = await stale(state(), false, sayT, err(409, "CONFLICT_RETRY", CONFLICT), resp(200, SCENE2()));
    out.s415_scene = v415(env);
    env.queue.push(turn("보낸 글", null, 11));
    env.$("tForm").dispatch("submit"); await flush();
    out.s415_scene_resend = v415(env);

    // 409로 돌아온 글을 그대로 제출 → 200
    env = await boot415(); openSeat(env);
    env.gets.push(resp(200, state()));
    await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
    env.queue.push(turn("보낸 글", 1, 11));
    env.$("dmForm").dispatch("submit"); await flush();
    out.s415_resend = v415(env);

    // 429 → '다시 시도' → 200 / → 409
    for (const form of ["tForm", "dmForm"]) {
        for (const [name, answer, get] of [["200", turn("보낸 글", form === "dmForm" ? 1 : null, 11)],
            ["409", FIN409(), resp(200, state())]]) {
            env = await boot415();
            if (form === "dmForm") openSeat(env);
            await submit(env, form, "보낸 글", err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
            env.seconds(30);
            env.queue.push(answer);
            if (get) env.gets.push(get);
            env.$("retryBtn").onclick(); await flush();
            out[`s415_${form}_retry${name}`] = v415(env);
        }
    }

    // 전체 발화를 기다리는 동안 '지도안 발문'을 누름 → 409
    env = await boot415();
    const hintWait = deferred();
    await submit(env, "tForm", "보낸 글", hintWait);
    await press(env, "hintBtn");
    env.gets.push(resp(200, state()));
    hintWait.settle(err(409, "CONFLICT_RETRY", CONFLICT)); await flush();
    out.s415_hint = v415(env);

    // 1:1 발화를 기다리는 동안 창을 닫음 / 다른 학생 창 / 같은 학생 창을 다시 엶 → 실패
    for (const [name, after] of [["closed", e => CLOSE.button(e)],
        ["other", e => { CLOSE.button(e); openSeat(e, 1); }],
        ["same", e => { CLOSE.button(e); openSeat(e, 0); }]]) {
        env = await boot415(); openSeat(env);
        const w = deferred();
        await dmSubmit(env, "보낸 글", w);
        after(env);
        w.settle(netfail); await flush();
        out["s415_away_" + name] = v415(env);
    }
    // 전체 발화를 기다리는 동안 1:1 창을 엶 → 실패
    env = await boot415();
    const classWait = deferred();
    await submit(env, "tForm", "보낸 글", classWait);
    openSeat(env, 1);
    classWait.settle(netfail); await flush();
    out.s415_class_open = v415(env);

    env = await boot415();
    await submit(env, "tForm", "   ");
    out.s415_blank = v415(env);

    // 채원(A)에게 되돌아온 글은 지호(B) 창에 나타나지 않는다. 다시 받기 중에 바꿔도, 끝난 뒤에 바꿔도 (#415 2차)
    for (const via of ["409", "retry409"]) {
        for (const when of ["pending", "done"]) {
            env = await boot415(); openSeat(env);
            const get = deferred();
            if (via === "409") {
                env.gets.push(get);
                await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
            } else {
                await dmSubmit(env, "보낸 글", err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
                env.seconds(30);
                env.queue.push(err(409, "CONFLICT_RETRY", CONFLICT));
                env.gets.push(get);
                env.$("retryBtn").onclick(); await flush();
            }
            const restored = env.$("dmInput").value;
            if (when === "done") { get.settle(resp(200, state())); await flush(); }
            CLOSE.button(env); openSeat(env, 1);
            if (when === "pending") { get.settle(resp(200, state())); await flush(); }
            const key = `s415_switch_${via}_${when}`;
            out[key] = { ...v415(env), restored };
            env.$("dmForm").dispatch("submit"); await flush();
            out[key + "_send"] = v415(env);
        }
    }
    // 같은 학생 창을 다시 열면 글이 남고 그 학생에게 보낼 수 있다
    env = await boot415(); openSeat(env);
    env.gets.push(resp(200, state()));
    await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
    CLOSE.button(env); openSeat(env, 0);
    out.s415_switch_same = v415(env);
    env.queue.push(turn("보낸 글", 1, 11));
    env.$("dmForm").dispatch("submit"); await flush();
    out.s415_switch_same_send = v415(env);
    // 교사가 친 글(보내지 않은 초안, 되돌아온 뒤 고친 글)은 지금처럼 창을 따라간다(범위 밖, 바꾸지 않음)
    env = await boot415(); openSeat(env);
    env.$("dmInput").value = "보내지 않은 초안";
    CLOSE.button(env); openSeat(env, 1);
    out.s415_switch_draft = v415(env);
    env = await boot415(); openSeat(env);
    env.gets.push(resp(200, state()));
    await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
    env.$("dmInput").value = "보낸 글 고침";
    CLOSE.button(env); openSeat(env, 1);
    out.s415_switch_edited = v415(env);

    // 교사가 입력칸에 친다: 브라우저처럼 input 이벤트가 간다 (#415 3차)
    const typeInto = (e, id, text) => { e.$(id).value = text; e.$(id).dispatch("input"); };
    // (a) 되돌린 글을 다시 보내 200 → 같은 문장을 새로 침 → 지호 창
    env = await boot415(); openSeat(env);
    env.gets.push(resp(200, state()));
    await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
    env.queue.push(turn("보낸 글", 1, 11));
    env.$("dmForm").dispatch("submit"); await flush();
    typeInto(env, "dmInput", "보낸 글");
    CLOSE.button(env); openSeat(env, 1);
    out.s415_marker_resent_retyped = v415(env);
    // (b) 되돌린 글을 고쳤다가 같은 글로 되돌림 → 지호 창
    env = await boot415(); openSeat(env);
    env.gets.push(resp(200, state()));
    await dmSubmit(env, "보낸 글", err(409, "CONFLICT_RETRY", CONFLICT));
    typeInto(env, "dmInput", "보낸 글 고침");
    typeInto(env, "dmInput", "보낸 글");
    CLOSE.button(env); openSeat(env, 1);
    out.s415_marker_edit_undo = v415(env);

    // 200 뒤 본문이 끊김: 서버에는 이미 저장된 발화이므로 되돌리지 않는다(다시 보내면 같은 글이 두 번) (#415 4차)
    for (const form of ["tForm", "dmForm"]) {
        env = await boot415();
        if (form === "dmForm") openSeat(env);
        await submit(env, form, "보낸 글", badbody);
        out[`s415_badbody_${form}`] = v415(env);
        env.$(form).dispatch("submit"); await flush();
        out[`s415_badbody_${form}_send`] = v415(env);
    }

    // ===== 이 탭이 보는 장면 번호를 싣고, 낡으면 409 뒤 새 장면을 그린다 (#420) =====
    const PNC = () => err(409, "PHASE_NOT_CURRENT", "현재 장면이 아닙니다.");
    const MOVED = (to = 1) => resp(200, { status: "running", current_phase_idx: to, next_phase: null });
    const ENTERED1 = () => resp(200, { utterances: ENTER1, agreement: AGREE, teacher_turns_used: 10, failed_persona_ids: [] });
    const TURN1 = resp(200, { utterances: [T(30, 1, "보낸 글"), S(31, 1, 1, "장면2 알겠어요"), S(32, 1, 2, "장면2 알겠어요")],
        agreement: AGREE, teacher_turns_used: 11, failed_persona_ids: [] });
    const AGREED2 = () => { const s = SCENE2(); s.agreement = ALL; return s; };
    const FINISHED_ADV = resp(200, { status: "finished", current_phase_idx: 1, next_phase: null });
    // 서버는 장면 1: 본문의 장면 번호가 0이면 409, 없으면 지금 서버처럼 ok로 답한다
    const at1 = ok => c => (c.body.phase_idx === 0 ? PNC() : ok)(c);

    // 낡지 않은 탭: 전체·1:1 발화와 Skip → 진입 → 발화, "다음 장면으로"
    env = await boot415();
    await submit(env, "tForm", "보낸 글", turn("보낸 글", null, 11));
    openSeat(env);
    await dmSubmit(env, "보낸 글", turn("보낸 글", 1, 12));
    out.p420_say = view(env);
    CLOSE.button(env);
    env.queue.push(MOVED(), ENTERED1()); env.gets.push(resp(200, SCENE2(false)));
    await press(env, "skipBtn");
    out.p420_skip = view(env);
    await submit(env, "tForm", "보낸 글", TURN1);
    out.p420_skip_say = view(env);
    const agreed0 = state(); agreed0.agreement = ALL;
    env = await stale(agreed0, false, e => press(e, "nextBtn"), MOVED(), resp(200, SCENE2()));
    out.p420_next = view(env);
    // 마지막 장면의 Skip: 다시 받지 않고 대화록으로
    env = await stale(SCENE2(), false, e => press(e, "skipBtn"), resp(200, { status: "finished", current_phase_idx: 1, next_phase: null }));
    out.p420_last = view(env);

    // 낡은 탭의 발화 409 → 새 장면, 글은 입력칸에 → 다시 보내면 새 장면 번호로
    env = await stale(state(), false, sayT, at1(TURN1), resp(200, SCENE2()));
    out.p420_stale_say = v415(env);
    env.queue.push(TURN1);
    env.$("tForm").dispatch("submit"); await flush();
    out.p420_stale_say_resend = v415(env);
    env = await stale(state(), true, sayDM, at1(TURN1), resp(200, SCENE2()));
    out.p420_stale_dm = v415(env);

    // 낡은 탭의 Skip·"다음 장면으로" 409 → 새 장면, 이동·진입 없음
    env = await stale(state(), false, e => press(e, "skipBtn"), at1(FINISHED_ADV), resp(200, SCENE2()));
    out.p420_stale_skip = view(env);
    env = await stale(agreed0, false, e => press(e, "nextBtn"), at1(FINISHED_ADV), resp(200, AGREED2()));
    out.p420_stale_next = view(env);
    env = await stale(state(), false, e => press(e, "skipBtn"), at1(FINISHED_ADV), resp(200, SCENE2(false)));
    out.p420_stale_skip_unentered = view(env);

    // 429 → (그 사이 다른 탭이 넘김) → '다시 시도': 처음 장면 번호로 보내고 409면 글을 되돌린다
    for (const form of ["tForm", "dmForm"]) {
        env = await boot415();
        if (form === "dmForm") openSeat(env);
        await submit(env, form, "보낸 글", err(429, "RESOURCE_EXHAUSTED", __Q429__, RA));
        env.seconds(30);
        env.queue.push(at1(TURN1)); env.gets.push(resp(200, SCENE2()));
        env.$("retryBtn").onclick(); await flush();
        out[`p420_retry_${form}`] = v415(env);
    }

    // A+: Skip 200 뒤 상태 GET을 기다리는 동안 버튼이 꺼져 있고, 다시 눌러도 요청이 나가지 않는다
    env = await boot415();
    const slowGet = deferred();
    env.queue.push(MOVED()); env.gets.push(slowGet);
    await press(env, "skipBtn");
    out.p420_gap = view(env);
    await press(env, "skipBtn");
    out.p420_gap_again = view(env);
    env.queue.push(ENTERED1());
    slowGet.settle(resp(200, SCENE2(false))); await flush();
    out.p420_gap_done = view(env);

    // A+: Skip 200 뒤 상태 GET이 전송 오류 → 옛 장면과 문구. 다시 Skip하면 409 뒤 새 장면
    env = await boot415();
    env.queue.push(MOVED()); env.gets.push(netfail);
    await press(env, "skipBtn");
    out.p420_getfail = view(env);
    env.queue.push(at1(FINISHED_ADV)); env.gets.push(resp(200, SCENE2(false)));
    await press(env, "skipBtn");
    out.p420_getfail_again = view(env);
    // 진입하지 않은 장면에서 Skip 200 뒤 GET 실패: 옛 장면에 진입 요청을 보내지 않는다(지금과 같다)
    env = makeEnv([err(503, "MODEL_OVERLOADED", __Q503__, RA)], [resp(200, state(10, false))]);
    await flush();
    env.queue.push(MOVED()); env.gets.push(netfail);
    await press(env, "skipBtn");
    out.p420_getfail_unentered = view(env);
    // Skip 200 뒤 상태 GET이 200인데 본문을 못 읽음: 옛 장면 그대로, 버튼은 풀리고 예외가 없다 (#420)
    const rejections = [];
    process.on("unhandledRejection", e => rejections.push(String(e)));
    env = await boot415();
    env.queue.push(MOVED()); env.gets.push(badbody);
    await press(env, "skipBtn");
    out.p420_badget = { ...view(env), rejections: rejections.length };
    env.queue.push(at1(FINISHED_ADV)); env.gets.push(resp(200, SCENE2()));
    await press(env, "skipBtn");
    out.p420_badget_again = { ...view(env), rejections: rejections.length };

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
        if s["open"]:
            assert not s["turnNote"], name
            # 안내 줄이나 상자가 생겨 대화 영역이 줄어도 마지막 말풍선이 보인다
            assert s["atBottom"], name
            if name in AWAY:
                # 다른 학생 몫의 재시도 오류는 창 안 줄에 들지 않는다
                assert s["dmTurnNote"] not in (Q429, Q503), name
                assert "@dmForm" not in s["box"], name
            else:
                assert not s["simStatus"] and "@tForm" not in s["box"], name
        else:
            assert not s["dmTurnNote"] and "@dmForm" not in s["box"], name


AWAY = {"away_say", "away_wait", "away_blank", "away_regen", "order_fail"}


@_node
def test_other_students_retry_stays_on_main_page(out):
    s = out["away_say"]
    assert (s["simStatus"], s["dmTurnNote"]) == (Q429, "남은 발화 3회")
    assert s["box"] == "다시 시도 (29초) off @tForm"
    s = out["away_wait"]
    assert (s["simStatus"], s["dmTurnNote"]) == (Q429, "")
    assert s["box"] == "다시 시도 (30초) off @tForm"


@_node
def test_back_in_targets_window_retry_resends_original(out):
    s = out["away_back"]
    assert (s["simStatus"], s["dmTurnNote"]) == ("", Q429)
    # 초 세기는 A → B → A를 거쳐도 이어진다
    assert s["box"] == "다시 시도 (29초) off @dmForm px-3"
    s = out["away_retry"]
    body = {
        "content": "채원아, 다시 말해 볼래?",
        "target_persona_id": 1,
        "phase_idx": 0,
    }
    assert s["bodies"] == [body, body]
    assert s["box"] == "hidden" and s["dmTurnNote"] == "남은 발화 2회"


@_node
def test_blank_input_in_other_window_still_shows_inside(out):
    s = out["away_blank"]
    assert (s["dmTurnNote"], s["simStatus"]) == (EMPTY, "")
    assert s["box"] == "다시 시도 (30초) off @tForm" and s["dmInput"] == "   "


@_node
def test_regenerate_retry_for_one_student_stays_on_main_page(out):
    s = out["away_regen"]
    assert (s["simStatus"], s["dmTurnNote"]) == (Q503, "")
    assert s["box"] == "다시 시도 (30초) off @tForm"
    assert s["POST"] == ["regenerate"]
    s = out["away_regen_back"]
    assert (s["simStatus"], s["dmTurnNote"]) == ("", Q503)
    assert s["box"] == "다시 시도 (30초) off @dmForm px-3"


@_node
def test_retry_box_is_not_reinserted_on_redraw(out):
    assert out["moves"]["again"] == 0


@_node
def test_retry_for_everyone_comes_into_any_window(out):
    s = out["skip503_open"]
    assert (s["simStatus"], s["dmTurnNote"]) == ("", Q503)
    assert s["box"] == "다시 시도 (30초) off @dmForm px-3"
    assert s["POST"] == ["advance"]


@_node
def test_other_students_error_never_written_into_window(out):
    log = out["order_fail"]["log"]
    assert "note:" + Q429 not in log, log
    assert "move:dmForm:shown" not in log, log
    assert out["order_fail"]["box"] == "다시 시도 (30초) off @tForm"


@_node
def test_box_hidden_before_it_moves_into_window(out):
    log = out["order_next"]["log"]
    # 숨기기 전에 창 안으로 옮기면 보이는 알림이 창 안에 잠깐 나타난다
    assert "move:dmForm:shown" not in log, log
    assert "move:dmForm:hidden" in log, log
    assert out["order_next"]["box"] == "hidden"


@_node
def test_open_window_panel_scrolled_to_form(out):
    # 패널이 화면보다 높으면 입력줄이 보이는 바닥으로 내린다
    for name, s in out.items():
        if s["open"]:
            assert s["panelAtBottom"], name


def test_panel_scrolls_instead_of_clipping():
    html = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(
        r'<div id="dmModal".*?\n\s*<div class="([^"]*)" role="dialog"',
        html,
        re.S,
    )
    assert m, "1:1 창 패널을 찾지 못함"
    classes = m.group(1).split()
    assert "overflow-y-auto" in classes and "overflow-hidden" not in classes
    assert {"max-h-[85vh]", "rounded-2xl", "flex", "flex-col"} <= set(classes)
    assert ".overflow-y-auto{overflow-y:auto}" in CSS.read_text(
        encoding="utf-8"
    )
    assert (
        "if (dmPersona) dmModal.firstElementChild.scrollTop ="
        " dmModal.firstElementChild.scrollHeight;" in html
    )


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
    # 좁은 화면에서 문장이 낱말 중간에서 끊기지 않게 한다 (#411)
    assert (
        '<span class="note break-keep">학생 반응을 받지 못했습니다.</span>'
        in html
    )
    assert (
        '<button type="button" id="retryBtn" class="text-sm font-semibold px-4 py-2'
        " rounded-lg bg-amber-500 hover:bg-amber-600 disabled:bg-gray-400"
        ' disabled:cursor-not-allowed text-white shrink-0">다시 시도</button>'
        in html
    )


# ===== 409 뒤 다시 받기 (#416) =====
CONFLICT = "동시에 요청이 처리되었습니다. 다시 시도해 주세요."
NOT_ENTERED = "아직 현재 장면에 들어가지 않았습니다."
ALL_OFF = {
    k: True
    for k in [
        "tInput",
        "tSend",
        "hintBtn",
        "skipBtn",
        "nextBtn",
        "endBtn",
        "dmInput",
        "dmSubmit",
    ]
}


def _finished_screen(s, text=FINISHED):
    assert s["GET"] == 2, s["urls"]  # 첫 로딩 + 다시 받기 1회
    assert (s["tForm"], s["finishedNote"]) == (False, True)
    assert s["off"] == ALL_OFF
    assert s["simStatus"] == text
    assert s["href"] is None


@_node
@pytest.mark.parametrize("key", ["s416_fin", "s416_skip409", "s416_end409"])
def test_409_finished_refetches_once_and_shows_finished_screen(out, key):
    _finished_screen(out[key])


@_node
def test_409_finished_then_cannot_say_again(out):
    s = out["s416_fin_again"]
    assert s["POST"] == ["say:보낸 글→null"] and s["GET"] == 2


@_node
def test_409_finished_in_window_keeps_window_open(out):
    s = out["s416_fin_dm"]
    assert s["open"] and s["GET"] == 2
    assert (s["dmTurnNote"], s["simStatus"]) == (FINISHED, "")
    assert s["off"]["dmInput"] and s["off"]["dmSubmit"]
    s = out["s416_fin_dm_reopen"]
    assert not s["open"] and s["finishedNote"]


@_node
def test_409_turn_limit_refetch_disables_saying(out):
    s = out["s416_limit"]
    assert s["GET"] == 2
    off = s["off"]
    assert off["tInput"] and off["tSend"] and off["hintBtn"]
    assert not off["skipBtn"] and not off["endBtn"]
    assert "남은 발화 3회" not in (s["turnNote"], s["simStatus"])
    assert s["simStatus"] == LIMIT


@_node
def test_409_conflict_shows_other_tabs_turn_and_keeps_message(out):
    s = out["s416_conflict"]
    assert s["GET"] == 2 and s["simStatus"] == CONFLICT
    assert "다른 탭 발화" in s["seats"][0] and "네 선생님" in s["seats"][0]
    # 다음 요청이 시작되면 문구가 지워진다
    assert out["s416_conflict_next"]["simStatus"] == ""


@_node
def test_409_phase_not_entered_shows_new_scene_with_retry_box(out):
    s = out["s416_not_entered"]
    assert s["GET"] == 2 and "전개" in s["eyebrow"]
    assert s["off"]["tInput"]
    assert s["box"] == "다시 시도 on @tForm"
    assert s["POST"] == ["say:보낸 글→null"]  # 저절로 진입하지 않는다
    s = out["s416_not_entered_retry"]
    assert s["urls"][-1] == "POST /api/simulation/sessions/1/phases/1/enter"
    assert s["POST"] == ["say:보낸 글→null", "enter"] and s["GET"] == 2
    assert "장면2 네" in s["seats"][0] and not s["off"]["tInput"]
    assert s["box"] == "hidden"


@_node
def test_409_phase_not_entered_retry_box_for_class_goes_into_window(out):
    # 반 전체의 재시도이므로 #411 규칙대로 열린 창 안에 둔다
    s = out["s416_not_entered_dm"]
    assert s["open"] and s["GET"] == 2
    assert s["box"] == "다시 시도 on @dmForm px-3"
    assert (s["dmTurnNote"], s["simStatus"]) == (NOT_ENTERED, "")


@_node
def test_enter_409_refetch_unblocks_screen(out):
    s = out["s416_enter409"]
    assert s["GET"] == 2 and "전개" in s["eyebrow"]
    assert "장면2 네" in s["seats"][0] and not s["off"]["tInput"]
    assert s["box"] == "hidden"


@_node
def test_next_409_shows_new_scene_and_disables_next(out):
    s = out["s416_next409"]
    assert s["GET"] == 2 and "전개" in s["eyebrow"]
    assert s["off"]["nextBtn"]


@_node
def test_regenerate_409_shows_fixed_row(out):
    s = out["s416_regen409"]
    assert s["GET"] == 2 and s["POST"] == ["regenerate"]
    assert "다른 탭에서 고친 반응" in s["seats"][0]
    assert "다시 생성" not in s["seats"][0] and "읽지 못했" not in s["seats"][0]


@_node
@pytest.mark.parametrize("name", ["net", "500", "404", "badbody"])
def test_refetch_failure_keeps_stale_screen_and_409_message(out, name):
    before, s = out[f"s416_refail_{name}_before"], out[f"s416_refail_{name}"]
    for k in ("eyebrow", "seats", "off", "tForm", "finishedNote", "box"):
        assert s[k] == before[k], k
    assert s["simStatus"] == FINISHED
    assert [u.split(" ")[0] for u in s["urls"]] == ["GET", "POST", "GET"]


@_node
@pytest.mark.parametrize("name", ["429", "503", "net", "500", "200"])
def test_non_409_does_not_refetch(out, name):
    assert out[f"s416_noget_{name}"]["GET"] == 1


@_node
def test_end_200_still_goes_to_transcript(out):
    s = out["s416_end200"]
    assert s["href"] == "/simulation/sessions/1/transcript" and s["GET"] == 1


@_node
@pytest.mark.parametrize("name", ["net", "500", "404", "badbody"])
def test_enter_409_refetch_failure_shows_no_retry_box(out, name):
    s = out[f"s416_enter_refail_{name}"]
    assert s["box"] == "hidden"
    assert s["simStatus"] == "현재 장면이 아닙니다."
    assert [u.split(" ")[0] for u in s["urls"]] == ["GET", "POST", "GET"]
    assert "도입" in s["eyebrow"] and s["off"]["tInput"]
    assert not any("네" in t for t in s["seats"])
    # 대기 중으로 남지 않는다: 진입 전 장면이라 말하기만 꺼지고 Skip·종료는 켜진다
    assert not s["off"]["skipBtn"] and not s["off"]["endBtn"]


# ===== 실패하면 보낸 글을 보낸 입력칸에 되돌린다 (#415) =====
SENT = "보낸 글"
NO_BOX_FAILS = [
    "SESSION_FINISHED",
    "TURN_LIMIT",
    "CONFLICT_RETRY",
    "PHASE_NOT_ENTERED",
    "net",
    "500",
    "502",
    "401",
]
FIELD = {"tForm": "tInput", "dmForm": "dmInput"}
OTHER = {"tForm": "dmInput", "dmForm": "tInput"}


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
@pytest.mark.parametrize("name", NO_BOX_FAILS)
def test_failure_without_retry_box_restores_text(out, form, name):
    s = out[f"s415_{form}_{name}"]
    assert (s[FIELD[form]], s[OTHER[form]]) == (SENT, "")
    assert s["box"] == "hidden" and len(s["POST"]) == 1
    # 요청 수와 순서는 그대로다: 409 뒤 다시 받기는 한 번뿐이다 (#416)
    methods = [u.split(" ")[0] for u in s["urls"]]
    expect = (
        ["GET", "POST", "GET"] if name in NO_BOX_FAILS[:4] else ["GET", "POST"]
    )
    assert methods == expect


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
@pytest.mark.parametrize("name", ["429", "503"])
def test_retry_box_failure_keeps_input_empty(out, form, name):
    s = out[f"s415_{form}_{name}"]
    assert (s["tInput"], s["dmInput"]) == ("", "")
    assert s["box"] != "hidden" and s["GET"] == 1


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
def test_success_leaves_input_empty_while_waiting_and_after(out, form):
    for key in (f"s415_{form}_wait", f"s415_{form}_200"):
        s = out[key]
        assert (s["tInput"], s["dmInput"]) == ("", ""), key


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
def test_retry_from_box_success_sends_once_more(out, form):
    s = out[f"s415_{form}_retry200"]
    assert len(s["POST"]) == 2 and s["bodies"][0] == s["bodies"][1]
    assert (s["tInput"], s["dmInput"]) == ("", "") and s["box"] == "hidden"


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
def test_retry_from_box_409_restores_text(out, form):
    s = out[f"s415_{form}_retry409"]
    assert (s[FIELD[form]], s[OTHER[form]]) == (SENT, "")
    assert len(s["POST"]) == 2 and s["GET"] == 2


@_node
@pytest.mark.parametrize(
    ("key", "field"),
    [
        ("s415_fin_t", "tInput"),
        ("s415_fin_dm", "dmInput"),
        ("s415_limit_t", "tInput"),
        ("s415_limit_dm", "dmInput"),
    ],
)
def test_409_that_disables_input_still_restores_text(out, key, field):
    s = out[key]
    assert s[field] == SENT and s["off"][field]
    assert s["GET"] == 2 and len(s["POST"]) == 1
    if field == "dmInput":
        assert s["open"] and s["tInput"] == ""


@_node
def test_409_with_changed_scene_restores_text_that_can_be_resent(out):
    s = out["s415_scene"]
    assert "전개" in s["eyebrow"]
    assert s["tInput"] == SENT and not s["off"]["tInput"]
    s = out["s415_scene_resend"]
    assert s["POST"] == [f"say:{SENT}→null"] * 2
    assert s["tInput"] == ""


@_node
def test_restored_text_resent_as_is(out):
    s = out["s415_resend"]
    assert s["POST"] == [f"say:{SENT}→1"] * 2
    assert s["dmInput"] == ""


@_node
def test_hint_written_while_waiting_is_not_overwritten(out):
    assert out["s415_hint"]["tInput"] == "발문"


@_node
@pytest.mark.parametrize(
    ("name", "dm"), [("closed", ""), ("other", ""), ("same", SENT)]
)
def test_dm_text_restored_only_in_same_students_window(out, name, dm):
    s = out["s415_away_" + name]
    assert (s["dmInput"], s["tInput"]) == (dm, "")


@_node
def test_class_text_restored_while_window_open(out):
    s = out["s415_class_open"]
    assert s["open"] and (s["tInput"], s["dmInput"]) == (SENT, "")


@_node
def test_blank_input_unchanged(out):
    s = out["s415_blank"]
    assert s["POST"] == [] and s["tInput"] == "   "


@_node
@pytest.mark.parametrize("via", ["409", "retry409"])
@pytest.mark.parametrize("when", ["pending", "done"])
def test_restored_dm_text_never_shows_in_other_students_window(out, via, when):
    key = f"s415_switch_{via}_{when}"
    s = out[key]
    assert s["restored"] == SENT
    assert s["open"] and s["dmInput"] == ""
    # 빈 칸이므로 Enter를 눌러도 지호에게 아무것도 가지 않는다
    sent = out[key + "_send"]["POST"]
    assert sent == s["POST"] and all(p.endswith("→1") for p in sent)


@_node
def test_restored_dm_text_stays_when_same_window_reopens(out):
    assert out["s415_switch_same"]["dmInput"] == SENT
    s = out["s415_switch_same_send"]
    assert s["POST"] == [f"say:{SENT}→1"] * 2 and s["dmInput"] == ""


@_node
@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("s415_switch_draft", "보내지 않은 초안"),
        ("s415_switch_edited", "보낸 글 고침"),
    ],
)
def test_typed_dm_draft_still_follows_window_switch(out, key, text):
    s = out[key]
    assert s["open"] and s["dmInput"] == text


@_node
@pytest.mark.parametrize(
    "key", ["s415_marker_resent_retyped", "s415_marker_edit_undo"]
)
def test_text_typed_after_restore_is_never_cleared_on_switch(out, key):
    # 표시는 손대지 않은 되돌린 글에만 붙는다. 같은 문장이라도 교사가 친 글은 남는다
    s = out[key]
    assert s["open"] and s["dmInput"] == SENT


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
def test_200_with_unreadable_body_restores_nothing(out, form):
    s = out[f"s415_badbody_{form}"]
    assert (s["tInput"], s["dmInput"]) == ("", "")
    # 빈 칸이므로 다시 제출해도 같은 글이 두 번 가지 않는다
    assert out[f"s415_badbody_{form}_send"]["POST"] == s["POST"]
    assert len(s["POST"]) == 1


# ===== 이 탭이 보는 장면 번호를 싣고, 낡으면 409 뒤 새 장면 (#420) =====
STALE_MSG = "현재 장면이 아닙니다."
OFF_IN_GAP = ["skipBtn", "nextBtn", "endBtn", "tInput", "dmInput"]


@_node
def test_requests_carry_shown_phase_idx(out):
    s = out["p420_say"]
    assert s["bodies"] == [
        {"content": SENT, "target_persona_id": None, "phase_idx": 0},
        {"content": SENT, "target_persona_id": 1, "phase_idx": 0},
    ]
    s = out["p420_skip"]
    assert s["bodies"][2] == {"mode": "skip", "phase_idx": 0}
    # 넘긴 뒤 GET은 한 번, 그 뒤 새 장면 진입 (A+)
    assert s["GET"] == 2 and [
        u.split("/sessions/1")[-1] for u in s["urls"][-3:]
    ] == [
        "/advance",
        "",
        "/phases/1/enter",
    ]
    assert "전개" in s["eyebrow"]
    assert out["p420_skip_say"]["bodies"][-1]["phase_idx"] == 1
    s = out["p420_next"]
    assert s["bodies"] == [{"mode": "agree", "phase_idx": 0}]
    assert s["GET"] == 2 and s["POST"] == ["advance"] and "전개" in s["eyebrow"]


@_node
def test_last_scene_skip_goes_to_transcript_without_refetch(out):
    s = out["p420_last"]
    assert s["bodies"] == [{"mode": "skip", "phase_idx": 1}]
    assert s["GET"] == 1 and s["href"] == "/simulation/sessions/1/transcript"


@_node
def test_stale_say_409_shows_new_scene_and_resend_uses_new_phase(out):
    s = out["p420_stale_say"]
    assert s["GET"] == 2 and "전개" in s["eyebrow"]
    assert any("장면2 네" in t for t in s["seats"])
    assert s["simStatus"] == STALE_MSG
    assert s["tInput"] == SENT and not s["off"]["tInput"]
    s = out["p420_stale_say_resend"]
    assert s["bodies"][1] == {
        "content": SENT,
        "target_persona_id": None,
        "phase_idx": 1,
    }
    assert len(s["POST"]) == 2 and s["simStatus"] == "" and s["tInput"] == ""
    assert any("장면2 알겠어요" in t for t in s["seats"])


@_node
def test_stale_dm_say_409_keeps_window_open_with_text_back(out):
    s = out["p420_stale_dm"]
    assert s["open"] and "전개" in s["eyebrow"]
    assert (s["dmTurnNote"], s["simStatus"]) == (STALE_MSG, "")
    assert (s["dmInput"], s["tInput"]) == (SENT, "")


@_node
@pytest.mark.parametrize("key", ["p420_stale_skip", "p420_stale_next"])
def test_stale_advance_409_shows_new_scene_without_moving(out, key):
    s = out[key]
    assert s["GET"] == 2 and "전개" in s["eyebrow"]
    assert s["POST"] == ["advance"] and s["href"] is None
    assert s["simStatus"] == STALE_MSG
    if key == "p420_stale_next":
        assert not s["off"]["nextBtn"]


@_node
def test_stale_skip_409_unentered_scene_shows_retry_box(out):
    s = out["p420_stale_skip_unentered"]
    assert "전개" in s["eyebrow"] and s["off"]["tInput"]
    assert s["box"] != "hidden" and s["POST"] == ["advance"]


@_node
@pytest.mark.parametrize("form", ["tForm", "dmForm"])
def test_retry_box_sends_original_phase_then_409_restores(out, form):
    s = out[f"p420_retry_{form}"]
    assert len(s["bodies"]) == 2 and s["bodies"][0] == s["bodies"][1]
    assert s["bodies"][1]["phase_idx"] == 0
    assert (s[FIELD[form]], s[OTHER[form]]) == (SENT, "")
    assert s["GET"] == 2 and "전개" in s["eyebrow"]


@_node
def test_controls_off_until_state_refetched_after_advance(out):
    s = out["p420_gap"]
    assert all(s["off"][k] for k in OFF_IN_GAP), s["off"]
    assert s["POST"] == ["advance"]
    assert out["p420_gap_again"]["POST"] == ["advance"]
    s = out["p420_gap_done"]
    assert s["POST"] == ["advance", "enter"] and s["GET"] == 2
    assert "전개" in s["eyebrow"] and not s["off"]["tInput"]
    assert s["box"] == "hidden" and s["simStatus"] == ""


@_node
def test_refetch_failure_after_advance_keeps_old_scene(out):
    s = out["p420_getfail"]
    assert "도입" in s["eyebrow"] and s["simStatus"] == "Failed to fetch"
    assert s["POST"] == ["advance"] and s["GET"] == 2
    s = out["p420_getfail_again"]
    assert s["POST"] == ["advance", "advance"] and s["GET"] == 3
    assert "전개" in s["eyebrow"] and s["box"] != "hidden"
    s = out["p420_getfail_unentered"]
    assert s["POST"] == ["enter", "advance"] and s["GET"] == 2


@_node
def test_unreadable_state_after_advance_keeps_old_scene_unlocked(out):
    s = out["p420_badget"]
    assert s["rejections"] == 0
    assert "도입" in s["eyebrow"] and s["POST"] == ["advance"] and s["GET"] == 2
    assert not any(s["off"][k] for k in OFF_IN_GAP if k != "nextBtn"), s["off"]
    s = out["p420_badget_again"]
    assert s["rejections"] == 0
    assert s["POST"] == ["advance", "advance"] and s["GET"] == 3
    assert "전개" in s["eyebrow"] and s["simStatus"] == STALE_MSG
