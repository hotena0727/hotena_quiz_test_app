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
<style>
@import url('https://fonts.googleapis.com/css2?family=Kosugi+Maru&display=swap');
:root{ --jp-rounded: "Kosugi Maru","Hiragino Sans","Yu Gothic","Meiryo",sans-serif; }
.jp, .jp *{ font-family: var(--jp-rounded) !important; line-height:1.7; letter-spacing:.2px; }
</style>
""", unsafe_allow_html=True)

st.title("い형용사 퀴즈")


# ============================================================
# ✅ Cookies
# ============================================================
cookies = EncryptedCookieManager(
    prefix="hatena_jlpt/",
    password=st.secrets.get("COOKIE_PASSWORD", "change-me-please")
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

# anon client (로그인/회원가입 + refresh_session 용)
sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ============================================================
# ✅ 상수/설정
# ============================================================
NAVER_TALK_URL = "https://talk.naver.com/W45141"
APP_URL = "https://hotenaquiztestapp-5wiha4zfuvtnq4qgxdhq72.streamlit.app/"
LEVEL = "N4"
N = 10

quiz_label_map = {"reading": "발음", "meaning": "뜻"}
quiz_label_for_table = {"reading": "발음", "meaning": "뜻"}

KST_TZ = "Asia/Seoul"


# ============================================================
# ✅ 유틸: JWT 만료 감지 + 세션 갱신 + DB 호출 래퍼
# ============================================================
def is_jwt_expired_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("jwt expired" in msg) or ("pgrst303" in msg)


def clear_auth_everywhere():
    # 쿠키 정리
    try:
        cookies["access_token"] = ""
        cookies["refresh_token"] = ""
        cookies.save()
    except Exception:
        pass

    # 세션 정리
    for k in [
        "user", "access_token", "refresh_token",
        "login_email", "email_link_notice_shown",
        "auth_mode", "signup_done", "last_signup_ts",
        "page",
        "quiz", "answers", "submitted", "wrong_list",
        "quiz_version", "quiz_type", "saved_this_attempt",
        "history", "wrong_counter", "total_counter",
    ]:
        st.session_state.pop(k, None)


def refresh_session_from_cookie_if_needed(force: bool = False) -> bool:
    """
    ✅ refresh_token으로 access_token 갱신
    - force=True면 무조건 refresh 시도
    """
    if not force and st.session_state.get("user") and st.session_state.get("access_token"):
        return True

    rt = cookies.get("refresh_token")
    if not rt:
        return False

    try:
        refreshed = sb.auth.refresh_session(rt)
        if not refreshed or not refreshed.session:
            return False

        st.session_state.user = refreshed.user
        st.session_state.access_token = refreshed.session.access_token
        st.session_state.refresh_token = refreshed.session.refresh_token

        # login_email fallback
        u_email = getattr(refreshed.user, "email", None)
        if u_email:
            st.session_state["login_email"] = u_email.strip()

        cookies["access_token"] = refreshed.session.access_token
        cookies["refresh_token"] = refreshed.session.refresh_token
        cookies.save()
        return True

    except Exception:
        return False


def get_authed_sb():
    """
    ✅ RLS 통과용: access_token을 PostgREST에 붙인 클라이언트
    - 토큰 없으면 쿠키 refresh 시도
    """
    if not st.session_state.get("access_token"):
        refresh_session_from_cookie_if_needed(force=True)

    token = st.session_state.get("access_token")
    if not token:
        return None

    sb2 = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb2.postgrest.auth(token)
    return sb2


def run_db(callable_fn):
    """
    ✅ DB 호출 래퍼:
    - JWT expired면 refresh → rerun (사용자에게 에러 노출 X)
    """
    try:
        return callable_fn()
    except Exception as e:
        if is_jwt_expired_error(e):
            ok = refresh_session_from_cookie_if_needed(force=True)
            if ok:
                st.rerun()
            # refresh가 실패면 깔끔하게 로그아웃 처리
            clear_auth_everywhere()
            st.warning("세션이 만료되었습니다. 다시 로그인해 주세요.")
            st.rerun()
        raise


def to_kst_naive(series_or_value):
    """
    created_at(UTC) -> KST -> timezone 제거(표시용)
    """
    ts = pd.to_datetime(series_or_value, utc=True, errors="coerce")
    return ts.dt.tz_convert(KST_TZ).dt.tz_localize(None)


# ============================================================
# ✅ Admin 설정
# ============================================================
def get_admin_email_set() -> set[str]:
    raw = st.secrets.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin() -> bool:
    u = st.session_state.get("user")
    email = getattr(u, "email", None) if u else None
    if not email:
        email = st.session_state.get("login_email")
    if not email:
        return False
    return email.strip().lower() in get_admin_email_set()


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
    if "user" not in st.session_state or st.session_state.user is None:
        auth_box()
        st.stop()


# ============================================================
# ✅ profiles upsert (선택)
# ============================================================
def ensure_profile(sb_authed, user):
    try:
        sb_authed.table("profiles").upsert({
            "id": user.id,
            "email": getattr(user, "email", None),
        }).execute()
    except Exception:
        pass


# ============================================================
# ✅ 앱 시작: refresh 시도 → 로그인 강제
# ============================================================
refresh_session_from_cookie_if_needed(force=False)
require_login()

user = st.session_state.user
user_id = user.id
user_email = getattr(user, "email", None) or st.session_state.get("login_email")

sb_authed = get_authed_sb()
if sb_authed is not None:
    # DB가 막혀도 앱은 계속 돌아가게 run_db로 감싸지 않음(실패해도 무시)
    try:
        ensure_profile(sb_authed, user)
    except Exception:
        pass


# ============================================================
# ✅ DB 함수
# ============================================================
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
# ✅ 관리자 대시보드
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


# ============================================================
# ✅ 내 대시보드 (유저용)
# ============================================================
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

    # 카드형
    st.markdown("""
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
.record-title{
  font-weight: 800;
  font-size: 16px;
}
.record-sub{
  opacity: 0.75;
  font-size: 12px;
}
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
}
</style>
""", unsafe_allow_html=True)

    for _, r in hist.head(15).iterrows():
        dt = pd.to_datetime(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        mode = r["유형"]
        score_i = int(r["score"])
        total = int(r["quiz_len"])
        wrong = int(r["wrong_count"])
        pct = float(r["정답률"] * 100)

        if pct >= 90:
            badge = "🏆"
        elif pct >= 70:
            badge = "👍"
        else:
            badge = "💪"

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

    # ✅ 학생 화면에서는 expander(표로 보기) 숨김
    if is_admin():
        with st.expander("표로 보기"):
            show = hist.rename(columns={
                "created_at": "일시",
                "level": "레벨",
                "pos_mode": "quiz_type(원값)",
                "quiz_len": "문항",
                "score": "점수",
                "wrong_count": "오답",
            })
            show["일시"] = pd.to_datetime(show["일시"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(
                show[["일시", "레벨", "유형", "문항", "점수", "오답", "quiz_type(원값)"]],
                use_container_width=True,
                hide_index=True,
            )



# ============================================================
# ✅ 상단 헤더 (페이지/버튼)
# ============================================================
if "page" not in st.session_state:
    st.session_state.page = "quiz"  # quiz | my | admin

colA, colB, colC, colD = st.columns([5, 2, 2, 3])

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
    render_admin_dashboard()
    st.stop()

if st.session_state.page == "my":
    render_my_dashboard()
    st.stop()


# ============================================================
# ✅ CSV 로드
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "words_adj_300.csv"

df = pd.read_csv(CSV_PATH)
if len(df.columns) == 1 and "\t" in df.columns[0]:
    df = pd.read_csv(CSV_PATH, sep="\t")

df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()

pool = df[df["level"] == LEVEL].copy()
pool_i = pool[pool["pos"] == "i_adj"].copy()

if len(pool_i) < N:
    st.error(f"い형용사 단어가 부족합니다: pool={len(pool_i)}")
    st.stop()


# ============================================================
# ✅ 퀴즈 로직
# ============================================================
def make_question(row: pd.Series, qtype: str, base_pool: pd.DataFrame) -> dict:
    if qtype == "reading":
        prompt = f"{row['jp_word']}의 발음은?"
        correct = row["reading"]
        candidates = (
            base_pool[base_pool["reading"] != correct]["reading"]
            .dropna().drop_duplicates().tolist()
        )
    else:
        prompt = f"{row['jp_word']}의 뜻은?"
        correct = row["meaning"]
        candidates = (
            base_pool[base_pool["meaning"] != correct]["meaning"]
            .dropna().drop_duplicates().tolist()
        )

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


def build_quiz(qtype: str) -> list:
    sampled = pool_i.sample(n=N).reset_index(drop=True)
    return [make_question(sampled.iloc[i], qtype, pool_i) for i in range(len(sampled))]


def build_quiz_from_wrongs(wrong_list: list, qtype: str) -> list:
    wrong_words = list({w["단어"] for w in wrong_list})
    retry_df = pool_i[pool_i["jp_word"].isin(wrong_words)].copy()

    if len(retry_df) == 0:
        st.error("오답 단어를 풀에서 찾지 못했습니다. (jp_word 매칭 확인 필요)")
        st.stop()

    retry_df = retry_df.sample(frac=1).reset_index(drop=True)
    return [make_question(retry_df.iloc[i], qtype, pool_i) for i in range(len(retry_df))]


# ============================================================
# ✅ 세션 초기화
# ============================================================
if "quiz_type" not in st.session_state:
    st.session_state.quiz_type = "reading"
if "quiz_version" not in st.session_state:
    st.session_state.quiz_version = 0
if "submitted" not in st.session_state:
    st.session_state.submitted = False
if "wrong_list" not in st.session_state:
    st.session_state.wrong_list = []
if "saved_this_attempt" not in st.session_state:
    st.session_state.saved_this_attempt = False

# 누적(세션) 통계
if "history" not in st.session_state:
    st.session_state.history = []
if "wrong_counter" not in st.session_state:
    st.session_state.wrong_counter = {}
if "total_counter" not in st.session_state:
    st.session_state.total_counter = {}

if "quiz" not in st.session_state:
    st.session_state.quiz = build_quiz(st.session_state.quiz_type)


# ============================================================
# ✅ 상단 UI (출제유형/새문제/초기화)
# ============================================================
selected = st.radio(
    "출제 유형",
    options=["reading", "meaning"],
    format_func=lambda x: quiz_label_map[x],
    horizontal=True,
    index=["reading", "meaning"].index(st.session_state.quiz_type),
    key="radio_quiz_type",
)

if selected != st.session_state.quiz_type:
    st.session_state.quiz_type = selected
    st.session_state.quiz = build_quiz(selected)
    st.session_state.submitted = False
    st.session_state.wrong_list = []
    st.session_state.saved_this_attempt = False
    st.session_state.quiz_version += 1
    st.rerun()

st.caption(f"현재 선택: **{quiz_label_map[st.session_state.quiz_type]}**")
st.divider()

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 새 문제(랜덤 10문항)", use_container_width=True, key="btn_new_quiz"):
        st.session_state.quiz = build_quiz(st.session_state.quiz_type)
        st.session_state.submitted = False
        st.session_state.wrong_list = []
        st.session_state.saved_this_attempt = False
        st.session_state.quiz_version += 1
        st.rerun()

with col2:
    if st.button("🧹 선택 초기화", use_container_width=True, key="btn_reset_choice"):
        st.session_state.submitted = False
        st.session_state.quiz_version += 1
        st.rerun()

st.divider()


# ============================================================
# ✅ answers 길이 자동 맞춤
# ============================================================
quiz_len = len(st.session_state.quiz)
if "answers" not in st.session_state or len(st.session_state.answers) != quiz_len:
    st.session_state.answers = [None] * quiz_len


# ============================================================
# ✅ 문제 표시
# ============================================================
for idx, q in enumerate(st.session_state.quiz):
    st.subheader(f"Q{idx+1}")
    st.markdown(
        f'<div class="jp" style="font-size:18px; font-weight:500;">{q["prompt"]}</div>',
        unsafe_allow_html=True
    )
    choice = st.radio(
        label="보기",
        options=q["choices"],
        index=None,
        key=f"q_{st.session_state.quiz_version}_{idx}",
        label_visibility="collapsed",
    )
    st.session_state.answers[idx] = choice
    st.divider()


# ============================================================
# ✅ 제출/채점
# ============================================================
all_answered = all(a is not None for a in st.session_state.answers)

if st.button("✅ 제출하고 채점하기", disabled=not all_answered, type="primary", use_container_width=True, key="btn_submit"):
    st.session_state.submitted = True

if not all_answered:
    st.info("모든 문제에 답을 선택하면 제출 버튼이 활성화됩니다.")

if st.session_state.submitted:
    score = 0
    wrong_list = []

    for idx, q in enumerate(st.session_state.quiz):
        picked = st.session_state.answers[idx]
        correct = q["correct_text"]

        if picked == correct:
            score += 1
        else:
            wrong_list.append({
                "No": idx + 1,
                "문제": q["prompt"],
                "내 답": picked,
                "정답": correct,
                "단어": q["jp_word"],
                "읽기": q["reading"],
                "뜻": q["meaning"],
                "유형": st.session_state.quiz_type,
            })

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
        # ✅ DB 저장(한 번만) - JWT expired면 자동 refresh+rerrun
        if not st.session_state.saved_this_attempt:
            def _save():
                return save_attempt_to_db(
                    sb_authed=sb_authed_local,
                    user_id=user_id,
                    user_email=user_email,
                    level=LEVEL,
                    quiz_type=st.session_state.quiz_type,
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

        # ✅ 최근 기록
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

    # ✅ 세션 누적 통계(원래 기능 유지)
    st.session_state.history.append({"type": st.session_state.quiz_type, "score": score, "total": quiz_len})

    for idx, q in enumerate(st.session_state.quiz):
        word = q["jp_word"]
        st.session_state.total_counter[word] = st.session_state.total_counter.get(word, 0) + 1
        if st.session_state.answers[idx] != q["correct_text"]:
            st.session_state.wrong_counter[word] = st.session_state.wrong_counter.get(word, 0) + 1

    # ✅ 오답 있을 때만: 오답 노트 + 재도전
if st.session_state.wrong_list:
    st.subheader("❌ 오답 노트")

    # 보기 좋게 표기용 스타일(선택)
    st.markdown("""
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
    .wrong-title{
      font-weight: 900;
      font-size: 15px;
      margin-bottom: 4px;
    }
    .wrong-sub{
      opacity: 0.8;
      font-size: 12px;
    }
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
    .ans-k{
      opacity: 0.7;
      font-weight: 700;
    }
    </style>
    """, unsafe_allow_html=True)

    # ✅ 상세 안내(최근 오답부터 보기)
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
  <div class="ans-row"><div class="ans-k">읽기</div><div>{reading}</div></div>
  <div class="ans-row"><div class="ans-k">뜻</div><div>{meaning}</div></div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.divider()

    if st.button("❌ 틀린 문제만 다시 풀기", type="primary", use_container_width=True, key="btn_retry_wrong"):
        st.session_state.quiz = build_quiz_from_wrongs(st.session_state.wrong_list, st.session_state.quiz_type)
        st.session_state.submitted = False
        st.session_state.wrong_list = []
        st.session_state.saved_this_attempt = False
        st.session_state.quiz_version += 1
        st.rerun()

    # ✅ 누적 현황(이번 세션)
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

    # ✅ 제출 후 상담 배너
    render_naver_talk()
