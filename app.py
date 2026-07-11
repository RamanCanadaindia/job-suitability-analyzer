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
    except Exception as e:
        st.error(f"Failed to save profile: {e}")

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

st.sidebar.markdown("---")
st.sidebar.markdown("### How to use:")
st.sidebar.info("""
1. Fill out your **Candidate Profile** in the main tab (skills, target titles, resume).
2. Enter your job search keywords and location.
3. Click **Search & Rank Jobs** to fetch listings via SerpAPI and grade them using Gemini AI.
""")

# Tabs
tab_profile, tab_search = st.tabs(["👤 Candidate Profile", "🔍 Job Search & Ranking"])

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
