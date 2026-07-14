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

# ==========================================
# 1. PAGE CONFIGURATION & STATE INIT
# ==========================================
st.set_page_config(page_title="VELOXA Storefront | Enterprise", page_icon="", layout="wide")

# Initialize Session States
if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "text": "Welcome to Veloxa. How may I assist you today?"}]
if "recommendations" not in st.session_state: st.session_state.recommendations = [] 
if "selected_shoe" not in st.session_state: st.session_state.selected_shoe = None
if "selected_color" not in st.session_state: st.session_state.selected_color = None
if "cart" not in st.session_state: st.session_state.cart = []
if "admin_trace" not in st.session_state: st.session_state.admin_trace = ["System Initialized: Cloud Connected"]
if "session_id" not in st.session_state: st.session_state.session_id = f"veloxa-session-{int(time.time())}"

# ==========================================
# 2. CUSTOM CSS & UI
# ==========================================
st.markdown("""
<style>
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 10px 0 20px 0; border-bottom: 1px solid #eaeaea; margin-bottom: 30px; }
    .nav-logo { font-weight: 900; font-size: 1.5rem; color: #000; letter-spacing: -1px; }
    .nav-links { color: #666; font-size: 0.9rem; font-weight: 600; }
    .nav-sale { color: #ef4444; }
    .hero-container { background: linear-gradient(135deg, #050505 0%, #1a1e26 100%); padding: 5rem 2rem; border-radius: 24px; color: white; text-align: center; margin-bottom: 2rem; box-shadow: 0 20px 40px rgba(0,0,0,0.4); }
    .hero-title { font-size: 4rem; font-weight: 900; margin-bottom: 1.5rem; letter-spacing: -2px; line-height: 1.1; }
    .hero-subtitle { font-size: 1.2rem; opacity: 0.8; max-width: 600px; margin: 0 auto 2rem auto; line-height: 1.6; }
    .reasoning-panel { background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 15px; border-radius: 0 8px 8px 0; margin-top: 15px; margin-bottom: 15px; color: #333; font-size: 0.9rem; }
    .match-badge { background: linear-gradient(90deg, #3b82f6, #8b5cf6); color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: bold; display: inline-block; margin-bottom: 8px; }
    .image-placeholder { height: 200px; background-color: #f1f5f9; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-size: 0.8rem; margin-bottom: 15px; text-align: center; padding: 20px;}
</style>
<div class="top-nav"><div class="nav-logo">VELOXA</div><div class="nav-links">MEN &nbsp;&nbsp;&nbsp;&nbsp; WOMEN &nbsp;&nbsp;&nbsp;&nbsp; RUNNING &nbsp;&nbsp;&nbsp;&nbsp; <span class="nav-sale">SALE</span></div></div>
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
    st.error("âš ï¸ API Keys are missing. Please check your st.secrets.")
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
    st.title("Veloxa Concierge")
    st.caption(f"Session: {st.session_state.session_id}")
    st.divider()
    
    # Cart UI
    st.subheader("Shopping Cart")
    if not st.session_state.cart:
        st.write("Your cart is empty.")
    else:
        cart_total = sum(float(item['price']) for item in st.session_state.cart)
        for item in st.session_state.cart:
            st.markdown(f"- {item['name']} **(${item['price']})**")
        st.success(f"**Total: ${cart_total:.2f}**")
        if st.button("Secure Checkout", use_container_width=True):
            st.info("Redirecting to payment gateway...")
    
    st.divider()
    
    # Glass-Box Local Telemetry
    with st.expander("Admin Trace Log (Gen-AI Ops)"):
        st.markdown("<div style='font-family: monospace; font-size: 0.8rem; line-height: 1.4;'>", unsafe_allow_html=True)
        for trace in st.session_state.admin_trace:
            st.markdown(f"> {trace}")
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption("ðŸ”’ Logs forwarded to Langfuse Cloud (v3)")
        
    st.divider()

    # Chat UI
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["text"])
    
    # Multimodal
    uploaded_image = st.file_uploader("Visual Search", type=['png', 'jpg', 'jpeg'])
    
    if prompt := st.chat_input("Ask about sizing, colors, or add items to cart..."):
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Processing request..."):
                res = handle_user_request(prompt, uploaded_image)
                
                ai_text = res.get("reply", "Error communicating with the Concierge.")
                st.markdown(ai_text)
                
                if res.get("escalate"):
                    st.warning("This requires human assistance.")
                    st.markdown("[Click here to email Support](mailto:support@veloxa.com)")

                st.session_state.recommendations = res.get("recommendations", [])
                st.session_state.messages.append({"role": "assistant", "text": ai_text})
                st.rerun()

# ==========================================
# 8. MAIN VIEW (HERO & CATALOG UI)
# ==========================================
st.markdown("""<div class="hero-container"><div class="hero-title">Defy Gravity.<br>Embrace Speed.</div><div class="hero-subtitle">Powered by Enterprise Visual Search & Agentic Tools.</div></div>""", unsafe_allow_html=True)

def get_recommendation_data(shoe_id):
    for rec in st.session_state.recommendations:
        if rec.get("id") == shoe_id: return rec
    return None

if catalog:
    # Detailed Shoe View
    if st.session_state.selected_shoe:
        shoe = st.session_state.selected_shoe
        st.markdown("---")
        if st.button("Back to Catalog"):
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
            else: st.markdown(f"<div class='image-placeholder'>ðŸ“¸ Image Missing:<br>{raw_img_filename}</div>", unsafe_allow_html=True)
        
        with c2:
            st.subheader(shoe["model"])
            p_html = f"<span style='font-size:1.4rem;font-weight:bold;'>&#36;{shoe['finalPrice']}</span>"
            if shoe['price'] != shoe['finalPrice']: p_html += f" <span style='text-decoration:line-through;color:#888;margin-left:10px;'>&#36;{shoe['price']}</span>"
            st.markdown(p_html, unsafe_allow_html=True)
            st.write("---")
            
            st.write("Select Color:**")
            color_cols = st.columns(len(shoe["colors_available"]))
            for idx, color_opt in enumerate(shoe["colors_available"]):
                with color_cols[idx]:
                    is_active = (color_opt == display_color)
                    btn_label = f"{color_opt}" if is_active else color_opt
                    if st.button(btn_label, key=f"sel_{color_opt}", use_container_width=True):
                        st.session_state.selected_color = color_opt
                        st.rerun()
                        
            if rec_data:
                st.markdown(f"""<div class="reasoning-panel"><strong> AI Match ({rec_data.get('match_percentage', 100)}%)</strong><br>{rec_data.get('reason', '')}<br><em>Recommended Color: {base_recommended_color}</em></div>""", unsafe_allow_html=True)
            
            st.write("---")
            st.write(f"**Live Stock Matrix ({display_color}):**")
            stock_cols = st.columns(len(sizes))
            color_inventory = [item for item in shoe["inventory"] if item["color"] == display_color]
            for idx, size in enumerate(sizes):
                stock_item = next((i for i in color_inventory if i["size"] == size), None)
                stock_qty = stock_item["stock"] if stock_item else 0
                with stock_cols[idx]:
                    if stock_qty > 0: st.markdown(f"<div style='text-align:center; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-bottom: 10px;'><div>{size}</div><div style='color:#10b981; font-weight:bold; font-size:12px;'>{stock_qty} in stock</div></div>", unsafe_allow_html=True)
                    else: st.markdown(f"<div style='text-align:center; padding:10px; border:1px solid #fee2e2; border-radius:8px; background:#fff5f5; margin-bottom: 10px;'><div>{size}</div><div style='color:#ef4444; font-weight:bold; font-size:12px;'>Out of Stock</div></div>", unsafe_allow_html=True)

    # Grid Catalog View
    else:
        display_catalog = sorted(catalog, key=lambda x: 0 if get_recommendation_data(x["id"]) else 1)
        cols = st.columns(3)
        for i, shoe in enumerate(display_catalog):
            with cols[i % 3]:
                with st.container(border=True):
                    rec_data = get_recommendation_data(shoe["id"])
                    display_color = rec_data.get("recommended_color") if rec_data and rec_data.get("recommended_color") else shoe["colors_available"][0]
                    
                    badge = ""
                    if rec_data: badge += f'<span class="match-badge">{rec_data.get("match_percentage", 100)}% Match</span> '
                    if shoe["price"] != shoe["finalPrice"]: badge += '<span style="background:#ef4444;color:#fff;padding:4px 8px;border-radius:12px;font-size:10px;font-weight:bold;">SALE</span>'
                    if badge: st.markdown(f"<div style='margin-bottom:8px;'>{badge}</div>", unsafe_allow_html=True)
                    
                    raw_img_filename = next((item["image"] for item in shoe["inventory"] if item["color"] == display_color), None)
                    valid_img_path = get_image_path(raw_img_filename)
                    if valid_img_path: st.image(valid_img_path)
                    else: st.markdown(f"<div class='image-placeholder'>ðŸ“¸ {raw_img_filename}</div>", unsafe_allow_html=True)
                        
                    st.markdown(f"**{shoe['model']}**")
                    if rec_data: st.caption(f"âœ¨ {rec_data.get('reason', '')}")
                    
                    p_html = f"<span style='font-weight:bold;'>&#36;{shoe['finalPrice']}</span>"
                    if shoe["price"] != shoe["finalPrice"]: p_html += f" <span style='text-decoration:line-through;color:#888;font-size:0.8rem;margin-left:8px;'>&#36;{shoe['price']}</span>"
                    st.markdown(p_html, unsafe_allow_html=True)
                    
                    if st.button("View Details", key=f"v_{shoe['id']}", use_container_width=True):
                        st.session_state.selected_shoe = shoe
                        st.session_state.selected_color = None
                        st.rerun()

st.markdown("""<div class="site-footer" style="text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #eaeaea; color: #666;"><h3>VELOXA</h3><p>&copy; 2026 VELOXA ALP Project.</p></div>""", unsafe_allow_html=True)
