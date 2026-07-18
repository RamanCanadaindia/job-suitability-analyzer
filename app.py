import streamlit as st
import pandas as pd
import json
import re
import os
import sys
import urllib.request
import urllib.parse
from utils.gemini_helper import query_gemini, GeminiError
from utils.pdf_helper import convert_markdown_to_pdf
from utils.excel_helper import save_to_excel
from utils.job_extraction import apply_evidence_rules
import auth
from datetime import datetime
import gspread

# Programmatically install Playwright Chromium browser on Streamlit Cloud (Linux) startup
playwright_browser_status = True
if os.name != "nt":
    try:
        import subprocess
        def install_playwright_browsers():
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    timeout=300,
                )
                return True
            except Exception as e:
                return str(e)
        
        status = install_playwright_browsers()
        playwright_browser_status = status
        if status is not True:
            st.warning(f"⚠️ Playwright browser auto-installation alert: {status}")
    except Exception as e:
        playwright_browser_status = str(e)


def launch_chromium(playwright):
    """Launch visibly on Windows and headlessly on Streamlit Cloud Linux."""
    if playwright_browser_status is not True:
        raise RuntimeError(f"Chromium setup failed: {playwright_browser_status}")

    launch_options = {"headless": os.name != "nt"}
    if os.name != "nt":
        launch_options["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
    return playwright.chromium.launch(**launch_options)

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
        
def scrape_job_url(url):
    try:
        from playwright.sync_api import sync_playwright
        import time
        
        if "linkedin.com" in url:
            desc = scrape_linkedin_job(url)
            if desc:
                return desc
                
        with sync_playwright() as p:
            browser = launch_chromium(p)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5)
            
            salary_text = ""
            salary_selectors = [
                "div[data-testid='jobsearch-JobDescriptionSection-section-pay']",
                ".salary-snippet-container",
                ".jobsearch-JobMetadataHeader-item",
                "div.salary-snippet",
                ".jobsearch-JobComponent"
            ]
            for ss in salary_selectors:
                try:
                    loc = page.locator(ss)
                    if loc.count() > 0:
                        t = loc.first.inner_text().strip()
                        if t and any(char.isdigit() for char in t) and ("$" in t or "year" in t or "hour" in t or "Pay" in t or "Salary" in t):
                            if "\n" in t:
                                for line in t.split("\n"):
                                    if "$" in line and any(char.isdigit() for char in line):
                                        salary_text = f"Salary/Pay Info: {line}\n"
                                        break
                            else:
                                salary_text = f"Salary/Pay Info: {t}\n"
                            if salary_text:
                                break
                except:
                    pass

            selectors = [
                "#jobDescriptionText",
                ".jobsearch-JobComponent-description",
                "div.jobsearch-jobDescriptionText",
                ".description__text",
                ".show-more-less-html__markup",
                "#details-job-description"
            ]
            full_desc = ""
            for s in selectors:
                try:
                    locator = page.locator(s)
                    if locator.count() > 0:
                        text = locator.first.inner_text()
                        if text and len(text.strip()) > 100:
                            full_desc = text.strip()
                            break
                except:
                    pass
                
            if salary_text and full_desc and salary_text not in full_desc:
                full_desc = salary_text + "\n" + full_desc
                
            browser.close()
            return full_desc if len(full_desc.strip()) > 50 else None
    except Exception as e:
        print(f"Scrape Job URL failed: {e}")
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

# Profile Persistence
profile_path = "user_profile.json"
def load_profile():
    # 1. Initialize default empty profile
    profile = {
        "candidate_name": "",
        "candidate_phone": "",
        "candidate_email": "",
        "candidate_linkedin": "",
        "target_titles": "",
        "skills": "",
        "experience": "",
        "salary": "",
        "resume": ""
    }
    
    # 2. Try loading from Secrets (permanent cloud settings)
    try:
        # Check flat keys
        for k in profile.keys():
            if k in st.secrets:
                profile[k] = str(st.secrets[k])
        # Check [profile] block
        if "profile" in st.secrets:
            for k in profile.keys():
                if k in st.secrets["profile"]:
                    profile[k] = str(st.secrets["profile"][k])
    except:
        pass
        
    # 3. Try loading from local user_profile.json
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                for k in profile.keys():
                    if local_data.get(k):
                        profile[k] = local_data[k]
        except:
            pass
            
    # 4. Try loading from Google Sheet if credentials & URL exist
    try:
        gmail_saved = load_gmail_config()
        sheet_url = st.session_state.get("google_spreadsheet_id", gmail_saved.get("sheet_url", st.secrets.get("google_spreadsheet_id", "")))
        if sheet_url:
            import sheets_helper
            client = sheets_helper.get_gspread_client()
            if client:
                spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                if spreadsheet:
                    try:
                        wks = spreadsheet.worksheet("Candidate_Profile")
                        records = wks.get_all_records()
                        if records:
                            row = records[0] # Load the first row of data
                            missing_fields = [field for field in profile if field not in row]
                            if missing_fields:
                                raise RuntimeError(
                                    "Candidate_Profile is missing columns: "
                                    + ", ".join(missing_fields)
                                )
                            for k in profile.keys():
                                # The sheet is authoritative, including blank cells.
                                profile[k] = str(row.get(k, ""))
                            return profile
                    except gspread.exceptions.WorksheetNotFound:
                        pass
    except Exception as e:
        st.warning(f"⚠️ Could not load profile from Google Sheets: {e}. Falling back to local configuration/secrets.")

    return profile

def save_profile(data):
    # 1. Save to local JSON
    try:
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        if e.errno == 30:
            pass # Ephemeral environment
        else:
            st.error(f"Failed to save profile locally: {e}")
    except Exception as e:
        st.error(f"Failed to save profile locally: {e}")

    # 2. Save/Sync to Google Sheet if configured
    try:
        gmail_saved = load_gmail_config()
        sheet_url = st.session_state.get("google_spreadsheet_id", gmail_saved.get("sheet_url", st.secrets.get("google_spreadsheet_id", "")))
        if sheet_url:
            import sheets_helper
            client = sheets_helper.get_gspread_client()
            if client:
                spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                if spreadsheet:
                    sheet_name = "Candidate_Profile"
                    try:
                        wks = spreadsheet.worksheet(sheet_name)
                    except gspread.exceptions.WorksheetNotFound:
                        # Create worksheet
                        headers = list(data.keys())
                        wks = spreadsheet.add_worksheet(title=sheet_name, rows="10", cols=str(len(headers)))
                        wks.append_row(headers)
                    
                    # Overwrite/Update the profile row
                    # Clear existing rows (except headers)
                    wks.resize(rows=2) # Resize to header + 1 data row
                    # Set values
                    headers = wks.row_values(1)
                    # Align values to headers
                    row_values = []
                    for h in headers:
                        row_values.append(str(data.get(h, "")))
                    
                    # Update row 2
                    wks.update("A2", [row_values])
                    st.success("✅ Profile also synced and saved permanently in your Google Sheet!")
    except Exception as e:
        st.warning(f"⚠️ Could not sync profile to Google Sheet: {e}. Check sheet share settings.")

PROFILE_FIELDS = [
    "candidate_name", "candidate_phone", "candidate_email",
    "candidate_linkedin", "target_titles", "skills", "experience",
    "salary", "resume"
]


def get_profile_sheet_url():
    """Return the spreadsheet URL/ID used for permanent profile storage."""
    gmail_saved = load_gmail_config()
    try:
        secret_sheet = st.secrets.get("google_spreadsheet_id", "")
    except Exception:
        secret_sheet = ""
    return (
        st.session_state.get("google_spreadsheet_id")
        or gmail_saved.get("sheet_url")
        or secret_sheet
    )


