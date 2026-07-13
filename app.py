import streamlit as st
import time
import json
import os
import re
from google import genai
from google.genai import types
from pinecone import Pinecone

# --- PHASE 3: LANGFUSE OBSERVABILITY (SDK v3) ---
from langfuse import observe, get_client

# --- OPTIONAL: Lottie animated loaders (graceful fallback if not installed) ---
# Keeps the app crash-proof (Challenge 3) — UI degrades gracefully if the
# package or network is unavailable.
try:
    from streamlit_lottie import st_lottie  # pip install streamlit-lottie
    LOTTIE_AVAILABLE = True
except Exception:
    LOTTIE_AVAILABLE = False

# ==========================================
# 1. PAGE CONFIGURATION & STATE INIT
# ==========================================
st.set_page_config(
    page_title="VELOXA | Enterprise Concierge",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize Session States
if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "text": "Welcome to Veloxa. How may I assist you today?"}]
if "recommendations" not in st.session_state: st.session_state.recommendations = []
if "selected_shoe" not in st.session_state: st.session_state.selected_shoe = None
if "selected_color" not in st.session_state: st.session_state.selected_color = None
if "cart" not in st.session_state: st.session_state.cart = []
if "admin_trace" not in st.session_state: st.session_state.admin_trace = ["System Initialized: Cloud Connected"]
if "session_id" not in st.session_state: st.session_state.session_id = f"veloxa-session-{int(time.time())}"

