from pathlib import Path
import random
import pandas as pd
import streamlit as st
from supabase import create_client
from streamlit_cookies_manager import EncryptedCookieManager
import streamlit.components.v1 as components
from collections import Counter

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

/* ✅ 캡션(품사/유형) - 세그먼트에 딱 붙게 */
.tabcap{
  font-weight: 900;
  font-size: 12.5px;
  opacity: .78;
  margin: 0 0 2px 0 !important;     /* ✅ 4px → 2px */
  padding: 0 !important;
  line-height: 1.0 !important;
  letter-spacing: .2px;
}

/* ✅ (삭제/수정) h10은 존재하지 않음 → 실제 헤더만 대상으로 */
div[data-testid="stMarkdownContainer"] h1,
div[data-testid="stMarkdownContainer"] h2,
div[data-testid="stMarkdownContainer"] h3,
div[data-testid="stMarkdownContainer"] h4{
  margin-top: 10px !important;
  margin-bottom: 8px !important;
}

/* 일반 버튼(새문제/초기화 등) */
div.stButton > button {
  padding: 6px 10px !important;
  font-size: 13px !important;
  line-height: 1.1 !important;
  white-space: nowrap !important;
}

/* ✅ iOS Segmented Control 느낌 */
div[data-baseweb="button-group"]{
  background: rgba(120,120,120,0.12) !important;
  padding: 6px !important;
  border-radius: 999px !important;
  border: 1px solid rgba(120,120,120,0.18) !important;
  gap: 6px !important;
  margin-top: 0px !important;       /* ✅ 캡션 바로 아래 붙게 */
  margin-bottom: 14px !important;
}

div[data-baseweb="button-group"] button{
  border-radius: 999px !important;
  padding: 10px 14px !important;
  font-weight: 800 !important;
  border: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  white-space: nowrap !important;
}

div[data-baseweb="button-group"] button[aria-pressed="true"]{
  background: rgba(255,255,255,0.92) !important;
  box-shadow: 0 6px 14px rgba(0,0,0,0.10) !important;
}

div[data-baseweb="button-group"] button[aria-pressed="false"]{
  opacity: 0.85 !important;
}

@media (max-width: 480px){
  div[data-baseweb="button-group"] button{
    padding: 9px 12px !important;
    font-size: 14px !important;
  }
}
</style>
""", unsafe_allow_html=True)



POS_MODE_MAP = {
    "i_adj": "い형용사",
    "na_adj": "な형용사",
    "mix_adj": "혼합",
}
POS_MODES = ["i_adj", "na_adj", "mix_adj"]

st.markdown('<div id="__TOP__"></div>', unsafe_allow_html=True)

def scroll_to_top(nonce: int = 0):
    components.html(
        f"""
        <script>
        (function () {{
          const doc = window.parent.document;

          const targets = [
            doc.querySelector('[data-testid="stAppViewContainer"]'),
            doc.querySelector('[data-testid="stMain"]'),
            doc.querySelector('section.main'),
            doc.documentElement,
            doc.body
          ].filter(Boolean);

          const go = () => {{
            try {{
              const top = doc.getElementById("__TOP__");
              if (top) top.scrollIntoView({{behavior: "auto", block: "start"}});

              targets.forEach(t => {{
                if (t && typeof t.scrollTo === "function") t.scrollTo({{top: 0, left: 0, behavior: "auto"}});
                if (t) t.scrollTop = 0;
              }});

              window.parent.scrollTo(0, 0);
              window.scrollTo(0, 0);
            }} catch(e) {{}}
          }};

          go();
          requestAnimationFrame(go);
          setTimeout(go, 50);
          setTimeout(go, 150);
          setTimeout(go, 350);
          setTimeout(go, 800);
        }})();
        </script>
        <!-- nonce:{nonce} -->
        """,
        height=1,
    )

def render_floating_scroll_top():
    components.html(
        """