def load_profile_from_google_sheet():
    """Fetch the canonical profile directly from Candidate_Profile row 2."""
    sheet_url = get_profile_sheet_url()
    if not sheet_url:
        raise RuntimeError("Google Spreadsheet URL/ID is not configured.")

    import sheets_helper

    client = sheets_helper.get_gspread_client()
    if not client:
        raise RuntimeError("Google Sheets authentication failed.")
    spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
    if not spreadsheet:
        raise RuntimeError("The configured Google Spreadsheet could not be opened.")

    try:
        worksheet = spreadsheet.worksheet("Candidate_Profile")
    except gspread.exceptions.WorksheetNotFound as exc:
        raise RuntimeError("Candidate_Profile worksheet was not found.") from exc

    values = worksheet.get_all_values()
    if len(values) < 2:
        raise RuntimeError("Candidate_Profile does not contain a profile in row 2.")

    headers = [str(value).strip() for value in values[0]]
    row = values[1]
    sheet_profile = {}
    for field in PROFILE_FIELDS:
        if field not in headers:
            raise RuntimeError(f"Candidate_Profile is missing the '{field}' column.")
        column_index = headers.index(field)
        sheet_profile[field] = row[column_index] if column_index < len(row) else ""
    return sheet_profile


def sync_profile_widgets_from_google_sheet():
    """Refresh every Candidate Profile widget from the canonical sheet row."""
    try:
        profile = load_profile_from_google_sheet()
        widget_fields = {
            "prof_name": "candidate_name",
            "prof_phone": "candidate_phone",
            "prof_email": "candidate_email",
            "prof_linkedin": "candidate_linkedin",
            "prof_titles": "target_titles",
            "prof_experience": "experience",
            "prof_skills": "skills",
            "prof_salary": "salary",
            "prof_resume": "resume",
        }
        for widget_key, field in widget_fields.items():
            st.session_state[widget_key] = profile[field]
        st.session_state["profile_sync_success"] = True
        st.session_state.pop("profile_sync_error", None)
    except Exception as exc:
        st.session_state["profile_sync_error"] = str(exc)
        st.session_state.pop("profile_sync_success", None)


def sync_tailor_resume_from_google_sheet():
    """Refresh the ATS Tailor base-resume widget from the sheet."""
    try:
        profile = load_profile_from_google_sheet()
        st.session_state["tailor_base_resume"] = profile["resume"]
        st.session_state["tailor_sync_success"] = True
        st.session_state.pop("tailor_sync_error", None)
    except Exception as exc:
        st.session_state["tailor_sync_error"] = str(exc)
        st.session_state.pop("tailor_sync_success", None)


def save_profile(data):
    """Save locally when possible and permanently to one Google Sheets row."""
    try:
        with open(profile_path, "w", encoding="utf-8") as profile_file:
            json.dump(data, profile_file, indent=4)
    except OSError as exc:
        if exc.errno != 30:
            st.warning(f"Local profile backup could not be saved: {exc}")
    except Exception as exc:
        st.warning(f"Local profile backup could not be saved: {exc}")

    sheet_url = get_profile_sheet_url()
    if not sheet_url:
        st.error(
            "Google Spreadsheet URL/ID is not configured. Add it in the "
            "Gmail Alert Scanner settings before saving your profile."
        )
        return False

    try:
        import sheets_helper

        client = sheets_helper.get_gspread_client()
        if not client:
            return False
        spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
        if not spreadsheet:
            return False

        try:
            worksheet = spreadsheet.worksheet("Candidate_Profile")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title="Candidate_Profile", rows="2", cols=str(len(PROFILE_FIELDS))
            )

        row_values = [str(data.get(field, "")) for field in PROFILE_FIELDS]
        worksheet.resize(rows=2, cols=len(PROFILE_FIELDS))
        worksheet.update(
            "A1", [PROFILE_FIELDS, row_values], value_input_option="RAW"
        )
        return True
    except Exception as exc:
        st.error(
            f"Could not save the profile permanently: {exc}. Check the "
            "spreadsheet sharing and service-account settings."
        )
        return False


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
tab_profile, tab_search, tab_gmail, tab_gap, tab_tailor = st.tabs(["👤 Candidate Profile", "🔍 Job Search & Ranking", "✉️ Gmail Alert Scanner", "🎯 Skill Gap Analyzer", "📄 ATS Resume Tailor"])

