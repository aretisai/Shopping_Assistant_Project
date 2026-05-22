import streamlit as st
import time
from google import genai
from google.genai import types
from pinecone import Pinecone
import json
import os

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="VELOXA Storefront", page_icon="⚡", layout="wide")

# --- 2. CUSTOM CSS & UI ---
st.markdown("""
<style>
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 10px 0 20px 0; border-bottom: 1px solid #eaeaea; margin-bottom: 30px; }
    .nav-logo { font-weight: 900; font-size: 1.5rem; color: #000; letter-spacing: -1px; }
    .nav-links { color: #666; font-size: 0.9rem; font-weight: 600; }
    .nav-sale { color: #ef4444; }
    .hero-container { background: linear-gradient(135deg, #050505 0%, #1a1e26 100%); padding: 5rem 2rem; border-radius: 24px; color: white; text-align: center; margin-bottom: 2rem; box-shadow: 0 20px 40px rgba(0,0,0,0.4); }
    .hero-title { font-size: 4rem; font-weight: 900; margin-bottom: 1.5rem; letter-spacing: -2px; line-height: 1.1; }
    .hero-subtitle { font-size: 1.2rem; opacity: 0.8; max-width: 600px; margin: 0 auto 2rem auto; line-height: 1.6; }
    .terminal-container { background-color: #0f172a; border-radius: 12px; padding: 1.5rem; font-family: 'Courier New', Courier, monospace; color: #34d399; font-size: 0.85rem; margin-bottom: 3rem; border: 1px solid #1e293b; min-height: 120px; }
    .terminal-header { color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; border-bottom: 1px solid #1e293b; padding-bottom: 5px; }
    .terminal-line { margin: 5px 0; }
    .terminal-prefix { color: #8b5cf6; font-weight: bold; }
    .reasoning-panel { background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 15px; border-radius: 0 8px 8px 0; margin-top: 15px; margin-bottom: 15px; color: #333; font-size: 0.9rem; }
    .match-badge { background: linear-gradient(90deg, #3b82f6, #8b5cf6); color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: bold; display: inline-block; margin-bottom: 8px; }
    .image-placeholder { height: 200px; background-color: #f1f5f9; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-size: 0.8rem; margin-bottom: 15px; text-align: center; padding: 20px;}
</style>
<div class="top-nav"><div class="nav-logo">VELOXA</div><div class="nav-links">MEN &nbsp;&nbsp;&nbsp;&nbsp; WOMEN &nbsp;&nbsp;&nbsp;&nbsp; RUNNING &nbsp;&nbsp;&nbsp;&nbsp; <span class="nav-sale">SALE</span></div></div>
""", unsafe_allow_html=True)

# --- 3. LOAD INVENTORY & POLICIES ---
@st.cache_data
def load_catalog():
    try:
        with open('veloxa_enhanced_catalog.json', 'r') as f:
            return json.load(f).get("catalog", [])
    except FileNotFoundError:
        return []
catalog = load_catalog()

store_policies = {
  "shipping": "Free standard shipping on orders over $150. Expedited shipping is $25 (2 business days).",
  "returns": "30-day trial period. Take them for a run! If you aren't completely satisfied, return them for a full refund.",
  "exchanges": "Free size and color exchanges within 30 days.",
  "warranty": "1-year warranty against manufacturing defects."
}

# --- 4. SMART IMAGE RESOLVER ---
def get_image_path(img_name):
    if not img_name: return None
    # Strip out the folder path so it just reads the pure filename
    clean_name = img_name.replace("images/", "").replace("images\\", "")
    # Check if the file is sitting directly in the cloud root
    if os.path.exists(clean_name): return clean_name
    # Check if it happens to be in a folder
    if os.path.exists(f"images/{clean_name}"): return f"images/{clean_name}"
    return None

# ==========================================
# 🛑 STREAMLIT SECRETS CONFIGURATION 🛑
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
    PINECONE_KEY = st.secrets["PINECONE_KEY"]
except:
    API_KEY = ""
    PINECONE_KEY = ""

