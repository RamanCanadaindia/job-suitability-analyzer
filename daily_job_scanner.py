import os
import re
import toml
import json
import imaplib
import email
from email.header import decode_header
from datetime import datetime
import time
from playwright.sync_api import sync_playwright
from utils.job_extraction import apply_evidence_rules
from google.oauth2.service_account import Credentials
import gspread
import urllib.request
import urllib.parse
import urllib.error

# Load Secrets and Configs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.path.join(BASE_DIR, ".streamlit", "secrets.toml")
GMAIL_CONFIG_PATH = os.path.join(BASE_DIR, "gmail_config.json")
PROFILE_PATH = os.path.join(BASE_DIR, "user_profile.json")

def load_secrets():
    if os.path.exists(SECRETS_PATH):
        try:
            return toml.load(SECRETS_PATH)
        except Exception as e:
            print(f"Error loading secrets.toml: {e}")
    return {}

def load_gmail_config():
    if os.path.exists(GMAIL_CONFIG_PATH):
        try:
            with open(GMAIL_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading gmail_config.json: {e}")
    return {}

def load_profile():
    # 1. Start with defaults
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
    
    # 2. Load from local file user_profile.json
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                for k in profile.keys():
                    if local_data.get(k):
                        profile[k] = local_data[k]
        except Exception as e:
            print(f"Error loading user_profile.json: {e}")
            
    # 3. Load from Google Sheets if we can (to allow syncing when running online/headless)
    try:
        gmail_cfg = load_gmail_config()
        sheet_url = gmail_cfg.get("sheet_url")
        
        # Get credentials
        secrets = load_secrets()
        gcp_json_str = secrets.get("gcp_service_account_json")
        gcp_acc = secrets.get("gcp_service_account")
        
        credentials_dict = None
        if gcp_json_str:
            credentials_dict = json.loads(gcp_json_str, strict=False)
        elif gcp_acc:
            credentials_dict = dict(gcp_acc)
            
        if credentials_dict and sheet_url:
            if "private_key" in credentials_dict:
                credentials_dict["private_key"] = credentials_dict["private_key"].replace("\\n", "\n")
            
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            client = gspread.authorize(creds)
            
            # Resolve sheet ID if URL
            spreadsheet_id = sheet_url
            if "docs.google.com/spreadsheets" in str(sheet_url):
                parts = str(sheet_url).split("/d/")
                if len(parts) > 1:
                    spreadsheet_id = parts[1].split("/")[0]
                    
            spreadsheet = client.open_by_key(spreadsheet_id)
            try:
                wks = spreadsheet.worksheet("Candidate_Profile")
                records = wks.get_all_records()
                if records:
                    row = records[0]
                    for k in profile.keys():
                        val = row.get(k) or row.get(k.replace("candidate_", ""))
                        if val:
                            profile[k] = str(val)
            except gspread.exceptions.WorksheetNotFound:
                pass
    except Exception as e:
        print(f"Daily scanner failed to load profile from Google Sheets: {e}")
        
    return profile

def query_gemini(prompt, api_key, response_json=False):
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash-latest", "gemini-1.5-flash"]
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if response_json:
            payload["generationConfig"] = {"responseMimeType": "application/json"}
            
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=req_data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
        except urllib.error.HTTPError as he:
            if he.code == 429:
                time.sleep(37)
                try:
                    with urllib.request.urlopen(req, timeout=15) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        candidates = res_data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                except:
                    pass
            elif he.code in (404, 400, 503):
                continue
    return None

def run_pipeline():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Automated Job Suitability Scan...")
    
    secrets = load_secrets()
    gmail_cfg = load_gmail_config()
    profile = load_profile()
    
    api_key = secrets.get("GEMINI_API_KEY")
    gmail_user = gmail_cfg.get("gmail_user")
    gmail_password = gmail_cfg.get("gmail_password")
    sheet_url = gmail_cfg.get("sheet_url")
    gcp_json = secrets.get("gcp_service_account_json")
    
    if not api_key or not gmail_user or not gmail_password or not sheet_url or not gcp_json:
        print("❌ Error: Missing configuration credentials. Ensure secrets.toml and config files are valid.")
        return
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_user, gmail_password)
        mail.select("inbox")
    except Exception as e:
        print(f"❌ Failed to connect to Gmail: {e}")
        return
        
    seen_ids = set()
    alert_emails = []
    
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
        print("ℹ️ No recent job alert emails (Indeed, Glassdoor, LinkedIn) found.")
        mail.logout()
        return
        
    # Scan the 5 most recent emails to prevent hitting limits
    alert_emails = sorted(alert_emails, key=lambda x: int(x[0]), reverse=True)[:5]
    print(f"Found {len(alert_emails)} recent job alert emails to process.")
    
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
                if part.get("Content-Disposition") and "attachment" in str(part.get("Content-Disposition")):
                    continue
                if content_type == "text/plain":
                    plain_content += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                elif content_type == "text/html":
                    html_content += part.get_payload(decode=True).decode("utf-8", errors="ignore")
        else:
            plain_content = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            
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
            if idx > 0:
                time.sleep(4.5)
            gemini_extracted = query_gemini(extract_prompt, api_key, response_json=True)
            if gemini_extracted:
                parsed_jobs = json.loads(gemini_extracted.strip())
                if isinstance(parsed_jobs, list):
                    for pj in parsed_jobs:
                        pj["source"] = source
                        if pj.get("apply_link") and pj.get("apply_link") != "https://www.google.com":
                            all_jobs_scraped.append(pj)
        except Exception as e:
            print(f"Error parsing email {idx+1}: {e}")
            
    mail.logout()
    
    if not all_jobs_scraped:
        print("ℹ️ No job links could be extracted from emails.")
        return
        
    print(f"Extracted {len(all_jobs_scraped)} total job links. Connecting to Google Sheets...")
    
    try:
        creds_dict = json.loads(gcp_json, strict=False)
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(creds)
        
        if "/" in sheet_url:
            spreadsheet = gc.open_by_url(sheet_url)
        else:
            spreadsheet = gc.open_by_key(sheet_url)
            
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
    except Exception as e:
        print(f"❌ Google Sheets Connection failed: {e}")
        return
        
    print("Starting Playwright headed scraper and Gemini analysis...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, http.proxy) Chrome/120.0.0.0 Safari/537.36"
        )
        
        for idx, job in enumerate(all_jobs_scraped):
            job_title = job.get("title", "Unknown Title")
            company = job.get("company", "Unknown Company")
            job_loc = job.get("location", "Unknown Location")
            apply_link = job.get("apply_link", "")
            source_board = job.get("source", "Indeed")
            
            key = f"{job_title}|{company}".strip().lower()
            if key in existing_keys:
                print(f"Skipping (Already Synced): {job_title} at {company}")
                continue
                
            print(f"Scraping: {job_title} at {company}...")
            
            full_desc = ""
            try:
                page = context.new_page()
                page.goto(apply_link, wait_until="domcontentloaded", timeout=45000)
                time.sleep(5)
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
                page.close()
            except Exception as e:
                print(f"Scraping failed for {job_title}: {e}")
                continue
                
            if not full_desc or len(full_desc.strip()) < 50:
                print(f"Skipping (Empty Description) for {job_title}")
                continue
                
            prompt = f"""
            Compare this job listing against the candidate's profile:
            Candidate Profile:
            - Target Titles: {profile.get('target_titles')}
            - Experience: {profile.get('experience')}
            - Core Skills: {profile.get('skills')}
            - Salary Target: {profile.get('salary')}
            - Resume details: {profile.get('resume')}

            Job Listing:
            - Title: {job_title}
            - Company: {company}
            - Location: {job_loc}
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
                time.sleep(2)
                gemini_res = query_gemini(prompt, api_key, response_json=True)
                eval_data = json.loads(gemini_res.strip())
            except Exception as e:
                print(f"Gemini Grading failed: {e}")
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
                
            row = [
                datetime.now().strftime("%Y-%m-%d"),
                source_board,
                job_title,
                company,
                job_loc,
                eval_data.get("salary", "Not Mentioned"),
                eval_data.get("employment_type", "Not Mentioned"),
                eval_data.get("work_mode", "Not Mentioned"),
                eval_data.get("experience_required", "Not Mentioned"),
                eval_data.get("education", "Not Mentioned"),
                eval_data.get("cpa_requirement", "Not Mentioned"),
                eval_data.get("tax_experience", "Not Mentioned"),
                eval_data.get("financial_statements", "Not Mentioned"),
                eval_data.get("year_end", "Not Mentioned"),
                eval_data.get("payroll", "Not Mentioned"),
                eval_data.get("gst_pst_wcb", "Not Mentioned"),
                eval_data.get("government_filing", "Not Mentioned"),
                eval_data.get("software", "Not Mentioned"),
                eval_data.get("client_interaction", "Not Mentioned"),
                eval_data.get("other_requirements", "Not Mentioned"),
                str(eval_data.get("suitability_score", 50)),
                eval_data.get("recommendation", "N/A"),
                f'=HYPERLINK("{apply_link}", "Apply")',
                eval_data.get("gaps_roadmap", "None")
            ]
            
            try:
                wks.append_row(row, value_input_option="USER_ENTERED")
                print(f"✅ Successfully posted and synced: {job_title} at {company} ({eval_data.get('suitability_score', 50)}% Match)")
            except Exception as sheet_err:
                print(f"❌ Failed to append row: {sheet_err}")
                
        browser.close()
        
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daily scan complete!")

if __name__ == "__main__":
    run_pipeline()