<script>
(function(){
  const doc = window.parent.document;

  // 중복 방지
  if (doc.getElementById("__FAB_TOP__")) return;

  const btn = doc.createElement("button");
  btn.id = "__FAB_TOP__";
  btn.textContent = "↑";

  // 기본 스타일
  btn.style.position = "fixed";
  btn.style.right = "14px";
  btn.style.zIndex = "2147483647";
  btn.style.width = "46px";
  btn.style.height = "46px";
  btn.style.borderRadius = "999px";
  btn.style.border = "1px solid rgba(120,120,120,0.25)";
  btn.style.background = "rgba(0,0,0,0.55)";
  btn.style.color = "#fff";
  btn.style.fontSize = "18px";
  btn.style.fontWeight = "900";
  btn.style.boxShadow = "0 10px 22px rgba(0,0,0,0.25)";
  btn.style.cursor = "pointer";
  btn.style.userSelect = "none";
  btn.style.display = "flex";
  btn.style.alignItems = "center";
  btn.style.justifyContent = "center";
  btn.style.opacity = "0";

  // ✅ PC에서는 숨김 (801px 이상이면 display:none)
  const applyDeviceVisibility = () => {
    try {
      const w = window.parent.innerWidth || window.innerWidth;
      if (w >= 801) {
        btn.style.display = "none";
      } else {
        btn.style.display = "flex";
      }
    } catch(e) {}
  };

  const goTop = () => {
    try {
      const top = doc.getElementById("__TOP__");
      if (top) top.scrollIntoView({behavior:"smooth", block:"start"});

      const targets = [
        doc.querySelector('[data-testid="stAppViewContainer"]'),
        doc.querySelector('[data-testid="stMain"]'),
        doc.querySelector('section.main'),
        doc.documentElement,
        doc.body
      ].filter(Boolean);

      targets.forEach(t => {
        if (t && typeof t.scrollTo === "function") t.scrollTo({top:0, left:0, behavior:"smooth"});
        if (t) t.scrollTop = 0;
      });

      window.parent.scrollTo(0,0);
      window.scrollTo(0,0);
    } catch(e) {}
  };

  btn.addEventListener("click", goTop);

  const mount = () => doc.querySelector('[data-testid="stAppViewContainer"]') || doc.body;

  const BASE = 18;
  const EXTRA = 34; // ← 가려지면 여기만 올리기

  const reposition = () => {
    try {
      const vv = window.parent.visualViewport || window.visualViewport;
      const innerH = window.parent.innerHeight || window.innerHeight;
      const hiddenBottom = vv ? Math.max(0, innerH - vv.height - (vv.offsetTop || 0)) : 0;

      btn.style.bottom = (BASE + EXTRA + hiddenBottom) + "px";
      btn.style.opacity = "1";
    } catch(e) {
      btn.style.bottom = "220px";
      btn.style.opacity = "1";
    }
    applyDeviceVisibility(); // ✅ 화면 크기 변하면 즉시 반영
  };

  const tryAttach = (n=0) => {
    const root = mount();
    if (!root) {
      if (n < 30) return setTimeout(() => tryAttach(n+1), 50);
      return;
    }
    root.appendChild(btn);
    reposition();
    setTimeout(reposition, 50);
    setTimeout(reposition, 200);
    setTimeout(reposition, 600);
  };

  tryAttach();

  // ✅ 리사이즈/회전 대응
  window.parent.addEventListener("resize", reposition, {passive:true});

  const vv = window.parent.visualViewport || window.visualViewport;
  if (vv) {
    vv.addEventListener("resize", reposition, {passive:true});
    vv.addEventListener("scroll", reposition, {passive:true});
  }
})();
</script>
        """,
        height=1,
    )

render_floating_scroll_top()

# ✅ 버튼 클릭 후 rerun되면, 이 플래그를 보고 최상단 스크롤 실행

if st.session_state.get("_scroll_top_once"):
    st.session_state["_scroll_top_once"] = False
    st.session_state["_scroll_top_nonce"] = st.session_state.get("_scroll_top_nonce", 0) + 1
    scroll_to_top(nonce=st.session_state["_scroll_top_nonce"])

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
SHOW_POST_SUBMIT_UI = "N"   # "Y"면 제출 후 상세(통계/기록/오답노트/누적현황) 표시
SHOW_NAVER_TALK = "Y"    
NAVER_TALK_URL = "https://talk.naver.com/W45141"
APP_URL = "https://hotenaquiztestapp-5wiha4zfuvtnq4qgxdhq72.streamlit.app/"
LEVEL = "N4"
N = 10
KST_TZ = "Asia/Seoul"
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "words_adj_300.csv"

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
QUIZ_TYPES_USER = ["reading", "meaning", "kr2jp"]                 # 일반 유저 , 3종은 뒤에 "kr2jp" 추가
QUIZ_TYPES_ADMIN = ["reading", "meaning", "kr2jp"]       # 관리자만 3종

# ============================================================
# ✅ (추가) 어디 페이지에서든 pool/pool_i를 보장하는 Lazy Loader
# ============================================================
READ_KW = dict(
    dtype=str,
    keep_default_na=False,
    na_values=["nan", "NaN", "NULL", "null", "None", "none"],
)

@st.cache_data(show_spinner=False)
def _load_pools_cached(csv_path_str: str, level: str):
    # 1) CSV 로드
    df = pd.read_csv(csv_path_str, **READ_KW)

    # 2) 필수 컬럼 체크
    required_cols = {"level", "pos", "jp_word", "reading", "meaning"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV 필수 컬럼 누락: {sorted(list(missing))}")

    # 3) level 필터
    pool = df[df["level"] == level].copy()

    # 4) 품사별 분리
    pool_i = pool[pool["pos"] == "i_adj"].copy()
    pool_na = pool[pool["pos"] == "na_adj"].copy()

    # 5) reading용(표기 없는 단어 제거), meaning용(전체 허용)
    pool_i_reading = pool_i[pool_i["jp_word"].notna() & (pool_i["jp_word"].astype(str).str.strip() != "")].copy()
    pool_i_meaning = pool_i.copy()

    pool_na_reading = pool_na[pool_na["jp_word"].notna() & (pool_na["jp_word"].astype(str).str.strip() != "")].copy()
    pool_na_meaning = pool_na.copy()

    return pool, pool_i, pool_i_reading, pool_i_meaning, pool_na, pool_na_reading, pool_na_meaning

def ensure_pools_ready():
    global pool, pool_i, pool_i_reading, pool_i_meaning
    global pool_na, pool_na_reading, pool_na_meaning

    globals_ok = all(
        (name in globals()) and (globals().get(name) is not None)
        for name in (
            "pool","pool_i","pool_i_reading","pool_i_meaning",
            "pool_na","pool_na_reading","pool_na_meaning"
        )
    )

    if st.session_state.get("pool_ready") and globals_ok:
        return

    try:
        pool, pool_i, pool_i_reading, pool_i_meaning, pool_na, pool_na_reading, pool_na_meaning = _load_pools_cached(str(CSV_PATH), LEVEL)
    except Exception as e:
        st.error(f"단어 데이터 로드 실패: {e}")
        st.stop()

    if len(pool_i) < N:
        st.error(f"い형용사 단어가 부족합니다: pool={len(pool_i)}")
        st.stop()

    if len(pool_na) < N:
        st.error(f"な형용사 단어가 부족합니다: pool={len(pool_na)}")
        st.stop()

    st.session_state["pool_ready"] = True

# ============================================================
# ✅ mastered_words를 유형별로 유지하는 유틸
# ============================================================
def ensure_mastered_words_shape():
    if "mastered_words" not in st.session_state or not isinstance(st.session_state.mastered_words, dict):
        st.session_state.mastered_words = {}

    types = QUIZ_TYPES_ADMIN if is_admin() else QUIZ_TYPES_USER
    for k in types:
        st.session_state.mastered_words.setdefault(k, set())


# ✅✅✅ [추가] "완벽합니다" 메시지를 유형별로 1번만 띄우기 위한 플래그
def ensure_mastery_banner_shape():
    if "mastery_banner_shown" not in st.session_state or not isinstance(st.session_state.mastery_banner_shown, dict):
        st.session_state.mastery_banner_shown = {}

    types = QUIZ_TYPES_ADMIN if is_admin() else QUIZ_TYPES_USER
    for t in types:
        st.session_state.mastery_banner_shown.setdefault(t, False)

    if "mastered_words" not in st.session_state or not isinstance(st.session_state.mastered_words, dict):
        st.session_state.mastered_words = {}

    # ✅ get_available_quiz_types()를 여기서 부르지 말고(순서 꼬임 방지),
    #    is_admin() 기준으로 직접 결정
    types = QUIZ_TYPES_ADMIN if is_admin() else QUIZ_TYPES_USER

    for k in types:
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
    if now - last < 10.0:
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
        "pool_ready",   # ✅ 추가
        "_sb_authed", "_sb_authed_token",
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
    # ✅ 토큰이 없으면 쿠키 기반 복원 시도
    if not st.session_state.get("access_token"):
        refresh_session_from_cookie_if_needed(force=True)

    token = st.session_state.get("access_token")
    if not token:
        return None

    # ✅ 같은 토큰이면, 매 rerun마다 create_client 하지 말고 캐시 재사용
    cached = st.session_state.get("_sb_authed")
    cached_token = st.session_state.get("_sb_authed_token")

    if cached is not None and cached_token == token:
        return cached

    sb2 = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb2.postgrest.auth(token)

    st.session_state["_sb_authed"] = sb2
    st.session_state["_sb_authed_token"] = token
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
    if isinstance(ts, pd.Series):
        return ts.dt.tz_convert(KST_TZ).dt.tz_localize(None)
    if pd.isna(ts):
        return ts
    return ts.tz_convert(KST_TZ).tz_localize(None)

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
        .select("created_at, level, pos_mode, quiz_len, score, wrong_count, wrong_list")
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

def build_word_results_bulk_payload(
    quiz: list[dict],
    answers: list,
    quiz_type: str,
    level: str
) -> list[dict]:
    items = []
    for idx, q in enumerate(quiz):
        word_key = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())
        if not word_key:
            continue

        picked = answers[idx] if idx < len(answers) else None
        is_correct = (picked == q.get("correct_text"))

        items.append(
            {
                "word_key": word_key,
                "level": str(level),
                "pos": str(q.get("pos", "") or ""),
                "quiz_type": str(quiz_type),
                "is_correct": bool(is_correct),
            }
        )

    return items
  
# ============================================================
# ✅ Progress (DB 저장/복원)
# ============================================================
def save_progress_to_db(sb_authed, user_id: str):
    if "quiz" not in st.session_state or "answers" not in st.session_state:
        return

    payload = {
        "quiz_type": st.session_state.get("quiz_type"),
        "pos_mode": st.session_state.get("pos_mode", "i_adj"), # ✅ 추가
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
    st.session_state.pos_mode = progress.get("pos_mode", st.session_state.get("pos_mode", "i_adj"))  # ✅ 추가


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

def get_available_quiz_types() -> list[str]:
    return QUIZ_TYPES_ADMIN if is_admin() else QUIZ_TYPES_USER
  
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
# ✅ 앱 시작: refresh → 로그인 강제 → progress 복원 → (pos/quiz 고정) → title → profile upsert → 출석 체크
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
    # ✅ 1) progress 복원 (pos_mode/quiz_type가 여기서 들어옴)
    if not st.session_state.get("progress_restored"):
        try:
            restore_progress_from_db(sb_authed, user_id)
        except Exception as e:
            st.caption(f"progress 복원 실패(무시하고 새로 시작): {e}")
        finally:
            st.session_state.progress_restored = True

    # ✅ 2) 복원 이후에만 기본값 보정 (복원값이 있으면 그대로 유지)
    if "pos_mode" not in st.session_state or st.session_state.get("pos_mode") not in POS_MODES:
        st.session_state.pos_mode = "i_adj"

    available_types = get_available_quiz_types()
    if "quiz_type" not in st.session_state or st.session_state.get("quiz_type") not in available_types:
        st.session_state.quiz_type = available_types[0]

    # ✅ 3) title은 “복원/보정” 끝난 다음에 출력 (이제 안 튐)
    st.title(f"{POS_MODE_MAP.get(st.session_state.pos_mode)} 퀴즈")

    # ✅ 4) 프로필/출석
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
    ensure_pools_ready()

    wrong_words = []
    for w in (wrong_list or []):
        key = str(w.get("단어", "")).strip()
        if key:
            wrong_words.append(key)
    wrong_words = list(dict.fromkeys(wrong_words))

    if not wrong_words:
        st.warning("현재 오답 노트가 비어 있어요. 🙂")
        return []

    pos_mode = st.session_state.get("pos_mode", "i_adj")

    if pos_mode == "i_adj":
        base = pool_i
        base_for_distractor = pool_i
    elif pos_mode == "na_adj":
        base = pool_na
        base_for_distractor = pool_na
    else:
        base = pd.concat([pool_i, pool_na], ignore_index=True)
        base_for_distractor = base  # ✅ concat 그대로 재사용

    retry_df = base[(base["jp_word"].isin(wrong_words)) | (base["reading"].isin(wrong_words))].copy()

    if len(retry_df) == 0:
        st.error("오답 단어를 풀에서 찾지 못했습니다. (jp_word/reading 매칭 확인)")
        st.stop()

    retry_df = retry_df.sample(frac=1).reset_index(drop=True)

    return [make_question(retry_df.iloc[i], qtype, base_for_distractor, pool) for i in range(len(retry_df))]



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

    st.markdown('<div class="weak-wrap">', unsafe_allow_html=True)

    counter = Counter()
    for row in (res.data or []):
        wl = row.get("wrong_list") or []
        if isinstance(wl, list):
            for w in wl:
                word = str(w.get("단어", "")).strip()
                if word:
                    counter[word] += 1

    top10 = counter.most_common(10)

    if not top10:
        st.info("오답 데이터가 없습니다.")
        return

    for idx, (word, cnt) in enumerate(top10, start=1):
        st.markdown(
            f"""
            <div class="weak-card">
              <div class="weak-word">{idx}. {word}</div>
              <div class="weak-badge">오답 {cnt}회</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)


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

    # ============================================================
    # ✅ 자주 틀린 단어 TOP10 (최근 50회 기준) - A안(카드+진행바)
    # ============================================================
    st.divider()
    st.markdown("### ❌ 자주 틀린 단어 TOP10 (최근 50회)")

    # ✅ A안 카드 렌더링 함수(이 블록 안에 같이 둬도 되고, 위쪽 유틸 영역으로 빼도 됨)
    def render_top_wrong_words_cards(top_items, title=None):
        """
        top_items: [(word, wrong_cnt), ...]
        """
        if not top_items:
            st.info("아직 집계된 오답 단어가 없습니다.")
            return

        max_cnt = max([cnt for _, cnt in top_items]) or 1

        if title:
            st.markdown(f"#### {title}")

        st.markdown(
            """
<style>
.weak-wrap{
  display:flex;
  flex-direction:column;
  gap:16px;
  margin-top:10px;
}
.weak-card{
  border: 1px solid rgba(120,120,120,0.20);
  border-radius: 16px;
  padding: 12px 14px;
  margin-bottom: 10px;  /* ✅ 카드 사이 간격 */
  background: rgba(255,255,255,0.02);
}
.weak-row{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
}
.weak-left{
  display:flex;
  align-items:center;
  gap:10px;
  min-width: 0;
}
.rank-badge{
  width:28px;
  height:28px;
  border-radius: 999px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-weight: 900;
  border: 1px solid rgba(120,120,120,0.25);
  background: rgba(255,255,255,0.03);
  flex: 0 0 auto;
}
.weak-word{
  font-weight: 900;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.weak-meta{
  opacity: 0.8;
  font-size: 12px;
  margin-top: 2px;
}
.weak-right{
  display:flex;
  align-items:center;
  gap:8px;
  flex: 0 0 auto;
}
.weak-chip{
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  border: 1px solid rgba(120,120,120,0.25);
  background: rgba(255,255,255,0.03);
  white-space: nowrap;
}
.bar{
  width: 100%;
  height: 8px;
  border-radius: 999px;
  background: rgba(120,120,120,0.18);
  overflow: hidden;
  margin-top: 10px;
}
.bar > div{
  height: 100%;
  border-radius: 999px;
  background: rgba(3,199,90,0.55);
}
</style>
""",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="weak-wrap">', unsafe_allow_html=True)

        for idx, (word, cnt) in enumerate(top_items, start=1):
            pct = int(round((cnt / max_cnt) * 100))
            st.markdown(
                f"""
<div class="weak-card">
  <div class="weak-row">
    <div class="weak-left">
      <div class="rank-badge">{idx}</div>
      <div style="min-width:0;">
        <div class="weak-word">{word}</div>
        <div class="weak-meta">자주 틀린 단어</div>
      </div>
    </div>
    <div class="weak-right">
      <div class="weak-chip">오답 {cnt}회</div>
      <div class="weak-chip">{pct}%</div>
    </div>
  </div>
  <div class="bar"><div style="width:{pct}%"></div></div>
</div>
""",
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    # quiz_attempts의 wrong_list를 펼쳐서 단어별로 카운트
    from collections import Counter
    counter = Counter()

    # res.data 원본에 wrong_list가 들어있음 (hist는 일부 컬럼만 쓰고 있어서 res.data를 사용)
    for row in (res.data or []):
        wl = row.get("wrong_list") or []
        if isinstance(wl, list):
            for w in wl:
                # w는 {"단어": "...", ...} 형태로 저장되어 있음
                word = str(w.get("단어", "")).strip()
                if word:
                    counter[word] += 1

    if not counter:
        st.caption("아직 오답 데이터가 충분하지 않습니다. 몇 번 더 풀면 TOP10이 생겨요 🙂")
        return

    top10 = counter.most_common(10)

    # ✅ (변경) 엑셀표 제거 → 카드 렌더링
    render_top_wrong_words_cards(top10)

    # 시험 보기 버튼
    if st.button(
        "❌ 이 TOP10으로 시험 보기",
        type="primary",
        use_container_width=True,
        key="btn_quiz_from_top10",
    ):
        clear_question_widget_keys()

        # build_quiz_from_wrongs가 기대하는 형태: [{"단어": "..."} , ...]
        weak_wrong_list = [{"단어": w} for w, _ in top10]

        retry_quiz = build_quiz_from_wrongs(
            weak_wrong_list,
            st.session_state.quiz_type,
        )

        start_quiz_state(retry_quiz, st.session_state.quiz_type, clear_wrongs=True)
        st.session_state["_scroll_top_once"] = True
        st.session_state.page = "quiz"
        st.rerun()

    # ============================================================
    # ✅ 최근 기록
    # ============================================================
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

ensure_pools_ready()

def _safe_build_quiz_after_reset(qtype: str) -> list:
    try:
        return build_quiz(qtype)
    except Exception:
        return []
  
def build_quiz(qtype: str) -> list:
    ensure_pools_ready()

    pos_mode = st.session_state.get("pos_mode", "i_adj")

    if pos_mode == "i_adj":
        base_reading = pool_i_reading
        base_meaning = pool_i_meaning
        base_for_distractor = pool_i
    elif pos_mode == "na_adj":
        base_reading = pool_na_reading
        base_meaning = pool_na_meaning
        base_for_distractor = pool_na
    else:
        base_reading = pd.concat([pool_i_reading, pool_na_reading], ignore_index=True)
        base_meaning = pd.concat([pool_i_meaning, pool_na_meaning], ignore_index=True)
        base_for_distractor = pd.concat([pool_i, pool_na], ignore_index=True)

    if qtype == "reading":
        base_pool = base_reading
    elif qtype == "meaning":
        base_pool = base_meaning
    elif qtype == "kr2jp":
        base_pool = base_meaning[
            base_meaning["jp_word"].notna()
            & (base_meaning["jp_word"].astype(str).str.strip() != "")
        ].copy()
    else:
        qtype = "meaning"
        base_pool = base_meaning

    ensure_mastered_words_shape()
    mastered = st.session_state.mastered_words.get(qtype, set())
    if mastered:
        base_pool = base_pool[
            (~base_pool["jp_word"].isin(mastered)) & (~base_pool["reading"].isin(mastered))
        ].copy()

    if len(base_pool) == 0:
        ensure_mastery_banner_shape()
        # (여기 기존 처리 그대로 두되) 마지막에 st.stop()으로 마무리
        st.stop()

    take_n = min(N, len(base_pool))
    if take_n < N:
        st.info(f"남은 문제가 {len(base_pool)}개라서, 남은 만큼만 출제합니다 🙂")

    sampled = base_pool.sample(n=take_n).reset_index(drop=True)
    return [make_question(sampled.iloc[i], qtype, base_for_distractor, pool) for i in range(len(sampled))]
    
# ============================================================
# ✅ 세션 초기화
# ============================================================

if "quiz_type" not in st.session_state or st.session_state.get("quiz_type") not in available_types:
    st.session_state.quiz_type = available_types[0]  # 보통 "reading"

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
ensure_mastery_banner_shape() 

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

colL, colR = st.columns(2, gap="small")

with colL:
    st.markdown('<div class="tabcap">품사</div>', unsafe_allow_html=True)

    pos_clicked = st.segmented_control(
        label="",
        options=POS_MODES,
        format_func=lambda x: ("✅ " + POS_MODE_MAP.get(x, x)) if x == st.session_state.pos_mode else POS_MODE_MAP.get(x, x),
        default=st.session_state.pos_mode,
        key="seg_pos_mode",
    )

with colR:
    st.markdown('<div class="tabcap">유형</div>', unsafe_allow_html=True)

    clicked = st.segmented_control(
        label="",
        options=available_types,
        format_func=lambda x: ("✅ " + quiz_label_map.get(x, x)) if x == st.session_state.quiz_type else quiz_label_map.get(x, x),
        default=st.session_state.quiz_type,
        key="seg_qtype",
    )

# ✅ 변경 감지 로직은 그대로 (아래는 기존과 동일)
if pos_clicked and pos_clicked != st.session_state.pos_mode:
    st.session_state.pos_mode = pos_clicked
    clear_question_widget_keys()
    new_quiz = build_quiz(st.session_state.quiz_type)  # 현재 유형 유지
    start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)
    st.rerun()

if clicked and clicked != st.session_state.quiz_type:
    clear_question_widget_keys()
    new_quiz = build_quiz(clicked)
    start_quiz_state(new_quiz, clicked, clear_wrongs=True)
    st.rerun()

st.divider()

# ✅✅ 여기부터 추가/정리 (새 문제 + 초기화)
cbtn1, cbtn2 = st.columns(2)

with cbtn1:
    if st.button("🔄 새 문제(랜덤 10문항)", use_container_width=True, key="btn_new_random_10"):
        clear_question_widget_keys()
        # 현재 유형 그대로 랜덤 새 세트 생성
        new_quiz = build_quiz(st.session_state.quiz_type)
        start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)
        st.session_state["_scroll_top_once"] = True
        st.rerun()

