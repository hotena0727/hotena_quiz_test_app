from pathlib import Path
import random
import pandas as pd
import streamlit as st
from supabase import create_client
from streamlit_cookies_manager import EncryptedCookieManager

# ============================================================
# ✅ Streamlit 기본 설정 (최상단)
# ============================================================
st.set_page_config(page_title="JLPT Quiz", layout="centered")

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kosugi+Maru&family=Noto+Sans+JP:wght@400;500;700;800&display=swap" rel="stylesheet">

<style>
:root{ --jp-rounded: "Noto Sans JP","Kosugi Maru","Hiragino Sans","Yu Gothic","Meiryo",sans-serif; }
.jp, .jp *{ font-family: var(--jp-rounded) !important; line-height:1.7; letter-spacing:.2px; }

div[data-testid="stRadio"] * ,
div[data-baseweb="radio"] * ,
label[data-baseweb="radio"] * {
  font-family: var(--jp-rounded) !important;
}
</style>
""", unsafe_allow_html=True)

st.title("い형용사 퀴즈")

# ============================================================
# ✅ Cookies
# ============================================================
cookies = EncryptedCookieManager(
    prefix="hatena_jlpt_",   # ✅ 슬래시 제거
    password=st.secrets["COOKIE_PASSWORD"],  # ✅ 가능하면 secrets에 고정
)
if not cookies.ready():
    st.info("쿠키를 초기화하는 중입니다… 잠시 후 자동으로 다시 시도됩니다.")
    st.stop()

# ============================================================
# ✅ Supabase 연결
# ============================================================
if "SUPABASE_URL" not in st.secrets or "SUPABASE_ANON_KEY" not in st.secrets:
    st.error("Supabase Secrets가 설정되지 않았습니다. (SUPABASE_URL / SUPABASE_ANON_KEY)")
    st.stop()

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ============================================================
# ✅ 상수/설정
# ============================================================
NAVER_TALK_URL = "https://talk.naver.com/W45141"
APP_URL = "https://hotenaquiztestapp-5wiha4zfuvtnq4qgxdhq72.streamlit.app/"
LEVEL = "N4"
N = 10
KST_TZ = "Asia/Seoul"

quiz_label_map = {
    "reading": "발음",
    "meaning": "뜻",
    "kr2jp": "한→일",
}
quiz_label_for_table = {
    "reading": "발음",
    "meaning": "뜻",
    "kr2jp": "한→일",
}
QUIZ_TYPES = ["reading", "meaning", "kr2jp"]

# ============================================================
# ✅ mastered_words를 유형별로 유지하는 유틸
# ============================================================
def ensure_mastered_words_shape():
    if "mastered_words" not in st.session_state or not isinstance(st.session_state.mastered_words, dict):
        st.session_state.mastered_words = {"reading": set(), "meaning": set(), "kr2jp": set()}
    else:
        for k in QUIZ_TYPES:
            st.session_state.mastered_words.setdefault(k, set())

# ============================================================
# ✅ (중요) 위젯 잔상(q_...) 완전 제거 유틸
# ============================================================
def clear_question_widget_keys():
    keys_to_del = [k for k in list(st.session_state.keys()) if isinstance(k, str) and k.startswith("q_")]
    for k in keys_to_del:
        st.session_state.pop(k, None)
# ============================================================
# ✅ (핵심) 위젯 값 기준으로 answers를 재구성 (보이는 것 = 채점)
# ============================================================
def sync_answers_from_widgets():
    qv = st.session_state.get("quiz_version", 0)
    quiz = st.session_state.get("quiz", [])
    if not isinstance(quiz, list):
        return

    answers = st.session_state.get("answers")
    if not isinstance(answers, list) or len(answers) != len(quiz):
        st.session_state.answers = [None] * len(quiz)

    for idx in range(len(quiz)):
        widget_key = f"q_{qv}_{idx}"
        if widget_key in st.session_state:
            st.session_state.answers[idx] = st.session_state[widget_key]

import time

def mark_progress_dirty():
    st.session_state.progress_dirty = True
    st.session_state._progress_dirty_ts = time.time()

    # ✅ 로그인 상태 + authed client 있을 때만 저장
    sb_authed_local = get_authed_sb()
    u = st.session_state.get("user")
    if (sb_authed_local is None) or (u is None):
        return

    # ✅ 너무 자주 저장하지 않게 1.0초 쿨다운(원하면 0.3~2초로 조절)
    now = time.time()
    last = st.session_state.get("_last_progress_save_ts", 0.0)
    if now - last < 1.0:
        return

    try:
        save_progress_to_db(sb_authed_local, u.id)
        st.session_state._last_progress_save_ts = now
        st.session_state.progress_dirty = False
    except Exception:
        # 저장 실패해도 앱 흐름은 유지
        pass


# ============================================================
# ✅ (핵심) 퀴즈 상태를 "시험 시작 전"으로 한 방에 세팅
# ============================================================
def start_quiz_state(quiz_list: list, qtype: str, clear_wrongs: bool = True):
    st.session_state.quiz_version = int(st.session_state.get("quiz_version", 0)) + 1

    st.session_state.quiz_type = qtype
    st.session_state.quiz = quiz_list
    st.session_state.answers = [None] * len(quiz_list)

    st.session_state.submitted = False
    st.session_state.saved_this_attempt = False
    st.session_state.stats_saved_this_attempt = False
    st.session_state.session_stats_applied_this_attempt = False

    if clear_wrongs:
        st.session_state.wrong_list = []

# ============================================================
# ✅ 유틸: JWT 만료 감지 + 세션 갱신 + DB 호출 래퍼
# ============================================================
def is_jwt_expired_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("jwt expired" in msg) or ("pgrst303" in msg)

def clear_auth_everywhere():
    try:
        cookies["access_token"] = ""
        cookies["refresh_token"] = ""
        cookies.save()
    except Exception:
        pass

    for k in [
        "user", "access_token", "refresh_token",
        "login_email", "email_link_notice_shown",
        "auth_mode", "signup_done", "last_signup_ts",
        "page",
        "quiz", "answers", "submitted", "wrong_list",
        "quiz_version", "quiz_type", "saved_this_attempt",
        "stats_saved_this_attempt",
        "history", "wrong_counter", "total_counter",
        "attendance_checked", "streak_count", "did_attend_today",
        "is_admin_cached",
        "session_stats_applied_this_attempt",
        "mastered_words",
        "progress_restored",
    ]:
        st.session_state.pop(k, None)

# ============================================================
# ✅✅✅ (로그인 유지/새로고침 복원) 최소 수정 핵심
#   1) refresh_token으로 refresh_session 시도
#   2) 실패하면 access_token으로 get_user 시도 (새로고침 대비)
# ============================================================
def refresh_session_from_cookie_if_needed(force: bool = False) -> bool:
    # 이미 세션 살아있으면 통과
    if not force and st.session_state.get("user") and st.session_state.get("access_token"):
        return True

    rt = cookies.get("refresh_token")
    at = cookies.get("access_token")

    # 1) refresh_token이 있으면 우선 refresh 시도
    if rt:
        try:
            refreshed = sb.auth.refresh_session(rt)
            if refreshed and refreshed.session and refreshed.session.access_token:
                st.session_state.user = refreshed.user
                st.session_state.access_token = refreshed.session.access_token
                st.session_state.refresh_token = refreshed.session.refresh_token

                u_email = getattr(refreshed.user, "email", None)
                if u_email:
                    st.session_state["login_email"] = u_email.strip()

                cookies["access_token"] = refreshed.session.access_token
                cookies["refresh_token"] = refreshed.session.refresh_token
                cookies.save()
                return True
        except Exception:
            # refresh 실패 시 2) access_token으로 user 조회 fallback
            pass

    # 2) refresh가 없거나 실패했을 때 access_token으로 user 복원 시도
    if at:
        try:
            u = sb.auth.get_user(at)
            # supabase-py 버전에 따라 u.user / u.data 등 차이 있을 수 있어 안전하게 처리
            user_obj = getattr(u, "user", None) or getattr(u, "data", None) or None
            if user_obj:
                st.session_state.user = user_obj
                st.session_state.access_token = at
                # refresh_token은 없을 수 있음 (있으면 세팅)
                if rt:
                    st.session_state.refresh_token = rt

                u_email = getattr(user_obj, "email", None)
                if u_email:
                    st.session_state["login_email"] = u_email.strip()
                return True
        except Exception:
            pass

    return False

def get_authed_sb():
    if not st.session_state.get("access_token"):
        refresh_session_from_cookie_if_needed(force=True)

    token = st.session_state.get("access_token")
    if not token:
        return None

    sb2 = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb2.postgrest.auth(token)
    return sb2

def run_db(callable_fn):
    try:
        return callable_fn()
    except Exception as e:
        if is_jwt_expired_error(e):
            ok = refresh_session_from_cookie_if_needed(force=True)
            if ok:
                st.rerun()
            clear_auth_everywhere()
            st.warning("세션이 만료되었습니다. 다시 로그인해 주세요.")
            st.rerun()
        raise

def to_kst_naive(x):
    ts = pd.to_datetime(x, utc=True, errors="coerce")
    if hasattr(ts, "dt"):
        return ts.dt.tz_convert(KST_TZ).dt.tz_localize(None)
    return ts.tz_convert(KST_TZ).tz_localize(None) if ts is not pd.NaT else ts

# ============================================================
# ✅ DB 함수
# ============================================================
def ensure_profile(sb_authed, user):
    try:
        sb_authed.table("profiles").upsert(
            {"id": user.id, "email": getattr(user, "email", None)},
            on_conflict="id",
        ).execute()
    except Exception:
        pass

def mark_attendance_once(sb_authed):
    if st.session_state.get("attendance_checked"):
        return None

    try:
        res = sb_authed.rpc("mark_attendance_kst", {}).execute()
        st.session_state.attendance_checked = True
        return res.data[0] if res.data else None
    except Exception:
        st.session_state.attendance_checked = True
        return None

def save_attempt_to_db(sb_authed, user_id, user_email, level, quiz_type, quiz_len, score, wrong_list):
    payload = {
        "user_id": user_id,
        "user_email": user_email,
        "level": level,
        "pos_mode": quiz_type,
        "quiz_len": int(quiz_len),
        "score": int(score),
        "wrong_count": int(len(wrong_list)),
        "wrong_list": wrong_list,
    }
    sb_authed.table("quiz_attempts").insert(payload).execute()

def fetch_recent_attempts(sb_authed, user_id, limit=10):
    return (
        sb_authed.table("quiz_attempts")
        .select("created_at, level, pos_mode, quiz_len, score, wrong_count")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

def fetch_all_attempts_admin(sb_authed, limit=500):
    return (
        sb_authed.table("quiz_attempts")
        .select("created_at, user_email, level, pos_mode, quiz_len, score, wrong_count")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

def fetch_is_admin_from_db(sb_authed, user_id):
    try:
        res = sb_authed.table("profiles").select("is_admin").eq("id", user_id).single().execute()
        if res and res.data and "is_admin" in res.data:
            return bool(res.data["is_admin"])
    except Exception:
        pass
    return False

def save_word_stats_via_rpc(sb_authed, quiz: list[dict], answers: list, quiz_type: str, level: str):
    for idx, q in enumerate(quiz):
        word_key = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())
        if not word_key:
            continue

        is_correct = (answers[idx] == q.get("correct_text"))
        pos = str(q.get("pos", "") or "")

        sb_authed.rpc(
            "record_word_result",
            {
                "p_word_key": word_key,
                "p_level": level,
                "p_pos": pos,
                "p_quiz_type": quiz_type,
                "p_is_correct": bool(is_correct),
            },
        ).execute()

# ============================================================
# ✅ Progress (DB 저장/복원)
# ============================================================
def save_progress_to_db(sb_authed, user_id: str):
    if "quiz" not in st.session_state or "answers" not in st.session_state:
        return

    payload = {
        "quiz_type": st.session_state.get("quiz_type"),
        "quiz_version": int(st.session_state.get("quiz_version", 0) or 0),
        "quiz": st.session_state.get("quiz"),
        "answers": st.session_state.get("answers"),
        "submitted": bool(st.session_state.get("submitted", False)),
    }

    sb_authed.table("profiles").upsert(
        {"id": user_id, "progress": payload},
        on_conflict="id",
    ).execute()

def clear_progress_in_db(sb_authed, user_id: str):
    sb_authed.table("profiles").upsert(
        {"id": user_id, "progress": None},
        on_conflict="id",
    ).execute()

def restore_progress_from_db(sb_authed, user_id: str):
    try:
        res = (
            sb_authed.table("profiles")
            .select("progress")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        return

    if not res or not res.data:
        return

    progress = res.data.get("progress")
    if not progress:
        return

    st.session_state.quiz_type = progress.get("quiz_type", st.session_state.get("quiz_type", "reading"))
    st.session_state.quiz_version = int(progress.get("quiz_version", st.session_state.get("quiz_version", 0) or 0))
    st.session_state.quiz = progress.get("quiz", st.session_state.get("quiz"))
    st.session_state.answers = progress.get("answers", st.session_state.get("answers"))
    st.session_state.submitted = bool(progress.get("submitted", st.session_state.get("submitted", False)))

    if isinstance(st.session_state.quiz, list):
        qlen = len(st.session_state.quiz)
        if not isinstance(st.session_state.answers, list) or len(st.session_state.answers) != qlen:
            st.session_state.answers = [None] * qlen

# ============================================================
# ✅ Admin 설정 (DB ONLY)
# ============================================================
def is_admin() -> bool:
    cached = st.session_state.get("is_admin_cached")
    if cached is not None:
        return bool(cached)

    u = st.session_state.get("user")
    if u is None:
        st.session_state["is_admin_cached"] = False
        return False

    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        st.session_state["is_admin_cached"] = False
        return False

    val = fetch_is_admin_from_db(sb_authed_local, u.id)
    st.session_state["is_admin_cached"] = val
    return bool(val)

# ============================================================
# ✅ 로그인 UI
# ============================================================
def auth_box():
    st.subheader("로그인")

    qp = st.query_params
    came_from_email_link = any(k in qp for k in ["code", "token", "type", "access_token", "refresh_token"])
    if came_from_email_link and not st.session_state.get("email_link_notice_shown"):
        st.session_state.email_link_notice_shown = True
        st.session_state.auth_mode = "login"
        st.success("이메일 인증(또는 링크 확인)이 완료되었습니다. 이제 로그인해 주세요.")

    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "login"

    mode = st.radio(
        label="",
        options=["login", "signup"],
        format_func=lambda x: "로그인" if x == "login" else "회원가입",
        horizontal=True,
        key="auth_mode_radio",
        index=0 if st.session_state.auth_mode == "login" else 1,
    )
    st.session_state.auth_mode = mode

    if st.session_state.get("signup_done"):
        st.success("회원가입 요청 완료! 이메일 인증이 필요할 수 있어요. 메일함을 확인한 뒤 로그인해 주세요.")
        st.session_state.signup_done = False

    if mode == "login":
        email = st.text_input("이메일", key="login_email_input")
        pw = st.text_input("비밀번호", type="password", key="login_pw_input")

        st.caption("비밀번호는 **회원가입 때 8자리 이상**으로 설정했을 가능성이 큽니다.")
        if pw and len(pw) < 8:
            st.warning(f"입력하신 비밀번호가 {len(pw)}자리입니다. 회원가입 때 8자리 이상으로 설정하셨다면 더 길게 입력해 주세요.")

        if st.button("로그인", use_container_width=True, key="btn_login"):
            if not email or not pw:
                st.warning("이메일과 비밀번호를 입력해주세요.")
                st.stop()

            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": pw})

                st.session_state.user = res.user
                st.session_state["login_email"] = email.strip()

                if res.session and res.session.access_token:
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token

                    cookies["access_token"] = res.session.access_token
                    cookies["refresh_token"] = res.session.refresh_token
                    cookies.save()
                else:
                    st.warning("로그인은 되었지만 세션 토큰이 없습니다. 이메일 인증 상태를 확인해주세요.")
                    st.session_state.access_token = None
                    st.session_state.refresh_token = None

                st.session_state.pop("is_admin_cached", None)
                st.success("로그인 완료!")
                st.rerun()

            except Exception:
                st.error("로그인 실패: 이메일/비밀번호 또는 이메일 인증 상태를 확인해주세요.")
                st.stop()

    else:
        email = st.text_input("이메일", key="signup_email")
        pw = st.text_input("비밀번호", type="password", key="signup_pw")

        pw_len = len(pw) if pw else 0
        pw_ok = pw_len >= 8
        email_ok = bool(email and email.strip())

        st.caption("비밀번호는 **8자리 이상**으로 설정해 주세요.")
        if pw and not pw_ok:
            st.warning(f"비밀번호가 너무 짧습니다. (현재 {pw_len}자) 8자리 이상으로 입력해 주세요.")

        if st.button("회원가입", use_container_width=True, disabled=not (email_ok and pw_ok), key="btn_signup"):
            try:
                import time
                last = st.session_state.get("last_signup_ts", 0.0)
                now = time.time()
                if now - last < 8:
                    st.warning("요청이 너무 빠릅니다. 잠시 후 다시 시도해주세요.")
                    st.stop()
                st.session_state.last_signup_ts = now

                sb.auth.sign_up(
                    {
                        "email": email,
                        "password": pw,
                        "options": {"email_redirect_to": APP_URL},
                    }
                )

                st.session_state.signup_done = True
                st.session_state.auth_mode = "login"
                st.session_state["login_email"] = email.strip()
                st.rerun()

            except Exception as e:
                msg = str(e).lower()
                if "rate limit" in msg and "email" in msg:
                    st.session_state.auth_mode = "login"
                    st.session_state["login_email"] = email.strip()
                    st.session_state.signup_done = False
                    st.warning("이메일 발송 제한에 걸렸습니다. 잠시 후 다시 시도해주세요.")
                    st.rerun()

                st.error("회원가입 실패(에러 확인):")
                st.exception(e)
                st.stop()

def require_login():
    if st.session_state.get("user") is None:
        auth_box()
        st.stop()

# ============================================================
# ✅ 네이버톡 배너 (제출 후만)
# ============================================================
def render_naver_talk():
    st.divider()
    st.markdown(
        f"""
