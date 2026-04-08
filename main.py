from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

app = FastAPI()

LUSHA_API_KEY = os.getenv("LUSHA_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")


class CompanySignalRequest(BaseModel):
    company_name: str
    domain: str | None = None


class EnrichPersonRequest(BaseModel):
    full_name: str
    company: str | None = None
    linkedin_url: str | None = None


class EnrichCompanyRequest(BaseModel):
    company_name: str
    domain: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/company-signal")
def company_signal(data: CompanySignalRequest):
    if not PERPLEXITY_API_KEY:
        return {
            "company_name": data.company_name,
            "error": "Missing PERPLEXITY_API_KEY in .env"
        }

    prompt = f"""
You are analyzing a company for executive recruiting outreach.

Company: {data.company_name}
Domain: {data.domain or ''}

Return:
1. The 3 most relevant recent signals for outbound recruiting outreach
2. Why those signals matter
3. A one-paragraph why-now summary
4. Source links

Focus on:
- funding
- expansion
- product launches
- executive changes
- hiring intensity
- market entry
- partnerships
- regulatory developments

Ignore generic company descriptions.
"""

    try:
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar-pro",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a concise research assistant."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    },
                ],
            },
            timeout=45,
        )

        result = response.json()

        if "choices" not in result:
            return {
                "company_name": data.company_name,
                "error": "Perplexity did not return a normal completion response.",
                "status_code": response.status_code,
                "raw_response": result
            }

        text = result["choices"][0]["message"]["content"]

        return {
            "company_name": data.company_name,
            "signal_summary": text,
            "confidence": "medium"
        }

    except Exception as e:
        return {
            "company_name": data.company_name,
            "error": str(e)
        }


@app.post("/enrich-person")
def enrich_person(data: EnrichPersonRequest):
    if not LUSHA_API_KEY:
        return {
            "full_name": data.full_name,
            "error": "Missing LUSHA_API_KEY in .env"
        }

    q = urllib.parse.quote(f"{data.full_name} {data.company or ''}")
    linkedin_search_url = f"https://www.linkedin.com/search/results/people/?keywords={q}"

    contact_payload = {
        "contactId": "1",
        "fullName": data.full_name,
    }

    if data.linkedin_url:
        contact_payload["linkedinUrl"] = data.linkedin_url
    elif data.company:
        contact_payload["companies"] = [
            {
                "name": data.company,
                "isCurrent": True
            }
        ]

    try:
        response = requests.post(
            "https://api.lusha.com/v2/person",
            headers={
                "api_key": LUSHA_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "contacts": [contact_payload]
            },
            timeout=45,
        )

        lusha_response = response.json()

        contact_wrapper = {}
        person_data = {}
        company_data = {}

        if isinstance(lusha_response, dict):
            contacts = lusha_response.get("contacts", {})
            if isinstance(contacts, dict):
                contact_wrapper = contacts.get("1", {})
                if isinstance(contact_wrapper, dict):
                    person_data = contact_wrapper.get("data", {}) or {}

            companies = lusha_response.get("companies", {})
            if isinstance(companies, dict):
                company_id = person_data.get("companyId")
                if company_id is not None:
                    company_data = companies.get(str(company_id), {}) or {}

        email_addresses = person_data.get("emailAddresses", []) if isinstance(person_data, dict) else []
        phone_numbers = person_data.get("phoneNumbers", []) if isinstance(person_data, dict) else []
        social_links = person_data.get("socialLinks", {}) if isinstance(person_data, dict) else {}
        job_title = person_data.get("jobTitle", {}) if isinstance(person_data, dict) else {}

        work_email = ""
        if email_addresses and isinstance(email_addresses, list):
            work_email = email_addresses[0].get("email", "")
        elif person_data.get("emails"):
            emails = person_data.get("emails", [])
            if emails and isinstance(emails, list):
                work_email = emails[0]

        phone = ""
        if phone_numbers and isinstance(phone_numbers, list):
            phone = phone_numbers[0].get("number", "")
        elif person_data.get("phones"):
            phones = person_data.get("phones", [])
            if phones and isinstance(phones, list):
                phone = phones[0]

        linkedin_url = social_links.get("linkedin", "")

        return {
            "full_name": person_data.get("fullName", data.full_name),
            "title": job_title.get("title", ""),
            "company": company_data.get("name", data.company or ""),
            "linkedin_url": linkedin_url,
            "linkedin_search_url": linkedin_search_url,
            "work_email": work_email,
            "phone": phone,
            "match_confidence": "high" if response.status_code == 201 else "medium",
            "source": "lusha"
        }

    except Exception as e:
        return {
            "full_name": data.full_name,
            "company": data.company or "",
            "linkedin_url": "",
            "linkedin_search_url": linkedin_search_url,
            "work_email": "",
            "phone": "",
            "match_confidence": "unknown",
            "source": "lusha",
            "error": str(e)
        }


@app.post("/enrich-company")
def enrich_company(data: EnrichCompanyRequest):
    if not LUSHA_API_KEY:
        return {
            "company_name": data.company_name,
            "error": "Missing LUSHA_API_KEY in .env"
        }

    try:
        response = requests.get(
            "https://api.lusha.com/v2/company",
            headers={
                "api_key": LUSHA_API_KEY,
                "Content-Type": "application/json",
            },
            params={
                "company": data.company_name,
                "domain": data.domain,
            },
            timeout=45,
        )

        lusha_response = response.json()

        company_data = {}
        if isinstance(lusha_response, dict):
            company_data = lusha_response.get("data", {}) or {}

        location = company_data.get("location", {}) if isinstance(company_data, dict) else {}
        social = company_data.get("social", {}) if isinstance(company_data, dict) else {}
        linkedin_social = social.get("linkedin", {}) if isinstance(social, dict) else {}

        return {
            "company_name": company_data.get("name", data.company_name),
            "domain": company_data.get("domain", data.domain or ""),
            "industry": company_data.get("subIndustry", company_data.get("mainIndustry", "")),
            "employee_count": company_data.get("employees", ""),
            "hq": location.get("rawLocation", ""),
            "linkedin_url": linkedin_social.get("url", ""),
            "source": "lusha"
        }

    except Exception as e:
        return {
            "company_name": data.company_name,
            "domain": data.domain or "",
            "industry": "",
            "employee_count": "",
            "hq": "",
            "linkedin_url": "",
            "source": "lusha",
            "error": str(e)
        }