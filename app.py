from pathlib import Path
import random
import pandas as pd
import streamlit as st
from supabase import create_client
from streamlit_cookies_manager import EncryptedCookieManager


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
# ✅ Streamlit 기본 설정
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
# ✅ Supabase 연결
# ============================================================
if "SUPABASE_URL" not in st.secrets or "SUPABASE_ANON_KEY" not in st.secrets:
    st.error("Supabase Secrets가 설정되지 않았습니다. (SUPABASE_URL / SUPABASE_ANON_KEY)")
    st.stop()

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

# anon client (로그인/회원가입용)
sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_authed_sb():
    """✅ RLS 통과용: access_token을 PostgREST에 붙인 클라이언트"""
    token = st.session_state.get("access_token")
    if not token:
        return None
    sb2 = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb2.postgrest.auth(token)
    return sb2


# ============================================================
# ✅ 상수/설정
# ============================================================
NAVER_TALK_URL = "https://talk.naver.com/W45141"
APP_URL = "https://hotenaquiztestapp-5wiha4zfuvtnq4qgxdhq72.streamlit.app/"
LEVEL = "N4"
N = 10

quiz_label_map = {"reading": "발음", "meaning": "뜻"}
quiz_label_for_table = {"reading": "발음", "meaning": "뜻"}


# ============================================================
# ✅ Admin 설정
# ============================================================
def get_admin_email_set() -> set[str]:
    raw = st.secrets.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin() -> bool:
    # ✅ user.email이 없을 때 login_email로도 판별
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

    # 이메일 컨펌/매직링크 등으로 들어온 경우 감지
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

    # ----------------------------
    # 로그인
    # ----------------------------
    if mode == "login":
        email = st.text_input("이메일", key="login_email")
        pw = st.text_input("비밀번호", type="password", key="login_pw")

        if st.button("로그인", use_container_width=True):
            if not email or not pw:
                st.warning("이메일과 비밀번호를 입력해주세요.")
                st.stop()

            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": pw})

                st.session_state.user = res.user
                st.session_state["login_email"] = email.strip()  # ✅ 중요: fallback용

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

    # ----------------------------
    # 회원가입
    # ----------------------------
    else:
        email = st.text_input("이메일", key="signup_email")
        pw = st.text_input("비밀번호", type="password", key="signup_pw")

        pw_len = len(pw) if pw else 0
        pw_ok = pw_len >= 8
        email_ok = bool(email and email.strip())

        st.caption("비밀번호는 **8자리 이상**으로 설정해 주세요.")
        if pw and not pw_ok:
            st.warning(f"비밀번호가 너무 짧습니다. (현재 {pw_len}자) 8자리 이상으로 입력해 주세요.")

        if st.button(
            "회원가입",
            use_container_width=True,
            disabled=not (email_ok and pw_ok),
            key="signup_btn",
        ):
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


# ============================================================
# ✅ 쿠키로 세션 복원
# ============================================================
def restore_session_from_cookies():
    if st.session_state.get("user") and st.session_state.get("access_token"):
        return

    rt = cookies.get("refresh_token")
    if not rt:
        return

    try:
        refreshed = sb.auth.refresh_session(rt)
        if not refreshed or not refreshed.session:
            # refresh_token이 invalid인 경우 쿠키 정리(선택)
            cookies["access_token"] = ""
            cookies["refresh_token"] = ""
            cookies.save()
            return

        st.session_state.user = refreshed.user
        st.session_state.access_token = refreshed.session.access_token
        st.session_state.refresh_token = refreshed.session.refresh_token

        # login_email fallback용(가능하면 채워둠)
        u_email = getattr(refreshed.user, "email", None)
        if u_email:
            st.session_state["login_email"] = u_email.strip()

        cookies["access_token"] = refreshed.session.access_token
        cookies["refresh_token"] = refreshed.session.refresh_token
        cookies.save()

    except Exception:
        # refresh 실패 시 쿠키 정리(선택)
        try:
            cookies["access_token"] = ""
            cookies["refresh_token"] = ""
            cookies.save()
        except Exception:
            pass
        return