<style>
@keyframes floaty {{
  0% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-6px); }}
  100% {{ transform: translateY(0); }}
}}
@keyframes ping {{
  0% {{ transform: scale(1); opacity: 0.9; }}
  70% {{ transform: scale(2.2); opacity: 0; }}
  100% {{ transform: scale(2.2); opacity: 0; }}
}}
.floating-naver-talk,
.floating-naver-talk:visited,
.floating-naver-talk:hover,
.floating-naver-talk:active {{
  position: fixed;
  right: 18px;
  bottom: 90px;
  z-index: 99999;
  text-decoration: none !important;
  color: inherit !important;
}}
.floating-wrap {{
  position: relative;
  animation: floaty 2.2s ease-in-out infinite;
}}
.talk-btn {{
  background: #03C75A;
  color: #fff;
  border: 0;
  border-radius: 999px;
  padding: 14px 18px;
  font-size: 15px;
  font-weight: 700;
  box-shadow: 0 12px 28px rgba(0,0,0,0.22);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.1;
  text-decoration: none !important;
}}
.talk-btn:hover {{ filter: brightness(0.95); }}
.talk-text small {{
  display: block;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.95;
  margin-top: 2px;
}}
.badge {{
  position: absolute;
  top: -6px;
  right: -6px;
  width: 12px;
  height: 12px;
  background: #ff3b30;
  border-radius: 999px;
  box-shadow: 0 6px 14px rgba(0,0,0,0.25);
}}
.badge::after {{
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 12px;
  height: 12px;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: rgba(255,59,48,0.55);
  animation: ping 1.2s ease-out infinite;
}}
@media (max-width: 600px) {{
  .floating-naver-talk {{ bottom: 110px; right: 14px; }}
  .talk-btn {{ padding: 13px 16px; font-size: 14px; }}
  .talk-text small {{ font-size: 11px; }}
}}
</style>