def generate_veloxa_ai(user_text, history):
    if not API_KEY or not PINECONE_KEY:
        return {"trace_log": ["Error: API Keys Missing"], "reply": "⚠️ API Keys are missing in Streamlit Secrets.", "recommendations": []}
    
    try:
        client = genai.Client(api_key=API_KEY)
        pc = Pinecone(api_key=PINECONE_KEY)
        index = pc.Index("veloxa-inventory")
        
        # --- NEW: INTENT ROUTER (Cures RAG Amnesia) ---
        # Grabs the last few messages to understand context
        history_str = ""
        for msg in history[-3:]: 
            history_str += f"{msg['role'].upper()}: {msg['text']}\n"
            
        router_instruction = "You are a search query optimizer. Look at the chat history and the user's latest message. Rewrite the user's message into a single, highly specific search string that includes any shoe names or context they are referring to. Output ONLY the rewritten string."
        
        router_response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"HISTORY:\n{history_str}\nUSER: {user_text}",
            config=types.GenerateContentConfig(system_instruction=router_instruction, temperature=0.1)
        )
        search_query = router_response.text.strip()

        # --- NEW: RETRY LOOP (Cures Pinecone 503 Errors) ---
        MAX_RETRIES = 3
        search_results = None
        
        for attempt in range(MAX_RETRIES):
            try:
                # STEP 1: Turn Contextualized Query into Math
                query_emb = client.models.embed_content(model="gemini-embedding-001", contents=search_query)
                
                # STEP 2: Semantic Search
                search_results = index.query(vector=query_emb.embeddings[0].values, top_k=4, include_metadata=True)
                break # Success! Exit the retry loop
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5) # Sleep for 1.5s while Pinecone wakes up
                else:
                    raise e # Trigger the main exception block after 3 fails
        
        matched_ids = [int(match['id']) for match in search_results['matches']]
        
        # STEP 3: Retrieve Live Stock Data ONLY for matched shoes
        relevant_shoes = [shoe for shoe in catalog if shoe['id'] in matched_ids]

        # STEP 4: Build dynamic RAG prompt
        SYSTEM_INSTRUCTION = f"""
        You are the VELOXA AI Concierge.
        
        RETRIEVED RELEVANT INVENTORY (Top Matches from Pinecone):
        {json.dumps(relevant_shoes)}

        STORE POLICIES:
        {json.dumps(store_policies)}

        YOUR DIRECTIVES:
        1. Check nested "inventory" array. If "stock": 0, YOU CANNOT RECOMMEND IT. Suggest an alternative.
        2. Formulate a multi-agent trace log showing Vector DB retrieval.
        3. Respond in STRICT JSON formatting matching this exact structure:
        {{
            "trace_log": ["Router Rewrote Query: '{search_query}'", "Pinecone DB: Retrieved Top Matches", "Stylist: Analyzing Stock"],
            "reply": "Conversational reply based on retrieved context.",
            "recommendations": [{{"id": 1, "match_percentage": 95, "reason": "Why it fits.", "recommended_color": "Red"}}]
        }}
        """
        
        # We pass the full history to the Concierge so it still sounds conversational
        prompt_text = f"CHAT HISTORY:\n{history_str}\nUSER: {user_text}\n\nRespond in strict JSON as instructed."

        # STEP 5: Generate Final Answer
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_text,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.3)
        )
        
        raw_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw_text)
            
    except Exception as e:
        return {"trace_log": [f"Cloud Connect Error: {str(e)}"], "reply": "Network timeout. Please try again in a moment.", "recommendations": []}

# --- STATE INITIALIZATION & UI ---
if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "text": "Welcome to Veloxa. How may I assist you today?"}]
if "recommendations" not in st.session_state: st.session_state.recommendations = [] 
if "selected_shoe" not in st.session_state: st.session_state.selected_shoe = None
if "selected_color" not in st.session_state: st.session_state.selected_color = None
if "latest_trace" not in st.session_state: st.session_state.latest_trace = ["System Status: CLOUD CONNECTED", "Awaiting user input..."]

def get_recommendation_data(shoe_id):
    for rec in st.session_state.recommendations:
        if rec.get("id") == shoe_id: return rec
    return None