def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        auth_box()
        st.stop()


def ensure_profile(sb_authed, user):
    """profiles에 (id, email) upsert"""
    try:
        sb_authed.table("profiles").upsert({
            "id": user.id,
            "email": getattr(user, "email", None),
        }).execute()
    except Exception:
        pass


# ============================================================
# ✅ 앱 시작: 쿠키 복원 → 로그인 강제
# ============================================================
restore_session_from_cookies()
require_login()

user = st.session_state.user
user_id = user.id

# ✅ user_email 안정적으로 확보
user_email = getattr(user, "email", None) or st.session_state.get("login_email")

sb_authed = get_authed_sb()
if sb_authed is not None:
    ensure_profile(sb_authed, user)


# ============================================================
# ✅ DB 저장/조회 함수
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
# ✅ 관리자 대시보드 (단 1개만 존재)
# ============================================================
def render_admin_dashboard():
    st.subheader("📊 관리자 대시보드")

    if not is_admin():
        st.error("접근 권한이 없습니다.")
        st.session_state.page = "quiz"
        st.stop()

    if st.button("← 퀴즈로 돌아가기", use_container_width=True):
        st.session_state.page = "quiz"
        st.rerun()

    sb_authed_local = get_authed_sb()
    if sb_authed_local is None:
        st.warning("토큰(sb_authed)이 없습니다. 로그인 세션 토큰 확인이 필요합니다.")
        st.stop()

    try:
        res = (
            sb_authed_local.table("quiz_attempts")
            .select("created_at, user_email, level, pos_mode, quiz_len, score, wrong_count")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        rows = len(res.data) if getattr(res, "data", None) else 0
        st.caption(f"DEBUG: quiz_attempts rows = {rows}")

    except Exception as e:
        st.error("❌ 관리자 조회 실패 (RLS/권한/테이블/컬럼 확인 필요)")
        st.exception(e)
        st.stop()

    if rows <= 0:
        st.info("데이터가 없거나 RLS 정책 때문에 전체 조회가 막혀 있습니다.")
        st.write("- Supabase Table Editor에서 quiz_attempts에 실제 데이터가 있는지 확인")
        st.write("- 데이터가 있는데도 0건이면 → RLS에서 관리자 전체 조회 허용 정책이 필요합니다.")
        return

    df_admin = pd.DataFrame(res.data).copy()
    ts = pd.to_datetime(df_admin["created_at"], utc=True)
    df_admin["created_at"] = ts.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)

    c1, c2, c3 = st.columns(3)
    c1.metric("최근 500건", rows)
    c2.metric("평균 점수", f"{df_admin['score'].mean():.2f}")
    c3.metric("평균 오답", f"{df_admin['wrong_count'].mean():.2f}")

    st.dataframe(df_admin, use_container_width=True, hide_index=True)

    csv = df_admin.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV 다운로드", csv, file_name="quiz_attempts_admin.csv", use_container_width=True)


# ============================================================
# ✅ 상단 UI (로그인 표시 + 관리자 버튼 + 로그아웃)
# ============================================================
if "page" not in st.session_state:
    st.session_state.page = "quiz"

colA, colB, colC = st.columns([5, 2, 3])

with colA:
    st.caption("환영합니다 🙂")

with colB:
    if is_admin():
        if st.button("📊 관리자 대시보드", use_container_width=True):
            st.session_state.page = "admin"
            st.rerun()

with colC:
    if st.button("🚪 로그아웃", use_container_width=True):
        try:
            sb.auth.sign_out()
        except Exception:
            pass

        try:
            cookies["access_token"] = ""
            cookies["refresh_token"] = ""
            cookies.save()
        except Exception:
            pass

        for k in [
            "user", "access_token", "refresh_token",
            "quiz", "answers", "submitted", "wrong_list",
            "quiz_version", "quiz_type", "saved_this_attempt",
            "history", "wrong_counter", "total_counter",
            "page", "login_email", "email_link_notice_shown",
            "auth_mode", "signup_done", "last_signup_ts",
        ]:
            st.session_state.pop(k, None)

        st.rerun()