<a class="floating-naver-talk" href="{NAVER_TALK_URL}" target="_blank" rel="noopener noreferrer">
  <div class="floating-wrap">
    <span class="badge"></span>
    <button class="talk-btn" type="button">
      <span>💬</span>
      <span class="talk-text">
        1:1 하테나쌤 상담
        <small>수강신청 문의하기</small>
      </span>
    </button>
  </div>
</a>
""",
        unsafe_allow_html=True,
    )

# ============================================================
# ✅ 앱 시작: refresh → 로그인 강제 → profile upsert → 출석 체크
# ============================================================
ok = refresh_session_from_cookie_if_needed(force=False)

if not ok and (cookies.get("refresh_token") or cookies.get("access_token")):
    clear_auth_everywhere()
    st.caption("세션 복원에 실패해서 로그인을 다시 요청합니다.")

require_login()

user = st.session_state.user
user_id = user.id
user_email = getattr(user, "email", None) or st.session_state.get("login_email")

sb_authed = get_authed_sb()

if sb_authed is not None:
    if not st.session_state.get("progress_restored"):
        try:
            restore_progress_from_db(sb_authed, user_id)
        except Exception as e:
            st.caption(f"progress 복원 실패(무시하고 새로 시작): {e}")
        finally:
            st.session_state.progress_restored = True

    ensure_profile(sb_authed, user)

    att = mark_attendance_once(sb_authed)
    if att:
        st.session_state["streak_count"] = int(att.get("streak_count", 0) or 0)
        st.session_state["did_attend_today"] = bool(att.get("did_attend", False))

else:
    st.caption("세션 토큰이 없습니다. (sb_authed=None) 다시 로그인해 주세요.")
    # st.stop()

# ============================================================
# ✅ 상단: 오늘의 목표(루틴) + 연속 출석 배지
# ============================================================
streak = st.session_state.get("streak_count")
did_today = st.session_state.get("did_attend_today")

if streak is not None:
    if did_today:
        st.success(f"✅ 오늘 출석 완료!  (연속 {streak}일)")
    else:
        st.caption(f"연속 출석 {streak}일")

    if streak >= 30:
        st.info("🔥 30일 연속 달성! 진짜 레전드…")
    elif streak >= 7:
        st.info("🏅 7일 연속 달성! 흐름이 잡혔어요.")

if "today_goal" not in st.session_state:
    st.session_state.today_goal = "오늘은 10문항 1회 완주"
if "today_goal_done" not in st.session_state:
    st.session_state.today_goal_done = False

with st.container():
    st.markdown("### 🎯 오늘의 목표(루틴)")
    c1, c2 = st.columns([7, 3])
    with c1:
        st.session_state.today_goal = st.text_input(
            "목표 문장",
            value=st.session_state.today_goal,
            label_visibility="collapsed",
            placeholder="예) 오늘은 10문항 2회 + 오답만 다시풀기 1회",
        )
    with c2:
        st.session_state.today_goal_done = st.checkbox(
            "달성",
            value=bool(st.session_state.today_goal_done),
        )

    if st.session_state.today_goal_done:
        st.success("좋아요. 오늘 루틴 완료 ✅")
    else:
        st.caption("가볍게라도 체크하면 루틴이 끊기지 않습니다.")

st.divider()

# ============================================================
# ✅ 관리자/내대시보드
# ============================================================
def render_admin_dashboard():
    st.subheader("📊 관리자 대시보드")

    if not is_admin():
        st.error("접근 권한이 없습니다.")
        st.session_state.page = "quiz"
        st.stop()

    if st.button("← 돌아가기", use_container_width=True, key="btn_admin_back"):
        st.session_state.page = "quiz"
        st.rerun()

    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        st.warning("세션 토큰이 없습니다. 다시 로그인해 주세요.")
        return

    show_debug = st.toggle("디버그 정보 표시", value=False, key="toggle_admin_debug")

    def _fetch():
        return fetch_all_attempts_admin(sb_authed_local, limit=500)

    try:
        res = run_db(_fetch)
    except Exception as e:
        st.error("❌ 관리자 조회 실패 (RLS/권한/테이블/컬럼 확인 필요)")
        st.write(str(e))
        return

    rows = len(res.data) if getattr(res, "data", None) else 0
    if show_debug:
        st.caption(f"DEBUG: quiz_attempts rows = {rows}")

    if rows <= 0:
        st.info("데이터가 없거나 RLS 정책 때문에 전체 조회가 막혀 있습니다.")
        st.write("- Supabase Table Editor에서 quiz_attempts에 실제 데이터가 있는지 확인")
        st.write("- 데이터가 있는데도 0건이면 → RLS에서 관리자 전체 조회 허용 정책이 필요합니다.")
        return

    df_admin = pd.DataFrame(res.data).copy()
    df_admin["created_at"] = to_kst_naive(df_admin["created_at"])

    c1, c2, c3 = st.columns(3)
    c1.metric("최근 500건", rows)
    c2.metric("평균 점수", f"{df_admin['score'].mean():.2f}")
    c3.metric("평균 오답", f"{df_admin['wrong_count'].mean():.2f}")

    st.dataframe(df_admin, use_container_width=True, hide_index=True)

    csv = df_admin.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV 다운로드", csv, file_name="quiz_attempts_admin.csv", use_container_width=True, key="btn_admin_csv")

def render_my_dashboard():
    st.subheader("📌 내 대시보드")

    if st.button("← 돌아가기", use_container_width=True, key="btn_my_back"):
        st.session_state.page = "quiz"
        st.rerun()

    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        st.warning("세션 토큰이 없습니다. 다시 로그인해 주세요.")
        return

    def _fetch():
        return fetch_recent_attempts(sb_authed_local, user_id, limit=50)

    try:
        res = run_db(_fetch)
    except Exception as e:
        st.info("기록을 불러오지 못했습니다.")
        st.write(str(e))
        return

    if not res.data:
        st.info("아직 저장된 기록이 없습니다. 문제를 풀고 제출하면 기록이 쌓여요.")
        return

    hist = pd.DataFrame(res.data).copy()
    hist["created_at"] = to_kst_naive(hist["created_at"])
    hist["유형"] = hist["pos_mode"].map(lambda x: quiz_label_for_table.get(x, x))
    hist["정답률"] = (hist["score"] / hist["quiz_len"]).fillna(0.0)

    avg_rate = float(hist["정답률"].mean() * 100)
    best = int(hist["score"].max())
    last_score = int(hist.iloc[0]["score"])
    last_total = int(hist.iloc[0]["quiz_len"])

    c1, c2, c3 = st.columns(3)
    c1.metric("최근 평균(최대 50회)", f"{avg_rate:.0f}%")
    c2.metric("최고 점수", f"{best} / {N}")
    c3.metric("최근 점수", f"{last_score} / {last_total}")

    st.divider()
    st.markdown("### 최근 기록")

    st.markdown(
        """
