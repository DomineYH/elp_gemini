"""
관리자 활동 집계에 시뮬레이션 포함 (#188) · 관리자 대시보드 실제 통계 (#181)
"""

import os
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.models.lessonplan_uploads import LessonPlanUpload
from app.routers.admin.dashboard import _collect_metrics
from tests.simulation.conftest import run


def _create_session(client, make_upload, user):
    make_upload(user)
    r = client.post(
        "/api/simulation/sessions",
        json={
            "random": {"n": 2, "grade": "all", "level": "all", "seed": 3},
            "phases": [{"name": "도입", "teacher_prompt": "발문"}],
        },
    )
    assert r.status_code == 201
    return r.json()["session"]["id"]


@pytest.fixture
def two_sessions(
    client, as_user, teacher, other_teacher, make_upload, fake_gemini
):
    mine = _create_session(client, make_upload, teacher)
    as_user(other_teacher)
    theirs = _create_session(client, make_upload, other_teacher)
    return mine, theirs


def test_account_list_and_profile_include_simulation_count(
    client, as_user, admin, teacher, other_teacher, two_sessions
):
    as_user(admin)
    accounts = client.get("/admin/api/users/accounts").json()["accounts"]
    by_id = {a["user_id"]: a for a in accounts}
    assert by_id[teacher.id]["simulation_count"] == 1
    assert by_id[teacher.id]["session_count"] == 0  # QnA 세션 의미는 그대로
    assert by_id[other_teacher.id]["simulation_count"] == 1

    profile = client.get(f"/admin/api/users/{teacher.id}").json()
    assert profile["simulation_count"] == 1
    assert profile["session_count"] == 0


def test_simulation_list_filters_by_user_id(
    client, as_user, admin, teacher, two_sessions
):
    mine, _ = two_sessions
    as_user(admin)
    assert client.get("/admin/api/simulation/sessions").json()["total"] == 2
    body = client.get(
        "/admin/api/simulation/sessions", params={"user_id": teacher.id}
    ).json()
    assert body["total"] == 1
    assert [s["id"] for s in body["sessions"]] == [mine]


def test_user_detail_links_to_filtered_simulation_logs(
    client, as_user, admin, teacher
):
    as_user(admin)
    html = client.get(f"/admin/users/{teacher.id}").text
    assert f'href="/admin/simulation/logs?user_id={teacher.id}"' in html
    assert 'id="simulationTotal"' in html
    logs = client.get("/admin/simulation/logs").text
    assert "get('user_id')" in logs
    assert "${userQuery}" in logs


def test_admin_dashboard_shows_real_counts(
    client, as_user, admin, two_sessions
):
    as_user(admin)
    html = client.get("/admin/dashboard").text

    def metric(key):
        m = re.search(rf'data-metric="{key}">(\d+)<', html)
        assert m, key
        return int(m.group(1))

    assert metric("total_users") == 2  # 관리자 제외
    assert metric("uploads") == 2
    assert metric("uploads_7d") == 2
    assert metric("simulations") == 2
    assert metric("simulations_7d") == 2
    assert metric("reports") == 0
    assert metric("qna_sessions") == 0


def test_user_dashboard_session_count_label_is_qna():
    from pathlib import Path

    html = Path("app/templates/user/dashboard.html").read_text()
    assert ">지난 QnA 세션<" in html


def test_dashboard_7day_boundary_uses_utc_on_non_utc_server(sim_db, teacher):
    # created_at은 UTC naive(CURRENT_TIMESTAMP). 서버 TZ가 KST여도 경계는 UTC.
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)

    async def _go():
        async with sim_db() as db:
            for hours, name in ((167, "in.pdf"), (169, "out.pdf")):
                db.add(
                    LessonPlanUpload(
                        user_id=teacher.id,
                        filename=name,
                        created_at=utc_now - timedelta(hours=hours),
                    )
                )
            await db.commit()
            return await _collect_metrics(db)

    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Seoul"
    time.tzset()
    try:
        metrics = run(_go())
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()

    uploads = next(m for m in metrics["activity"] if m["key"] == "uploads")
    assert uploads["total"] == 2
    assert uploads["last_7days"] == 1
