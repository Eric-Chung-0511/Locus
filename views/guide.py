"""Guide: the bilingual in-app guide, with the language switch at the top."""

from __future__ import annotations

import streamlit as st

from locus import labels as L
from views.shared import help_text, lang


def _remember_language() -> None:
    # Widget state is dropped on pages where the switch is not drawn, so the
    # choice is copied to a plain session key that every page reads.
    st.session_state["lang"] = st.session_state["_lang_switch"]


st.title("Guide")
st.segmented_control("Language", options=list(L.LANGUAGES), format_func=L.LANGUAGES.get,
                     default=lang(), required=True, key="_lang_switch", on_change=_remember_language,
                     label_visibility="collapsed")
st.subheader("How to use Locus" if lang() == "en" else "Locus 使用說明")

tab_start, tab_settings, tab_pages, tab_glossary = st.tabs(
    ["What this app does", "Settings", "Each page", "Glossary"])
with tab_start:
    st.markdown(help_text("start", with_title=False))
with tab_settings:
    st.markdown(help_text("settings", with_title=False))
with tab_pages:
    for key in ("summary", "confidence", "drivers", "recovery", "reviews", "late_start", "assumptions"):
        title, _, body = help_text(key).partition("\n")
        with st.expander(title.lstrip("# ").strip()):
            st.markdown(body.strip())
with tab_glossary:
    st.markdown(help_text("glossary", with_title=False))
