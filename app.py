import streamlit as st
import pandas as pd
import requests
import jwt
import time
import datetime
import re
from collections import defaultdict
import plotly.express as px
import json 

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Focus Analytics Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. CUSTOM CSS (THE BEAUTIFICATION)
# ==========================================
st.markdown("""
<style>
    /* 1. Main Background */
    .stApp {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }

    /* 2. Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #0f172a; 
    }
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] span {
        color: #e2e8f0 !important; 
    }

    /* 3. Metric Cards */
    div[data-testid="stMetric"] {
        background-color: rgba(255, 255, 255, 0.9);
        border: 1px solid #e0e0e0;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
        text-align: center;
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-5px); 
        border-color: #ec008c; 
    }
    div[data-testid="stMetricLabel"] {
        font-size: 14px;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 32px;
        color: #0f172a; 
        font-weight: 800;
    }

    /* 4. Headers */
    h1, h2, h3 {
        font-family: 'Inter', sans-serif;
        color: #1e293B;
    }
    
    /* 5. Custom Button */
    div.stButton > button {
        background: linear-gradient(90deg, #ec008c 0%, #db2777 100%); 
        color: white;
        border: none;
        padding: 12px 28px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 16px;
        width: 100%;
        box-shadow: 0 4px 14px 0 rgba(236, 0, 140, 0.39);
        transition: all 0.2s ease-in-out;
    }
    div.stButton > button:hover {
        transform: scale(1.02);
        box-shadow: 0 6px 20px rgba(236, 0, 140, 0.23);
        color: white;
    }

    /* 6. Table Styling */
    div[data-testid="stDataFrame"] {
        background-color: white;
        padding: 10px;
        border-radius: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    
    /* Error Box Styling */
    .stAlert {
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Regex for filters
UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def generate_jwt(client_id, client_secret):
    payload = {
        "appId": client_id,
        "sub": "bot-auth",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600
    }
    return jwt.encode(payload, client_secret, algorithm="HS256")

def clean_kore_text(raw_text):
    if not raw_text: return ""
    # Handle JSON
    if raw_text.strip().startswith("{"):
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict) and "text" in parsed:
                raw_text = parsed["text"]
            elif "payload" in parsed:
                return f"[Interactive: {parsed.get('type', 'template')}]"
        except: pass
    
    # Strip HTML & Fix Entities
    clean_text = re.sub(r'<[^>]+>', '', raw_text)
    clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
    return clean_text

# ==========================================
# 4. DATA FETCHING (UPDATED ERROR HANDLING)
# ==========================================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
    token = generate_jwt(client_id, client_secret)
    host = "https://de-platform.kore.ai" 
    url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
    headers = { "auth": token, "content-type": "application/json" }
    
    all_messages = []
    skip = 0
    has_more = True
    limit = 100
    
    # Custom Progress UI
    progress_placeholder = st.empty()
    bar = st.progress(0)
    
    page_count = 0
    
    while has_more:
        try:
            payload = {
                "skip": skip,
                "limit": limit,
                "dateFrom": date_from.strftime('%Y-%m-%d'),
                "dateTo": date_to.strftime('%Y-%m-%d'),
                "forward": "false" 
            }
            response = requests.post(url, headers=headers, json=payload)
            
            # --- IMPROVED ERROR HANDLING ---
            if response.status_code != 200:
                st.error(f"🛑 CRITICAL API ERROR on Page {page_count + 1}")
                st.markdown(f"**Status Code:** `{response.status_code} {response.reason}`")
                
                with st.expander("🔍 View Full Error Response (Click to Expand)", expanded=True):
                    try:
                        # Try to pretty print JSON error
                        st.json(response.json())
                    except:
                        # Otherwise print raw text
                        st.code(response.text)
                
                # Stop the spinner
                progress_placeholder.empty()
                bar.empty()
                break # Exit loop, return partial data
            # -------------------------------
                
            data = response.json()
            messages = data.get("messages", [])
            
            page_count += 1
            progress_placeholder.info(f"⏳ Reading page {page_count}... ({len(all_messages)} chats so far)")
            bar.progress(min(page_count * 5, 90))
            
            for msg in messages:
                raw_text = ""
                if msg.get("components") and len(msg["components"]) > 0:
                    raw_text = msg["components"][0].get("data", {}).get("text", "")
                
                final_text = clean_kore_text(raw_text)
                clean_msg_strip = final_text.strip()

                if not final_text: continue
                if UUID_PATTERN.match(clean_msg_strip): continue
                if "@@userdetailspayload@@" in clean_msg_strip: continue

                all_messages.append({
                    "Timestamp": msg.get("createdOn"),
                    "SessionID": msg.get("sessionId", "unknown"),
                    "UserID": msg.get("createdBy", "system"),
                    "Sender": "USER" if msg.get("type") == "incoming" else "BOT",
                    "Message": final_text
                })
            
            has_more = data.get("moreAvailable", False)
            if has_more:
                skip += limit
                time.sleep(0.1)
            else:
                bar.progress(100)
                break
                
        except Exception as e:
            st.error(f"🔌 Connection Error: {e}")
            break
            
    progress_placeholder.empty()
    bar.empty()
    return all_messages

# ==========================================
# 5. PROCESSING
# ==========================================
def process_to_pairs(raw_data):
    sessions = defaultdict(list)
    for msg in raw_data:
        sessions[msg['SessionID']].append(msg)
    
    final_pairs = []

    for session_id, chats in sessions.items():
        chats.sort(key=lambda x: x['Timestamp'])
        current_pair = None
        
        for chat in chats:
            text = chat['Message']
            sender = chat['Sender']
            
            if sender == "USER":
                if current_pair: final_pairs.append(current_pair)
                current_pair = {
                    "Timestamp": chat['Timestamp'],
                    "SessionID": session_id,
                    "UserID": chat['UserID'],
                    "Query": text,
                    "Response": "" 
                }
            elif sender == "BOT":
                if current_pair:
                    if current_pair["Response"]: current_pair["Response"] += " \n " + text
                    else: current_pair["Response"] = text
                else:
                    final_pairs.append({
                        "Timestamp": chat['Timestamp'],
                        "SessionID": session_id,
                        "UserID": chat['UserID'],
                        "Query": "(Bot Initiated / Welcome)",
                        "Response": text
                    })
        
        if current_pair: final_pairs.append(current_pair)

    if final_pairs:
        df = pd.DataFrame(final_pairs)
        df = df[df['Query'] != "(Bot Initiated / Welcome)"]

        if not df.empty:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df = df.sort_values(by='Timestamp', ascending=False)
            return df
            
    return pd.DataFrame()

# ==========================================
# 6. MAIN UI
# ==========================================
def main():
    
    # --- HEADER ---
    c1, c2 = st.columns([1, 6])
    
    with c1:
        st.image("https://upload.wikimedia.org/wikipedia/commons/a/a0/Genpact_logo.svg", width=120)
        
    with c2:
        st.markdown("<h1 style='margin-top: -10px;'>FOCUS ANALYTICS DASHBOARD</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b; margin-top: -15px;'>Real-time insights for Focus 2026 Bot Interactions</p>", unsafe_allow_html=True)

    st.markdown("---")
    
    # --- SIDEBAR ---
    st.sidebar.markdown("### ⚙️ Dashboard Config")
    st.sidebar.info("Select the date range for analysis. Kindly select a range of maximum 7 days.")
    
    try:
        bot_id = st.secrets["BOT_ID"]
        client_id = st.secrets["CLIENT_ID"]
        client_secret = st.secrets["CLIENT_SECRET"]
    except:
        st.sidebar.error("❌ Secrets missing in .streamlit/secrets.toml")
        st.stop()

    today = datetime.date.today()
    start_date = st.sidebar.date_input("Start Date", today - datetime.timedelta(days=7))
    end_date = st.sidebar.date_input("End Date", today + datetime.timedelta(days=1))
    
    st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
    
    with st.sidebar.form("fetch_form"):
        fetch_btn = st.form_submit_button("GENERATE REPORT 🚀")

    # --- MAIN CONTENT ---
    if fetch_btn:
        raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
        if raw_data:
            df = process_to_pairs(raw_data)
            
            if not df.empty:
                # 1. METRICS CARDS
                st.markdown("### 📈 Key Performance Indicators")
                m1, m2, m3, m4 = st.columns(4)
                
                m1.metric("Total Queries", len(df))
                m2.metric("Unique Users", df['UserID'].nunique())
                m3.metric("Sessions", df['SessionID'].nunique())
                
                responded = df[df['Response'] != ""].shape[0]
                resp_rate = round((responded / len(df)) * 100, 1)
                m4.metric("Response Rate", f"{resp_rate}%")
                
                st.markdown("<br>", unsafe_allow_html=True) 

                # 2. CHARTS AREA
                c1, c2 = st.columns(2)
                
                with c1:
                    st.markdown("<div style='background:white; padding:15px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1)'>", unsafe_allow_html=True)
                    st.markdown("#### 📊 Activity Volume")
                    df['Date'] = df['Timestamp'].dt.date
                    daily_counts = df.groupby('Date').size().reset_index(name='Count')
                    
                    fig_activity = px.bar(
                        daily_counts, x='Date', y='Count',
                        color_discrete_sequence=['#005A9C'] 
                    )
                    fig_activity.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", 
                        plot_bgcolor="rgba(0,0,0,0)",
                        xaxis_title="", yaxis_title="Queries",
                        margin=dict(l=20, r=20, t=30, b=20)
                    )
                    st.plotly_chart(fig_activity, use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                with c2:
                    st.markdown("<div style='background:white; padding:15px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1)'>", unsafe_allow_html=True)
                    st.markdown("#### 🔥 Top 5 Topics")
                    top_questions = df['Query'].value_counts().head(5).reset_index()
                    top_questions.columns = ['Question', 'Count']
                    
                    fig_top = px.bar(
                        top_questions, x='Count', y='Question', 
                        orientation='h', text='Count',
                        color_discrete_sequence=['#EC008C'] 
                    )
                    fig_top.update_layout(
                        yaxis=dict(autorange="reversed"),
                        paper_bgcolor="rgba(0,0,0,0)", 
                        plot_bgcolor="rgba(0,0,0,0)",
                        xaxis_title="Frequency", yaxis_title="",
                        margin=dict(l=20, r=20, t=30, b=20)
                    )
                    st.plotly_chart(fig_top, use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)

                # 3. DATA TABLE
                st.markdown("### 🗂 Detailed Conversation Logs")
                
                st.dataframe(
                    df[['Timestamp', 'UserID', 'Query', 'Response']],
                    use_container_width=True,
                    column_config={
                        "Timestamp": st.column_config.DatetimeColumn("Time", format="D MMM, HH:mm"),
                        "Query": st.column_config.TextColumn("User Asked", width="medium"),
                        "Response": st.column_config.TextColumn("Bot Replied", width="large"),
                    },
                    height=400
                )
                
                # 4. DOWNLOAD
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 Download Clean CSV",
                    data=csv,
                    file_name=f"Focus_Report_{start_date}_{end_date}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("⚠️ Data fetched, but all messages were filtered out (Welcome messages hidden).")
        else:
            st.info("ℹ️ No messages found in the selected date range.")

    else:
        st.markdown("""
        <div style="background-color: white; padding: 40px; border-radius: 15px; text-align: center; border: 1px dashed #cbd5e1; margin-top: 20px;">
            <h3 style="color: #64748b;">Ready to Analyze</h3>
            <p style="color: #94a3b8;">Select a date range in the sidebar and click <b>GENERATE REPORT</b> to begin.</p>
        </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
    


# import streamlit as st
# import pandas as pd
# import requests
# import jwt
# import time
# import datetime
# import re
# from collections import defaultdict
# import plotly.express as px
# import json 

# # ==========================================
# # 1. PAGE CONFIGURATION
# # ==========================================
# st.set_page_config(
#     page_title="Focus Analytics Dashboard",
#     page_icon="📈",
#     layout="wide",
#     initial_sidebar_state="expanded"
# )

# # ==========================================
# # 2. CUSTOM CSS (THE BEAUTIFICATION)
# # ==========================================
# st.markdown("""
# <style>
#     /* 1. Main Background - Subtle Professional Gradient */
#     .stApp {
#         background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
#     }

#     /* 2. Sidebar Styling */
#     section[data-testid="stSidebar"] {
#         background-color: #0f172a; /* Dark Navy Sidebar */
#     }
#     section[data-testid="stSidebar"] h1, 
#     section[data-testid="stSidebar"] label, 
#     section[data-testid="stSidebar"] span {
#         color: #e2e8f0 !important; /* Light text for sidebar */
#     }

#     /* 3. Metric Cards - "Glassmorphism" Look */
#     div[data-testid="stMetric"] {
#         background-color: rgba(255, 255, 255, 0.9);
#         border: 1px solid #e0e0e0;
#         padding: 20px;
#         border-radius: 12px;
#         box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
#         text-align: center;
#         transition: transform 0.2s ease-in-out;
#     }
#     div[data-testid="stMetric"]:hover {
#         transform: translateY(-5px); /* Lift effect on hover */
#         border-color: #ec008c; /* Genpact Pink/Magenta accent */
#     }
#     div[data-testid="stMetricLabel"] {
#         font-size: 14px;
#         color: #64748b;
#         font-weight: 600;
#         text-transform: uppercase;
#         letter-spacing: 0.5px;
#     }
#     div[data-testid="stMetricValue"] {
#         font-size: 32px;
#         color: #0f172a; /* Dark Text */
#         font-weight: 800;
#     }

#     /* 4. Headers & Text */
#     h1, h2, h3 {
#         font-family: 'Inter', sans-serif;
#         color: #1e293b;
#     }
    
#     /* 5. Custom Button */
#     div.stButton > button {
#         background: linear-gradient(90deg, #ec008c 0%, #db2777 100%); /* Genpact-ish Pink Gradient */
#         color: white;
#         border: none;
#         padding: 12px 28px;
#         border-radius: 8px;
#         font-weight: 700;
#         font-size: 16px;
#         width: 100%;
#         box-shadow: 0 4px 14px 0 rgba(236, 0, 140, 0.39);
#         transition: all 0.2s ease-in-out;
#     }
#     div.stButton > button:hover {
#         transform: scale(1.02);
#         box-shadow: 0 6px 20px rgba(236, 0, 140, 0.23);
#         color: white;
#     }

#     /* 6. Table Styling */
#     div[data-testid="stDataFrame"] {
#         background-color: white;
#         padding: 10px;
#         border-radius: 10px;
#         box-shadow: 0 1px 3px rgba(0,0,0,0.1);
#     }
# </style>
# """, unsafe_allow_html=True)

# # Regex for filters
# UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# # ==========================================
# # 3. HELPER FUNCTIONS
# # ==========================================
# def generate_jwt(client_id, client_secret):
#     payload = {
#         "appId": client_id,
#         "sub": "bot-auth",
#         "iat": int(time.time()),
#         "exp": int(time.time()) + 3600
#     }
#     return jwt.encode(payload, client_secret, algorithm="HS256")

# def clean_kore_text(raw_text):
#     if not raw_text: return ""
#     # Handle JSON
#     if raw_text.strip().startswith("{"):
#         try:
#             parsed = json.loads(raw_text)
#             if isinstance(parsed, dict) and "text" in parsed:
#                 raw_text = parsed["text"]
#             elif "payload" in parsed:
#                 return f"[Interactive: {parsed.get('type', 'template')}]"
#         except: pass
    
#     # Strip HTML & Fix Entities
#     clean_text = re.sub(r'<[^>]+>', '', raw_text)
#     clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
#     return clean_text

# # ==========================================
# # 4. DATA FETCHING
# # ==========================================
# @st.cache_data(ttl=300, show_spinner=False)
# def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
#     token = generate_jwt(client_id, client_secret)
#     host = "https://de-platform.kore.ai" 
#     url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
#     headers = { "auth": token, "content-type": "application/json" }
    
#     all_messages = []
#     skip = 0
#     has_more = True
#     limit = 100
    
#     # Custom Progress UI
#     progress_placeholder = st.empty()
#     bar = st.progress(0)
    
#     page_count = 0
    
#     while has_more:
#         try:
#             payload = {
#                 "skip": skip,
#                 "limit": limit,
#                 "dateFrom": date_from.strftime('%Y-%m-%d'),
#                 "dateTo": date_to.strftime('%Y-%m-%d'),
#                 "forward": "false" 
#             }
#             response = requests.post(url, headers=headers, json=payload)
            
#             if response.status_code != 200:
#                 st.error(f"API Error: {response.text}")
#                 break
                
#             data = response.json()
#             messages = data.get("messages", [])
            
#             page_count += 1
#             progress_placeholder.info(f"⏳ Reading page {page_count}... ({len(all_messages)} chats so far)")
#             bar.progress(min(page_count * 5, 90))
            
#             for msg in messages:
#                 raw_text = ""
#                 if msg.get("components") and len(msg["components"]) > 0:
#                     raw_text = msg["components"][0].get("data", {}).get("text", "")
                
#                 final_text = clean_kore_text(raw_text)
#                 clean_msg_strip = final_text.strip()

#                 if not final_text: continue
#                 if UUID_PATTERN.match(clean_msg_strip): continue
#                 if "@@userdetailspayload@@" in clean_msg_strip: continue

#                 all_messages.append({
#                     "Timestamp": msg.get("createdOn"),
#                     "SessionID": msg.get("sessionId", "unknown"),
#                     "UserID": msg.get("createdBy", "system"),
#                     "Sender": "USER" if msg.get("type") == "incoming" else "BOT",
#                     "Message": final_text
#                 })
            
#             has_more = data.get("moreAvailable", False)
#             if has_more:
#                 skip += limit
#                 time.sleep(0.1)
#             else:
#                 bar.progress(100)
#                 break
                
#         except Exception as e:
#             st.error(f"Connection Error: {e}")
#             break
            
#     progress_placeholder.empty()
#     bar.empty()
#     return all_messages

# # ==========================================
# # 5. PROCESSING
# # ==========================================
# def process_to_pairs(raw_data):
#     sessions = defaultdict(list)
#     for msg in raw_data:
#         sessions[msg['SessionID']].append(msg)
    
#     final_pairs = []

#     for session_id, chats in sessions.items():
#         chats.sort(key=lambda x: x['Timestamp'])
#         current_pair = None
        
#         for chat in chats:
#             text = chat['Message']
#             sender = chat['Sender']
            
#             if sender == "USER":
#                 if current_pair: final_pairs.append(current_pair)
#                 current_pair = {
#                     "Timestamp": chat['Timestamp'],
#                     "SessionID": session_id,
#                     "UserID": chat['UserID'],
#                     "Query": text,
#                     "Response": "" 
#                 }
#             elif sender == "BOT":
#                 if current_pair:
#                     if current_pair["Response"]: current_pair["Response"] += " \n " + text
#                     else: current_pair["Response"] = text
#                 else:
#                     final_pairs.append({
#                         "Timestamp": chat['Timestamp'],
#                         "SessionID": session_id,
#                         "UserID": chat['UserID'],
#                         "Query": "(Bot Initiated / Welcome)",
#                         "Response": text
#                     })
        
#         if current_pair: final_pairs.append(current_pair)

#     if final_pairs:
#         df = pd.DataFrame(final_pairs)
#         # Filter Welcome
#         df = df[df['Query'] != "(Bot Initiated / Welcome)"]

#         if not df.empty:
#             df['Timestamp'] = pd.to_datetime(df['Timestamp'])
#             df = df.sort_values(by='Timestamp', ascending=False)
#             return df
            
#     return pd.DataFrame()

# # ==========================================
# # 6. MAIN UI
# # ==========================================
# def main():
    
#     # --- HEADER SECTION ---
#     c1, c2 = st.columns([1, 6])
    
#     with c1:
#         # Genpact Logo (Public URL or Placeholder)
#         # Using a clean public logo. If this link breaks, you can use a local file path.
#         st.image("https://upload.wikimedia.org/wikipedia/commons/a/a0/Genpact_logo.svg", width=120)
        
#     with c2:
#         st.markdown("<h1 style='margin-top: -10px;'>FOCUS ANALYTICS DASHBOARD</h1>", unsafe_allow_html=True)
#         st.markdown("<p style='color: #64748b; margin-top: -15px;'>Real-time insights for Focus 2026 Bot Interactions</p>", unsafe_allow_html=True)

#     st.markdown("---")
    
#     # --- SIDEBAR ---
#     st.sidebar.markdown("### ⚙️ Dashboard Config")
#     st.sidebar.info("Select the date range for analysis.")
    
#     try:
#         bot_id = st.secrets["BOT_ID"]
#         client_id = st.secrets["CLIENT_ID"]
#         client_secret = st.secrets["CLIENT_SECRET"]
#     except:
#         st.sidebar.error("❌ Secrets missing in .streamlit/secrets.toml")
#         st.stop()

#     today = datetime.date.today()
#     start_date = st.sidebar.date_input("Start Date", today - datetime.timedelta(days=7))
#     end_date = st.sidebar.date_input("End Date", today + datetime.timedelta(days=1))
    
#     # Spacer
#     st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
    
#     # Using a form to prevent reload on every date change
#     with st.sidebar.form("fetch_form"):
#         fetch_btn = st.form_submit_button("GENERATE REPORT 🚀")

#     # --- MAIN CONTENT ---
#     if fetch_btn:
#         raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
#         if raw_data:
#             df = process_to_pairs(raw_data)
            
#             if not df.empty:
#                 # 1. METRICS CARDS
#                 st.markdown("### 📈 Key Performance Indicators")
#                 m1, m2, m3, m4 = st.columns(4)
                
#                 m1.metric("Total Queries", len(df))
#                 m2.metric("Unique Users", df['UserID'].nunique())
#                 m3.metric("Sessions", df['SessionID'].nunique())
                
#                 # Calculate Response Rate (Simple estimation: rows with response text)
#                 responded = df[df['Response'] != ""].shape[0]
#                 resp_rate = round((responded / len(df)) * 100, 1)
#                 m4.metric("Response Rate", f"{resp_rate}%")
                
#                 st.markdown("<br>", unsafe_allow_html=True) 

#                 # 2. CHARTS AREA (Beautified Plotly)
#                 c1, c2 = st.columns(2)
                
#                 with c1:
#                     # Card-like container for chart
#                     st.markdown("<div style='background:white; padding:15px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1)'>", unsafe_allow_html=True)
#                     st.markdown("#### 📊 Activity Volume")
#                     df['Date'] = df['Timestamp'].dt.date
#                     daily_counts = df.groupby('Date').size().reset_index(name='Count')
                    
#                     fig_activity = px.bar(
#                         daily_counts, x='Date', y='Count',
#                         # Clean Blue Color
#                         color_discrete_sequence=['#005A9C'] 
#                     )
#                     fig_activity.update_layout(
#                         paper_bgcolor="rgba(0,0,0,0)", 
#                         plot_bgcolor="rgba(0,0,0,0)",
#                         xaxis_title="", yaxis_title="Queries",
#                         margin=dict(l=20, r=20, t=30, b=20)
#                     )
#                     st.plotly_chart(fig_activity, use_container_width=True)
#                     st.markdown("</div>", unsafe_allow_html=True)

#                 with c2:
#                     st.markdown("<div style='background:white; padding:15px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1)'>", unsafe_allow_html=True)
#                     st.markdown("#### 🔥 Top 5 Topics")
#                     top_questions = df['Query'].value_counts().head(5).reset_index()
#                     top_questions.columns = ['Question', 'Count']
                    
#                     fig_top = px.bar(
#                         top_questions, x='Count', y='Question', 
#                         orientation='h', text='Count',
#                         # Magenta Color for contrast
#                         color_discrete_sequence=['#EC008C'] 
#                     )
#                     fig_top.update_layout(
#                         yaxis=dict(autorange="reversed"),
#                         paper_bgcolor="rgba(0,0,0,0)", 
#                         plot_bgcolor="rgba(0,0,0,0)",
#                         xaxis_title="Frequency", yaxis_title="",
#                         margin=dict(l=20, r=20, t=30, b=20)
#                     )
#                     st.plotly_chart(fig_top, use_container_width=True)
#                     st.markdown("</div>", unsafe_allow_html=True)

#                 st.markdown("<br>", unsafe_allow_html=True)

#                 # 3. DATA TABLE
#                 st.markdown("### 🗂 Detailed Conversation Logs")
                
#                 # Configure columns for better readability
#                 st.dataframe(
#                     df[['Timestamp', 'UserID', 'Query', 'Response']],
#                     use_container_width=True,
#                     column_config={
#                         "Timestamp": st.column_config.DatetimeColumn("Time", format="D MMM, HH:mm"),
#                         "Query": st.column_config.TextColumn("User Asked", width="medium"),
#                         "Response": st.column_config.TextColumn("Bot Replied", width="large"),
#                     },
#                     height=400
#                 )
                
#                 # 4. DOWNLOAD
#                 csv = df.to_csv(index=False).encode('utf-8-sig')
#                 st.download_button(
#                     label="📥 Download Clean CSV",
#                     data=csv,
#                     file_name=f"Focus_Report_{start_date}_{end_date}.csv",
#                     mime="text/csv"
#                 )
#             else:
#                 st.warning("⚠️ Data fetched, but all messages were filtered out (Welcome messages hidden).")
#         else:
#             st.info("ℹ️ No messages found in the selected date range.")

#     else:
#         # Placeholder content on first load
#         st.markdown("""
#         <div style="background-color: white; padding: 40px; border-radius: 15px; text-align: center; border: 1px dashed #cbd5e1; margin-top: 20px;">
#             <h3 style="color: #64748b;">Ready to Analyze</h3>
#             <p style="color: #94a3b8;">Select a date range in the sidebar and click <b>GENERATE REPORT</b> to begin.</p>
#         </div>
#         """, unsafe_allow_html=True)

# if __name__ == "__main__":
#     main()
    























# # import streamlit as st
# # import pandas as pd
# # import requests
# # import jwt
# # import time
# # import datetime
# # import re
# # from collections import defaultdict
# # import plotly.express as px
# # import json 

# # # ==========================================
# # # 1. PAGE & VISUAL CONFIGURATION
# # # ==========================================
# # st.set_page_config(
# #     page_title="Kore.ai Analytics",
# #     page_icon="📊",
# #     layout="wide",
# #     initial_sidebar_state="expanded"
# # )

# # # Custom CSS to "Beautify" the app
# # st.markdown("""
# # <style>
# #     /* Main Background adjustments */
# #     .block-container {
# #         padding-top: 2rem;
# #         padding-bottom: 2rem;
# #     }
    
# #     /* CARD STYLE: For Metrics */
# #     div[data-testid="metric-container"] {
# #         background-color: #ffffff; /* White Card */
# #         border: 1px solid #e0e0e0;
# #         padding: 15px 20px;
# #         border-radius: 10px;
# #         box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
# #         text-align: center;
# #         transition: transform 0.2s;
# #     }
# #     div[data-testid="metric-container"]:hover {
# #         transform: scale(1.02);
# #         border-color: #4F8BF9;
# #     }
    
# #     /* Text Coloring for Metrics */
# #     div[data-testid="stMetricValue"] {
# #         font-size: 28px;
# #         font-weight: 700;
# #         color: #4F8BF9; /* Brand Blue */
# #     }
# #     div[data-testid="stMetricLabel"] {
# #         font-size: 14px;
# #         color: #666;
# #     }

# #     /* Sidebar Styling */
# #     section[data-testid="stSidebar"] {
# #         background-color: #F7F9FC;
# #     }
    
# #     /* Header Styling */
# #     h1 {
# #         font-family: 'Helvetica Neue', sans-serif;
# #         font-weight: 700;
# #         color: #1E293B;
# #     }
# #     h3 {
# #         color: #334155;
# #         font-weight: 600;
# #     }
    
# #     /* Button Styling */
# #     div.stButton > button {
# #         background-color: #4F8BF9;
# #         color: white;
# #         border-radius: 8px;
# #         border: none;
# #         padding: 10px 24px;
# #         font-weight: bold;
# #         width: 100%;
# #     }
# #     div.stButton > button:hover {
# #         background-color: #2c6cd6;
# #         color: white;
# #         border-color: #2c6cd6;
# #     }
# # </style>
# # """, unsafe_allow_html=True)

# # # Regex for filters
# # UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# # # ==========================================
# # # 2. HELPER FUNCTIONS (Logic unchanged)
# # # ==========================================
# # def generate_jwt(client_id, client_secret):
# #     payload = {
# #         "appId": client_id,
# #         "sub": "bot-auth",
# #         "iat": int(time.time()),
# #         "exp": int(time.time()) + 3600
# #     }
# #     return jwt.encode(payload, client_secret, algorithm="HS256")

# # def clean_kore_text(raw_text):
# #     if not raw_text: return ""
# #     # Handle JSON
# #     if raw_text.strip().startswith("{"):
# #         try:
# #             parsed = json.loads(raw_text)
# #             if isinstance(parsed, dict) and "text" in parsed:
# #                 raw_text = parsed["text"]
# #             elif "payload" in parsed:
# #                 return f"[Interactive: {parsed.get('type', 'template')}]"
# #         except: pass
    
# #     # Strip HTML & Fix Entities
# #     clean_text = re.sub(r'<[^>]+>', '', raw_text)
# #     clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
# #     return clean_text

# # # ==========================================
# # # 3. DATA FETCHING
# # # ==========================================
# # @st.cache_data(ttl=300, show_spinner=False)
# # def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
# #     token = generate_jwt(client_id, client_secret)
# #     host = "https://de-platform.kore.ai" 
# #     url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
# #     headers = { "auth": token, "content-type": "application/json" }
    
# #     all_messages = []
# #     skip = 0
# #     has_more = True
# #     limit = 100
    
# #     # Custom Progress UI
# #     progress_placeholder = st.empty()
# #     bar = st.progress(0)
    
# #     page_count = 0
    
# #     while has_more:
# #         try:
# #             payload = {
# #                 "skip": skip,
# #                 "limit": limit,
# #                 "dateFrom": date_from.strftime('%Y-%m-%d'),
# #                 "dateTo": date_to.strftime('%Y-%m-%d'),
# #                 "forward": "false" 
# #             }
# #             response = requests.post(url, headers=headers, json=payload)
            
# #             if response.status_code != 200:
# #                 st.error(f"API Error: {response.text}")
# #                 break
                
# #             data = response.json()
# #             messages = data.get("messages", [])
            
# #             page_count += 1
# #             progress_placeholder.info(f"⏳ Reading page {page_count}... ({len(all_messages)} chats so far)")
# #             bar.progress(min(page_count * 5, 90))
            
# #             for msg in messages:
# #                 raw_text = ""
# #                 if msg.get("components") and len(msg["components"]) > 0:
# #                     raw_text = msg["components"][0].get("data", {}).get("text", "")
                
# #                 final_text = clean_kore_text(raw_text)
# #                 clean_msg_strip = final_text.strip()

# #                 if not final_text: continue
# #                 if UUID_PATTERN.match(clean_msg_strip): continue
# #                 if "@@userdetailspayload@@" in clean_msg_strip: continue

# #                 all_messages.append({
# #                     "Timestamp": msg.get("createdOn"),
# #                     "SessionID": msg.get("sessionId", "unknown"),
# #                     "UserID": msg.get("createdBy", "system"),
# #                     "Sender": "USER" if msg.get("type") == "incoming" else "BOT",
# #                     "Message": final_text
# #                 })
            
# #             has_more = data.get("moreAvailable", False)
# #             if has_more:
# #                 skip += limit
# #                 time.sleep(0.1)
# #             else:
# #                 bar.progress(100)
# #                 break
                
# #         except Exception as e:
# #             st.error(f"Connection Error: {e}")
# #             break
            
# #     progress_placeholder.empty()
# #     bar.empty()
# #     return all_messages

# # # ==========================================
# # # 4. PROCESSING
# # # ==========================================
# # def process_to_pairs(raw_data):
# #     sessions = defaultdict(list)
# #     for msg in raw_data:
# #         sessions[msg['SessionID']].append(msg)
    
# #     final_pairs = []

# #     for session_id, chats in sessions.items():
# #         chats.sort(key=lambda x: x['Timestamp'])
# #         current_pair = None
        
# #         for chat in chats:
# #             text = chat['Message']
# #             sender = chat['Sender']
            
# #             if sender == "USER":
# #                 if current_pair: final_pairs.append(current_pair)
# #                 current_pair = {
# #                     "Timestamp": chat['Timestamp'],
# #                     "SessionID": session_id,
# #                     "UserID": chat['UserID'],
# #                     "Query": text,
# #                     "Response": "" 
# #                 }
# #             elif sender == "BOT":
# #                 if current_pair:
# #                     if current_pair["Response"]: current_pair["Response"] += " \n " + text
# #                     else: current_pair["Response"] = text
# #                 else:
# #                     final_pairs.append({
# #                         "Timestamp": chat['Timestamp'],
# #                         "SessionID": session_id,
# #                         "UserID": chat['UserID'],
# #                         "Query": "(Bot Initiated / Welcome)",
# #                         "Response": text
# #                     })
        
# #         if current_pair: final_pairs.append(current_pair)

# #     if final_pairs:
# #         df = pd.DataFrame(final_pairs)
# #         # Filter Welcome
# #         df = df[df['Query'] != "(Bot Initiated / Welcome)"]

# #         if not df.empty:
# #             df['Timestamp'] = pd.to_datetime(df['Timestamp'])
# #             df = df.sort_values(by='Timestamp', ascending=False)
# #             return df
            
# #     return pd.DataFrame()

# # # ==========================================
# # # 5. MAIN UI
# # # ==========================================
# # def main():
# #     # --- HEADER ---
# #     col_logo, col_title = st.columns([1, 10])
# #     with col_logo:
# #         st.markdown("## 🤖")
# #     with col_title:
# #         st.markdown("# Conversation Analytics Dashboard")
# #         st.markdown("View bot performance, analyze top queries, and export clean data.")

# #     st.markdown("---")
    
# #     # --- SIDEBAR ---
# #     st.sidebar.title("Configuration")
# #     st.sidebar.info("Select a date range to fetch chat history.")
    
# #     try:
# #         bot_id = st.secrets["BOT_ID"]
# #         client_id = st.secrets["CLIENT_ID"]
# #         client_secret = st.secrets["CLIENT_SECRET"]
# #     except:
# #         st.sidebar.error("Secrets missing in .streamlit/secrets.toml")
# #         st.stop()

# #     today = datetime.date.today()
# #     start_date = st.sidebar.date_input("Start Date", today - datetime.timedelta(days=7))
# #     end_date = st.sidebar.date_input("End Date", today + datetime.timedelta(days=1))
    
# #     # Using a form to prevent reload on every date change
# #     with st.sidebar.form("fetch_form"):
# #         fetch_btn = st.form_submit_button("Fetch Data 🚀")

# #     # --- MAIN CONTENT ---
# #     if fetch_btn:
# #         raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
# #         if raw_data:
# #             df = process_to_pairs(raw_data)
            
# #             if not df.empty:
# #                 # 1. METRICS CARDS
# #                 m1, m2, m3 = st.columns(3)
# #                 m1.metric("Total Interactions", len(df), delta="Queries")
# #                 m2.metric("Unique Users", df['UserID'].nunique(), delta="People")
# #                 m3.metric("Total Sessions", df['SessionID'].nunique(), delta="Conversations")
                
# #                 st.markdown("<br>", unsafe_allow_html=True) # Spacer

# #                 # 2. CHARTS AREA
# #                 c1, c2 = st.columns(2)
                
# #                 with c1:
# #                     st.subheader("📊 Activity Trend")
# #                     df['Date'] = df['Timestamp'].dt.date
# #                     daily_counts = df.groupby('Date').size().reset_index(name='Count')
                    
# #                     fig_activity = px.bar(
# #                         daily_counts, x='Date', y='Count',
# #                         color='Count', color_continuous_scale='Bluyl' # Beautiful Blue-Yellow gradient
# #                     )
# #                     fig_activity.update_layout(
# #                         paper_bgcolor="rgba(0,0,0,0)", 
# #                         plot_bgcolor="rgba(0,0,0,0)",
# #                         xaxis_title="", yaxis_title="Queries"
# #                     )
# #                     st.plotly_chart(fig_activity, use_container_width=True)

# #                 with c2:
# #                     st.subheader("🔥 Top 5 Questions")
# #                     top_questions = df['Query'].value_counts().head(5).reset_index()
# #                     top_questions.columns = ['Question', 'Count']
                    
# #                     fig_top = px.bar(
# #                         top_questions, x='Count', y='Question', 
# #                         orientation='h', text='Count',
# #                         color='Count', color_continuous_scale='Purples' # Beautiful Purple gradient
# #                     )
# #                     fig_top.update_layout(
# #                         yaxis=dict(autorange="reversed"),
# #                         paper_bgcolor="rgba(0,0,0,0)", 
# #                         plot_bgcolor="rgba(0,0,0,0)",
# #                         xaxis_title="Frequency", yaxis_title=""
# #                     )
# #                     st.plotly_chart(fig_top, use_container_width=True)

# #                 st.markdown("---")

# #                 # 3. DATA TABLE
# #                 st.subheader("🗂 Detailed Interaction Logs")
                
# #                 # Configure columns for better readability
# #                 st.dataframe(
# #                     df[['Timestamp', 'UserID', 'Query', 'Response']],
# #                     use_container_width=True,
# #                     column_config={
# #                         "Timestamp": st.column_config.DatetimeColumn("Time", format="D MMM, HH:mm"),
# #                         "Query": st.column_config.TextColumn("User Asked", width="medium"),
# #                         "Response": st.column_config.TextColumn("Bot Replied", width="large"),
# #                     },
# #                     height=400
# #                 )
                
# #                 # 4. DOWNLOAD
# #                 csv = df.to_csv(index=False).encode('utf-8-sig')
# #                 st.download_button(
# #                     label="📥 Download Clean CSV",
# #                     data=csv,
# #                     file_name=f"chat_history_{start_date}_{end_date}.csv",
# #                     mime="text/csv"
# #                 )
# #             else:
# #                 st.warning("⚠️ Data fetched, but all messages were filtered out (Welcome messages hidden).")
# #         else:
# #             st.info("ℹ️ No messages found in the selected date range.")

# #     else:
# #         # Placeholder content on first load
# #         st.markdown("""
# #         <div style="background-color: #F0F2F6; padding: 20px; border-radius: 10px; text-align: center; color: #666;">
# #             Select a date range in the sidebar and click <b>Fetch Data</b> to begin.
# #         </div>
# #         """, unsafe_allow_html=True)

# # if __name__ == "__main__":
# #     main()
    

# # # import streamlit as st
# # # import pandas as pd
# # # import requests
# # # import jwt
# # # import time
# # # import datetime
# # # import re
# # # from collections import defaultdict
# # # import plotly.express as px
# # # import json 

# # # # ==========================================
# # # # 1. APP CONFIG & SECRETS
# # # # ==========================================
# # # st.set_page_config(page_title="Kore.ai Chat History", layout="wide")

# # # # Regex for filters
# # # UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# # # # ==========================================
# # # # 2. HELPER FUNCTIONS
# # # # ==========================================
# # # def generate_jwt(client_id, client_secret):
# # #     payload = {
# # #         "appId": client_id,
# # #         "sub": "bot-auth",
# # #         "iat": int(time.time()),
# # #         "exp": int(time.time()) + 3600
# # #     }
# # #     return jwt.encode(payload, client_secret, algorithm="HS256")

# # # def clean_kore_text(raw_text):
# # #     if not raw_text: return ""
    
# # #     # Handle JSON
# # #     if raw_text.strip().startswith("{"):
# # #         try:
# # #             parsed = json.loads(raw_text)
# # #             if isinstance(parsed, dict) and "text" in parsed:
# # #                 raw_text = parsed["text"]
# # #             elif "payload" in parsed:
# # #                 return f"[Interactive Element: {parsed.get('type', 'template')}]"
# # #         except: pass
    
# # #     # Strip HTML
# # #     clean_text = re.sub(r'<[^>]+>', '', raw_text)
# # #     # Fix Entities
# # #     clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
# # #     return clean_text

# # # # ==========================================
# # # # 3. DATA FETCHING (Cached)
# # # # ==========================================
# # # @st.cache_data(ttl=300) 
# # # def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
# # #     token = generate_jwt(client_id, client_secret)
# # #     host = "https://de-platform.kore.ai" 
# # #     url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
# # #     headers = { "auth": token, "content-type": "application/json" }
    
# # #     all_messages = []
# # #     skip = 0
# # #     has_more = True
# # #     limit = 100
    
# # #     # Progress bar in UI
# # #     progress_bar = st.progress(0)
# # #     status_text = st.empty()
    
# # #     page_count = 0
    
# # #     while has_more:
# # #         try:
# # #             payload = {
# # #                 "skip": skip,
# # #                 "limit": limit,
# # #                 "dateFrom": date_from.strftime('%Y-%m-%d'),
# # #                 "dateTo": date_to.strftime('%Y-%m-%d'),
# # #                 "forward": "false" 
# # #             }
# # #             response = requests.post(url, headers=headers, json=payload)
            
# # #             if response.status_code != 200:
# # #                 st.error(f"API Error: {response.text}")
# # #                 break
                
# # #             data = response.json()
# # #             messages = data.get("messages", [])
            
# # #             # Status Update
# # #             page_count += 1
# # #             status_text.text(f"Fetching page {page_count}... ({len(all_messages)} messages found)")
# # #             progress_bar.progress(min(page_count * 5, 90)) 
            
# # #             for msg in messages:
# # #                 raw_text = ""
# # #                 if msg.get("components") and len(msg["components"]) > 0:
# # #                     raw_text = msg["components"][0].get("data", {}).get("text", "")
                
# # #                 final_text = clean_kore_text(raw_text)
# # #                 clean_msg_strip = final_text.strip()

# # #                 if not final_text: continue
# # #                 if UUID_PATTERN.match(clean_msg_strip): continue
# # #                 if "@@userdetailspayload@@" in clean_msg_strip: continue

# # #                 all_messages.append({
# # #                     "Timestamp": msg.get("createdOn"),
# # #                     "SessionID": msg.get("sessionId", "unknown"),
# # #                     "UserID": msg.get("createdBy", "system"),
# # #                     "Sender": "USER" if msg.get("type") == "incoming" else "BOT",
# # #                     "Message": final_text
# # #                 })
            
# # #             has_more = data.get("moreAvailable", False)
# # #             if has_more:
# # #                 skip += limit
# # #                 time.sleep(0.1)
# # #             else:
# # #                 progress_bar.progress(100)
# # #                 break
                
# # #         except Exception as e:
# # #             st.error(f"Connection Error: {e}")
# # #             break
            
# # #     status_text.empty()
# # #     progress_bar.empty()
# # #     return all_messages

# # # # ==========================================
# # # # 4. DATA PROCESSING
# # # # ==========================================
# # # def process_to_pairs(raw_data):
# # #     sessions = defaultdict(list)
# # #     for msg in raw_data:
# # #         sessions[msg['SessionID']].append(msg)
    
# # #     final_pairs = []

# # #     for session_id, chats in sessions.items():
# # #         chats.sort(key=lambda x: x['Timestamp'])
# # #         current_pair = None
        
# # #         for chat in chats:
# # #             text = chat['Message']
# # #             sender = chat['Sender']
            
# # #             if sender == "USER":
# # #                 if current_pair: final_pairs.append(current_pair)
# # #                 current_pair = {
# # #                     "Timestamp": chat['Timestamp'],
# # #                     "SessionID": session_id,
# # #                     "UserID": chat['UserID'],
# # #                     "Query": text,
# # #                     "Response": "" 
# # #                 }
# # #             elif sender == "BOT":
# # #                 if current_pair:
# # #                     if current_pair["Response"]: current_pair["Response"] += " \n " + text
# # #                     else: current_pair["Response"] = text
# # #                 else:
# # #                     final_pairs.append({
# # #                         "Timestamp": chat['Timestamp'],
# # #                         "SessionID": session_id,
# # #                         "UserID": chat['UserID'],
# # #                         "Query": "(Bot Initiated / Welcome)",
# # #                         "Response": text
# # #                     })
        
# # #         if current_pair: final_pairs.append(current_pair)

# # #     if final_pairs:
# # #         df = pd.DataFrame(final_pairs)
        
# # #         # Filter out Welcome Messages
# # #         df = df[df['Query'] != "(Bot Initiated / Welcome)"]

# # #         if not df.empty:
# # #             df['Timestamp'] = pd.to_datetime(df['Timestamp'])
# # #             df = df.sort_values(by='Timestamp', ascending=False)
# # #             return df
            
# # #     return pd.DataFrame()

# # # # ==========================================
# # # # 5. MAIN UI
# # # # ==========================================
# # # def main():
# # #     st.title("🤖 Kore.ai Chat Analytics Dashboard")
    
# # #     # --- Sidebar ---
# # #     st.sidebar.header("Configuration")
    
# # #     try:
# # #         bot_id = st.secrets["BOT_ID"]
# # #         client_id = st.secrets["CLIENT_ID"]
# # #         client_secret = st.secrets["CLIENT_SECRET"]
# # #     except:
# # #         st.sidebar.error("Secrets not found! Please check .streamlit/secrets.toml")
# # #         st.stop()

# # #     today = datetime.date.today()
# # #     col1, col2 = st.sidebar.columns(2)
# # #     start_date = col1.date_input("Start Date", today - datetime.timedelta(days=3))
# # #     end_date = col2.date_input("End Date", today + datetime.timedelta(days=1)) 

# # #     if st.sidebar.button("Fetch Data"):
# # #         raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
# # #         if raw_data:
# # #             df = process_to_pairs(raw_data)
            
# # #             if not df.empty:
# # #                 # --- Metrics Row ---
# # #                 m1, m2, m3 = st.columns(3)
# # #                 m1.metric("Total Interactions", len(df))
# # #                 m2.metric("Unique Users", df['UserID'].nunique())
# # #                 m3.metric("Sessions", df['SessionID'].nunique())
                
# # #                 st.markdown("---")
                
# # #                 # --- VISUALIZATIONS ROW ---
# # #                 c1, c2 = st.columns(2)
                
# # #                 # CHART 1: Activity Over Time
# # #                 with c1:
# # #                     st.subheader("📊 Activity Trend")
# # #                     df['Date'] = df['Timestamp'].dt.date
# # #                     daily_counts = df.groupby('Date').size().reset_index(name='Count')
# # #                     fig_activity = px.bar(daily_counts, x='Date', y='Count')
# # #                     st.plotly_chart(fig_activity, use_container_width=True)

# # #                 # CHART 2: Top 5 Questions (NEW!)
# # #                 with c2:
# # #                     st.subheader("🔝 Top 5 Questions")
# # #                     # Count occurrences of each query
# # #                     top_questions = df['Query'].value_counts().head(5).reset_index()
# # #                     top_questions.columns = ['Question', 'Count'] # Rename for Plotly
                    
# # #                     # Create Horizontal Bar Chart
# # #                     fig_top = px.bar(
# # #                         top_questions, 
# # #                         x='Count', 
# # #                         y='Question', 
# # #                         orientation='h', # Horizontal bars are easier to read for text
# # #                         text='Count'
# # #                     )
# # #                     fig_top.update_layout(yaxis=dict(autorange="reversed")) # Top question at the top
# # #                     st.plotly_chart(fig_top, use_container_width=True)

# # #                 st.markdown("---")

# # #                 # --- Data Table ---
# # #                 st.subheader("🗂 Conversation Logs")
# # #                 st.dataframe(df[['Timestamp', 'UserID', 'Query', 'Response']], use_container_width=True)
                
# # #                 # --- Download ---
# # #                 csv = df.to_csv(index=False).encode('utf-8-sig')
# # #                 st.download_button(
# # #                     "📥 Download CSV",
# # #                     csv,
# # #                     "chat_history.csv",
# # #                     "text/csv",
# # #                     key='download-csv'
# # #                 )
# # #             else:
# # #                 st.warning("Data fetched, but no valid user queries found (Welcome messages hidden).")
# # #         else:
# # #             st.info("No messages found in this date range.")

# # # if __name__ == "__main__":
# # #     main()