with cbtn2:
    if st.button("✅ 맞힌 단어 제외 초기화", use_container_width=True, key="btn_reset_mastered_current_type"):
        ensure_mastered_words_shape()
        st.session_state.mastered_words[st.session_state.quiz_type] = set()

        ensure_mastery_banner_shape()
        st.session_state.mastery_banner_shown[st.session_state.quiz_type] = False

        clear_question_widget_keys()
        new_quiz = _safe_build_quiz_after_reset(st.session_state.quiz_type)
        start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)

        st.success(f"초기화 완료 (유형: {quiz_label_map[st.session_state.quiz_type]})")
        st.session_state["_scroll_top_once"] = True
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
    show_post_ui = (SHOW_POST_SUBMIT_UI == "Y") or is_admin()

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

    # ✅ 학생에게 남길 것(점수/격려)만 여기서 출력
    st.success(f"점수: {score} / {quiz_len}")
    ratio = score / quiz_len if quiz_len else 0

    if ratio == 1:
        st.balloons()
        st.success("🎉 완벽해요! 전부 정답입니다. 정말 잘했어요!")
    elif ratio >= 0.7:
        st.info("👍 잘하고 있어요! 조금만 더 다듬으면 완벽해질 거예요.")
    else:
        st.warning("💪 괜찮아요! 틀린 문제는 성장의 재료예요. 다시 한 번 도전해봐요.")

    # ✅ DB 저장은 UI와 무관하게 계속 수행
    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        if show_post_ui:
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
                if show_post_ui:
                    st.warning("DB 저장에 실패했습니다. (테이블/컬럼/권한/RLS 정책 확인 필요)")
                    st.write(str(e))

        if not st.session_state.stats_saved_this_attempt:
            def _save_stats_bulk():
                # (중요) 위젯 값이 answers와 100% 동기화되게
                sync_answers_from_widgets()

                items = build_word_results_bulk_payload(
                    quiz=st.session_state.quiz,
                    answers=st.session_state.answers,
                    quiz_type=current_type,
                    level=LEVEL,
                )

                if not items:
                    return None

                # ✅ RPC 1번 호출로 끝
                return sb_authed_local.rpc(
                    "record_word_results_bulk",
                    {"p_items": items},
                ).execute()

            try:
                run_db(_save_stats_bulk)
                st.session_state.stats_saved_this_attempt = True
                if show_post_ui:
                    st.success("✅ 단어 통계(bulk) 저장 성공")
            except Exception as e:
                if show_post_ui:
                    st.error("❌ 단어 통계(bulk) 저장 실패 (아래 에러가 진짜 원인입니다)")
                    st.exception(e)

        # ✅ 아래는 전부 "보여주기"에 해당하므로 show_post_ui로 한번에 묶기
        if show_post_ui:
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

    # ✅ 누적 카운터 업데이트(내부 로직) — 화면과 무관하게 유지
    if not st.session_state.session_stats_applied_this_attempt:
        st.session_state.history.append({"type": current_type, "score": score, "total": quiz_len})

        for idx, q in enumerate(st.session_state.quiz):
            word_key = (str(q.get("jp_word", "")).strip() or str(q.get("reading", "")).strip())
            st.session_state.total_counter[word_key] = st.session_state.total_counter.get(word_key, 0) + 1
            if st.session_state.answers[idx] != q["correct_text"]:
                st.session_state.wrong_counter[word_key] = st.session_state.wrong_counter.get(word_key, 0) + 1

        st.session_state.session_stats_applied_this_attempt = True

