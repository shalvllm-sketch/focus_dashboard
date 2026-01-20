import streamlit as st
import pandas as pd
import requests
import jwt
import time
import datetime
import re
from collections import defaultdict
import plotly.express as px
import json # Explicit import

# ==========================================
# 1. APP CONFIG & SECRETS
# ==========================================
st.set_page_config(page_title="Kore.ai Chat History", layout="wide")

# Regex for filters
UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# ==========================================
# 2. HELPER FUNCTIONS
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
                return f"[Interactive Element: {parsed.get('type', 'template')}]"
        except: pass
    
    # Strip HTML
    clean_text = re.sub(r'<[^>]+>', '', raw_text)
    # Fix Entities
    clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
    return clean_text

# ==========================================
# 3. DATA FETCHING (Cached)
# ==========================================
@st.cache_data(ttl=300) # Cache for 5 minutes
def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
    token = generate_jwt(client_id, client_secret)
    host = "https://de-platform.kore.ai" # Update if needed
    url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
    headers = { "auth": token, "content-type": "application/json" }
    
    all_messages = []
    skip = 0
    has_more = True
    limit = 100
    
    # Progress bar in UI
    progress_bar = st.progress(0)
    status_text = st.empty()
    
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
            
            if response.status_code != 200:
                st.error(f"API Error: {response.text}")
                break
                
            data = response.json()
            messages = data.get("messages", [])
            
            # Status Update
            page_count += 1
            status_text.text(f"Fetching page {page_count}... ({len(all_messages)} messages found)")
            progress_bar.progress(min(page_count * 5, 90)) # Fake progress logic
            
            for msg in messages:
                # Raw Text Extraction
                raw_text = ""
                if msg.get("components") and len(msg["components"]) > 0:
                    raw_text = msg["components"][0].get("data", {}).get("text", "")
                
                final_text = clean_kore_text(raw_text)
                clean_msg_strip = final_text.strip()

                # FILTERS
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
                progress_bar.progress(100)
                break
                
        except Exception as e:
            st.error(f"Connection Error: {e}")
            break
            
    status_text.empty()
    progress_bar.empty()
    return all_messages

# ==========================================
# 4. DATA PROCESSING (UPDATED)
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

    # Convert to DataFrame
    if final_pairs:
        df = pd.DataFrame(final_pairs)
        
        # --- NEW FILTER ADDED HERE ---
        # This removes rows where the Bot spoke first (Welcome Messages)
        df = df[df['Query'] != "(Bot Initiated / Welcome)"]
        # -----------------------------

        if not df.empty:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df = df.sort_values(by='Timestamp', ascending=False)
            return df
            
    return pd.DataFrame()

# ==========================================
# 5. MAIN UI
# ==========================================
def main():
    st.title("🤖 Kore.ai Chat Analytics Dashboard")
    
    # --- Sidebar ---
    st.sidebar.header("Configuration")
    
    # Secrets handling
    try:
        bot_id = st.secrets["BOT_ID"]
        client_id = st.secrets["CLIENT_ID"]
        client_secret = st.secrets["CLIENT_SECRET"]
    except:
        st.sidebar.error("Secrets not found! Please check .streamlit/secrets.toml")
        st.stop()

    # Date Pickers
    today = datetime.date.today()
    col1, col2 = st.sidebar.columns(2)
    start_date = col1.date_input("Start Date", today - datetime.timedelta(days=3))
    end_date = col2.date_input("End Date", today + datetime.timedelta(days=1)) # Tomorrow covers today

    if st.sidebar.button("Fetch Data"):
        raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
        if raw_data:
            df = process_to_pairs(raw_data)
            
            if not df.empty:
                # --- Metrics Row ---
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Interactions", len(df))
                m2.metric("Unique Users", df['UserID'].nunique())
                m3.metric("Sessions", df['SessionID'].nunique())
                
                # --- Charts ---
                st.subheader("Activity Over Time")
                df['Date'] = df['Timestamp'].dt.date
                daily_counts = df.groupby('Date').size().reset_index(name='Count')
                fig = px.bar(daily_counts, x='Date', y='Count')
                st.plotly_chart(fig, use_container_width=True)

                # --- Data Table ---
                st.subheader("Conversation Logs (Query vs Response)")
                st.dataframe(df[['Timestamp', 'UserID', 'Query', 'Response']], use_container_width=True)
                
                # --- Download ---
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    "📥 Download CSV",
                    csv,
                    "chat_history.csv",
                    "text/csv",
                    key='download-csv'
                )
            else:
                st.warning("Data fetched, but no valid Q&A pairs found (Note: Welcome messages are hidden).")
        else:
            st.info("No messages found in this date range.")

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

# # ==========================================
# # 1. APP CONFIG & SECRETS
# # ==========================================
# st.set_page_config(page_title="Kore.ai Chat History", layout="wide")

