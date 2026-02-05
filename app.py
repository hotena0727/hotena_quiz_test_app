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

# ✅ (빈 박스 제거) today_goal 입력칸은 없애고, 체크박스만 유지
if "today_goal_done" not in st.session_state:
    st.session_state.today_goal_done = False

with st.container():
    st.markdown("### 🎯 오늘의 목표(루틴)")

    # ✅ 입력칸 제거: 빈 박스의 정체가 st.text_input 이었음
    st.session_state.today_goal_done = st.checkbox(
        "달성",
        value=bool(st.session_state.today_goal_done),
    )

    if st.session_state.today_goal_done:
        st.success("좋아요. 오늘 루틴 완료 ✅")
    else:
        st.caption("가볍게라도 체크하면 루틴이 끊기지 않습니다.")

st.divider()
