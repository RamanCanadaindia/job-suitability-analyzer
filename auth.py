import streamlit as st

def check_password():
    """Returns True if the user entered the correct password."""

    def password_entered():
        try:
            correct_password = st.secrets.get("APP_PASSWORD", "admin")
        except Exception:
            correct_password = "admin"
        entered_password = st.session_state.get("password", "")
        if entered_password == correct_password:
            st.session_state["password_correct"] = True
            st.session_state.pop("password", None)  # do not retain the password
        else:
            st.session_state["password_correct"] = False

    # The callback can run during widget-state reconciliation, so make sure
    # its key exists before the password widget is constructed.
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        st.session_state.setdefault("password", "")

    if not st.session_state["password_correct"]:
        st.text_input(
            "Enter password to unlock application", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        if st.session_state.get("password"):
            st.error("😕 Password incorrect")
        return False

    return True