# # Regex for filters
# UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# # ==========================================
# # 2. HELPER FUNCTIONS
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
#                 return f"[Interactive Element: {parsed.get('type', 'template')}]"
#         except: pass
    
#     # Strip HTML
#     clean_text = re.sub(r'<[^>]+>', '', raw_text)
#     # Fix Entities
#     clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
#     return clean_text

# # ==========================================
# # 3. DATA FETCHING (Cached)
# # ==========================================
# @st.cache_data(ttl=300) # Cache for 5 minutes
# def fetch_data(bot_id, client_id, client_secret, date_from, date_to):
#     token = generate_jwt(client_id, client_secret)
#     host = "https://de-platform.kore.ai" # Update if needed
#     url = f"{host}/api/public/bot/{bot_id}/getMessages"
    
#     headers = { "auth": token, "content-type": "application/json" }
    
#     all_messages = []
#     skip = 0
#     has_more = True
#     limit = 100
    
#     # Progress bar in UI
#     progress_bar = st.progress(0)
#     status_text = st.empty()
    
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
            
#             # Status Update
#             page_count += 1
#             status_text.text(f"Fetching page {page_count}... ({len(all_messages)} messages found)")
#             progress_bar.progress(min(page_count * 5, 90)) # Fake progress logic
            
#             for msg in messages:
#                 # Raw Text Extraction
#                 raw_text = ""
#                 if msg.get("components") and len(msg["components"]) > 0:
#                     raw_text = msg["components"][0].get("data", {}).get("text", "")
                
#                 final_text = clean_kore_text(raw_text)
#                 clean_msg_strip = final_text.strip()

#                 # FILTERS
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
#                 progress_bar.progress(100)
#                 break
                
#         except Exception as e:
#             st.error(f"Connection Error: {e}")
#             break
            
#     status_text.empty()
#     progress_bar.empty()
#     return all_messages

# # ==========================================
# # 4. DATA PROCESSING
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

#     # Convert to DataFrame
#     if final_pairs:
#         df = pd.DataFrame(final_pairs)
#         df['Timestamp'] = pd.to_datetime(df['Timestamp'])
#         df = df.sort_values(by='Timestamp', ascending=False)
#         return df
#     return pd.DataFrame()

# # ==========================================
# # 5. MAIN UI
# # ==========================================
# def main():
#     st.title("🤖 Kore.ai Chat Analytics Dashboard")
    
#     # --- Sidebar ---
#     st.sidebar.header("Configuration")
    
#     # Secrets handling
#     try:
#         bot_id = st.secrets["BOT_ID"]
#         client_id = st.secrets["CLIENT_ID"]
#         client_secret = st.secrets["CLIENT_SECRET"]
#     except:
#         st.sidebar.error("Secrets not found! Please check .streamlit/secrets.toml")
#         st.stop()

#     # Date Pickers
#     today = datetime.date.today()
#     col1, col2 = st.sidebar.columns(2)
#     start_date = col1.date_input("Start Date", today - datetime.timedelta(days=3))
#     end_date = col2.date_input("End Date", today + datetime.timedelta(days=1)) # Tomorrow covers today

#     if st.sidebar.button("Fetch Data"):
#         raw_data = fetch_data(bot_id, client_id, client_secret, start_date, end_date)
        
#         if raw_data:
#             df = process_to_pairs(raw_data)
            
#             if not df.empty:
#                 # --- Metrics Row ---
#                 m1, m2, m3 = st.columns(3)
#                 m1.metric("Total Interactions", len(df))
#                 m2.metric("Unique Users", df['UserID'].nunique())
#                 m3.metric("Sessions", df['SessionID'].nunique())
                
#                 # --- Charts ---
#                 st.subheader("Activity Over Time")
#                 # Group by Hour or Date
#                 df['Date'] = df['Timestamp'].dt.date
#                 daily_counts = df.groupby('Date').size().reset_index(name='Count')
#                 fig = px.bar(daily_counts, x='Date', y='Count')
#                 st.plotly_chart(fig, use_container_width=True)

#                 # --- Data Table ---
#                 st.subheader("Conversation Logs (Query vs Response)")
#                 st.dataframe(df[['Timestamp', 'UserID', 'Query', 'Response']], use_container_width=True)
                
#                 # --- Download ---
#                 csv = df.to_csv(index=False).encode('utf-8-sig')
#                 st.download_button(
#                     "📥 Download CSV",
#                     csv,
#                     "chat_history.csv",
#                     "text/csv",
#                     key='download-csv'
#                 )
#             else:
#                 st.warning("Data fetched, but no valid Q&A pairs found.")
#         else:
#             st.info("No messages found in this date range.")

# if __name__ == "__main__":
#     import json # Import needed inside main if used in main logic, but good practice to keep at top
#     main()
