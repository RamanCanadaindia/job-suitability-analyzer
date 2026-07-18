import sys
sys.path.append('C:\\Users\\admin\\.gemini\\antigravity\\scratch\\job_suitability_analyzer')
import json
from datetime import datetime
from utils import gemini_helper
import sheets_helper
import gspread
from google.oauth2.service_account import Credentials

def main():
    # Load user profile
    with open('user_profile.json', 'r', encoding='utf-8') as f:
        cand_profile = json.load(f)
        
    # Load Gmail config for sheet URL
    with open('gmail_config.json', 'r', encoding='utf-8') as f:
        gmail_config = json.load(f)
    sheet_url = gmail_config["sheet_url"]
    
    # Load API keys from secrets.toml
    import toml
    secrets = toml.load('.streamlit/secrets.toml')
    gemini_key = secrets.get("GEMINI_API_KEY", "")
    gcp_json = secrets.get("gcp_service_account_json", "")
    
    job_title = "Junior Accountant"
    company = "Vasto Builders Inc."
    job_loc = "8543 Commerce Crt, Burnaby, BC V5A 4N4"
    source_board = "Indeed"
    apply_link = "https://ca.indeed.com/viewjob?jk=a5ecc4125ecf2a4d"
    
    full_desc = """
Junior Accountant
Vasto Builders Inc.
8543 Commerce Crt, Burnaby, BC V5A 4N4
$45,000–$55,000 a year - Permanent, Full-time
 
Job details
Pay
$45,000–$55,000 a year
Job type
Permanent
Full-time
Shift and schedule
Overtime
 
Location
8543 Commerce Crt, Burnaby, BC V5A 4N4
 
Benefits
Pulled from the full job description
Paid time off
Vision care
Dental care
Extended health care
On-site parking
 
Full job description
Who We Are
Vasto Builders is a fast-growing construction company based in Vancouver, specializing in design-build, general contracting, and development consulting. We partner with government and non-profit organizations to deliver high-quality, sustainable, and innovative building solutions. From multi-family housing to institutional and commercial projects, we are committed to excellence, collaboration, and community impact.

Key ResponsResponsibilities
Keep files, records, and financial documents well organized, both digitally and in hard copy.
Assist with purchasing and communicate with vendors for office supplies.
Assist with accounts payable and accounts receivable, including processing vendor invoices, subcontractor invoices, and customer billings.
Review invoices, receipts, purchase orders, and supporting documents to ensure accuracy and proper coding to the correct project or cost category.
Maintain organized accounting records for construction projects, including contracts, change orders, invoices, payment certificates, and backup documents.
Prepare and process payments to vendors, subcontractors, and suppliers in accordance with company procedures and approval requirements.
Assist with bank reconciliations, credit card reconciliations, and monthly accounting close procedures.
Support payroll, timesheet review, expense reimbursement, GST/PST filing, and other administrative accounting tasks as needed.
Communicate with vendors regarding billing issues and invoicing issues.
Review site labour's timesheets and calculate wages, overtime, and applicable allowances.
Assist with T2 filling.

Qualifications
Fluent in Mandarin and English
Degree or diploma in Finance/Accounting, or a related field.
At least 3 years of experience in Accounting, or related field.
Advanced Excel skills and familiar with QuickBooks are required.
Hold a valid driver license and own a reliable vehicle.
Strong attention to detail.
Excellent organizational skills with the ability to handle multiple priorities.
Strong written and verbal communication skills.
Interest in the building construction field is a plus, but not required.

Pay: $45,000.00-$55,000.00 per year
Benefits:
Dental care
Extended health care
On-site parking
Paid time off
Vision care
Experience:
Accounting: 3 years (preferred)
Language:
Mandarin (preferred)
Work Location: In person
"""
    
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
      "salary": "Salary or pay range, otherwise 'Not Mentioned'"
    }}
    Only return valid JSON.
    """
    
    import os
    os.environ["GEMINI_API_KEY"] = gemini_key
    gemini_res = gemini_helper.query_gemini(prompt, response_json=True)
    eval_data = json.loads(gemini_res.strip())
    
    print("Connecting to Google Sheets...")
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
    headers = ["Date Found", "Source", "Job Title", "Company", "Location", "Salary", "Employment Type", "Work Mode", "Experience Required", "Education", "CPA Requirement", "Tax Experience", "Financial Statements", "Year-End", "Payroll", "GST/PST/WCB", "Government Filing", "Software", "Client Interaction", "Other Requirements", "Score", "Recommendation", "Apply Link"]
    
    try:
        wks = spreadsheet.worksheet(sheet_name)
        existing_rows = wks.get_all_records()
        existing_keys = {f"{r.get('Job Title','')}|{r.get('Company','')}".strip().lower() for r in existing_rows}
        
        # Ensure headers contain critical columns non-destructively
        first_row = wks.row_values(1)
        if "Work Mode" not in first_row or "GST/PST/WCB" not in first_row:
            for col_idx, header_val in enumerate(headers, 1):
                try:
                    wks.update_cell(1, col_idx, header_val)
                except:
                    pass
    except Exception:
        wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(headers)))
        wks.append_row(headers)
        existing_keys = set()

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
        f'=HYPERLINK("{apply_link}", "Apply")'
    ]
    
    print("Appending evaluated row to Google Sheets...")
    wks.append_row(row, value_input_option="USER_ENTERED")
    print("✅ Success!")

if __name__ == '__main__':
    main()