# ==========================================
# 2. CUSTOM CSS & UI  — "Velocity" design system
# ==========================================
st.markdown("""
<style>
    /* ---------- Fonts ---------- */
    @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800;900&family=Inter:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

    /* ---------- Design tokens ---------- */
    :root {
        --ink:        #0A0A0B;
        --ink-2:      #16171A;
        --paper:      #FAFAF7;
        --paper-2:    #F1F1EC;
        --line:       #E6E6E0;
        --molten:     #FF3B1F;   /* primary energy accent */
        --molten-2:   #E42E14;
        --volt:       #00E5FF;   /* secondary speed-streak accent */
        --text:       #17181B;
        --text-soft:  #6B6B72;
        --success:    #06B96B;
        --danger:     #E11D2E;
        --radius:     16px;
        --shadow:     0 10px 30px rgba(10,10,11,0.08);
        --shadow-lg:  0 24px 60px rgba(10,10,11,0.18);
    }

    /* ---------- Global typography ---------- */
    html, body, [class*="css"], .stMarkdown, p, div, span, label {
        font-family: 'Inter', -apple-system, sans-serif;
        color: var(--text);
    }
    .block-container { padding-top: 1.2rem; max-width: 1180px; }
    h1, h2, h3, h4 { font-family: 'Archivo', sans-serif; letter-spacing: -0.02em; }

    /* ---------- Top nav ---------- */
    .top-nav {
        display: flex; justify-content: space-between; align-items: center;
        padding: 6px 0 18px 0; border-bottom: 1px solid var(--line); margin-bottom: 28px;
    }
    .nav-logo {
        font-family: 'Archivo', sans-serif; font-weight: 900; font-size: 1.55rem;
        color: var(--ink); letter-spacing: -1.5px; display: flex; align-items: center; gap: 6px;
    }
    .nav-logo::before {
        content: ""; width: 12px; height: 22px; display: inline-block;
        background: var(--molten); transform: skewX(-16deg); border-radius: 2px;
        box-shadow: 4px 0 0 var(--volt);
    }
    .nav-links { color: var(--text-soft); font-size: 0.82rem; font-weight: 600; letter-spacing: 0.06em; }
    .nav-sale { color: var(--molten); }

    /* ---------- Hero ---------- */
    .hero-container {
        position: relative; overflow: hidden;
        background: radial-gradient(120% 140% at 12% 8%, #1e2027 0%, var(--ink) 55%);
        padding: 5.5rem 2.5rem; border-radius: 26px; color: #fff; margin-bottom: 2.5rem;
        box-shadow: var(--shadow-lg);
    }
    /* signature velocity streaks */
    .hero-container::before {
        content: ""; position: absolute; inset: 0;
        background:
          linear-gradient(115deg, transparent 40%, rgba(255,59,31,0.55) 41%, rgba(255,59,31,0) 44%),
          linear-gradient(115deg, transparent 52%, rgba(0,229,255,0.40) 53%, rgba(0,229,255,0) 55%),
          linear-gradient(115deg, transparent 63%, rgba(255,59,31,0.25) 64%, rgba(255,59,31,0) 66%);
        pointer-events: none;
    }
    .hero-eyebrow {
        position: relative; font-family: 'Space Mono', monospace; font-size: 0.72rem;
        letter-spacing: 0.34em; text-transform: uppercase; color: var(--volt);
        margin-bottom: 1rem; opacity: 0.95;
    }
    .hero-title {
        position: relative; font-family: 'Archivo', sans-serif; font-weight: 900;
        font-size: 4.2rem; line-height: 0.95; letter-spacing: -2.5px; margin-bottom: 1.2rem;
    }
    .hero-title .accent {
        color: var(--molten); font-style: italic; transform: skewX(-6deg); display: inline-block;
    }
    .hero-subtitle { position: relative; font-size: 1.05rem; opacity: 0.72; max-width: 560px; line-height: 1.6; }

    /* ---------- Section eyebrow ---------- */
    .section-eyebrow {
        font-family: 'Space Mono', monospace; font-size: 0.72rem; letter-spacing: 0.28em;
        text-transform: uppercase; color: var(--text-soft); margin: 8px 0 18px 0;
        display: flex; align-items: center; gap: 10px;
    }
    .section-eyebrow::after { content: ""; flex: 1; height: 1px; background: var(--line); }

    /* ---------- Buttons ---------- */
    .stButton > button {
        font-family: 'Inter', sans-serif; font-weight: 600; border-radius: 12px;
        border: 1px solid var(--line); background: #fff; color: var(--text);
        transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
        padding: 0.5rem 1rem;
    }
    .stButton > button:hover {
        transform: translateY(-2px); border-color: var(--molten);
        box-shadow: 0 8px 18px rgba(255,59,31,0.16);
    }
    .stButton > button:active { transform: translateY(0); }

    /* ---------- Product cards ---------- */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: var(--radius) !important; border: 1px solid var(--line) !important;
        transition: transform .18s ease, box-shadow .18s ease; overflow: hidden; position: relative;
        background: #fff;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:hover {
        transform: translateY(-4px); box-shadow: var(--shadow);
    }
    /* molten sweep underline on card hover */
    [data-testid="stVerticalBlockBorderWrapper"]::after {
        content: ""; position: absolute; left: 0; bottom: 0; height: 3px; width: 0;
        background: linear-gradient(90deg, var(--molten), var(--volt)); transition: width .28s ease;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:hover::after { width: 100%; }

    /* ---------- Badges ---------- */
    .match-badge {
        background: var(--ink); color: #fff; padding: 4px 11px; border-radius: 20px;
        font-size: 0.72rem; font-weight: 700; font-style: italic; letter-spacing: 0.02em;
        display: inline-block; transform: skewX(-6deg);
    }
    .match-badge span { display: inline-block; transform: skewX(6deg); }
    .sale-badge {
        background: var(--molten); color: #fff; padding: 4px 10px; border-radius: 20px;
        font-size: 0.68rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase;
    }

    /* ---------- AI reasoning panel ---------- */
    .reasoning-panel {
        background: var(--paper-2); border-left: 3px solid var(--molten);
        padding: 16px 18px; border-radius: 0 12px 12px 0; margin: 16px 0;
        font-size: 0.9rem; line-height: 1.55;
    }
    .reasoning-panel strong { font-family: 'Archivo', sans-serif; }

    /* ---------- Image placeholder ---------- */
    .image-placeholder {
        height: 200px; background: var(--paper-2); border-radius: 12px; display: flex;
        align-items: center; justify-content: center; color: var(--text-soft);
        font-size: 0.8rem; margin-bottom: 15px; text-align: center; padding: 20px;
        font-family: 'Space Mono', monospace;
    }

    /* ---------- Sidebar ---------- */
    [data-testid="stSidebar"] { background: var(--paper); border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] h1 {
        font-family: 'Archivo', sans-serif; font-weight: 900; letter-spacing: -1px; font-size: 1.4rem;
    }
    /* sticky cart summary total */
    .cart-total {
        position: sticky; top: 8px; z-index: 5;
        background: var(--ink); color: #fff; padding: 14px 16px; border-radius: 12px;
        font-family: 'Archivo', sans-serif; font-weight: 800; font-size: 1.05rem;
        display: flex; justify-content: space-between; align-items: center; margin-top: 6px;
    }
    .cart-total .amt { color: var(--volt); }
    .cart-line {
        display: flex; justify-content: space-between; padding: 8px 0;
        border-bottom: 1px dashed var(--line); font-size: 0.9rem;
    }
    .cart-line .price { font-weight: 700; }

    /* ---------- Chat ---------- */
    [data-testid="stChatMessage"] { border-radius: 14px; }

    /* ---------- Trace log (glass-box) ---------- */
    .trace-log { font-family: 'Space Mono', monospace; font-size: 0.76rem; line-height: 1.5; color: var(--text-soft); }

    /* ---------- Spinner styling ---------- */
    [data-testid="stSpinner"] > div { color: var(--molten) !important; font-weight: 600; }

    /* ---------- Footer ---------- */
    .site-footer {
        text-align: center; margin-top: 60px; padding-top: 24px;
        border-top: 1px solid var(--line); color: var(--text-soft);
    }
    .site-footer h3 { font-family: 'Archivo', sans-serif; font-weight: 900; letter-spacing: -1px; }

    /* ---------- Reduced motion ---------- */
    @media (prefers-reduced-motion: reduce) {
        * { transition: none !important; animation: none !important; }
    }
</style>
<div class="top-nav">
    <div class="nav-logo">VELOXA</div>
    <div class="nav-links">MEN &nbsp;&nbsp;&nbsp; WOMEN &nbsp;&nbsp;&nbsp; RUNNING &nbsp;&nbsp;&nbsp; <span class="nav-sale">SALE</span></div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 3. LOAD SECRETS & ENVIRONMENT VARS
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
    PINECONE_KEY = st.secrets["PINECONE_KEY"]

    # Langfuse requires environment variables for the decorator to pick them up
    os.environ["LANGFUSE_PUBLIC_KEY"] = st.secrets["LANGFUSE_PUBLIC_KEY"]
    os.environ["LANGFUSE_SECRET_KEY"] = st.secrets["LANGFUSE_SECRET_KEY"]
    os.environ["LANGFUSE_HOST"] = st.secrets.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
except Exception as e:
    st.error("⚠️ API Keys are missing. Please check your st.secrets.")
    API_KEY, PINECONE_KEY = "", ""

@st.cache_data
def load_catalog():
    try:
        with open('veloxa_enhanced_catalog.json', 'r') as f:
            return json.load(f).get("catalog", [])
    except FileNotFoundError:
        return []

catalog = load_catalog()
sizes = ["US 7", "US 8", "US 9", "US 10", "US 11", "US 12"]
store_policies = {
  "shipping": "Free standard shipping on orders over $150. Expedited shipping is $25.",
  "returns": "30-day trial period. Take them for a run!",
  "exchanges": "Free size and color exchanges within 30 days."
}

def get_image_path(img_name):
    """Smart Image Resolver"""
    if not img_name: return None
    clean_name = img_name.replace("images/", "").replace("images\\", "")
    if os.path.exists(clean_name): return clean_name
    if os.path.exists(f"images/{clean_name}"): return f"images/{clean_name}"
    return None

def log_trace(msg: str):
    """Local Glass-Box UI Telemetry"""
    st.session_state.admin_trace.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

def safe_toast(msg: str, icon: str = None):
    """Crash-proof toast wrapper (Challenge 3: never let UI sugar break the demo)."""
    try:
        st.toast(msg, icon=icon)
    except Exception:
        pass

# ==========================================
# 4. PHASE 2: ENTERPRISE GOVERNANCE MODULES
# ==========================================
@observe(as_type="span", name="PII_Scrubber")
def scrub_pii(text: str) -> str:
    """Security Gateway: Scrubber for PII before data hits the LLM."""
    log_trace("Security: Scrubbing PII...")
    scrubbed = re.sub(r'\b(?:\d[ -]*?){13,16}\b', '[REDACTED_CC]', text)
    scrubbed = re.sub(r'\b\d{3}[-.\s]??\d{3}[-.\s]??\d{4}\b', '[REDACTED_PHONE]', scrubbed)

    if scrubbed != text:
        log_trace("Security: PII detected and redacted.")
        safe_toast("Sensitive data redacted before processing.", icon="🔒")
    return scrubbed

@observe(as_type="span", name="Intent_Router")
def check_hitl_escalation(text: str) -> bool:
    """Human-In-The-Loop (HITL) Router: Bypasses LLM for sensitive issues."""
    log_trace("Router: Evaluating intent for HITL escalation...")
    keywords = ["refund", "fraud", "lawsuit", "sue", "manager"]
    if any(k in text.lower() for k in keywords):
        log_trace("Router: High-risk keyword detected. Escalating to HITL.")
        return True
    return False

# ==========================================
# 5. PHASE 2: ACTION EXECUTION (TOOL CALLING)
# ==========================================
@observe(as_type="span", name="Tool_Execution")
def add_to_cart(item_name: str, price: float) -> str:
    """Tool function to add an item to the shopping cart."""
    st.session_state.cart.append({"name": item_name, "price": price})
    log_trace(f"Action Execution: add_to_cart('{item_name}', {price})")
    safe_toast(f"Added {item_name} to cart — ${price}", icon="🛒")
    return f"Success: Added {item_name} to cart for ${price}."

# ==========================================
# 6. DYNAMIC ROUTING & MICRO-FUNCTIONS
# ==========================================
def process_multimodal_input(uploaded_file) -> types.Part | None:
    if uploaded_file is None: return None
    log_trace("Vision: Processing multimodal image input...")
    return types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=uploaded_file.type)

@observe(as_type="span", name="Vector_Retrieval")
def retrieve_pinecone_context(query: str, index: Pinecone, client: genai.Client) -> list:
    log_trace("RAG: Generating query embedding...")
    query_emb = client.models.embed_content(model="gemini-embedding-001", contents=query)

    log_trace("RAG: Querying Pinecone Vector DB...")
    search_results = index.query(vector=query_emb.embeddings[0].values, top_k=4, include_metadata=True)

    matched_ids = [int(match['id']) for match in search_results['matches']]
    relevant_shoes = [shoe for shoe in catalog if shoe['id'] in matched_ids]
    log_trace(f"RAG: Retrieved {len(relevant_shoes)} relevant items.")
    return relevant_shoes

@observe(name="Veloxa_Agent_Flow")
def call_gemini_sales_agent(user_text: str, safe_text: str, image_part: types.Part | None, history: list) -> dict:
    """Main Orchestrator tying the decoupled functions together."""

    # Langfuse SDK v3 Context Update
    langfuse = get_client()
    langfuse.update_current_trace(
        session_id=st.session_state.session_id,
        user_id="enterprise-shopper",
        tags=["production", "phase-2-omnichannel"]
    )

    client = genai.Client(api_key=API_KEY)
    pc = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index("veloxa-inventory")

    # 1. RAG RETRIEVAL (Uses safe scrubbed text)
    relevant_shoes = retrieve_pinecone_context(safe_text, index, client)

    # 2. PROMPT & HISTORY CONSTRUCTION
    history_str = "\n".join([f"{msg['role'].upper()}: {msg['text']}" for msg in history[-3:]])
    system_instruction = f"""
    You are the VELOXA AI Concierge - an enterprise omnichannel shopping assistant.
    RETRIEVED INVENTORY: {json.dumps(relevant_shoes)}
    STORE POLICIES: {json.dumps(store_policies)}

    DIRECTIVES:
    1. If the user provides an image, use Visual Search to find the closest match.
    2. If the user asks to buy or add an item to their cart, trigger the `add_to_cart` tool.
    3. You must ONLY output strictly formatted JSON matching this exact structure:
    {{
        "trace_log": ["Router Rewrote Query", "RAG Retrieved Matches", "Stylist Analyzing Stock"],
        "reply": "Your conversational reply...",
        "recommendations": [{{"id": 1, "match_percentage": 95, "reason": "Why it fits.", "recommended_color": "Red"}}]
    }}
    Do NOT wrap the response in markdown code blocks. Output raw JSON.
    """

    agent_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.3,
        tools=[add_to_cart]
    )

    user_parts = []
    if image_part: user_parts.append(image_part)
    user_parts.append(types.Part.from_text(text=f"HISTORY:\n{history_str}\nUSER: {safe_text}"))
    contents = [types.Content(role="user", parts=user_parts)]

    # 3. PRIMARY LLM CALL (Creates an inner span in Langfuse automatically)
    log_trace("Orchestrator: Calling Gemini 2.5 Flash...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=agent_config
    )

    # 4. ACTION EXECUTION (TOOL CALLING)
    if response.function_calls:
        log_trace("Agent: Tool execution requested.")
        contents.append(response.candidates[0].content)

        tool_responses = []
        for call in response.function_calls:
            if call.name == "add_to_cart":
                result = add_to_cart(call.args["item_name"], call.args["price"])
                tool_responses.append(
                    types.Part.from_function_response(name="add_to_cart", response={"result": result})
                )

        contents.append(types.Content(role="user", parts=tool_responses))

        log_trace("Orchestrator: Returning tool output to agent for final synthesis...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=agent_config
        )

    # 5. PARSING
    try:
        raw_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw_text)
        log_trace("Orchestrator: Successfully parsed JSON response.")
        return data
    except json.JSONDecodeError:
        log_trace("Error: Failed to parse JSON from LLM.")
        return {"trace_log": ["JSON Parsing Error"], "reply": "I encountered an error structuring my response.", "recommendations": []}

def handle_user_request(prompt: str, uploaded_image):
    """Wrapper to handle Gateway Logic & Execution."""
    # Run the gateway checks BEFORE hitting the main observable trace
    safe_text = scrub_pii(prompt)
    if check_hitl_escalation(safe_text):
        safe_toast("Escalating to a human agent.", icon="🙋")
        return {
            "trace_log": st.session_state.admin_trace[-3:],
            "reply": "I am escalating your request to a specialized human agent.",
            "recommendations": [],
            "escalate": True
        }

    img_part = process_multimodal_input(uploaded_image)

    # Send both raw (for telemetry setup) and safe_text to orchestrator
    result = call_gemini_sales_agent(prompt, safe_text, img_part, st.session_state.messages[:-1])

    # Flush langfuse telemetry to cloud asynchronously using v3 global client
    get_client().flush()
    return result

# ==========================================
# 7. SIDEBAR (CART & GLASS-BOX TRACEABILITY)
# ==========================================
with st.sidebar:
    st.title("⚡ Veloxa Concierge")
    st.caption(f"Session · {st.session_state.session_id}")
    st.divider()

    # Cart UI
    st.markdown('<div class="section-eyebrow">Shopping Cart</div>', unsafe_allow_html=True)
    if not st.session_state.cart:
        st.markdown("<div style='color:var(--text-soft); font-size:0.9rem;'>Your cart is empty. Ask the concierge to add a pair.</div>", unsafe_allow_html=True)
    else:
        cart_total = sum(float(item['price']) for item in st.session_state.cart)
        for item in st.session_state.cart:
            st.markdown(
                f"<div class='cart-line'><span>{item['name']}</span><span class='price'>${item['price']}</span></div>",
                unsafe_allow_html=True
            )
        st.markdown(
            f"<div class='cart-total'><span>Total</span><span class='amt'>${cart_total:.2f}</span></div>",
            unsafe_allow_html=True
        )
        if st.button("Secure Checkout", use_container_width=True):
            st.balloons()
            safe_toast("Order confirmed! Redirecting to payment.", icon="✅")
            st.info("Redirecting to payment gateway...")

    st.divider()

    # Glass-Box Local Telemetry
    with st.expander("Admin Trace Log (GenAIOps)"):
        st.markdown("<div class='trace-log'>", unsafe_allow_html=True)
        for trace in st.session_state.admin_trace:
            st.markdown(f"> {trace}")
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption("🔒 Logs forwarded to Langfuse Cloud (v3)")

    st.divider()

    # Chat UI
    st.markdown('<div class="section-eyebrow">Concierge</div>', unsafe_allow_html=True)
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["text"])

    # Multimodal
    uploaded_image = st.file_uploader("📸 Visual Search", type=['png', 'jpg', 'jpeg'])

    if prompt := st.chat_input("Ask about sizing, colors, or add items to cart..."):
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Concierge is thinking…"):
                res = handle_user_request(prompt, uploaded_image)

                ai_text = res.get("reply", "Error communicating with the Concierge.")
                st.markdown(ai_text)

                if res.get("escalate"):
                    st.warning("This requires human assistance.")
                    st.markdown("[Contact Support](mailto:support@veloxa.com)")

                st.session_state.recommendations = res.get("recommendations", [])
                st.session_state.messages.append({"role": "assistant", "text": ai_text})
                st.rerun()

# ==========================================
# 8. MAIN VIEW (HERO & CATALOG UI)
# ==========================================
st.markdown("""
<div class="hero-container">
    <div class="hero-eyebrow">Enterprise Visual Search · Agentic Tools</div>
    <div class="hero-title">Defy Gravity.<br><span class="accent">Embrace Speed.</span></div>
    <div class="hero-subtitle">An autonomous commerce concierge — multimodal search, real-time reasoning, and tool-driven checkout.</div>
</div>
""", unsafe_allow_html=True)

def get_recommendation_data(shoe_id):
    for rec in st.session_state.recommendations:
        if rec.get("id") == shoe_id: return rec
    return None

if catalog:
    # Detailed Shoe View
    if st.session_state.selected_shoe:
        shoe = st.session_state.selected_shoe
        if st.button("← Back to Catalog"):
            st.session_state.selected_shoe = None
            st.session_state.selected_color = None
            st.rerun()

        c1, c2 = st.columns([1, 2])
        rec_data = get_recommendation_data(shoe["id"])
        base_recommended_color = rec_data.get("recommended_color") if rec_data and rec_data.get("recommended_color") else shoe["colors_available"][0]
        display_color = st.session_state.selected_color if st.session_state.selected_color else base_recommended_color

        with c1:
            raw_img_filename = next((item["image"] for item in shoe["inventory"] if item["color"] == display_color), None)
            valid_img_path = get_image_path(raw_img_filename)
            if valid_img_path: st.image(valid_img_path, use_container_width=True)
            else: st.markdown(f"<div class='image-placeholder'>📸 Image Missing<br>{raw_img_filename}</div>", unsafe_allow_html=True)

        with c2:
            st.subheader(shoe["model"])
            p_html = f"<span style='font-family:Archivo;font-size:1.6rem;font-weight:900;'>&#36;{shoe['finalPrice']}</span>"
            if shoe['price'] != shoe['finalPrice']: p_html += f" <span style='text-decoration:line-through;color:var(--text-soft);margin-left:10px;'>&#36;{shoe['price']}</span>"
            st.markdown(p_html, unsafe_allow_html=True)
            st.markdown("<hr style='border:none;border-top:1px solid var(--line);margin:14px 0;'>", unsafe_allow_html=True)

            st.markdown("**Select Color**")
            color_cols = st.columns(len(shoe["colors_available"]))
            for idx, color_opt in enumerate(shoe["colors_available"]):
                with color_cols[idx]:
                    is_active = (color_opt == display_color)
                    btn_label = f"● {color_opt}" if is_active else color_opt
                    if st.button(btn_label, key=f"sel_{color_opt}", use_container_width=True):
                        st.session_state.selected_color = color_opt
                        st.rerun()

            if rec_data:
                st.markdown(f"""<div class="reasoning-panel"><strong>⚡ AI Match · {rec_data.get('match_percentage', 100)}%</strong><br>{rec_data.get('reason', '')}<br><em>Recommended color: {base_recommended_color}</em></div>""", unsafe_allow_html=True)

            st.markdown("<hr style='border:none;border-top:1px solid var(--line);margin:14px 0;'>", unsafe_allow_html=True)
            st.markdown(f"**Live Stock Matrix · {display_color}**")
            stock_cols = st.columns(len(sizes))
            color_inventory = [item for item in shoe["inventory"] if item["color"] == display_color]
            for idx, size in enumerate(sizes):
                stock_item = next((i for i in color_inventory if i["size"] == size), None)
                stock_qty = stock_item["stock"] if stock_item else 0
                with stock_cols[idx]:
                    if stock_qty > 0:
                        st.markdown(f"<div style='text-align:center;padding:10px;border:1px solid var(--line);border-radius:10px;margin-bottom:10px;'><div style='font-weight:600;'>{size}</div><div style='color:var(--success);font-weight:700;font-size:12px;'>{stock_qty} in stock</div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='text-align:center;padding:10px;border:1px solid #fde2e2;border-radius:10px;background:#fff6f6;margin-bottom:10px;'><div style='font-weight:600;'>{size}</div><div style='color:var(--danger);font-weight:700;font-size:12px;'>Out of stock</div></div>", unsafe_allow_html=True)

    # Grid Catalog View
    else:
        st.markdown('<div class="section-eyebrow">The Collection</div>', unsafe_allow_html=True)
        display_catalog = sorted(catalog, key=lambda x: 0 if get_recommendation_data(x["id"]) else 1)
        cols = st.columns(3)
        for i, shoe in enumerate(display_catalog):
            with cols[i % 3]:
                with st.container(border=True):
                    rec_data = get_recommendation_data(shoe["id"])
                    display_color = rec_data.get("recommended_color") if rec_data and rec_data.get("recommended_color") else shoe["colors_available"][0]

                    badge = ""
                    if rec_data: badge += f'<span class="match-badge"><span>{rec_data.get("match_percentage", 100)}% Match</span></span> '
                    if shoe["price"] != shoe["finalPrice"]: badge += '<span class="sale-badge">Sale</span>'
                    if badge: st.markdown(f"<div style='margin-bottom:10px;'>{badge}</div>", unsafe_allow_html=True)

                    raw_img_filename = next((item["image"] for item in shoe["inventory"] if item["color"] == display_color), None)
                    valid_img_path = get_image_path(raw_img_filename)
                    if valid_img_path: st.image(valid_img_path)
                    else: st.markdown(f"<div class='image-placeholder'>📸 {raw_img_filename}</div>", unsafe_allow_html=True)

                    st.markdown(f"**{shoe['model']}**")
                    if rec_data: st.caption(f"✨ {rec_data.get('reason', '')}")

                    p_html = f"<span style='font-family:Archivo;font-weight:900;'>&#36;{shoe['finalPrice']}</span>"
                    if shoe["price"] != shoe["finalPrice"]: p_html += f" <span style='text-decoration:line-through;color:var(--text-soft);font-size:0.8rem;margin-left:8px;'>&#36;{shoe['price']}</span>"
                    st.markdown(p_html, unsafe_allow_html=True)

                    if st.button("View Details", key=f"v_{shoe['id']}", use_container_width=True):
                        st.session_state.selected_shoe = shoe
                        st.session_state.selected_color = None
                        st.rerun()

st.markdown("""<div class="site-footer"><h3>VELOXA</h3><p>&copy; 2026 VELOXA ALP Project.</p></div>""", unsafe_allow_html=True)