with tab_profile:
    st.subheader("Define your Profile & Skills")
    st.markdown("Gemini uses this data to grade incoming job descriptions for suitability.")
    
    saved_profile = load_profile()
    
    st.markdown("#### 📞 Contact Information")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        c_name = st.text_input("Full Name", value=saved_profile.get("candidate_name", ""), placeholder="e.g. Raman Deep Kumar", key="prof_name")
        c_phone = st.text_input("Phone Number", value=saved_profile.get("candidate_phone", ""), placeholder="e.g. 604-440-9885", key="prof_phone")
    with col_c2:
        c_email = st.text_input("Email Address", value=saved_profile.get("candidate_email", ""), placeholder="e.g. email@domain.com", key="prof_email")
        c_linkedin = st.text_input("LinkedIn Profile URL", value=saved_profile.get("candidate_linkedin", ""), placeholder="e.g. https://www.linkedin.com/in/username", key="prof_linkedin")
        
    st.markdown("#### 🎯 Target Role & Skills")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        titles = st.text_input("Target Job Titles (comma separated)", value=saved_profile.get("target_titles", ""), placeholder="e.g., Accountant, Bookkeeper", key="prof_titles")
        experience = st.text_input("Years of Experience", value=saved_profile.get("experience", ""), placeholder="e.g., 5 years", key="prof_experience")
    with col_t2:
        skills = st.text_input("Core Technical/Soft Skills (comma separated)", value=saved_profile.get("skills", ""), placeholder="e.g., T1/T2 Tax, QuickBooks, CaseWare", key="prof_skills")
        salary = st.text_input("Target Salary (optional)", value=saved_profile.get("salary", ""), placeholder="e.g., $65,000 CAD", key="prof_salary")
        
    resume = st.text_area("Paste Resume Text / Qualifications summary", value=saved_profile.get("resume", ""), height=250, placeholder="Paste your full resume text here...", key="prof_resume")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        save_btn = st.button("💾 Save Profile Permanently", use_container_width=True)
    with col_b2:
        st.button(
            "🔄 Sync/Reload from Google Sheet",
            use_container_width=True,
            on_click=sync_profile_widgets_from_google_sheet,
        )

    if st.session_state.pop("profile_sync_success", False):
        st.success("🎉 Profile successfully reloaded from Google Sheets!")
    profile_sync_error = st.session_state.pop("profile_sync_error", None)
    if profile_sync_error:
        st.error(f"❌ Profile reload failed: {profile_sync_error}")
        
    if save_btn:
        profile_data = {
            "candidate_name": c_name,
            "candidate_phone": c_phone,
            "candidate_email": c_email,
            "candidate_linkedin": c_linkedin,
            "target_titles": titles,
            "skills": skills,
            "experience": experience,
            "salary": salary,
            "resume": resume
        }
        if save_profile(profile_data):
            st.success("🎉 Profile saved permanently in Google Sheets!")
            st.rerun()

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
                        if not gemini_res:
                            raise ValueError("API Key limit exceeded or request failed.")
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

    # Smart discovery for default configuration values in Secrets
    default_secret_sheet = ""
    default_secret_email = ""
    default_secret_email_pass = ""
    
    try:
        # 1. Search Google Sheet ID/URL
        default_secret_sheet = st.secrets.get("google_spreadsheet_id", "")
        if not default_secret_sheet:
            default_secret_sheet = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
        if not default_secret_sheet:
            for key in st.secrets.keys():
                if "sheet" in key.lower() or "spreadsheet" in key.lower():
                    val = st.secrets[key]
                    if isinstance(val, str) and (len(val) > 15 or "docs.google.com" in val):
                        default_secret_sheet = val
                        break
                    elif isinstance(val, dict):
                        for subkey in ["id", "url", "spreadsheet_id"]:
                            if subkey in val:
                                default_secret_sheet = val[subkey]
                                break
                        if default_secret_sheet:
                            break
                            
        # 2. Search Email Address
        default_secret_email = st.secrets.get("gmail_user", "")
        if not default_secret_email:
            default_secret_email = st.secrets.get("email_user", "")
        if not default_secret_email:
            for key in st.secrets.keys():
                kl = key.lower()
                if ("email" in kl or "gmail" in kl or "outlook" in kl) and "pass" not in kl:
                    val = st.secrets[key]
                    if isinstance(val, str) and "@" in val:
                        default_secret_email = val
                        break
                        
        # 3. Search Email App Password
        default_secret_email_pass = st.secrets.get("gmail_password", "")
        if not default_secret_email_pass:
            default_secret_email_pass = st.secrets.get("email_password", "")
        if not default_secret_email_pass:
            for key in st.secrets.keys():
                kl = key.lower()
                if ("gmail" in kl or "email" in kl or "outlook" in kl) and ("pass" in kl or "key" in kl):
                    val = st.secrets[key]
                    if isinstance(val, str) and val != "" and kl != "app_password":
                        default_secret_email_pass = val
                        break
    except:
        pass

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        gmail_user = st.text_input("Gmail Address", value=st.session_state.get("GMAIL_USER") or gmail_saved.get("gmail_user") or default_secret_email, placeholder="yourname@gmail.com")
        gmail_password = st.text_input("Gmail App Password", type="password", value=st.session_state.get("GMAIL_PASSWORD") or gmail_saved.get("gmail_password") or default_secret_email_pass, help="Create an App Password in your Google Account Security settings.")
    with col_g2:
        sheet_url = st.text_input("Google Spreadsheet URL or ID", value=st.session_state.get("google_spreadsheet_id") or gmail_saved.get("sheet_url") or default_secret_sheet or st.secrets.get("google_spreadsheet_id", ""), placeholder="Paste sheet link here")
        scan_limit = st.slider("Scan Limit (Recent Emails)", min_value=5, max_value=50, value=5)

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
            import toml
            secrets_dir = ".streamlit"
            secrets_file = os.path.join(secrets_dir, "secrets.toml")
            os.makedirs(secrets_dir, exist_ok=True)
            
            data = {}
            if os.path.exists(secrets_file):
                try:
                    data = toml.load(secrets_file)
                except Exception:
                    pass
            data[key_name] = value_str
            with open(secrets_file, "w") as sf:
                toml.dump(data, sf)
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
                with st.spinner("🔍 Searching for job alert emails (Indeed, Glassdoor, LinkedIn)..."):
                    seen_ids = set()
                    
                    # Indeed
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
                                
                    # Glassdoor
                    status_gd, data_gd = mail.search(None, 'FROM "glassdoor"')
                    if status_gd == "OK" and data_gd[0]:
                        for msg_id in data_gd[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "Glassdoor"))
                                
                    status_gd_sb, data_gd_sb = mail.search(None, 'SUBJECT "Glassdoor"')
                    if status_gd_sb == "OK" and data_gd_sb[0]:
                        for msg_id in data_gd_sb[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "Glassdoor"))
                                
                    # LinkedIn
                    status_li, data_li = mail.search(None, 'FROM "linkedin"')
                    if status_li == "OK" and data_li[0]:
                        for msg_id in data_li[0].split():
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                alert_emails.append((msg_id, "LinkedIn"))

                if not alert_emails:
                    st.warning("No recent job alert emails (Indeed, Glassdoor, LinkedIn) found.")
                    mail.logout()
                else:
                    alert_emails = sorted(alert_emails, key=lambda x: int(x[0]), reverse=True)[:scan_limit]
                    st.info(f"Found {len(alert_emails)} recent alert emails. Extracting job links...")
                    
                    progress_gmail = st.progress(0)
                    all_jobs_scraped = []
                    
                    for idx, (msg_id, source) in enumerate(alert_emails):
                        res, msg_data = mail.fetch(msg_id, "(RFC822)")
                        if res != "OK":
                            continue
                        
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8", errors="ignore")
                            
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
                            clean_html = re.sub(r'<head\b[^>]*>([\s\S]*?)</head>', ' ', html_content, flags=re.IGNORECASE)
                            clean_html = re.sub(r'<style\b[^>]*>([\s\S]*?)</style>', ' ', clean_html, flags=re.IGNORECASE)
                            clean_html = re.sub(r'<script\b[^>]*>([\s\S]*?)</script>', ' ', clean_html, flags=re.IGNORECASE)
                            
                            processed_html = re.sub(
                                r'<a\s+[^>]*?href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
                                r'\2 (\1)',
                                clean_html,
                                flags=re.IGNORECASE | re.DOTALL
                            )
                            body = re.sub(r'<[^<]+?>', ' ', processed_html)
                        else:
                            body = plain_content
                            
                        body_cleaned = " ".join(body.split())[:12000]
                        
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
                            "apply_link": "Application link or view job URL"
                          }}
                        ]
                        Only return a valid JSON array.
                        """
                        try:
                            # Sleep to avoid hitting 15 RPM API rate limit
                            import time
                            if idx > 0:
                                time.sleep(4.5)
                            gemini_extracted = query_gemini(extract_prompt, response_json=True)
                            if gemini_extracted:
                                parsed_jobs = json.loads(gemini_extracted.strip())
                                if isinstance(parsed_jobs, list):
                                    for pj in parsed_jobs:
                                        pj["source"] = source
                                        if pj.get("apply_link") and pj.get("apply_link") != "https://www.google.com":
                                            all_jobs_scraped.append(pj)
                            else:
                                st.warning(f"⚠️ Gemini API rate limit or error encountered for email {idx+1}. Skipping.")
                        except Exception as parse_e:
                            st.error(f"❌ Error parsing email {idx+1}: {parse_e}")
                            
                        progress_gmail.progress(int((idx + 1) / len(alert_emails) * 100))
                    
                    mail.logout()
                    
                    if not all_jobs_scraped:
                        st.warning("No structured job links could be extracted from your emails.")
                    else:
                        st.session_state["jobs_scraped_links"] = all_jobs_scraped
                        st.success(f"🎉 Successfully extracted {len(all_jobs_scraped)} job links from your Gmail Indeed alerts!")
                        st.rerun()

    # Display selection of extracted links
    scraped_links = st.session_state.get("jobs_scraped_links", [])
    if scraped_links:
        st.markdown("### 📋 Extracted Indeed Job Alert Links")
        st.write("Select which job links you want to open in a visible Chrome browser, extract full job descriptions, and evaluate against your profile.")
        
        selected_jobs = []
        for idx, job in enumerate(scraped_links):
            chk = st.checkbox(f"**{job['title']}** at **{job['company']}** ({job['location']})", value=True, key=f"chk_job_{idx}")
            st.caption(f"🔗 [View Original Job Link]({job['apply_link']})")
            if chk:
                selected_jobs.append(job)
                
        chrome_btn = st.button("🌐 Open & Analyze Selected in Visible Chrome", type="primary", use_container_width=True)
        if chrome_btn:
            if not selected_jobs:
                st.error("Please select at least one job to process!")
            else:
                progress_bar = st.progress(0)
                evaluated_rows = []
                cand_profile = load_profile()
                
                from playwright.sync_api import sync_playwright
                import time
                
                for idx, job in enumerate(selected_jobs):
                    job_title = job.get("title", "Unknown Title")
                    company = job.get("company", "Unknown Company")
                    job_loc = job.get("location", "Unknown Location")
                    apply_link = job.get("apply_link", "")
                    source_board = job.get("source", "Indeed")
                    
                    st.write(f"🔄 Opening visible Chrome and navigating to **{job_title}** at **{company}**...")
                    
                    full_desc = ""
                    try:
                        with sync_playwright() as p:
                            # Visible on local Windows; headless on Streamlit Cloud.
                            browser = launch_chromium(p)
                            context = browser.new_context(
                                viewport={"width": 1280, "height": 800},
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            )
                            page = context.new_page()
                            page.goto(apply_link, wait_until="domcontentloaded", timeout=45000)
                            time.sleep(5)  # Let user see the page and bypass Cloudflare if needed
                            
                            # Extract salary information explicitly from header cards
                            salary_text = ""
                            salary_selectors = [
                                "div[data-testid='jobsearch-JobDescriptionSection-section-pay']",
                                ".salary-snippet-container",
                                ".jobsearch-JobMetadataHeader-item",
                                "div.salary-snippet",
                                ".jobsearch-JobComponent"
                            ]
                            for ss in salary_selectors:
                                try:
                                    loc = page.locator(ss)
                                    if loc.count() > 0:
                                        t = loc.first.inner_text().strip()
                                        if t and any(char.isdigit() for char in t) and ("$" in t or "year" in t or "hour" in t or "Pay" in t or "Salary" in t):
                                            if "\n" in t:
                                                for line in t.split("\n"):
                                                    if "$" in line and any(char.isdigit() for char in line):
                                                        salary_text = f"Salary/Pay Info: {line}\n"
                                                        break
                                            else:
                                                salary_text = f"Salary/Pay Info: {t}\n"
                                            if salary_text:
                                                break
                                except:
                                    pass
                                    
                            selectors = [
                                "#jobDescriptionText",
                                ".jobsearch-JobComponent-description",
                                "div.jobsearch-jobDescriptionText",
                                "body"
                            ]
                            for s in selectors:
                                try:
                                    locator = page.locator(s)
                                    if locator.count() > 0:
                                        text = locator.first.inner_text()
                                        if text and len(text.strip()) > 100:
                                            full_desc = text.strip()
                                            break
                                except:
                                    pass
                            if not full_desc:
                                full_desc = page.locator("body").inner_text()
                                
                            if salary_text and salary_text not in full_desc:
                                full_desc = salary_text + "\n" + full_desc
                            browser.close()
                    except Exception as e:
                        st.warning(f"⚠️ Visible Chrome browser scraping failed for this link: {e}")
                        full_desc = ""
                        
                    if not full_desc or len(full_desc.strip()) < 50:
                        st.error(f"Could not extract description for **{job_title}**.")
                        continue
                        
                    st.success(f"✅ Successfully extracted {len(full_desc)} characters of details. Comparing against your Accounting profile...")
                    
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
                    - Description: {full_desc}

                    FACT EXTRACTION RULES:
                    - Extract factual job fields ONLY from the Job Listing above, never from the Candidate Profile.
                    - Do not infer, generalize, or add common accounting requirements.
                    - Software must be named verbatim in the listing.
                    - "month-end" does not mean "year-end".
                    - Return "Not Mentioned" when the listing does not explicitly support a value.

                    Analyze suitability. Output STRICTLY in JSON format:
                    {{
                      "suitability_score": 85,
                      "recommendation": "Strong Match",
                      "employment_type": "Full-Time, Part-Time, Contract, otherwise 'Not Mentioned'",
                      "work_mode": "On-site, Remote, Hybrid, otherwise 'Not Mentioned'",
                      "experience_required": "Years of experience required, otherwise 'Not Mentioned'",
                      "education": "Required education (e.g. Degree/Diploma in Accounting), otherwise 'Not Mentioned'",
                      "cpa_requirement": "CPA requirement or status (e.g. CPA Student, CPA Designated), otherwise 'Not Mentioned'",
                      "tax_experience": "Tax preparation requirements (e.g. T1, T2), otherwise 'Not Mentioned'",
                      "financial_statements": "Yes or No",
                      "year_end": "Yes or No",
                      "payroll": "Yes or No",
                      "gst_pst_wcb": "Comma-separated list of GST, PST, WCB requirements, otherwise 'Not Mentioned'",
                      "government_filing": "CRA Online Filing, etc. if mentioned, otherwise 'Not Mentioned'",
                      "software": "Comma-separated list of software (e.g. CaseWare, Excel, QuickBooks), otherwise 'Not Mentioned'",
                      "client_interaction": "Yes or No",
                      "other_requirements": "Other critical requirements (e.g. PR Card Required), otherwise 'Not Mentioned'",
                      "salary": "Salary or pay range, otherwise 'Not Mentioned'",
                      "gaps_roadmap": "A summary of any missing skills (e.g. CaseWare, QuickBooks, driver's license) and a quick recommendation on how to learn them, otherwise 'None'"
                    }}
                    
                    CRITICAL CONSTRAINT RULE: If the job description explicitly lists a language fluency requirement (e.g. Mandarin, Cantonese, French, Punjabi) that the candidate's resume/profile does not list or support, treat this as a CRITICAL unmet hard constraint. Reduce the suitability_score below 40% and set the recommendation to "Weak Match" or "Not Suitable".
                    
                    Only return valid JSON.
                    """
                    
                    try:
                        gemini_res = query_gemini(prompt, response_json=True)
                        eval_data = json.loads(gemini_res.strip())
                    except Exception:
                        eval_data = {
                            "suitability_score": 50,
                            "recommendation": "N/A",
                            "employment_type": "Not Mentioned",
                            "work_mode": "Not Mentioned",
                            "experience_required": "Not Mentioned",
                            "education": "Not Mentioned",
                            "cpa_requirement": "Not Mentioned",
                            "tax_experience": "Not Mentioned",
                            "financial_statements": "Not Mentioned",
                            "year_end": "Not Mentioned",
                            "payroll": "Not Mentioned",
                            "gst_pst_wcb": "Not Mentioned",
                            "government_filing": "Not Mentioned",
                            "software": "Not Mentioned",
                            "client_interaction": "Not Mentioned",
                            "other_requirements": "Not Mentioned",
                            "salary": "Not Mentioned",
                            "gaps_roadmap": "None"
                        }

                    eval_data = apply_evidence_rules(full_desc, eval_data)
                        
                    evaluated_rows.append({
                        "Date Found": datetime.now().strftime("%Y-%m-%d"),
                        "Source": source_board,
                        "Job Title": job_title,
                        "Company": company,
                        "Location": job_loc,
                        "Salary": eval_data.get("salary", "Not Mentioned"),
                        "Employment Type": eval_data.get("employment_type", "Not Mentioned"),
                        "Work Mode": eval_data.get("work_mode", "Not Mentioned"),
                        "Experience Required": eval_data.get("experience_required", "Not Mentioned"),
                        "Education": eval_data.get("education", "Not Mentioned"),
                        "CPA Requirement": eval_data.get("cpa_requirement", "Not Mentioned"),
                        "Tax Experience": eval_data.get("tax_experience", "Not Mentioned"),
                        "Financial Statements": eval_data.get("financial_statements", "Not Mentioned"),
                        "Year-End": eval_data.get("year_end", "Not Mentioned"),
                        "Payroll": eval_data.get("payroll", "Not Mentioned"),
                        "GST/PST/WCB": eval_data.get("gst_pst_wcb", "Not Mentioned"),
                        "Government Filing": eval_data.get("government_filing", "Not Mentioned"),
                        "Software": eval_data.get("software", "Not Mentioned"),
                        "Client Interaction": eval_data.get("client_interaction", "Not Mentioned"),
                        "Other Requirements": eval_data.get("other_requirements", "Not Mentioned"),
                        "Score": eval_data.get("suitability_score", 50),
                        "Recommendation": eval_data.get("recommendation", "N/A"),
                        "Apply Link": apply_link,
                        "Gaps / Roadmap": eval_data.get("gaps_roadmap", "None")
                    })
                    progress_bar.progress(int((idx + 1) / len(selected_jobs) * 100))
                    
                # Post to Google Sheets
                if evaluated_rows:
                    with st.spinner("📊 Posting ranked listings to Google Sheets..."):
                        client = sheets_helper.get_gspread_client()
                        if client:
                            spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                            if spreadsheet:
                                sheet_name = "Ranked_Job_Alerts"
                                headers = ["Date Found", "Source", "Job Title", "Company", "Location", "Salary", "Employment Type", "Work Mode", "Experience Required", "Education", "CPA Requirement", "Tax Experience", "Financial Statements", "Year-End", "Payroll", "GST/PST/WCB", "Government Filing", "Software", "Client Interaction", "Other Requirements", "Score", "Recommendation", "Apply Link", "Gaps / Roadmap"]
                                try:
                                    wks = spreadsheet.worksheet(sheet_name)
                                    existing_rows = wks.get_all_records()
                                    existing_keys = {f"{r.get('Job Title','')}|{r.get('Company','')}".strip().lower() for r in existing_rows}
                                    
                                    # Ensure headers contain critical columns
                                    first_row = wks.row_values(1)
                                    if "Work Mode" not in first_row or "GST/PST/WCB" not in first_row or "Gaps / Roadmap" not in first_row:
                                        for col_idx, header_val in enumerate(headers, 1):
                                            try:
                                                wks.update_cell(1, col_idx, header_val)
                                            except:
                                                pass
                                except Exception:
                                    wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(headers)))
                                    wks.append_row(headers)
                                    existing_keys = set()
                                    
                                rows_to_add = []
                                for r in evaluated_rows:
                                    key = f"{r['Job Title']}|{r['Company']}".strip().lower()
                                    if key in existing_keys:
                                        continue
                                    rows_to_add.append([
                                        r["Date Found"], r["Source"], r["Job Title"], r["Company"], r["Location"],
                                        r["Salary"], r["Employment Type"], r["Work Mode"], r["Experience Required"],
                                        r["Education"], r["CPA Requirement"], r["Tax Experience"], r["Financial Statements"],
                                        r["Year-End"], r["Payroll"], r["GST/PST/WCB"], r["Government Filing"],
                                        r["Software"], r["Client Interaction"], r["Other Requirements"],
                                        str(r["Score"]), r["Recommendation"], f'=HYPERLINK("{r["Apply Link"]}", "Apply")',
                                        r.get("Gaps / Roadmap", "None")
                                    ])
                                if rows_to_add:
                                    wks.append_rows(rows_to_add, value_input_option="USER_ENTERED")
                                    st.success(f"🎉 Successfully posted {len(rows_to_add)} new ranked listings to your Google Sheet '{sheet_name}'!")
                                else:
                                    st.info("ℹ️ All alerts parsed are already synced to the Google Sheet.")
                                    
                    st.session_state["jobs_scraped_links"] = []  # Clear processed queue
                    
                    st.subheader("📋 Scraping & Suitability Analysis Results")
                    for r in evaluated_rows:
                        st.markdown(f"### **{r['Job Title']}** at **{r['Company']}**")
                        st.write(f"- **Match Score**: **{r['Score']}%** ({r['Recommendation']})")
                        st.write(f"- **Location**: {r['Location']} | **Source**: {r['Source']}")
                        st.write(f"- **Work Mode**: {r['Work Mode']} | **Employment Type**: {r['Employment Type']}")
                        st.write(f"- **Salary**: {r['Salary']}")
                        st.write(f"- **Software**: {r['Software']}")
                        st.write(f"- **Tax Experience**: {r['Tax Experience']}")
                        # Extracted formula contains '=HYPERLINK("url", "Apply")', extract the clean url to link in st.write
                        clean_url = r['Apply Link']
                        if 'HYPERLINK' in clean_url:
                            # Extract url from '=HYPERLINK("url", "Apply")'
                            try:
                                clean_url = clean_url.split('"')[1]
                            except:
                                pass
                        st.write(f"- [Apply Link]({clean_url})")
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
    
    col_gap_btn1, col_gap_btn2 = st.columns(2)
    with col_gap_btn1:
        analyze_gap_btn = st.button("🔍 Analyze Skill Gaps & Generate Roadmap", type="secondary", use_container_width=True)
    with col_gap_btn2:
        analyze_save_btn = st.button("🚀 Analyze & Save to Google Sheets", type="primary", use_container_width=True)
    
    if analyze_gap_btn or analyze_save_btn:
        cand_profile = load_profile()
        job_desc = ""
        
        if job_desc_input.strip():
            job_desc = job_desc_input.strip()
        elif job_url_input:
            with st.spinner("🌐 Attempting to fetch job details from URL..."):
                fetched_desc = scrape_job_url(job_url_input)
                if fetched_desc:
                    job_desc = fetched_desc
                    st.success("🎉 Successfully fetched job description from URL!")
                else:
                    st.warning("⚠️ Could not scrape the URL automatically. Please make sure the URL is valid or paste the description text directly in the box below.")
            
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

                Analyze suitability. Output STRICTLY in JSON format:
                {{
                  "job_title": "extracted job title",
                  "company": "extracted company",
                  "location": "extracted location if found, otherwise 'Not specified'",
                  "salary": "extracted salary if found, otherwise 'Not Mentioned'",
                  "employment_type": "Full-Time, Part-Time, Contract, otherwise 'Not Mentioned'",
                  "work_mode": "On-site, Remote, Hybrid, otherwise 'Not Mentioned'",
                  "experience_required": "Years of experience required, otherwise 'Not Mentioned'",
                  "education": "Required education, otherwise 'Not Mentioned'",
                  "cpa_requirement": "CPA requirement status, otherwise 'Not Mentioned'",
                  "tax_experience": "T1, T2 tax prep requirements, otherwise 'Not Mentioned'",
                  "financial_statements": "Yes or No",
                  "year_end": "Yes or No",
                  "payroll": "Yes or No",
                  "gst_pst_wcb": "GST, PST, WCB requirements, otherwise 'Not Mentioned'",
                  "government_filing": "CRA Online Filing, etc., otherwise 'Not Mentioned'",
                  "software": "CaseWare, Excel, QuickBooks, etc., otherwise 'Not Mentioned'",
                  "client_interaction": "Yes or No",
                  "other_requirements": "PR Card, reliable vehicle, etc., otherwise 'Not Mentioned'",
                  "suitability_score": 75,
                  "recommendation": "Strong Match or Growth Match or Weak Match",
                  "skills_required": ["skill 1", "skill 2"],
                  "matching_skills": ["skill A", "skill B"],
                  "missing_skills": ["skill X", "skill Y"],
                  "learning_roadmap": {{
                    "skill X": "specific action item to learn skill X",
                    "skill Y": "specific action item to learn skill Y"
                  }}
                }}
                
                CRITICAL CONSTRAINT RULE: If the job description explicitly lists a language fluency requirement (e.g. Mandarin, Cantonese, French, Punjabi) that the candidate's resume/profile does not list or support, treat this as a CRITICAL unmet hard constraint. Reduce the suitability_score below 40% and set the recommendation to "Weak Match" or "Not Suitable".
                
                Only return valid JSON. Do not include markdown code blocks or formatting.
                """
                try:
                    res = query_gemini(prompt, response_json=True)
                    if not res:
                        st.error("❌ Failed to analyze skill gaps.")
                    else:
                        gap_data = json.loads(res.strip())
                        st.session_state["gap_data"] = gap_data
                        st.session_state["gap_job_desc"] = job_desc
                        st.session_state["gap_url"] = job_url_input
                        
                        if analyze_save_btn:
                            with st.spinner("📊 Posting to Google Sheets..."):
                                client = sheets_helper.get_gspread_client()
                                if client:
                                    spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                                    if spreadsheet:
                                        sheet_name = "Ranked_Job_Alerts"
                                        headers = ["Date Found", "Source", "Job Title", "Company", "Location", "Salary", "Employment Type", "Work Mode", "Experience Required", "Education", "CPA Requirement", "Tax Experience", "Financial Statements", "Year-End", "Payroll", "GST/PST/WCB", "Government Filing", "Software", "Client Interaction", "Other Requirements", "Score", "Recommendation", "Apply Link", "Gaps / Roadmap"]
                                        try:
                                            wks = spreadsheet.worksheet(sheet_name)
                                            first_row = wks.row_values(1)
                                            if "Work Mode" not in first_row or "GST/PST/WCB" not in first_row or "Gaps / Roadmap" not in first_row:
                                                for col_idx, header_val in enumerate(headers, 1):
                                                    try:
                                                        wks.update_cell(1, col_idx, header_val)
                                                    except:
                                                        pass
                                        except Exception:
                                            wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(headers)))
                                            wks.append_row(headers)
                                            
                                        gaps_val = "Gaps: " + ", ".join(gap_data.get("missing_skills", []))
                                        roadmap_details = "; ".join([f"How to learn {k}: {v}" for k, v in gap_data.get("learning_roadmap", {}).items()])
                                        gaps_roadmap_val = f"{gaps_val} | Roadmap: {roadmap_details}" if roadmap_details else gaps_val
                                        
                                        row = [
                                            datetime.now().strftime("%Y-%m-%d"),
                                            "Direct URL" if job_url_input else "Manual Paste",
                                            gap_data.get("job_title", "Unknown Title"),
                                            gap_data.get("company", "Unknown Company"),
                                            gap_data.get("location", "Unknown Location"),
                                            gap_data.get("salary", "Not Mentioned"),
                                            gap_data.get("employment_type", "Not Mentioned"),
                                            gap_data.get("work_mode", "Not Mentioned"),
                                            gap_data.get("experience_required", "Not Mentioned"),
                                            gap_data.get("education", "Not Mentioned"),
                                            gap_data.get("cpa_requirement", "Not Mentioned"),
                                            gap_data.get("tax_experience", "Not Mentioned"),
                                            gap_data.get("financial_statements", "Not Mentioned"),
                                            gap_data.get("year_end", "Not Mentioned"),
                                            gap_data.get("payroll", "Not Mentioned"),
                                            gap_data.get("gst_pst_wcb", "Not Mentioned"),
                                            gap_data.get("government_filing", "Not Mentioned"),
                                            gap_data.get("software", "Not Mentioned"),
                                            gap_data.get("client_interaction", "Not Mentioned"),
                                            gap_data.get("other_requirements", "Not Mentioned"),
                                            str(gap_data.get("suitability_score", 50)),
                                            gap_data.get("recommendation", "N/A"),
                                            f'=HYPERLINK("{job_url_input}", "Apply")' if job_url_input else "N/A",
                                            gaps_roadmap_val
                                        ]
                                        try:
                                            wks.append_row(row, value_input_option="USER_ENTERED")
                                            st.success("🎉 Successfully posted and saved this job to your Google Sheet!")
                                        except Exception as err:
                                            st.error(f"❌ Failed to append row: {err}")
                except Exception as e:
                    st.error(f"❌ Failed to parse gap analysis: {e}")
                    
    # Render results from session state if available
    if "gap_data" in st.session_state:
        gap_data = st.session_state["gap_data"]
        job_desc = st.session_state["gap_job_desc"]
        job_url_input = st.session_state.get("gap_url", "")
        
        st.subheader(f"📊 Analysis: {gap_data.get('job_title', 'Job')} at {gap_data.get('company', 'Employer')}")
        st.metric("Suitability Score", f"{gap_data.get('suitability_score', 0)}%")
        
        with st.expander("📄 View Extracted Job Description & Details", expanded=False):
            st.markdown(f"**Extracted Job Title**: {gap_data.get('job_title', 'Not specified')}")
            st.markdown(f"**Extracted Company**: {gap_data.get('company', 'Not specified')}")
            st.markdown(f"**Extracted Location**: {gap_data.get('location', 'Not specified')}")
            st.text_area("Extracted Text Content", value=job_desc, height=250, disabled=True)
            
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
            
        st.write("---")
        st.subheader("💾 Save to Google Sheets")
        save_btn = st.button("📤 Post this Job & Analysis to Google Sheets", key="save_gap_to_sheet")
        
        if save_btn:
            with st.spinner("📊 Posting to Google Sheets..."):
                client = sheets_helper.get_gspread_client()
                if client:
                    spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                    if spreadsheet:
                        sheet_name = "Ranked_Job_Alerts"
                        headers = ["Date Found", "Source", "Job Title", "Company", "Location", "Salary", "Employment Type", "Work Mode", "Experience Required", "Education", "CPA Requirement", "Tax Experience", "Financial Statements", "Year-End", "Payroll", "GST/PST/WCB", "Government Filing", "Software", "Client Interaction", "Other Requirements", "Score", "Recommendation", "Apply Link", "Gaps / Roadmap"]
                        try:
                            wks = spreadsheet.worksheet(sheet_name)
                            first_row = wks.row_values(1)
                            if "Work Mode" not in first_row or "GST/PST/WCB" not in first_row or "Gaps / Roadmap" not in first_row:
                                for col_idx, header_val in enumerate(headers, 1):
                                    try:
                                        wks.update_cell(1, col_idx, header_val)
                                    except:
                                        pass
                        except Exception:
                            wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(headers)))
                            wks.append_row(headers)
                            
                        gaps_val = "Gaps: " + ", ".join(gap_data.get("missing_skills", []))
                        roadmap_details = "; ".join([f"How to learn {k}: {v}" for k, v in gap_data.get("learning_roadmap", {}).items()])
                        gaps_roadmap_val = f"{gaps_val} | Roadmap: {roadmap_details}" if roadmap_details else gaps_val
                        
                        row = [
                            datetime.now().strftime("%Y-%m-%d"),
                            "Direct URL" if job_url_input else "Manual Paste",
                            gap_data.get("job_title", "Unknown Title"),
                            gap_data.get("company", "Unknown Company"),
                            gap_data.get("location", "Unknown Location"),
                            gap_data.get("salary", "Not Mentioned"),
                            gap_data.get("employment_type", "Not Mentioned"),
                            gap_data.get("work_mode", "Not Mentioned"),
                            gap_data.get("experience_required", "Not Mentioned"),
                            gap_data.get("education", "Not Mentioned"),
                            gap_data.get("cpa_requirement", "Not Mentioned"),
                            gap_data.get("tax_experience", "Not Mentioned"),
                            gap_data.get("financial_statements", "Not Mentioned"),
                            gap_data.get("year_end", "Not Mentioned"),
                            gap_data.get("payroll", "Not Mentioned"),
                            gap_data.get("gst_pst_wcb", "Not Mentioned"),
                            gap_data.get("government_filing", "Not Mentioned"),
                            gap_data.get("software", "Not Mentioned"),
                            gap_data.get("client_interaction", "Not Mentioned"),
                            gap_data.get("other_requirements", "Not Mentioned"),
                            str(gap_data.get("suitability_score", 50)),
                            gap_data.get("recommendation", "N/A"),
                            f'=HYPERLINK("{job_url_input}", "Apply")' if job_url_input else "N/A",
                            gaps_roadmap_val
                        ]
                        try:
                            wks.append_row(row, value_input_option="USER_ENTERED")
                            st.success("🎉 Successfully posted and saved this job to your Google Sheet!")
                        except Exception as err:
                            st.error(f"❌ Failed to append row: {err}")

with tab_tailor:
    st.subheader("📄 ATS-Friendly Resume Tailor")
    st.markdown("Instantly adapt your base resume to highlight matching skills and keywords for a specific job description.")
    
    cand_profile = load_profile()
    base_resume_text = cand_profile.get("resume", "")
    
    st.markdown("### 1. Select Target Job")
    job_option = st.radio("Target Job Source", ["Choose from Google Sheet", "Paste Job Details manually"], key="tailor_source")
    
    target_job_desc = ""
    target_job_title = ""
    target_company = ""
    
    if job_option == "Choose from Google Sheet":
        gmail_saved = {}
        try:
            with open("gmail_config.json", "r", encoding="utf-8") as f:
                gmail_saved = json.load(f)
        except:
            pass
        sheet_url = st.session_state.get("google_spreadsheet_id", gmail_saved.get("sheet_url", st.secrets.get("google_spreadsheet_id", "")))
        
        if not sheet_url:
            st.warning("⚠️ Google Spreadsheet URL is not set. Please set it in the sidebar or Gmail Alert Scanner tab.")
        else:
            try:
                client = sheets_helper.get_gspread_client()
                if client:
                    spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                    if spreadsheet:
                        wks = spreadsheet.worksheet("Ranked_Job_Alerts")
                        records = wks.get_all_records()
                        if not records:
                            st.info("ℹ️ No jobs found in your Google Sheet yet.")
                        else:
                            job_labels = [f"{r.get('Job Title','Unknown')} at {r.get('Company','Unknown')} ({r.get('Date Found','')})" for r in records]
                            selected_label_idx = st.selectbox("Select job to tailor for", range(len(job_labels)), format_func=lambda x: job_labels[x], key="tailor_select_job")
                            selected_record = records[selected_label_idx]
                            
                            target_job_title = selected_record.get('Job Title', 'Unknown Title')
                            target_company = selected_record.get('Company', 'Unknown Company')
                            
                            apply_link = selected_record.get('Apply Link', '')
                            if 'HYPERLINK' in apply_link:
                                try:
                                    apply_link = apply_link.split('"')[1]
                                except:
                                    pass
                                    
                            if apply_link and apply_link != "N/A":
                                st.write(f"🔗 Job Apply Link: {apply_link}")
                                
                            if apply_link and apply_link != "N/A":
                                fetch_btn = st.button("🌐 Fetch Job Details from Link", key="tailor_fetch_link", use_container_width=True)
                                if fetch_btn:
                                    with st.spinner("Fetching job details..."):
                                        fetched = scrape_job_url(apply_link)
                                        if fetched:
                                            st.session_state["tailor_job_desc"] = fetched
                                            st.success("🎉 Successfully fetched job description!")
                                            st.rerun()
                                        else:
                                            st.error("❌ Failed to scrape the URL automatically. Please copy-paste the job text below.")
                            
                            target_job_desc = st.text_area("Job Description Details", value=st.session_state.get("tailor_job_desc", ""), height=150, key="tailor_sheet_desc")
            except Exception as e:
                st.error(f"❌ Failed to load jobs from Google Sheets: {e}")
    else:
        col_t_title, col_t_comp = st.columns(2)
        with col_t_title:
            target_job_title = st.text_input("Target Job Title", placeholder="e.g. Junior Accountant", key="t_title")
        with col_t_comp:
            target_company = st.text_input("Target Company", placeholder="e.g. Vasto Builders Inc.", key="t_company")
            
        target_job_desc = st.text_area("Paste Job Description details here", height=150, key="tailor_manual_desc")
        
    if target_job_desc and target_job_desc.strip():
        # Reset trigger if job description changes
        if target_job_desc != st.session_state.get("tailor_prev_desc", ""):
            st.session_state["tailor_extracted_triggered"] = False
            st.session_state["tailor_prev_desc"] = target_job_desc
            
        extract_btn = st.button("🔍 Extract Job Requirements (ATS Focus)", use_container_width=True, key="tailor_extract_ats_btn")
        if extract_btn:
            st.session_state["tailor_extracted_triggered"] = True
            
        if st.session_state.get("tailor_extracted_triggered", False):
            import utils.job_extraction as job_extraction
            extracted_info = job_extraction.apply_evidence_rules(target_job_desc, {})
            with st.expander("🔍 Extracted Job Requirements (ATS Focus)", expanded=True):
                st.markdown("Here is the key matching information extracted from the job description:")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**💼 Experience:** {extracted_info.get('experience_required', 'Not Mentioned')}")
                    st.markdown(f"**🎓 Education:** {extracted_info.get('education', 'Not Mentioned')}")
                    st.markdown(f"**📜 CPA Requirement:** {extracted_info.get('cpa_requirement', 'Not Mentioned')}")
                    st.markdown(f"**🖥️ Software Required:** {extracted_info.get('software', 'Not Mentioned')}")
                with col2:
                    st.markdown(f"**📊 Work Mode:** {extracted_info.get('work_mode', 'Not Mentioned')} ({extracted_info.get('employment_type', 'Not Mentioned')})")
                    st.markdown(f"**💵 Salary:** {extracted_info.get('salary', 'Not Mentioned')}")
                    st.markdown(f"**📝 Tax Experience:** {extracted_info.get('tax_experience', 'Not Mentioned')}")
                    st.markdown(f"**🤝 Client Interaction:** {extracted_info.get('client_interaction', 'No')}")

    st.markdown("### 2. Base Resume / Qualifications")
    editable_resume = st.text_area("Your Base Resume (Loaded from profile)", value=base_resume_text, height=200, key="tailor_base_resume")
    
    st.button(
        "🔄 Sync/Reload from Google Sheet",
        key="tailor_reload_profile_btn",
        use_container_width=True,
        on_click=sync_tailor_resume_from_google_sheet,
    )
    if st.session_state.pop("tailor_sync_success", False):
        st.success("🎉 Base resume successfully reloaded from Google Sheets!")
    tailor_sync_error = st.session_state.pop("tailor_sync_error", None)
    if tailor_sync_error:
        st.error(f"❌ Base resume reload failed: {tailor_sync_error}")
    
    st.markdown("### 3. Generate Tailored Resume")
    tailor_btn = st.button("✨ Tailor my Resume for this Job", type="primary", use_container_width=True)
    if tailor_btn:
        if not target_job_desc.strip():
            st.error("❗ Please select or paste the target job description details first!")
        elif not editable_resume.strip():
            st.error("❗ Please provide your base resume text!")
        elif not gemini_key:
            st.error("🔑 Please enter your Google AI Studio API Key in the sidebar first!")
        else:
            with st.spinner("🤖 Adaptively rewriting experience and optimizing keywords..."):
                raw_phone = cand_profile.get('candidate_phone', '604-440-9885')
                formatted_phone = raw_phone if raw_phone.lower().startswith('ph') else f"Ph: {raw_phone}"
                
                prompt = f"""
                You are a professional resume writer and ATS optimization expert.
                Your task is to tailor the candidate's resume to match the target job description.
                
                Candidate Contact Details:
                - Name: {cand_profile.get('candidate_name', 'Raman Deep Kumar')}
                - Phone: {formatted_phone}
                - Email: {cand_profile.get('candidate_email', 'beedhtaxservices@outlook.com')}
                - LinkedIn: {cand_profile.get('candidate_linkedin', 'https://www.linkedin.com/feed/')}
                
                Candidate Profile & Base Resume:
                {editable_resume}
                
                Target Job Description:
                - Title: {target_job_title}
                - Company: {target_company}
                - Content: {target_job_desc}
                
                Instructions:
                1. Name & Single-Line Contact Header: Always use the name 'Raman Deep Kumar' (with proper capitalization). Immediately after the name, format the contact details on a SINGLE line using vertical bars '|' as separators. Use the email and LinkedIn handle. Example structure:
                   Ph: 604-440-9885 | beedhtaxservices@outlook.com | linkedin.com/in/ramanbeedh
                   Do NOT split the contact info onto multiple lines, and do NOT use placeholders.
                2. Professional Experience Structure: Format the work history as a proper 'Professional Experience' section (do NOT use generic titles like 'Professional Experience Highlights').
                3. Verified Employer Facts: For the current role at Raman Tax & Accounting Inc., you must ALWAYS include the exact employer name, location, job title, and dates:
                   - Title: FULL-CYCLE BOOKKEEPER
                   - Company: Raman Tax & Accounting Inc.
                   - Location: Surrey, BC
                   - Dates: 2020–Present
                   Explain that the candidate handled multiple client companies through Raman Tax & Accounting Inc. Do NOT present those clients as separate employers.
                4. Experience & Bullet Tailoring: Tailor and reorder the bullet points to align with the target job description (e.g. highlighting QuickBooks, tax returns, bank reconciliations, payroll, or GST/HST/PST where relevant). Do NOT alter the verified facts or invent achievements, metrics, numbers, software, or experience not present in the base resume. Only include software or skills that are explicitly present in the candidate's profile or base resume (never hallucinate software like CaseWare).
                5. ATS-Safe Layout:
                   - Do NOT include any visible horizontal rule separators (such as '---').
                   - Use standard bullets (like '-') and keep them concise (ideally 3-4 bullet points per job, maximum 1-2 lines per bullet).
                   - Ensure the layout is clean, compact, and fits the entire resume onto exactly one page. Education, Certifications, and Skills must fit on page 1.
                   - Include clear, capitalized headers for main sections (e.g. PROFESSIONAL SUMMARY, PROFESSIONAL EXPERIENCE, EDUCATION, CERTIFICATIONS, TECHNICAL SKILLS).
                6. Only return the tailored resume. Do not include introductory or concluding remarks.
                """
                try:
                    tailored_res = query_gemini(prompt, response_json=False)
                    if tailored_res:
                        st.session_state["tailored_resume_text"] = tailored_res
                    else:
                        st.error("❌ Failed to tailor resume.")
                        
                    cover_prompt = f"""
                    You are a professional cover letter writer and job application coach.
                    Your task is to write a highly compelling, professional cover letter tailored to the target job description based on the candidate's resume/profile.
                    
                    Candidate Contact Information:
                    - Name: {cand_profile.get('candidate_name', 'Raman Deep Kumar')}
                    - Phone: {formatted_phone}
                    - Email: {cand_profile.get('candidate_email', 'beedhtaxservices@outlook.com')}
                    - LinkedIn: {cand_profile.get('candidate_linkedin', 'https://www.linkedin.com/feed/')}
                    - Today's Date: {datetime.now().strftime("%B %d, %Y")}
                    
                    Candidate Profile & Resume:
                    {editable_resume}
                    
                    Target Job Description:
                    - Title: {target_job_title}
                    - Company: {target_company}
                    - Content: {target_job_desc}
                    
                    Instructions:
                    1. Format the cover letter professionally with standard contact info blocks. Use Today's Date: {datetime.now().strftime("%B %d, %Y")} directly at the very top. Do NOT write placeholders like '[Current Date]'.
                    2. Use the provided contact details at the top header (with the phone number prefixed as '{formatted_phone}') and in the closing sign-off block.
                    3. Explicitly tie the candidate's matching accomplishments (e.g. QuickBooks, T1/T2 tax preparation, bookkeeping) to the specific challenges/requirements of the job description. Do NOT mention any software or skills (such as CaseWare) that are not present in the candidate's resume/profile.
                    4. Address key requirements and qualifications from the listing. Make it engaging, professional, and convincing.
                    5. Keep it under one page (around 250-350 words).
                    
                    Only return the cover letter text. Do not include extra markdown comments or introductory conversational remarks.
                    """
                    tailored_cover = query_gemini(cover_prompt, response_json=False)
                    if tailored_cover:
                        st.session_state["tailored_cover_letter_text"] = tailored_cover
                        st.success("🎉 Successfully generated tailored Resume & Cover Letter!")
                    else:
                        st.error("❌ Failed to generate cover letter.")
                except Exception as err:
                    st.error(f"❌ Error during document tailoring: {err}")
                    
    if "tailored_resume_text" in st.session_state:
        st.write("---")
        st.subheader("✨ Generated Application Documents")
        
        tab_res_out, tab_cl_out = st.tabs(["📝 Tailored Resume", "✉️ Tailored Cover Letter"])
        
        with tab_res_out:
            clean_title = "".join(c for c in target_job_title.replace("/", "_").replace("\\", "_").replace(" ", "_") if c.isalnum() or c in ["_", "-"])
            st.markdown(st.session_state["tailored_resume_text"])
            col_res_down1, col_res_down2 = st.columns(2)
            with col_res_down1:
                st.download_button(
                    label="💾 Download Tailored Resume (.md)",
                    data=st.session_state["tailored_resume_text"],
                    file_name=f"Raman_{clean_title}_Resume.md",
                    mime="text/markdown",
                    use_container_width=True,
                    key="dl_res_md"
                )
            with col_res_down2:
                try:
                    pdf_res_data = convert_markdown_to_pdf(st.session_state["tailored_resume_text"])
                    st.download_button(
                        label="📄 Download Tailored Resume (.pdf)",
                        data=pdf_res_data.getvalue(),
                        file_name=f"Raman_{clean_title}_Resume.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key="dl_res_pdf"
                    )
                except Exception as pe:
                    st.error(f"⚠️ Failed to generate Resume PDF: {pe}")
                    
        with tab_cl_out:
            if "tailored_cover_letter_text" in st.session_state:
                st.markdown(st.session_state["tailored_cover_letter_text"])
                col_cl_down1, col_cl_down2 = st.columns(2)
                with col_cl_down1:
                    st.download_button(
                        label="💾 Download Cover Letter (.md)",
                        data=st.session_state["tailored_cover_letter_text"],
                        file_name=f"Raman_{clean_title}_Cover_Letter.md",
                        mime="text/markdown",
                        use_container_width=True,
                        key="dl_cl_md"
                    )
                with col_cl_down2:
                    try:
                        pdf_cl_data = convert_markdown_to_pdf(st.session_state["tailored_cover_letter_text"])
                        st.download_button(
                            label="📄 Download Cover Letter (.pdf)",
                            data=pdf_cl_data.getvalue(),
                            file_name=f"Raman_{clean_title}_Cover_Letter.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="dl_cl_pdf"
                        )
                    except Exception as pe:
                        st.error(f"⚠️ Failed to generate Cover Letter PDF: {pe}")
            else:
                st.info("ℹ️ Cover letter details are not available. Re-run tailoring to generate it.")
