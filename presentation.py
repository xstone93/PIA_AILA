"""Small presentation helpers for the chat dock, intro views, and celebration."""
from uuid import uuid4

import streamlit as st


def render_task_progress(activity, state):
    """Count completed sections, leaving the current section in progress."""
    total = len(activity["tasks"])
    completed = total if state.get("completed") else state["task_index"]
    label = "Abgeschlossen" if state.get("completed") else f"Aufgabe {completed + 1} von {total}"
    st.progress(completed / total, text=label)


def page_style(intro=False):
    dark = st.context.theme.type == "dark"
    background = st.get_option("theme.backgroundColor") or ("#0e1117" if dark else "#ffffff")
    tint = "background-color: color-mix(in srgb, currentColor 4%, transparent);" if intro else ""
    st.html(f"""
    <style>
    [data-testid="stMain"] {{ {tint} }}
    [data-testid="stMainBlockContainer"] {{
        padding-bottom: calc(17rem + env(safe-area-inset-bottom));
    }}
    .st-key-chat_dock {{
        position: fixed;
        bottom: 0;
        left: var(--chat-main-center, 50%);
        transform: translateX(-50%);
        width: min(46rem, calc(var(--chat-main-width, 100vw) - 2rem));
        max-height: min(14rem, 50dvh);
        overflow-y: auto;
        z-index: 100;
        box-sizing: border-box;
        padding: .75rem .75rem calc(.75rem + env(safe-area-inset-bottom));
        border-radius: .75rem .75rem 0 0;
        background: {background};
        box-shadow: 0 -3px 14px #00000012;
    }}
    .st-key-chat_dock textarea {{ max-height: 6rem !important; }}
    @media (max-width: 480px) {{
        .st-key-chat_dock {{ width: calc(var(--chat-main-width, 100vw) - 1rem); padding-inline: .5rem; }}
    }}
    [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{ font-size: 0; }}
    [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after {{
        content: "menu"; font-size: 24px;
    }}
    </style>
    """)


def control_sidebar(command):
    """Use the native sidebar controls so its arrow and Information stay in sync."""
    if command not in {"open", "close", "toggle"}:
        raise ValueError("Unknown sidebar command")
    st.html("""
    <script>
    // sidebar-event-EVENT_ID
    (() => {
        const main = document.querySelector('[data-testid="stMain"]');
        if (main) {
            window.activityDockObserver?.disconnect();
            const alignDock = () => {
                const rect = main.getBoundingClientRect();
                document.documentElement.style.setProperty('--chat-main-center', `${rect.left + rect.width / 2}px`);
                document.documentElement.style.setProperty('--chat-main-width', `${rect.width}px`);
            };
            window.activityDockObserver = new ResizeObserver(alignDock);
            window.activityDockObserver.observe(main);
            alignDock();
        }
        let done = false;
        const apply = () => {
            if (done) return true;
            const sidebar = document.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) return false;
            const expanded = sidebar.getAttribute('aria-expanded') === 'true';
            const command = 'SIDEBAR_COMMAND';
            const shouldOpen = command === 'toggle' ? !expanded : command === 'open';
            if (expanded !== shouldOpen) {
                const button = document.querySelector(shouldOpen
                    ? '[data-testid="stExpandSidebarButton"]'
                    : '[data-testid="stSidebarCollapseButton"] button');
                if (!button) return false;
                done = true;
                button.click();
            }
            done = true;
            return true;
        };
        if (!apply()) {
            const observer = new MutationObserver(() => { if (apply()) observer.disconnect(); });
            observer.observe(document.body, {childList: true, subtree: true});
            setTimeout(() => observer.disconnect(), 2000);
        }
    })();
    </script>
    """.replace("SIDEBAR_COMMAND", command).replace("EVENT_ID", uuid4().hex),
            unsafe_allow_javascript=True)


def celebrate():
    colors = ["#ef476f", "#ffd166", "#06d6a0", "#118ab2", "#a78bfa"]
    pieces = "".join(
        f'<i style="left:{(i * 37) % 100}%;background:{colors[i % len(colors)]};'
        f'animation-delay:{(i % 9) * .08}s;--drift:{(i % 7 - 3) * 22}px"></i>'
        for i in range(70)
    )
    st.html("""
    <style>
    .activity-confetti { position:fixed; inset:0; pointer-events:none; z-index:1000; overflow:hidden; }
    .activity-confetti i {
        position:absolute; top:-20px; width:8px; height:13px; opacity:0;
        animation:activity-confetti-fall 3s ease-in forwards;
    }
    @keyframes activity-confetti-fall {
        0% { opacity:1; transform:translate(0, 0) rotate(0deg); }
        85% { opacity:1; }
        100% { opacity:0; transform:translate(var(--drift), 105dvh) rotate(650deg); }
    }
    @media (prefers-reduced-motion: reduce) {
        .activity-confetti { display:none; }
        .activity-confetti i { animation:none; }
    }
    </style>
    <div class="activity-confetti" aria-hidden="true">""" + pieces + "</div>")


def scroll_to_latest():
    """Scroll on a chat event, allowing images to finish laying out."""
    st.html("""
    <script>
    (() => {
        const main = document.querySelector('[data-testid="stMain"]');
        const content = document.querySelector('[data-testid="stMainBlockContainer"]');
        if (!main || !content) return;
        let active = true;
        let frame;
        let timer;
        const bottom = () => {
            if (active) main.scrollTo({top: main.scrollHeight, behavior: 'instant'});
        };
        const observer = new ResizeObserver(() => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(bottom);
        });
        const stop = () => {
            active = false;
            observer.disconnect();
            cancelAnimationFrame(frame);
            clearTimeout(timer);
            for (const event of ['wheel', 'touchstart', 'keydown', 'pointerdown']) {
                document.removeEventListener(event, stop, true);
            }
        };
        for (const event of ['wheel', 'touchstart', 'keydown', 'pointerdown']) {
            document.addEventListener(event, stop, {capture: true, passive: true});
        }
        observer.observe(content);
        frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(bottom);
        });
        timer = setTimeout(stop, 2000);
    })();
    </script>
    """ + f"<!-- scroll-event-{uuid4().hex} -->", unsafe_allow_javascript=True)