with st.sidebar:
    st.title("⚡ Veloxa Concierge")
    st.caption("Cloud RAG Architecture Active")
    st.divider()
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["text"])
    if prompt := st.chat_input("Ask about sizing, colors, or performance..."):
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Querying Pinecone DB..."):
                res = generate_veloxa_ai(prompt, st.session_state.messages[:-1])
                ai_text = res.get("reply", "Error communicating with the Concierge.")
                st.markdown(ai_text)
                st.session_state.recommendations = res.get("recommendations", [])
                st.session_state.latest_trace = res.get("trace_log", ["Trace unavailable."])
        st.session_state.messages.append({"role": "assistant", "text": ai_text})
        st.rerun()

st.markdown("""<div class="hero-container"><div class="hero-title">Defy Gravity.<br>Embrace Speed.</div><div class="hero-subtitle">Powered by Cloud Vector Search.</div></div>""", unsafe_allow_html=True)

terminal_placeholder = st.empty()
trace_html = "<div class='terminal-container'><div class='terminal-header'>🔴 CLOUD TRACE LOG</div>"
for line in st.session_state.latest_trace: trace_html += f"<div class='terminal-line'><span class='terminal-prefix'>&gt;</span> {line}</div>"
trace_html += "</div>"
terminal_placeholder.markdown(trace_html, unsafe_allow_html=True)

sizes = ["US 7", "US 8", "US 9", "US 10", "US 11", "US 12"]

if catalog:
    if st.session_state.selected_shoe:
        shoe = st.session_state.selected_shoe
        st.markdown("---")
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
            
            if valid_img_path: 
                st.image(valid_img_path, use_container_width=True)
            else: 
                st.markdown(f"<div class='image-placeholder'>📸 Image File Missing:<br>{raw_img_filename}</div>", unsafe_allow_html=True)
        
        with c2:
            st.subheader(shoe["model"])
            p_html = f"<span style='font-size:1.4rem;font-weight:bold;'>&#36;{shoe['finalPrice']}</span>"
            if shoe['price'] != shoe['finalPrice']: p_html += f" <span style='text-decoration:line-through;color:#888;margin-left:10px;'>&#36;{shoe['price']}</span>"
            st.markdown(p_html, unsafe_allow_html=True)
            st.write("---")
            st.write("**🎨 Select Color:**")
            color_cols = st.columns(len(shoe["colors_available"]))
            for idx, color_opt in enumerate(shoe["colors_available"]):
                with color_cols[idx]:
                    is_active = (color_opt == display_color)
                    btn_label = f"✅ {color_opt}" if is_active else color_opt
                    if st.button(btn_label, key=f"sel_{color_opt}", use_container_width=True):
                        st.session_state.selected_color = color_opt
                        st.rerun()
            if rec_data:
                st.markdown(f"""<div class="reasoning-panel"><strong>🧠 Cloud Search Match ({rec_data.get('match_percentage', 100)}%)</strong><br>{rec_data.get('reason', '')}<br><em>Recommended Color: {base_recommended_color}</em></div>""", unsafe_allow_html=True)
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
                    
                    if valid_img_path: 
                        st.image(valid_img_path)
                    else: 
                        st.markdown(f"<div class='image-placeholder'>📸 {raw_img_filename}</div>", unsafe_allow_html=True)
                        
                    st.markdown(f"**{shoe['model']}**")
                    if rec_data: st.caption(f"✨ {rec_data.get('reason', '')}")
                    p_html = f"<span style='font-weight:bold;'>&#36;{shoe['finalPrice']}</span>"
                    if shoe["price"] != shoe["finalPrice"]: p_html += f" <span style='text-decoration:line-through;color:#888;font-size:0.8rem;margin-left:8px;'>&#36;{shoe['price']}</span>"
                    st.markdown(p_html, unsafe_allow_html=True)
                    if st.button("View Details & Stock", key=f"v_{shoe['id']}", use_container_width=True):
                        st.session_state.selected_shoe = shoe
                        st.session_state.selected_color = None
                        st.rerun()

st.markdown("""<div class="site-footer" style="text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #eaeaea; color: #666;"><h3>VELOXA</h3><p>&copy; 2026 VELOXA ALP Project.</p></div>""", unsafe_allow_html=True)
