import streamlit as st
import pandas as pd
import json
import re
import os
import urllib.request
import urllib.parse
from utils.gemini_helper import query_gemini
from utils.excel_helper import save_to_excel
import auth
from datetime import datetime
import gspread

def scrape_linkedin_job(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        import re
        match = re.search(r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>([\s\S]*?)</div>', html)
        if match:
            desc_html = match.group(1)
            desc_text = re.sub(r'<[^>]+?>', ' ', desc_html)
            return " ".join(desc_text.split())
            
        match_section = re.search(r'<section[^>]*class="[^"]*description[^"]*"[^>]*>([\s\S]*?)</section>', html)
        if match_section:
            desc_html = match_section.group(1)
            desc_text = re.sub(r'<[^>]+?>', ' ', desc_html)
            return " ".join(desc_text.split())
            
        match_meta = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
        if match_meta:
            return match_meta.group(1)
            
        return None
    except Exception as e:
        print(f"Scrape LinkedIn failed: {e}")
        return None


# Force Page Configurations
st.set_page_config(
    page_title="Gemini AI Job Suitability Analyzer",
    page_icon="💼",
    layout="wide"
)

# Password Protection
if not auth.check_password():
    st.stop()

# Header Styling
st.markdown("""
<style>
    .welcome-container {
        padding: 2rem;
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        border-radius: 12px;
        color: white;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .welcome-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .welcome-subtitle {
        font-size: 1.1rem;
        opacity: 0.9;
    }
    .job-card {
        padding: 1.5rem;
        background: #fdfdfd;
        border-radius: 10px;
        border-left: 6px solid #203a43;
        box-shadow: 0 4px 10px rgba(0,0,0,0.06);
        margin-bottom: 1.5rem;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .job-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(0,0,0,0.1);
    }
</style>
<div class="welcome-container">
    <div class="welcome-title">💼 Gemini AI Job Suitability Analyzer & Ranker</div>
    <div class="welcome-subtitle">Scrape real-time job postings from LinkedIn & Indeed, evaluate matching skills, and rank suitability instantly.</div>
</div>
""", unsafe_allow_html=True)

# Profile Persistence
profile_path = "user_profile.json"
def load_profile():
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"target_titles": "", "skills": "", "experience": "", "salary": "", "resume": ""}

def save_profile(data):
    try:
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        if e.errno == 30:
            st.info("ℹ️ Running online: profile is kept in memory for this session (files are read-only).")
        else:
            st.error(f"Failed to save profile: {e}")
    except Exception as e:
        st.error(f"Failed to save profile: {e}")

# Gmail Credentials Persistence
gmail_config_path = "gmail_config.json"
def load_gmail_config():
    if os.path.exists(gmail_config_path):
        try:
            with open(gmail_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"gmail_user": "", "gmail_password": "", "sheet_url": ""}

def save_gmail_config(data):
    try:
        with open(gmail_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        if e.errno == 30:
            pass # Silent skip, handled dynamically
        else:
            st.error(f"Failed to save Gmail credentials: {e}")
    except Exception as e:
        st.error(f"Failed to save Gmail credentials: {e}")

# Sidebar Configuration
st.sidebar.header("⚙️ API Configurations")

api_key_default = os.environ.get("GEMINI_API_KEY", "")
try:
    if not api_key_default and "GEMINI_API_KEY" in st.secrets:
        api_key_default = st.secrets["GEMINI_API_KEY"]
except:
    pass

gemini_key = st.sidebar.text_input(
    "Google AI Studio API Key",
    type="password",
    value=st.session_state.get("GEMINI_API_KEY", api_key_default),
    help="Get a free key from https://aistudio.google.com/"
)

if gemini_key:
    os.environ["GEMINI_API_KEY"] = gemini_key
    st.session_state["GEMINI_API_KEY"] = gemini_key

serpapi_default = ""
try:
    if "serpapi_key" in st.secrets:
        serpapi_default = st.secrets["serpapi_key"]
except:
    pass

serp_key = st.sidebar.text_input(
    "SerpAPI Key (Google Jobs Search)",
    type="password",
    value=st.session_state.get("SERPAPI_API_KEY", serpapi_default)
)
if serp_key:
    st.session_state["SERPAPI_API_KEY"] = serp_key

gcp_json_default = ""
try:
    if "gcp_service_account_json" in st.secrets:
        gcp_json_default = st.secrets["gcp_service_account_json"]
except:
    pass

gcp_json = st.sidebar.text_input(
    "Google Sheets Service Account JSON",
    type="password",
    value=st.session_state.get("GCP_SERVICE_ACCOUNT_JSON", gcp_json_default),
    help="Paste the content of your Google Cloud Service Account JSON file here."
)
if gcp_json:
    st.session_state["GCP_SERVICE_ACCOUNT_JSON"] = gcp_json

st.sidebar.markdown("---")
st.sidebar.markdown("### How to use:")
st.sidebar.info("""
1. Fill out your **Candidate Profile** in the main tab (skills, target titles, resume).
2. Enter your job search keywords and location.
3. Click **Search & Rank Jobs** to fetch listings via SerpAPI and grade them using Gemini AI.
""")

# Tabs
tab_profile, tab_search, tab_gmail, tab_gap = st.tabs(["👤 Candidate Profile", "🔍 Job Search & Ranking", "✉️ Gmail Alert Scanner", "🎯 Skill Gap Analyzer"])

with tab_profile:
    st.subheader("Define your Profile & Skills")
    st.markdown("Gemini uses this data to grade incoming job descriptions for suitability.")
    
    saved_profile = load_profile()
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        titles = st.text_input("Target Job Titles (comma separated)", value=saved_profile.get("target_titles", ""), placeholder="e.g., Python Developer, Data Analyst")
        experience = st.text_input("Years of Experience", value=saved_profile.get("experience", ""), placeholder="e.g., 3 years")
    with col_t2:
        skills = st.text_input("Core Technical/Soft Skills (comma separated)", value=saved_profile.get("skills", ""), placeholder="e.g., Python, SQL, REST APIs, Git")
        salary = st.text_input("Target Salary (optional)", value=saved_profile.get("salary", ""), placeholder="e.g., $90,000 CAD")
        
    resume = st.text_area("Paste Resume Text / Qualifications summary", value=saved_profile.get("resume", ""), height=250, placeholder="Paste your full resume text here...")
    
    if st.button("💾 Save Profile locally"):
        profile_data = {
            "target_titles": titles,
            "skills": skills,
            "experience": experience,
            "salary": salary,
            "resume": resume
        }
        save_profile(profile_data)
        st.success("Profile saved successfully!")

with tab_search:
    st.subheader("Search Real-time Listings")
    
    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
    with col_s1:
        query = st.text_input("Job Keyword/Title", value="Python developer", placeholder="e.g. Software Engineer")
    with col_s2:
        location = st.text_input("Location", value="Canada", placeholder="e.g. Vancouver, BC")
    with col_s3:
        max_jobs = st.slider("Max Jobs to Analyze", min_value=3, max_value=20, value=5)
        
    search_btn = st.button("⚡ Search & Rank Jobs", type="primary", use_container_width=True)
    
    if search_btn:
        s_key = st.session_state.get("SERPAPI_API_KEY", serpapi_default)
        if not s_key:
            st.error("🔑 Please enter your SerpAPI Key in the sidebar first!")
        elif not gemini_key:
            st.error("🔑 Please enter your Google AI Studio API Key in the sidebar first!")
        else:
            with st.spinner("🔍 Fetching live jobs via SerpAPI Google Jobs..."):
                try:
                    params = {
                        "engine": "google_jobs",
                        "q": query,
                        "location": location,
                        "api_key": s_key,
                        "hl": "en"
                    }
                    query_string = urllib.parse.urlencode(params)
                    url = f"https://serpapi.com/search?{query_string}"
                    
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        search_data = json.loads(response.read().decode("utf-8"))
                        
                    jobs_list = search_data.get("jobs_results", [])
                except Exception as err:
                    st.error(f"SerpAPI Fetch Failed: {err}")
                    jobs_list = []
                    
            if not jobs_list:
                st.warning("No jobs found matching your criteria. Try adjusting keywords or location.")
            else:
                st.success(f"Found {len(jobs_list)} job listings! Starting Gemini AI Suitability scoring...")
                
                progress_bar = st.progress(0)
                evaluated_jobs = []
                
                # Load profile details
                cand_profile = load_profile()
                
                for idx, job in enumerate(jobs_list[:max_jobs]):
                    job_title = job.get("title", "Unknown Title")
                    company = job.get("company_name", "Unknown Company")
                    job_loc = job.get("location", "Unknown Location")
                    via = job.get("via", "Unknown Board")
                    desc = job.get("description", "")
                    share_link = job.get("share_link", "https://www.google.com/search?q=google+jobs")
                    
                    # Grade suitability with Gemini
                    prompt = f"""
                    Compare this job listing against the candidate's profile:
                    Candidate Profile:
                    - Target Titles: {cand_profile.get('target_titles')}
                    - Experience: {cand_profile.get('experience')}
                    - Core Skills: {cand_profile.get('skills')}
                    - Salary Target: {cand_profile.get('salary')}
                    - Resume details: {cand_profile.get('resume')}

                    Job Listing:
                    - Title: {job_title}
                    - Company: {company}
                    - Location: {job_loc}
                    - Source: {via}
                    - Description: {desc}

                    Analyze suitability. Output STRICTLY in JSON format:
                    {{
                      "suitability_score": 85,
                      "recommendation": "Strong Match",
                      "key_matches": ["skills matching...", "..."],
                      "gaps": ["missing skills...", "..."],
                      "pros": ["pros of applying...", "..."],
                      "cons": ["cons of applying...", "..."]
                    }}
                    Only output valid JSON.
                    """
                    
                    try:
                        gemini_res = query_gemini(prompt, response_json=True)
                        eval_data = json.loads(gemini_res.strip())
                    except Exception as e:
                        eval_data = {
                            "suitability_score": 50,
                            "recommendation": "Could not evaluate",
                            "key_matches": [],
                            "gaps": [f"Error evaluating listing: {e}"],
                            "pros": [],
                            "cons": []
                        }
                        
                    evaluated_jobs.append({
                        "Title": job_title,
                        "Company": company,
                        "Location": job_loc,
                        "Source": via,
                        "Score": eval_data.get("suitability_score", 50),
                        "Recommendation": eval_data.get("recommendation", "N/A"),
                        "Key Matches": ", ".join(eval_data.get("key_matches", [])),
                        "Gaps": ", ".join(eval_data.get("gaps", [])),
                        "Pros": ", ".join(eval_data.get("pros", [])),
                        "Cons": ", ".join(eval_data.get("cons", [])),
                        "Apply Link": share_link
                    })
                    
                    progress_bar.progress(int((idx + 1) / min(max_jobs, len(jobs_list)) * 100))
                    
                # Sort by score descending
                evaluated_jobs = sorted(evaluated_jobs, key=lambda x: x["Score"], reverse=True)
                st.session_state["evaluated_jobs"] = evaluated_jobs
                st.success("🔥 All jobs evaluated and ranked!")
                
    # Render evaluated jobs
    if "evaluated_jobs" in st.session_state:
        eval_list = st.session_state["evaluated_jobs"]
        
        # Download button
        df = pd.DataFrame(eval_list)
        try:
            excel_bytes = save_to_excel(eval_list, "Job Ranking", return_bytes=True)
            st.download_button(
                label="📥 Download Ranked Jobs Excel Report",
                data=excel_bytes,
                file_name="ranked_job_suitability_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"Failed to build Excel downloader: {e}")
            
        st.write("")
        for idx, job in enumerate(eval_list):
            score = job["Score"]
            if score >= 80:
                color_class = "background-color: #d4edda; color: #155724;"
            elif score >= 50:
                color_class = "background-color: #fff3cd; color: #856404;"
            else:
                color_class = "background-color: #f8d7da; color: #721c24;"
                
            st.markdown(f"""
            <div class="job-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="margin:0; color:#203a43;">{idx+1}. {job['Title']}</h3>
                    <span style="{color_class} padding: 0.3rem 0.8rem; border-radius: 20px; font-weight: bold; font-size:1.1rem;">
                        {score}% Match ({job['Recommendation']})
                    </span>
                </div>
                <div style="color:#555; margin-top:0.3rem; font-weight: 500;">🏢 {job['Company']} &nbsp;|&nbsp; 📍 {job['Location']} &nbsp;|&nbsp; 📢 {job['Source']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Details Expander
            with st.expander("🔍 View Match Details & Gap Analysis"):
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.markdown("**✅ Key Matches:**")
                    if job["Key Matches"]:
                        for item in job["Key Matches"].split(", "):
                            st.write(f"- {item}")
                    else:
                        st.write("None specified.")
                        
                    st.markdown("**📈 Pros of applying:**")
                    if job["Pros"]:
                        for item in job["Pros"].split(", "):
                            st.write(f"- {item}")
                    else:
                        st.write("None specified.")
                with col_m2:
                    st.markdown("**⚠️ Skill Gaps / Missing requirements:**")
                    if job["Gaps"]:
                        for item in job["Gaps"].split(", "):
                            st.write(f"- {item}")
                    else:
                        st.write("None specified.")
                        
                    st.markdown("**📉 Cons of applying:**")
                    if job["Cons"]:
                        for item in job["Cons"].split(", "):
                            st.write(f"- {item}")
                    else:
                        st.write("None specified.")
                        
                st.write("")
                st.link_button("🚀 Apply on Job Board", url=job["Apply Link"], use_container_width=True)
                st.write("")


with tab_gmail:
    st.subheader("✉️ Scan Gmail for Indeed & LinkedIn Job Alerts")
    st.markdown("This scanner logs into your Gmail, extracts jobs from recent Indeed/LinkedIn alert emails, ranks them using Gemini, and posts the results directly to Google Sheets!")

    import imaplib
    import email
    from email.header import decode_header
    import sheets_helper

    gmail_saved = load_gmail_config()

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        gmail_user = st.text_input("Gmail Address", value=st.session_state.get("GMAIL_USER", gmail_saved.get("gmail_user", "")), placeholder="yourname@gmail.com")
        gmail_password = st.text_input("Gmail App Password", type="password", value=st.session_state.get("GMAIL_PASSWORD", gmail_saved.get("gmail_password", "")), help="Create an App Password in your Google Account Security settings.")
    with col_g2:
        sheet_url = st.text_input("Google Spreadsheet URL or ID", value=st.session_state.get("google_spreadsheet_id", gmail_saved.get("sheet_url", st.secrets.get("google_spreadsheet_id", ""))), placeholder="Paste sheet link here")
        scan_limit = st.slider("Scan Limit (Recent Emails)", min_value=5, max_value=50, value=15)

    if gmail_user:
        st.session_state["GMAIL_USER"] = gmail_user
    if gmail_password:
        st.session_state["GMAIL_PASSWORD"] = gmail_password
    if sheet_url:
        st.session_state["google_spreadsheet_id"] = sheet_url

    # Read service account email to show to user
    client_email = "Not configured"
    try:
        if "gcp_service_account_json" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_service_account_json"])
            client_email = creds_dict.get("client_email", "Not configured")
        elif "gcp_service_account" in st.secrets:
            client_email = st.secrets["gcp_service_account"].get("client_email", "Not configured")
    except:
        pass

    if client_email != "Not configured":
        st.info(f"📋 **Service Account Email to share your Google Sheet with:**\n`{client_email}`\n\n*(Make sure this email has **Editor** access to your spreadsheet!)*")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        gmail_btn = st.button("🚀 Scan Gmail & Post to Sheets", type="primary", use_container_width=True)
    with col_btn2:
        save_gmail_btn = st.button("💾 Save Credentials locally", use_container_width=True)

    # Track if we encounter a read-only filesystem error during save
    st.session_state["read_only_fs"] = False

    def save_secret_key(key_name, value_str):
        try:
            secrets_dir = ".streamlit"
            secrets_file = os.path.join(secrets_dir, "secrets.toml")
            os.makedirs(secrets_dir, exist_ok=True)
            
            lines = []
            if os.path.exists(secrets_file):
                with open(secrets_file, "r") as sf:
                    lines = sf.readlines()
                    
            found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith(f"{key_name} =") or line.strip().startswith(f"{key_name}="):
                    new_lines.append(f'{key_name} = {json.dumps(value_str)}\n')
                    found = True
                else:
                    new_lines.append(line)
                    
            if not found:
                new_lines.append(f'{key_name} = {json.dumps(value_str)}\n')
                
            with open(secrets_file, "w") as sf:
                sf.writelines(new_lines)
        except OSError as e:
            if e.errno == 30:
                st.session_state["read_only_fs"] = True
            else:
                st.error(f"Failed to save secret {key_name}: {e}")
        except Exception as e:
            st.error(f"Failed to save secret {key_name}: {e}")

    if save_gmail_btn:
        # Save Gmail Credentials
        gmail_data = {
            "gmail_user": gmail_user,
            "gmail_password": gmail_password,
            "sheet_url": sheet_url
        }
        save_gmail_config(gmail_data)
        
        # Save GCP JSON
        gcp_val = st.session_state.get("GCP_SERVICE_ACCOUNT_JSON", "")
        if gcp_val:
            save_secret_key("gcp_service_account_json", gcp_val)
            
        # Save Gemini API Key
        gemini_val = st.session_state.get("GEMINI_API_KEY", "")
        if gemini_val:
            save_secret_key("GEMINI_API_KEY", gemini_val)
            
        # Save SerpAPI Key
        serp_val = st.session_state.get("SERPAPI_API_KEY", "")
        if serp_val:
            save_secret_key("serpapi_key", serp_val)
            
        if st.session_state.get("read_only_fs", False):
            st.warning("⚠️ Running online (read-only file system). Gmail settings are active in memory, but permanent API keys/GCP secrets must be configured in your **Streamlit Cloud Settings Dashboard (Secrets)** to persist!")
        else:
            st.success("💾 All credentials and API keys saved successfully!")

    if gmail_btn:
        if not gmail_user or not gmail_password:
            st.error("🔑 Please enter your Gmail Address and App Password!")
        elif not sheet_url:
            st.error("📊 Please specify your Google Sheet URL or ID!")
        elif not gemini_key:
            st.error("🔑 Please enter your Google AI Studio API Key in the sidebar first!")
        else:
            with st.spinner("📧 Connecting to Gmail IMAP server..."):
                try:
                    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                    mail.login(gmail_user, gmail_password)
                    mail.select("inbox")
                except Exception as e:
                    st.error(f"❌ Failed to connect to Gmail: {e}. Check if IMAP is enabled and app password is correct.")
                    mail = None

            if mail:
                alert_emails = []
                with st.spinner("🔍 Searching for LinkedIn & Indeed job alert emails..."):
                    # Search Indeed with subject fallback
                    seen_ids = set()
                    status_ind, data_ind = mail.search(None, 'FROM "indeed"')
                    if status_ind == "OK" and data_ind[0]:
                        for msg_id in data_ind[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "Indeed"))
                    
                    status_ind_fb, data_ind_fb = mail.search(None, 'SUBJECT "Indeed"')
                    if status_ind_fb == "OK" and data_ind_fb[0]:
                        for msg_id in data_ind_fb[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "Indeed"))
                    
                    # Search LinkedIn with subject fallback
                    status_li, data_li = mail.search(None, 'FROM "linkedin"')
                    if status_li == "OK" and data_li[0]:
                        for msg_id in data_li[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "LinkedIn"))
                                
                    status_li_fb, data_li_fb = mail.search(None, 'SUBJECT "LinkedIn"')
                    if status_li_fb == "OK" and data_li_fb[0]:
                        for msg_id in data_li_fb[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "LinkedIn"))

                if not alert_emails:
                    st.warning("No recent job alert emails found from Indeed or LinkedIn.")
                    mail.logout()
                else:
                    # Sort by message ID descending (most recent first)
                    alert_emails = sorted(alert_emails, key=lambda x: int(x[0]), reverse=True)[:scan_limit]
                    st.info(f"Found {len(alert_emails)} recent job alert emails to process!")
                    
                    progress_gmail = st.progress(0)
                    all_jobs_scraped = []
                    
                    for idx, (msg_id, source) in enumerate(alert_emails):
                        # Fetch email
                        res, msg_data = mail.fetch(msg_id, "(RFC822)")
                        if res != "OK":
                            continue
                        
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        
                        # Extract subject
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8", errors="ignore")
                            
                        # Extract body (prefer HTML to capture links, preserve anchors)
                        body = ""
                        html_content = ""
                        plain_content = ""
                        
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if "attachment" in content_disposition:
                                    continue
                                if content_type == "text/plain":
                                    try:
                                        plain_content += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    except:
                                        pass
                                elif content_type == "text/html":
                                    try:
                                        html_content += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    except:
                                        pass
                        else:
                            try:
                                plain_content = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                            except:
                                pass
                                
                        if html_content:
                            # Strip head, style, and script blocks (including their contents)
                            clean_html = re.sub(r'<head\b[^>]*>([\s\S]*?)</head>', ' ', html_content, flags=re.IGNORECASE)
                            clean_html = re.sub(r'<style\b[^>]*>([\s\S]*?)</style>', ' ', clean_html, flags=re.IGNORECASE)
                            clean_html = re.sub(r'<script\b[^>]*>([\s\S]*?)</script>', ' ', clean_html, flags=re.IGNORECASE)
                            
                            # Transform <a href="url">text</a> into text (url)
                            processed_html = re.sub(
                                r'<a\s+[^>]*?href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
                                r'\2 (\1)',
                                clean_html,
                                flags=re.IGNORECASE | re.DOTALL
                            )
                            # Strip all HTML tags
                            body = re.sub(r'<[^<]+?>', ' ', processed_html)
                        else:
                            body = plain_content
                            
                        # Token cleanup
                        body_cleaned = " ".join(body.split())[:12000] # Cap size for Gemini context
                        
                        # Use Gemini to extract jobs from the alert body
                        extract_prompt = f"""
                        Extract all job listings from the following email content.
                        Email Source: {source}
                        Email Subject: {subject}
                        
                        Content:
                        {body_cleaned}
                        
                        Output the list strictly in JSON format (list of objects):
                        [
                          {{
                            "title": "Job Title",
                            "company": "Company Name",
                            "location": "Location",
                            "description": "Short summary or requirements excerpt",
                            "apply_link": "Application link or view button URL"
                          }}
                        ]
                        Only return a valid JSON array.
                        """
                        try:
                            gemini_extracted = query_gemini(extract_prompt, response_json=True)
                            parsed_jobs = json.loads(gemini_extracted.strip())
                            if isinstance(parsed_jobs, list):
                                for pj in parsed_jobs:
                                    pj["source"] = source
                                    all_jobs_scraped.append(pj)
                        except Exception as parse_e:
                            pass
                            
                        progress_gmail.progress(int((idx + 1) / len(alert_emails) * 100))
                    
                    mail.logout()
                    
                    if not all_jobs_scraped:
                        st.warning("No structured jobs could be extracted from the emails.")
                    else:
                        st.success(f"Parsed {len(all_jobs_scraped)} total jobs from your alerts! Scoring suitability...")
                        
                        progress_grade = st.progress(0)
                        evaluated_rows = []
                        cand_profile = load_profile()
                        
                        for idx, job in enumerate(all_jobs_scraped):
                            job_title = job.get("title", "Unknown Title")
                            company = job.get("company", "Unknown Company")
                            job_loc = job.get("location", "Unknown Location")
                            job_desc = job.get("description", "")
                            apply_link = job.get("apply_link", "https://www.google.com")
                            source_board = job.get("source", "Alert")
                            
                            prompt = f"""
                            Compare this job listing against the candidate's profile:
                            Candidate Profile:
                            - Target Titles: {cand_profile.get('target_titles')}
                            - Experience: {cand_profile.get('experience')}
                            - Core Skills: {cand_profile.get('skills')}
                            - Salary Target: {cand_profile.get('salary')}
                            - Resume details: {cand_profile.get('resume')}

                            Job Listing:
                            - Title: {job_title}
                            - Company: {company}
                            - Location: {job_loc}
                            - Source: {source_board}
                            - Description: {job_desc}

                            Analyze suitability. Output STRICTLY in JSON format:
                            {{
                              "suitability_score": 85,
                              "recommendation": "Strong Match",
                              "key_matches": ["matching skill 1", "2"],
                              "gaps": ["missing skill 1", "2"],
                              "pros": ["pro 1", "2"],
                              "cons": ["con 1", "2"]
                            }}
                            Only return valid JSON.
                            """
                            try:
                                gemini_res = query_gemini(prompt, response_json=True)
                                eval_data = json.loads(gemini_res.strip())
                            except Exception:
                                eval_data = {
                                    "suitability_score": 50,
                                    "recommendation": "N/A",
                                    "key_matches": [],
                                    "gaps": [],
                                    "pros": [],
                                    "cons": []
                                }
                                
                            evaluated_rows.append({
                                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "Title": job_title,
                                "Company": company,
                                "Location": job_loc,
                                "Source": source_board,
                                "Score": eval_data.get("suitability_score", 50),
                                "Recommendation": eval_data.get("recommendation", "N/A"),
                                "Key Matches": ", ".join(eval_data.get("key_matches", [])),
                                "Gaps": ", ".join(eval_data.get("gaps", [])),
                                "Pros": ", ".join(eval_data.get("pros", [])),
                                "Cons": ", ".join(eval_data.get("cons", [])),
                                "Apply Link": apply_link
                            })
                            progress_grade.progress(int((idx + 1) / len(all_jobs_scraped) * 100))
                            
                        # Sort by Match Score Descending
                        evaluated_rows = sorted(evaluated_rows, key=lambda x: x["Score"], reverse=True)
                        
                        # Post to Google Sheet
                        with st.spinner("📊 Posting ranked listings to Google Sheets..."):
                            client = sheets_helper.get_gspread_client()
                            if client:
                                spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                                if spreadsheet:
                                    # Create/Get Ranked_Job_Alerts worksheet
                                    sheet_name = "Ranked_Job_Alerts"
                                    try:
                                        wks = spreadsheet.worksheet(sheet_name)
                                        existing_rows = wks.get_all_records()
                                        # Deduplicate based on Title & Company combo
                                        existing_keys = {f"{r.get('Title','')}|{r.get('Company','')}".strip().lower() for r in existing_rows}
                                    except gspread.exceptions.WorksheetNotFound:
                                        # headers
                                        headers = ["Timestamp", "Title", "Company", "Location", "Source", "Score", "Recommendation", "Key Matches", "Gaps", "Pros", "Cons", "Apply Link"]
                                        wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(headers)))
                                        wks.append_row(headers)
                                        existing_keys = set()
                                        
                                    rows_to_add = []
                                    for r in evaluated_rows:
                                        key = f"{r['Title']}|{r['Company']}".strip().lower()
                                        if key in existing_keys:
                                            continue
                                        rows_to_add.append([
                                            r["Timestamp"], r["Title"], r["Company"], r["Location"], r["Source"],
                                            str(r["Score"]), r["Recommendation"], r["Key Matches"], r["Gaps"],
                                            r["Pros"], r["Cons"], r["Apply Link"]
                                        ])
                                        
                                    if rows_to_add:
                                        wks.append_rows(rows_to_add, value_input_option="USER_ENTERED")
                                        st.success(f"🎉 Successfully posted {len(rows_to_add)} new ranked listings to your Google Sheet '{sheet_name}'!")
                                    else:
                                        st.info("ℹ️ All alerts parsed are already synced to the Google Sheet.")
                                        
                        # Visual display
                        st.subheader("📋 Parsed Alert Results")
                        for idx, job in enumerate(evaluated_rows):
                            st.write(f"**{idx+1}. {job['Title']}** at **{job['Company']}** ({job['Score']}% Match)")
                            st.caption(f"📍 {job['Location']} | Source: {job['Source']}")
                            st.write(f"*Recommendation:* {job['Recommendation']}")
                            st.write(f"*Apply Link:* {job['Apply Link']}")
                            st.write("---")

with tab_gap:
    st.subheader("🎯 Single Job Skill Gap Analyzer")
    st.markdown("Paste a job URL (LinkedIn, Indeed, etc.) or paste the raw Job Description text to analyze matches and gaps against your candidate profile.")
    
    col_gap1, col_gap2 = st.columns(2)
    with col_gap1:
        job_url_input = st.text_input("Job URL (LinkedIn, Indeed, etc.)", placeholder="Paste job posting link here", key="gap_url")
    with col_gap2:
        job_title_input = st.text_input("Job Title / Company (Optional)", placeholder="e.g. Bookkeeper at Maple Services", key="gap_title")
        
    job_desc_input = st.text_area("Or, paste the Job Description text directly", height=200, placeholder="Paste job description details here...", key="gap_desc")
    
    analyze_gap_btn = st.button("🔍 Analyze Skill Gaps & Generate Roadmap", type="primary", use_container_width=True)
    
    if analyze_gap_btn:
        job_desc = ""
        
        # 1. Try to fetch from URL if provided
        if job_url_input:
            with st.spinner("🌐 Attempting to fetch job details from URL..."):
                fetched_desc = scrape_linkedin_job(job_url_input)
                if fetched_desc:
                    job_desc = fetched_desc
                    st.success("🎉 Successfully fetched job description from URL!")
                else:
                    st.warning("⚠️ Could not scrape the URL automatically. Falling back to pasted description.")
                    
        # 2. Use pasted description if URL fetch failed or wasn't provided
        if not job_desc:
            job_desc = job_desc_input
            
        if not job_desc:
            st.error("❗ Please paste a job URL or copy-paste the Job Description text!")
        elif not gemini_key:
            st.error("🔑 Please enter your Google AI Studio API Key in the sidebar first!")
        else:
            with st.spinner("🤖 Analyzing skills and generating learning roadmap..."):
                prompt = f"""
                Compare the candidate's profile against this job description and identify the exact skills required by the employer.
                Highlight the matching skills, missing skills (gaps), and provide a study/development roadmap to acquire the missing skills.

                Candidate Profile:
                - Skills: {cand_profile.get('skills')}
                - Target Titles: {cand_profile.get('target_titles')}
                - Experience: {cand_profile.get('experience')}
                - Resume: {cand_profile.get('resume')}

                Job Description:
                - Title/Company: {job_title_input}
                - Content: {job_desc}

                Output STRICTLY in JSON format:
                {{
                  "job_title": "extracted job title",
                  "company": "extracted company",
                  "skills_required": ["skill 1", "skill 2"],
                  "matching_skills": ["skill A", "skill B"],
                  "missing_skills": ["skill X", "skill Y"],
                  "learning_roadmap": {{
                    "skill X": "specific action item or resource to learn skill X",
                    "skill Y": "specific action item or resource to learn skill Y"
                  }},
                  "suitability_score": 85
                }}
                Only return valid JSON. Do not include markdown code blocks or formatting.
                """
                try:
                    res = query_gemini(prompt, response_json=True)
                    gap_data = json.loads(res.strip())
                    
                    st.subheader(f"📊 Analysis: {gap_data.get('job_title', 'Job')} at {gap_data.get('company', 'Employer')}")
                    st.metric("Suitability Score", f"{gap_data.get('suitability_score', 0)}%")
                    
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        st.success("✅ Matching Skills (You have these!)")
                        for s in gap_data.get("matching_skills", []):
                            st.write(f"- {s}")
                            
                    with col_m2:
                        st.error("❌ Missing Skills / Gaps (Employer requires these!)")
                        for s in gap_data.get("missing_skills", []):
                            st.write(f"- {s}")
                            
                    st.subheader("📚 Recommended Learning Roadmap")
                    roadmap = gap_data.get("learning_roadmap", {})
                    if roadmap:
                        for skill, path in roadmap.items():
                            st.info(f"**How to learn {skill}:**\n{path}")
                    else:
                        st.success("🎉 You meet all skill requirements for this position!")
                        
                except Exception as e:
                    st.error(f"❌ Failed to parse gap analysis: {e}")