<style>
.record-card{
  border: 1px solid rgba(120,120,120,0.25);
  border-radius: 16px;
  padding: 14px 14px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.02);
}
.record-top{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom: 8px;
}
.record-title{ font-weight: 800; font-size: 16px; }
.record-sub{ opacity: 0.75; font-size: 12px; }
.pill{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid rgba(120,120,120,0.25);
  background: rgba(255,255,255,0.03);
  white-space: nowrap;
}
</style>
""",
        unsafe_allow_html=True,
    )

    for _, r in hist.head(15).iterrows():
        dt = pd.to_datetime(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        mode = r["유형"]
        score_i = int(r["score"])
        total = int(r["quiz_len"])
        wrong = int(r["wrong_count"])
        pct = float(r["정답률"] * 100)

        badge = "🏆" if pct >= 90 else ("👍" if pct >= 70 else "💪")

        st.markdown(
            f"""
<div class="record-card">
  <div class="record-top">
    <div>
      <div class="record-title">{badge} {score_i} / {total}</div>
      <div class="record-sub">{dt} · {mode} · 레벨 {LEVEL}</div>
    </div>
    <div class="pill">오답 {wrong}개</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.progress(min(max(pct / 100.0, 0.0), 1.0))
        st.caption(f"정답률 {pct:.0f}%")
        st.write("")