# ============================================================
# ✅ 페이지 라우팅
# ============================================================
if st.session_state.get("page") == "admin":
    render_admin_dashboard()
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
    if st.button("🔄 새 문제(랜덤 10문항)", use_container_width=True):
        st.session_state.quiz = build_quiz(st.session_state.quiz_type)
        st.session_state.submitted = False
        st.session_state.wrong_list = []
        st.session_state.saved_this_attempt = False
        st.session_state.quiz_version += 1
        st.rerun()

with col2:
    if st.button("🧹 선택 초기화", use_container_width=True):
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

if st.button("✅ 제출하고 채점하기", disabled=not all_answered, type="primary", use_container_width=True):
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
        st.warning("DB 저장/조회용 토큰이 없습니다. (로그인 세션 토큰 확인 필요)")
    else:
        if not st.session_state.saved_this_attempt:
            try:
                save_attempt_to_db(
                    sb_authed=sb_authed_local,
                    user_id=user_id,
                    user_email=user_email,
                    level=LEVEL,
                    quiz_type=st.session_state.quiz_type,
                    quiz_len=quiz_len,
                    score=score,
                    wrong_list=wrong_list,
                )
                st.session_state.saved_this_attempt = True
            except Exception as e:
                st.warning("DB 저장에 실패했습니다. (테이블/컬럼/권한/RLS 정책 확인 필요)")
                st.write(getattr(e, "args", e))

        st.subheader("📌 내 최근 기록")

        try:
            res = fetch_recent_attempts(sb_authed_local, user_id, limit=10)

            if not res.data:
                st.info("아직 저장된 기록이 없습니다. 문제를 풀고 제출하면 기록이 쌓여요.")
            else:
                hist = pd.DataFrame(res.data).copy()
                ts = pd.to_datetime(hist["created_at"], utc=True)
                hist["created_at"] = ts.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)

                hist["유형"] = hist["pos_mode"].map(lambda x: quiz_label_for_table.get(x, x))
                hist["정답률"] = (hist["score"] / hist["quiz_len"]).fillna(0)

                avg_rate = float(hist["정답률"].mean() * 100)
                best = int(hist["score"].max())
                last_score = int(hist.iloc[0]["score"])
                last_total = int(hist.iloc[0]["quiz_len"])

                c1, c2, c3 = st.columns(3)
                c1.metric("최근 10회 평균", f"{avg_rate:.0f}%")
                c2.metric("최고 점수", f"{best} / {N}")
                c3.metric("최근 점수", f"{last_score} / {last_total}")

        except Exception as e:
            st.info("기록을 불러오지 못했습니다. (DB/RLS 확인 필요)")
            st.write(getattr(e, "args", e))

    # 세션 누적 통계
    st.session_state.history.append({"type": st.session_state.quiz_type, "score": score, "total": quiz_len})

    for idx, q in enumerate(st.session_state.quiz):
        word = q["jp_word"]
        st.session_state.total_counter[word] = st.session_state.total_counter.get(word, 0) + 1
        if st.session_state.answers[idx] != q["correct_text"]:
            st.session_state.wrong_counter[word] = st.session_state.wrong_counter.get(word, 0) + 1

    if st.session_state.wrong_list:
        st.subheader("❌ 오답 노트")

        if st.button("❌ 틀린 문제만 다시 풀기", type="primary", use_container_width=True, key="retry_wrong"):
            st.session_state.quiz = build_quiz_from_wrongs(st.session_state.wrong_list, st.session_state.quiz_type)
            st.session_state.submitted = False
            st.session_state.wrong_list = []
            st.session_state.saved_this_attempt = False
            st.session_state.quiz_version += 1
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

    if st.button("🗑️ 누적 기록 초기화", use_container_width=True):
        st.session_state.history = []
        st.session_state.wrong_counter = {}
        st.session_state.total_counter = {}
        st.rerun()

    render_naver_talk()