# ✅ 오답노트/다시풀기/다음10문항은 "항상" 노출 (submitted 후, 오답 있을 때)
if st.session_state.submitted and st.session_state.wrong_list:
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

    def _s(v):
        return "" if v is None else str(v)

    # ✅ 카드 렌더링 (오답마다 1장)
    for w in st.session_state.wrong_list:
        no = _s(w.get("No"))
        qtext = _s(w.get("문제"))
        picked = _s(w.get("내 답"))
        correct = _s(w.get("정답"))
        word = _s(w.get("단어"))
        reading = _s(w.get("읽기"))
        meaning = _s(w.get("뜻"))
        mode = quiz_label_map.get(w.get("유형"), w.get("유형", ""))

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

    # ✅ 버튼은 "오답노트 전체" 아래에 1번만 (항상 노출)
    if st.button(
        "❌ 틀린 문제만 다시 풀기",
        type="primary",
        use_container_width=True,
        key="btn_retry_wrongs_bottom",
    ):
        clear_question_widget_keys()
        retry_quiz = build_quiz_from_wrongs(
            st.session_state.wrong_list,
            st.session_state.quiz_type,
        )
        start_quiz_state(retry_quiz, st.session_state.quiz_type, clear_wrongs=True)
        st.session_state["_scroll_top_once"] = True
        st.rerun()

# ✅✅✅ 다음 10문항은 "submitted면 항상" (오답 0개여도)
if st.session_state.submitted:
    if st.button(
        "✅ 다음 10문항 시작하기",
        type="primary",
        use_container_width=True,
        key="btn_next_10",
    ):
        clear_question_widget_keys()
        new_quiz = build_quiz(st.session_state.quiz_type)
        start_quiz_state(new_quiz, st.session_state.quiz_type, clear_wrongs=True)
        st.session_state["_scroll_top_once"] = True
        st.rerun()
     
    show_naver_talk = (SHOW_NAVER_TALK == "N") or is_admin()
        
    if show_naver_talk:
        render_naver_talk()