# ============================================================
# ✅ 상단 헤더 (페이지/버튼)
# ============================================================
if "page" not in st.session_state:
    st.session_state.page = "quiz"

colA, colB, colC, colD = st.columns([7, 3, 2, 3])

with colA:
    st.caption("환영합니다 🙂")

with colB:
    if st.button("📌 나의 기록", use_container_width=True, key="btn_go_my"):
        st.session_state.page = "my"
        st.rerun()

with colC:
    if is_admin():
        if st.button("📊 관리자", use_container_width=True, key="btn_go_admin"):
            st.session_state.page = "admin"
            st.rerun()

with colD:
    if st.button("🚪 로그아웃", use_container_width=True, key="btn_logout"):
        try:
            sb.auth.sign_out()
        except Exception:
            pass
        clear_auth_everywhere()
        st.rerun()

# ============================================================
# ✅ 라우팅
# ============================================================
if st.session_state.page == "admin":
    if not is_admin():
        st.session_state.page = "quiz"
        st.warning("관리자 권한이 없습니다.")
        st.rerun()
    render_admin_dashboard()
    st.stop()

if st.session_state.page == "my":
    render_my_dashboard()
    st.stop()

# ============================================================
# ✅ CSV 로드 (nan 방지 최종형)
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "words_adj_300.csv"

READ_KW = dict(
    dtype=str,
    keep_default_na=False,
    na_values=["nan", "NaN", "NULL", "null", "None", "none"],
)

df = pd.read_csv(CSV_PATH, **READ_KW)
if len(df.columns) == 1 and "\t" in df.columns[0]:
    df = pd.read_csv(CSV_PATH, sep="\t", **READ_KW)

df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()

required_cols = ["jp_word", "reading", "meaning", "level", "pos"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    st.error(f"CSV 컬럼이 부족합니다: {missing}")
    st.stop()

for c in required_cols:
    df[c] = df[c].astype(str).str.strip()
    df[c] = df[c].replace({"nan": "", "NaN": "", "NULL": "", "null": "", "None": "", "none": ""})

df = df[
    (df["reading"] != "")
    & (df["meaning"] != "")
    & (df["level"] != "")
    & (df["pos"] != "")
].copy()

pool = df[df["level"] == LEVEL].copy()
pool_i = pool[pool["pos"] == "i_adj"].copy()

pool_i_reading = pool_i[
    pool_i["jp_word"].notna() & (pool_i["jp_word"].astype(str).str.strip() != "")
].copy()

pool_i_meaning = pool_i.copy()

if len(pool_i) < N:
    st.error(f"い형용사 단어가 부족합니다: pool={len(pool_i)}")
    st.stop()

# ============================================================
# ✅ 퀴즈 로직
# ============================================================
def make_question(row: pd.Series, qtype: str, base_pool_i: pd.DataFrame, distractor_pool_level: pd.DataFrame) -> dict:
    jp = row.get("jp_word")
    rd = row.get("reading")
    mn = row.get("meaning")

    display_word = jp if pd.notna(jp) and str(jp).strip() != "" else rd

    if qtype == "reading":
        prompt = f"{display_word}의 발음은?"
        correct = row["reading"]
        candidates = (
            base_pool_i.loc[base_pool_i["reading"] != correct, "reading"]
            .dropna().drop_duplicates().tolist()
        )

    elif qtype == "meaning":
        prompt = f"{display_word}의 뜻은?"
        correct = row["meaning"]
        candidates = (
            distractor_pool_level.loc[distractor_pool_level["meaning"] != correct, "meaning"]
            .dropna().drop_duplicates().tolist()
        )

    elif qtype == "kr2jp":
        prompt = f"'{mn}'의 일본어는?"
        correct = str(row["jp_word"]).strip()
        candidates = (
            base_pool_i.loc[base_pool_i["jp_word"] != correct, "jp_word"]
            .dropna().astype(str).str.strip()
        )
        candidates = [x for x in candidates.tolist() if x]
        candidates = list(dict.fromkeys(candidates))

    else:
        raise ValueError("Unknown qtype")

    if len(candidates) < 3:
        st.error(f"오답 후보 부족: 유형={qtype}, 후보={len(candidates)}개")
        st.stop()

    wrongs = random.sample(candidates, 3)
    choices = wrongs + [correct]
    random.shuffle(choices)

    return {
        "prompt": prompt,
        "choices": choices,
        "correct_text": correct,
        "jp_word": row["jp_word"],
        "reading": row["reading"],
        "meaning": row["meaning"],
        "pos": row["pos"],
        "qtype": qtype,
    }

def build_quiz_from_wrongs(wrong_list: list, qtype: str) -> list:
    wrong_words = []
    for w in (wrong_list or []):
        key = str(w.get("단어", "")).strip()
        if key:
            wrong_words.append(key)

    wrong_words = list(dict.fromkeys(wrong_words))

    if not wrong_words:
        st.warning("현재 오답 노트가 비어 있어요. 🙂")
        return []

    retry_df = pool_i[
        (pool_i["jp_word"].isin(wrong_words)) | (pool_i["reading"].isin(wrong_words))
    ].copy()

    if len(retry_df) == 0:
        st.error("오답 단어를 풀에서 찾지 못했습니다. (jp_word/reading 매칭 확인)")
        st.stop()

    retry_df = retry_df.sample(frac=1).reset_index(drop=True)
    return [make_question(retry_df.iloc[i], qtype, pool_i, pool) for i in range(len(retry_df))]

def build_quiz(qtype: str) -> list:
    if qtype == "reading":
        base_pool = pool_i_reading
    elif qtype == "meaning":
        base_pool = pool_i_meaning
    elif qtype == "kr2jp":
        base_pool = pool_i_reading
    else:
        base_pool = pool_i_meaning

    ensure_mastered_words_shape()
    mastered = st.session_state.mastered_words.get(qtype, set())

    if mastered:
        base_pool = base_pool[
            (~base_pool["jp_word"].isin(mastered)) & (~base_pool["reading"].isin(mastered))
        ].copy()

    if len(base_pool) < N:
        if len(base_pool) == 0:
            st.success("완벽합니다. 드디어 모두 정복했어요 ✅")
            st.info("복습/재도전을 원하시면 아래 버튼으로 **현재 유형만** 바로 운용할 수 있어요.")

            if st.button("🧹 여기서 바로 초기화(원클릭)", use_container_width=True, key="btn_inline_reset_mastered"):
                ensure_mastered_words_shape()
                st.session_state.mastered_words[qtype] = set()
                clear_question_widget_keys()
                new_quiz = _safe_build_quiz_after_reset(qtype)
                start_quiz_state(new_quiz, qtype, clear_wrongs=True)
                st.rerun()

            if st.button("❌ 오답만 다시 풀기", use_container_width=True, key="btn_inline_retry_wrongs"):
                if not st.session_state.get("wrong_list"):
                    st.warning("현재 오답 노트가 비어 있어요. 🙂")
                else:
                    clear_question_widget_keys()
                    retry_quiz = build_quiz_from_wrongs(st.session_state.wrong_list, qtype)
                    start_quiz_state(retry_quiz, qtype, clear_wrongs=True)
                    st.rerun()

            st.stop()

        st.info(f"남은 문제가 {len(base_pool)}개라서, 남은 만큼만 출제합니다 🙂")
        take_n = min(N, len(base_pool))
        sampled = base_pool.sample(n=take_n).reset_index(drop=True)
    else:
        sampled = base_pool.sample(n=N).reset_index(drop=True)

    return [make_question(sampled.iloc[i], qtype, pool_i, pool) for i in range(len(sampled))]

def _safe_build_quiz_after_reset(qtype: str) -> list:
    return build_quiz(qtype)

# ============================================================
# ✅ 세션 초기화
# ============================================================
if "quiz_type" not in st.session_state or st.session_state.get("quiz_type") not in QUIZ_TYPES:
    st.session_state.quiz_type = "reading"

if "quiz_version" not in st.session_state:
    st.session_state.quiz_version = 0
if "submitted" not in st.session_state:
    st.session_state.submitted = False
if "wrong_list" not in st.session_state:
    st.session_state.wrong_list = []
if "saved_this_attempt" not in st.session_state:
    st.session_state.saved_this_attempt = False
if "stats_saved_this_attempt" not in st.session_state:
    st.session_state.stats_saved_this_attempt = False
if "session_stats_applied_this_attempt" not in st.session_state:
    st.session_state.session_stats_applied_this_attempt = False

ensure_mastered_words_shape()

if "history" not in st.session_state:
    st.session_state.history = []
if "progress_dirty" not in st.session_state:
    st.session_state.progress_dirty = False
if "wrong_counter" not in st.session_state:
    st.session_state.wrong_counter = {}
if "total_counter" not in st.session_state:
    st.session_state.total_counter = {}

if "quiz" not in st.session_state:
    st.session_state.quiz = build_quiz(st.session_state.quiz_type)

# ============================================================
# ✅ 상단 UI (출제유형/새문제/초기화)
# ============================================================
current_index = QUIZ_TYPES.index(st.session_state.quiz_type)

selected = st.radio(
    "출제 유형",
    options=QUIZ_TYPES,
    format_func=lambda x: quiz_label_map.get(x, x),
    horizontal=True,
    index=current_index,
    key="radio_quiz_type",
)

if selected != st.session_state.quiz_type:
    clear_question_widget_keys()
    new_quiz = build_quiz(selected)
    start_quiz_state(new_quiz, selected, clear_wrongs=True)
    st.rerun()

st.caption(f"현재 선택: **{quiz_label_map[st.session_state.quiz_type]}**")
st.divider()

col1, col2 = st.columns(2)

with col1:
    if st.button("🔄 새 문제(랜덤 10문항)", use_container_width=True, key="btn_new_quiz"):
        clear_question_widget_keys()
        new_quiz = build_quiz(st.session_state.quiz_type)
        start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)
        st.rerun()

with col2:
    if st.button("🧹 선택 초기화", use_container_width=True, key="btn_reset_choice"):
        clear_question_widget_keys()
        start_quiz_state(st.session_state.quiz, st.session_state.quiz_type, clear_wrongs=False)
        st.rerun()

st.divider()

if st.button("✅ 맞힌 단어 제외 초기화", use_container_width=True, key="btn_reset_mastered_current_type"):
    ensure_mastered_words_shape()
    st.session_state.mastered_words[st.session_state.quiz_type] = set()

    clear_question_widget_keys()
    new_quiz = _safe_build_quiz_after_reset(st.session_state.quiz_type)
    start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)

    st.success(f"초기화 완료 (유형: {quiz_label_map[st.session_state.quiz_type]})")
    st.rerun()

# ============================================================
# ✅ answers 길이 자동 맞춤
# ============================================================
quiz_len = len(st.session_state.quiz)
if "answers" not in st.session_state or len(st.session_state.answers) != quiz_len:
    st.session_state.answers = [None] * quiz_len

# ============================================================
# ✅ 문제 표시  (★ 새로고침/세션초기화 후에도 선택값 복원되게 수정)
# ============================================================
for idx, q in enumerate(st.session_state.quiz):
    st.subheader(f"Q{idx+1}")
    st.markdown(
        f'<div class="jp" style="font-size:18px; font-weight:500;">{q["prompt"]}</div>',
        unsafe_allow_html=True,
    )

    widget_key = f"q_{st.session_state.quiz_version}_{idx}"

    # ✅ DB에서 복원된 answers를 "라디오 기본 선택값"으로 반영
    prev = st.session_state.answers[idx]  # 복원되었을 수도 있는 값
    default_index = None
    if prev is not None and prev in q["choices"]:
        default_index = q["choices"].index(prev)

        # (선택) key 자체가 없을 때만 세션에도 박아주면 더 안전
        if widget_key not in st.session_state:
            st.session_state[widget_key] = prev

    choice = st.radio(
        label="보기",
        options=q["choices"],
        index=default_index,      # ★ 여기가 핵심
        key=widget_key,
        label_visibility="collapsed",
        on_change=mark_progress_dirty,
    )

    # ✅ 이제 choice가 None으로 덮어쓰는 일이 거의 없어짐
    st.session_state.answers[idx] = choice
sync_answers_from_widgets()

# ============================================================
# ✅ 제출/채점
# ============================================================
all_answered = all(a is not None for a in st.session_state.answers)

if st.button("✅ 제출하고 채점하기", disabled=not all_answered, type="primary", use_container_width=True, key="btn_submit"):
    st.session_state.submitted = True
    st.session_state.session_stats_applied_this_attempt = False

if not all_answered:
    st.info("모든 문제에 답을 선택하면 제출 버튼이 활성화됩니다.")

# ============================================================
# ✅ 제출 후 화면
# ============================================================
if st.session_state.submitted:
    ensure_mastered_words_shape()
    current_type = st.session_state.quiz_type

    score = 0
    wrong_list = []

    for idx, q in enumerate(st.session_state.quiz):
        picked = st.session_state.answers[idx]
        correct = q["correct_text"]

        word_key = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())

        if picked == correct:
            score += 1
            if word_key:
                st.session_state.mastered_words[current_type].add(word_key)
        else:
            word_display = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())
            wrong_list.append(
                {
                    "No": idx + 1,
                    "문제": q["prompt"],
                    "내 답": picked,
                    "정답": correct,
                    "단어": word_display,
                    "읽기": q["reading"],
                    "뜻": q["meaning"],
                    "유형": current_type,
                }
            )

    st.session_state.wrong_list = wrong_list
    quiz_len = len(st.session_state.quiz)

    st.success(f"점수: {score} / {quiz_len}")
    ratio = score / quiz_len if quiz_len else 0

    if ratio == 1:
        st.balloons()
        st.success("🎉 완벽해요! 전부 정답입니다. 정말 잘했어요!")
    elif ratio >= 0.7:
        st.info("👍 잘하고 있어요! 조금만 더 다듬으면 완벽해질 거예요.")
    else:
        st.warning("💪 괜찮아요! 틀린 문제는 성장의 재료예요. 다시 한 번 도전해봐요.")

    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        st.warning("DB 저장/조회용 토큰이 없습니다. 다시 로그인해 주세요.")
    else:
        if not st.session_state.saved_this_attempt:
            def _save():
                return save_attempt_to_db(
                    sb_authed=sb_authed_local,
                    user_id=user_id,
                    user_email=user_email,
                    level=LEVEL,
                    quiz_type=current_type,
                    quiz_len=quiz_len,
                    score=score,
                    wrong_list=wrong_list,
                )
            try:
                run_db(_save)
                st.session_state.saved_this_attempt = True
            except Exception as e:
                st.warning("DB 저장에 실패했습니다. (테이블/컬럼/권한/RLS 정책 확인 필요)")
                st.write(str(e))

        if not st.session_state.stats_saved_this_attempt:
            def _save_stats():
                sync_answers_from_widgets()
                return save_word_stats_via_rpc(
                    sb_authed=sb_authed_local,
                    quiz=st.session_state.quiz,
                    answers=st.session_state.answers,
                    quiz_type=current_type,
                    level=LEVEL,
                )
            try:
                run_db(_save_stats)
                st.session_state.stats_saved_this_attempt = True
                st.success("✅ 단어 통계 저장 성공")
            except Exception as e:
                st.error("❌ 단어 통계 저장 실패 (아래 에러가 진짜 원인입니다)")
                st.exception(e)  # ← 이게 핵심 (원인을 숨기지 않음)

        st.subheader("📌 내 최근 기록")

        def _fetch_hist():
            return fetch_recent_attempts(sb_authed_local, user_id, limit=10)

        try:
            res = run_db(_fetch_hist)
            if not res.data:
                st.info("아직 저장된 기록이 없습니다. 문제를 풀고 제출하면 기록이 쌓여요.")
            else:
                hist = pd.DataFrame(res.data).copy()
                hist["created_at"] = to_kst_naive(hist["created_at"])
                hist["유형"] = hist["pos_mode"].map(lambda x: quiz_label_for_table.get(x, x))
                hist["정답률"] = (hist["score"] / hist["quiz_len"]).fillna(0.0)

                avg_rate = float(hist["정답률"].mean() * 100)
                best = int(hist["score"].max())
                last_score = int(hist.iloc[0]["score"])
                last_total = int(hist.iloc[0]["quiz_len"])

                c1, c2, c3 = st.columns(3)
                c1.metric("최근 10회 평균", f"{avg_rate:.0f}%")
                c2.metric("최고 점수", f"{best} / {N}")
                c3.metric("최근 점수", f"{last_score} / {last_total}")

        except Exception as e:
            st.info("기록을 불러오지 못했습니다.")
            st.write(str(e))

    if not st.session_state.session_stats_applied_this_attempt:
        st.session_state.history.append({"type": current_type, "score": score, "total": quiz_len})

        for idx, q in enumerate(st.session_state.quiz):
            word_key = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())
            st.session_state.total_counter[word_key] = st.session_state.total_counter.get(word_key, 0) + 1
            if st.session_state.answers[idx] != q["correct_text"]:
                st.session_state.wrong_counter[word_key] = st.session_state.wrong_counter.get(word_key, 0) + 1

        st.session_state.session_stats_applied_this_attempt = True

    if st.session_state.wrong_list:
        st.subheader("❌ 오답 노트")

        st.markdown(
            """
<style>
.wrong-card{
  border: 1px solid rgba(120,120,120,0.25);
  border-radius: 16px;
  padding: 14px 14px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.02);
}
.wrong-top{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  margin-bottom: 8px;
}
.wrong-title{ font-weight: 900; font-size: 15px; margin-bottom: 4px; }
.wrong-sub{ opacity: 0.8; font-size: 12px; }
.tag{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 5px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid rgba(120,120,120,0.25);
  background: rgba(255,255,255,0.03);
  white-space: nowrap;
}
.ans-row{
  display:grid;
  grid-template-columns: 72px 1fr;
  gap:10px;
  margin-top:6px;
  font-size: 13px;
}
.ans-k{ opacity: 0.7; font-weight: 700; }
</style>
""",
            unsafe_allow_html=True,
        )

        for w in st.session_state.wrong_list:
            no = w.get("No", "")
            qtext = w.get("문제", "")
            picked = w.get("내 답", "")
            correct = w.get("정답", "")
            word = w.get("단어", "")
            reading = w.get("읽기", "")
            meaning = w.get("뜻", "")
            mode = quiz_label_map.get(w.get("유형", ""), w.get("유형", ""))

            st.markdown(
                f"""
<div class="wrong-card">
  <div class="wrong-top">
    <div>
      <div class="wrong-title">Q{no}. {word}</div>
      <div class="wrong-sub">{qtext} · 유형: {mode}</div>
    </div>
    <div class="tag">오답</div>
  </div>

  <div class="ans-row"><div class="ans-k">내 답</div><div>{picked}</div></div>
  <div class="ans-row"><div class="ans-k">정답</div><div><b>{correct}</b></div></div>
  <div class="ans-row"><div class="ans-k">발음</div><div>{reading}</div></div>
  <div class="ans-row"><div class="ans-k">뜻</div><div>{meaning}</div></div>
</div>
""",
                unsafe_allow_html=True,
            )

        st.divider()

        if st.button("❌ 틀린 문제만 다시 풀기", type="primary", use_container_width=True, key="btn_retry_wrong"):
            if not st.session_state.wrong_list:
                st.warning("오답이 없어서 다시 풀 문제가 없습니다.")
                st.stop()

            clear_question_widget_keys()
            retry_quiz = build_quiz_from_wrongs(st.session_state.wrong_list, current_type)
            start_quiz_state(retry_quiz, current_type, clear_wrongs=True)
            st.rerun()

    st.divider()
    st.subheader("📊 누적 학습 현황 (이번 세션)")

    total_attempts = sum(x["total"] for x in st.session_state.history) if st.session_state.history else 0
    total_score = sum(x["score"] for x in st.session_state.history) if st.session_state.history else 0
    acc = (total_score / total_attempts) if total_attempts else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("누적 회차", len(st.session_state.history))
    c2.metric("누적 점수", f"{total_score} / {total_attempts}")
    c3.metric("누적 정답률", f"{acc*100:.0f}%")

    if st.session_state.wrong_counter:
        st.markdown("#### ❌ 자주 틀리는 단어 TOP 5")
        top5 = sorted(st.session_state.wrong_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        for rank, (w, cnt) in enumerate(top5, start=1):
            total_seen = st.session_state.total_counter.get(w, 0)
            st.write(f"{rank}. **{w}**  —  {cnt}회 오답 / {total_seen}회 출제")
    else:
        st.info("아직 오답 누적 데이터가 없습니다.")

    if st.button("🗑️ 누적 기록 초기화", use_container_width=True, key="btn_reset_session_stats"):
        st.session_state.history = []
        st.session_state.wrong_counter = {}
        st.session_state.total_counter = {}
        st.rerun()

    render_naver_talk()
