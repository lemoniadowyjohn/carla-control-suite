from __future__ import annotations

import csv
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


DESKTOP = Path(r"F:\pulpit")
BACKUP_ROOT = DESKTOP / "job_search_backup_continued"
APP_READY = DESKTOP / "application_ready_today"

CONTINUED_CSV = DESKTOP / "munich_job_matches_michal_dembski_CONTINUED.csv"
CONTINUED_MD = DESKTOP / "munich_job_matches_michal_dembski_CONTINUED.md"
NEW_ONLY_CSV = DESKTOP / "new_jobs_only_michal_dembski.csv"
TOP30_MD = DESKTOP / "top_30_application_shortlist_UPDATED.md"
APPLY_TODAY_MD = DESKTOP / "apply_today_priority_list.md"
FOLLOW_UP_MD = DESKTOP / "follow_up_recruiter_targets.md"
DAILY_LOG_MD = DESKTOP / "daily_search_log.md"
CV_MAPPING_MD = DESKTOP / "cv_version_mapping_for_jobs.md"
MISSING_SKILLS_MD = DESKTOP / "missing_skills_market_gap.md"
APPLICATION_PLAN_MD = DESKTOP / "application_plan_today.md"
RECRUITER_MESSAGES_MD = DESKTOP / "recruiter_messages_for_top_jobs.md"

FIELDNAMES = [
    "Rank",
    "NewOrExisting",
    "FitScore",
    "JobTitle",
    "Company",
    "Location",
    "RemoteHybridOnsite",
    "EmploymentType",
    "Source",
    "SourceURL",
    "PostingDate",
    "DirectOrAgency",
    "EndClientKnown",
    "RoleCluster",
    "WhyItFits",
    "MatchingKeywords",
    "MissingOrRiskAreas",
    "RecommendedCVVersion",
    "RecommendedHeadline",
    "ApplicationPriority",
    "ApplyToday",
    "ApplicationNoteShort",
    "DuplicateOf",
    "CheckedAt",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M CET")


CHECKED_AT = now_stamp()


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    split = urlsplit(raw)
    scheme = split.scheme.lower()
    netloc = split.netloc.lower()
    path = split.path.rstrip("/").lower()
    query = parse_qs(split.query)
    if "indeed." in netloc and path.endswith("/viewjob") and query.get("jk"):
        return f"{scheme}://{netloc}{path}?jk={query['jk'][0].lower()}"
    return f"{scheme}://{netloc}{path}"


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("&", "and")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    text = re.sub(r"\b(m w d|w m d|d w m|m f d|f m d|all genders|gn)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_value(row: dict[str, str]) -> float:
    try:
        return float(str(row.get("FitScore", "0")).replace(",", "."))
    except ValueError:
        return 0.0


def priority_for_score(score: float) -> str:
    if score >= 8.5:
        return "Apply immediately"
    if score >= 8.0:
        return "Apply this week"
    if score >= 7.0:
        return "Good option - apply if attractive"
    return "Stretch - apply selectively"


def cv_for(cluster: str, language: str = "English", quality: bool = False) -> str:
    if quality or "Quality" in cluster or "Validation" in cluster:
        return f"ATS Quality & Validation CV - {language}"
    return f"ATS Process Automation CV - {language}"


def make_row(
    *,
    fit: float,
    title: str,
    company: str,
    location: str,
    remote: str,
    employment: str,
    source: str,
    url: str,
    date: str,
    direct: str,
    end_client: str,
    cluster: str,
    why: str,
    keywords: list[str],
    risks: list[str],
    cv: str,
    headline: str,
    note: str,
) -> dict[str, str]:
    return {
        "Rank": "",
        "NewOrExisting": "New",
        "FitScore": f"{fit:.1f}",
        "JobTitle": title,
        "Company": company,
        "Location": location,
        "RemoteHybridOnsite": remote,
        "EmploymentType": employment,
        "Source": source,
        "SourceURL": url,
        "PostingDate": date,
        "DirectOrAgency": direct,
        "EndClientKnown": end_client,
        "RoleCluster": cluster,
        "WhyItFits": why,
        "MatchingKeywords": "; ".join(keywords),
        "MissingOrRiskAreas": "; ".join(risks),
        "RecommendedCVVersion": cv,
        "RecommendedHeadline": headline,
        "ApplicationPriority": priority_for_score(fit),
        "ApplyToday": "No",
        "ApplicationNoteShort": note,
        "DuplicateOf": "",
        "CheckedAt": CHECKED_AT,
    }


ADDITIONS: list[dict[str, str]] = [
    make_row(
        fit=8.7,
        title="KI- und Automatisierungsspezialist Digitalisierung & IT",
        company="RATHGEBER GmbH & Co. KG",
        location="Oberhaching, Bavaria",
        remote="Hybrid / flexible mobile work",
        employment="Full-time, permanent",
        source="Direct company portal - Personio",
        url="https://rathgeber-gmbh-co-kg.jobs.personio.com/job/2683489",
        date="Date unclear; page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - RATHGEBER GmbH & Co. KG",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster D - AI automation",
        why="One of the cleanest new matches: the role combines AI/automation use cases, digital workflows, documentation, test management, quality assurance and Microsoft 365/Power Platform tooling.",
        keywords=[
            "Power Automate",
            "Power Platform",
            "SharePoint",
            "process automation",
            "AI use cases",
            "documentation",
            "quality assurance",
        ],
        risks=[
            "May expect broader IT ownership",
            "Low-code/Python/SQL listed as optional but useful",
            "Manufacturing-signage domain rather than automotive",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Process Automation & AI Workflow Specialist | Power Automate, SharePoint, Python, Quality Documentation",
        note="Lead with Power Automate/SharePoint workflows, Python automation and quality-documentation evidence.",
    ),
    make_row(
        fit=8.6,
        title="Operations & Automation Berufseinstieg",
        company="Vogel",
        location="Munich, Bavaria",
        remote="On-site / Munich",
        employment="Full-time, entry-level",
        source="Direct company portal - Ashby",
        url="https://jobs.ashbyhq.com/Vogel/44503dfa-c2e1-42bf-b99c-82276d064065",
        date="Date unclear; page active in search index on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Vogel",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster D - AI automation",
        why="Entry-level automation role explicitly values Wirtschaftsingenieurwesen, own automation projects, n8n/Make/Zapier/Power Automate or Python scripts, documentation and AI tooling.",
        keywords=[
            "Power Automate",
            "Python scripts",
            "n8n",
            "Make",
            "Zapier",
            "AI tools",
            "process automation",
            "documentation",
        ],
        risks=[
            "Startup pace and on-site expectation",
            "Operations role may include non-engineering execution",
            "Needs concrete examples of own automations",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Junior Operations & Automation Specialist | Power Automate, Python, AI Workflows, Industrial Engineering",
        note="Position the two B.Eng. programs and personal AI-agent workflow R&D as practical automation evidence.",
    ),
    make_row(
        fit=8.6,
        title="Junior AI Automation Developer",
        company="Workspacer",
        location="Munich, Bavaria",
        remote="Hybrid / home office possible",
        employment="Full-time, permanent; junior",
        source="StepStone / JobPortal",
        url="https://www.stepstone.de/stellenangebote--Junior-AI-Automation-Developer-m-w-d-Muenchen-Workspacer--14392577-inline.html",
        date="Active since 2026-08-12; updated 2026-08-16 on JobPortal mirror",
        direct="Direct employer via job board",
        end_client="Known - Workspacer",
        cluster="Cluster D - AI automation; Cluster B - Python automation / industrial data",
        why="A realistic junior AI-automation match with n8n/Make/Zapier, scripts, APIs, LLM/AI agents, cloud automation and quality improvement rather than senior ML research.",
        keywords=[
            "n8n",
            "Make",
            "Zapier",
            "scripts",
            "REST APIs",
            "LLM",
            "AI agents",
            "automation",
        ],
        risks=[
            "JavaScript/TypeScript and API auth may be tested",
            "Less automotive/quality context",
            "Need to distinguish from existing Workspacer senior/general posting",
        ],
        cv=cv_for("Cluster D", "English"),
        headline="Junior AI Automation Developer | Python Automation, Power Automate, n8n Basics, AI-Agent Workflow R&D",
        note="Use this as an AI-automation bridge role and show repository-validation/evidence-check workflow projects.",
    ),
    make_row(
        fit=8.4,
        title="Workflow- und Automationsspezialist Power Platform",
        company="Bayern Facility Management GmbH",
        location="Munich, Bavaria",
        remote="Munich; remote/hybrid not clearly stated",
        employment="Full-time, permanent",
        source="Indeed Germany",
        url="https://de.indeed.com/viewjob?jk=ec91c9f7eca848c2",
        date="Date unclear; page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Bayern Facility Management GmbH",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Exact Power Platform workflow role: Power Automate, SharePoint, Power Apps, AI chatbot use cases, BPMN/workflow design and M365 process automation.",
        keywords=[
            "Power Automate",
            "Power Apps",
            "SharePoint",
            "Microsoft 365",
            "AI chatbot",
            "workflow design",
            "BPMN",
        ],
        risks=[
            "May expect several years of Power Platform delivery",
            "Facility-management domain",
            "Remote policy unclear",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Automation Specialist | Power Automate, SharePoint, M365 Workflows, Python Support",
        note="Apply with Power Platform CV and emphasize concrete Power Automate/SharePoint workflow examples.",
    ),
    make_row(
        fit=8.2,
        title="Microsoft Power Platform Consultant",
        company="Dataciders ixto GmbH",
        location="Remote Germany or Munich",
        remote="Remote Germany / Munich",
        employment="Full-time",
        source="RapidJob / company career hub",
        url="https://www.rapidjob.de/job/rrh7v5c/",
        date="Date unclear; page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Dataciders ixto GmbH",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Strong Power Platform consultant match with Power Apps/Power Automate, apps and automation, remote Germany option and openness to graduates/career changers.",
        keywords=[
            "Power Platform",
            "Power Apps",
            "Power Automate",
            "low-code",
            "automation",
            "remote Germany",
            "consulting",
        ],
        risks=[
            "Consulting delivery and client-facing German may be important",
            "May expect Power BI/Data Governance exposure",
            "Need to show structured requirements work",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Consultant | Power Automate, SharePoint/M365 Workflows, Python Automation",
        note="Good portal application if the CV is German and ATS-oriented around Power Platform and process automation.",
    ),
    make_row(
        fit=7.9,
        title="(Senior) Business Process Manager - KI & Automatisierung",
        company="AUXILIA Rechtsschutz-Versicherungs-AG / KS-AUXILIA",
        location="Munich, Bavaria",
        remote="Hybrid / home office possible",
        employment="Full-time, permanent",
        source="Direct company portal - Personio / Bundesagentur mirror",
        url="https://ks-auxilia.jobs.personio.com/job/2685849",
        date="Published about 2026-08-13; updated about 2026-08-26 in BA search; direct date unclear",
        direct="Direct employer",
        end_client="Known - AUXILIA Rechtsschutz-Versicherungs-AG",
        cluster="Cluster D - AI automation; Cluster B - process automation",
        why="Good process/KI automation match focused on business-process analysis, AI automation and implementation coordination; useful if positioned as process automation rather than insurance expertise.",
        keywords=[
            "business process management",
            "AI automation",
            "process optimization",
            "workflow automation",
            "requirements",
            "stakeholder coordination",
        ],
        risks=[
            "Senior label",
            "Insurance domain",
            "May require deeper BPM/process-owner experience",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Business Process Automation Specialist | AI Workflows, Python, Power Automate, Process Documentation",
        note="Apply selectively; present AI-agent R&D as process-control thinking, not as production AI architecture.",
    ),
    make_row(
        fit=7.8,
        title="Prozessautomatisierungsspezialist - Schwerpunkt KI-Agenten-Technologien",
        company="ADAC Versicherung AG",
        location="Munich, Bavaria",
        remote="Hybrid up to 50%",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://karriere.adac.de/stellenanzeige/prozessautomatisierungsspezialist-schwerpunkt-ki-agenten-t-de-j16834.html",
        date="Published about 2026-09-02 in BA search; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - ADAC Versicherung AG",
        cluster="Cluster D - AI automation; Cluster B - process automation",
        why="Very relevant AI-agent/process-automation role with low-code, BPMN/DMN, LLM/API integration and process lifecycle responsibility; score held down by seniority and governance expectations.",
        keywords=[
            "AI agents",
            "LLM",
            "low-code",
            "process automation",
            "BPMN",
            "API integrations",
            "Python",
            "SQL",
        ],
        risks=[
            "Multi-year strategic process-management expected",
            "Governance and regulatory environment",
            "Need more explicit LLM/API implementation examples",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Process Automation & AI-Agent Workflow Specialist | Python, Power Automate, Documentation",
        note="High-value stretch; apply after tailoring the AI-agent workflow R&D into a concise, defensible project story.",
    ),
    make_row(
        fit=7.8,
        title="IT-Inhouse Consultant & Data Specialist",
        company="BBE Handelsberatung GmbH",
        location="Munich, Bavaria",
        remote="Home office possible",
        employment="Full-time",
        source="Indeed Germany / HRworks company board",
        url="https://de.indeed.com/viewjob?jk=c0792ac05aa5db45",
        date="Date unclear; page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - BBE Handelsberatung GmbH",
        cluster="Cluster B - Python automation / industrial data; Cluster A - M365 automation",
        why="Good data/digitalization role with Excel, Power Query, Power BI, data preparation, data quality assurance, process optimization and M365 exposure.",
        keywords=[
            "Excel",
            "Power Query",
            "Power BI",
            "data quality",
            "process optimization",
            "Microsoft 365",
            "AI tools",
        ],
        risks=[
            "Retail/consulting domain rather than industrial automotive",
            "Power BI/SQL may be stronger than Python",
            "Inhouse consulting/stakeholder work",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Industrial Data & Process Automation Specialist | Excel/Python, M365, Data Quality, Documentation",
        note="Use the Excel/OpenPyXL/Pandas reconciliation story and avoid overstating Power BI depth.",
    ),
    make_row(
        fit=7.7,
        title="Manager Process Automation",
        company="Tyczka GmbH",
        location="Geretsried, Bavaria",
        remote="Hybrid / mobile work",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://tyczka.de/karriere/jobportal/9881272",
        date="Date unclear; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Tyczka GmbH",
        cluster="Cluster B - process automation; Cluster D - AI automation",
        why="Relevant process-automation and AI role covering process analysis, requirements, technical concepts, implementation coordination, testing and acceptance.",
        keywords=[
            "process automation",
            "AI",
            "requirements",
            "technical concepts",
            "low-code",
            "testing",
            "acceptance",
            "project management",
        ],
        risks=[
            "Manager title and project leadership expectations",
            "May prefer IT/AI/Data Science background",
            "Energy/gas domain",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Process Automation Engineer | Low-Code, Python Automation, Testing, Quality Documentation",
        note="Apply selectively with focus on implementation support, testing and process documentation.",
    ),
    make_row(
        fit=7.5,
        title="Sachbearbeiter Reklamationsmanagement Schienenfahrzeuge",
        company="Bertrandt Group",
        location="Munich, Bavaria",
        remote="On-site / Munich",
        employment="Full-time, permanent",
        source="Indeed Germany / Bundesagentur mirror",
        url="https://de.indeed.com/viewjob?jk=e05ad31adcec4322",
        date="Published/edited about 2026-09-06 in BA search; Indeed page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Bertrandt Group",
        cluster="Cluster C - Automotive quality / validation",
        why="Strong continuity with Bertrandt experience, complaint management, production deviations, root-cause analysis, supplier coordination, SAP quality data and documentation.",
        keywords=[
            "complaint management",
            "quality deviations",
            "root-cause analysis",
            "production",
            "supplier coordination",
            "documentation",
            "SAP QM",
        ],
        risks=[
            "Rail vehicle domain",
            "SAP MM/PP/QM preferred",
            "Less automation-focused than target cluster A/B",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Quality & Validation Documentation Specialist | Bertrandt Automotive, Traceability, Process Improvement",
        note="Use as a quality fallback; the Bertrandt brand match helps, but automation career value is lower.",
    ),
    make_row(
        fit=7.4,
        title="Freelancer Microsoft Power Platform und Automation Specialist",
        company="Amadeus Fire - end client hidden",
        location="Munich, Bavaria",
        remote="Hybrid; about 80% remote",
        employment="Freelance project",
        source="Freelancermap",
        url="https://www.freelancermap.de/projekt/freelancer-microsoft-power-platform-und-automation-specialist-m-w-d-muenchen-hybrid",
        date="Published about 2026-09-05; project start 2026-10-01",
        direct="Agency / recruiter",
        end_client="Hidden",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Exact Power Platform, SharePoint, PowerShell, M365, Power BI and Copilot automation match, but it is a freelance contract via agency with hidden end client.",
        keywords=[
            "Power Platform",
            "Power Automate",
            "SharePoint",
            "PowerShell",
            "Microsoft 365",
            "Power BI",
            "Copilot",
        ],
        risks=[
            "Freelance rather than employee role",
            "Hidden end client",
            "May require independent contractor readiness and daily-rate expectations",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Automation Specialist | Power Automate, SharePoint, M365, Python Automation",
        note="Only pursue if freelance/contract work is acceptable; useful for recruiter outreach.",
    ),
    make_row(
        fit=7.3,
        title="Fullstack Softwareentwickler HR-Automation",
        company="CHECK24",
        location="Munich, Bavaria",
        remote="Hybrid / Munich",
        employment="Full-time",
        source="Direct company portal",
        url="https://jobs.check24.de/de/jobs/interner-it-support-it-operations/REF332Z-fullstack-softwareentwickler-mwd-hr-automation/",
        date="Date unclear; direct page active in search index on 2026-09-07",
        direct="Direct employer",
        end_client="Known - CHECK24",
        cluster="Cluster B - Python automation / industrial data; Cluster D - AI automation",
        why="Automation theme is relevant: internal HR process automation, Python/Django, APIs and AI tools. It is a software-heavy stretch rather than a pure process role.",
        keywords=[
            "Python",
            "Django",
            "REST APIs",
            "automation",
            "ChatGPT",
            "Claude",
            "internal tools",
        ],
        risks=[
            "Full-stack software engineering is outside the strongest evidence",
            "React/TypeScript/Django depth likely tested",
            "Less M365/quality relevance",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Python Automation Engineer | Process Automation, Data Reconciliation, AI Workflow Projects",
        note="Stretch if the candidate wants to move toward software automation; do not overclaim frontend/backend depth.",
    ),
    make_row(
        fit=7.2,
        title="IT-Projektleiter - Systemintegration & Automatisierungstechnik",
        company="HOERMANN Industries GmbH",
        location="Unterschleissheim, Bavaria",
        remote="Hybrid / home office possible",
        employment="Full-time",
        source="Indeed Germany",
        url="https://de.indeed.com/viewjob?jk=db461663c774f7a6",
        date="Date unclear; page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - HOERMANN Industries GmbH",
        cluster="Cluster B - process automation; Technical project engineering",
        why="Matches Wirtschaftsingenieurwesen, automation project work, system integration, acceptance/training, documentation/reporting and industrial process context.",
        keywords=[
            "automation technology",
            "system integration",
            "project management",
            "documentation",
            "acceptance",
            "WMS",
            "material flow control",
        ],
        risks=[
            "Project-lead role may require more formal PM experience",
            "30% travel",
            "Specific intralogistics/WMS systems",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Technical Project Engineer Automation | Industrial Engineering, Process Documentation, Python/M365 Automation",
        note="Use as a technical-project bridge role; emphasize two engineering degrees and documentation discipline.",
    ),
    make_row(
        fit=7.2,
        title="(Senior) Power Platform Consultant",
        company="CGI",
        location="Munich, Bavaria",
        remote="Partial home office",
        employment="Full-time",
        source="StudySmarter jobs mirror",
        url="https://talents.studysmarter.de/companies/cgi/senior-power-platform-consultant-m-w-d-3470035/",
        date="Date unclear; page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - CGI",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Relevant Power Platform and low-code consulting role in Munich, but score is limited by senior label and likely Azure/consulting delivery expectations.",
        keywords=[
            "Power Platform",
            "low-code",
            "consulting",
            "Power Apps",
            "Power Automate",
            "Azure",
        ],
        risks=[
            "Senior role",
            "Azure and broader consulting depth may be expected",
            "Direct CGI posting not confirmed through tool",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Automation Consultant | Power Automate, SharePoint, M365, Process Automation",
        note="Apply only if the ad allows consultant rather than senior-only positioning.",
    ),
    make_row(
        fit=7.1,
        title="AI Software Developer",
        company="CIB Group",
        location="Munich or home office, Germany",
        remote="Home office / Munich",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.cib.de/jobboerse/ai-software-developer/",
        date="Date unclear; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - CIB Group",
        cluster="Cluster D - AI automation",
        why="Relevant AI/process-automation role around document workflows, LLM APIs and AI applications; score is limited by backend/software development and architecture expectations.",
        keywords=[
            "AI applications",
            "LLM APIs",
            "workflow automation",
            "document management",
            "APIs",
            "testing",
            "monitoring",
        ],
        risks=[
            "Software developer role with backend expectations",
            "Cloud/MLOps/vector databases are nice-to-have but relevant gaps",
            "Less automotive/process-quality overlap",
        ],
        cv=cv_for("Cluster D", "English"),
        headline="Applied AI Automation Engineer | Python, Workflow Automation, LLM Concepts, Documentation",
        note="Use as a stretch AI role; prepare a concise explanation of personal AI-agent workflow R&D.",
    ),
    make_row(
        fit=7.1,
        title="Quality Validation Engineer - Batteriesysteme",
        company="Bertrandt Group",
        location="Schierling, Bavaria",
        remote="Full-time; mobile work unclear",
        employment="Full-time, permanent",
        source="Indeed Germany / LinkedIn / BA mirror",
        url="https://de.indeed.com/viewjob?jk=23c86255ef145e3f",
        date="Published 2026-09-05 via BA mirror; Indeed page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Bertrandt Group",
        cluster="Cluster C - Automotive quality / validation",
        why="Relevant Bertrandt quality/validation role involving battery fault analysis, documentation, production-process optimization and quality methods.",
        keywords=[
            "quality validation",
            "battery systems",
            "fault analysis",
            "documentation",
            "production optimization",
            "FMEA",
            "8D",
        ],
        risks=[
            "HV battery expertise required",
            "Multi-year root-cause and quality-method experience expected",
            "Schierling commute/relocation consideration",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Quality & Validation Engineer | Automotive Documentation, Traceability, Process Improvement",
        note="Apply only if battery/quality methods can be credibly framed from Bertrandt and thesis experience.",
    ),
    make_row(
        fit=7.0,
        title="Data & AI Software Engineer",
        company="WashTec AG",
        location="Augsburg, Bavaria",
        remote="Hybrid; about 3 days/week onsite",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://jobs.washtec.com/en/jobs/41214/data-ai-software-engineer-mwd",
        date="Date unclear; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - WashTec AG",
        cluster="Cluster D - AI automation; Cluster B - data/process automation",
        why="Industrial company using n8n and Copilot Studio to automate business processes and implement AI/data solutions with departments.",
        keywords=[
            "n8n",
            "Copilot Studio",
            "AI solutions",
            "business process automation",
            "data solutions",
            "Azure OpenAI",
        ],
        risks=[
            "Software/data engineering role may require stronger cloud and DevOps/MLOps",
            "Augsburg with 3 days onsite",
            "German and English communication expected",
        ],
        cv=cv_for("Cluster D", "English"),
        headline="AI & Process Automation Engineer | Python, n8n/Copilot Concepts, Industrial Digitalization",
        note="Selective stretch; useful if the candidate wants Augsburg and industrial AI exposure.",
    ),
    make_row(
        fit=7.0,
        title="Consultant for Digital Transformation and Digital Processes",
        company="antegma GmbH",
        location="Munich, Bavaria / client sites",
        remote="Consulting; remote unclear",
        employment="Full-time",
        source="RapidJob",
        url="https://www.rapidjob.de/job/ukdtv4u/",
        date="Date unclear; page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - antegma GmbH",
        cluster="Cluster A - low-code automation; Cluster B - process digitalization",
        why="Process digitalization and workflow-solution consulting with low-code/no-code tools including Microsoft Power Platform, Zapier/Integromat/Make.",
        keywords=[
            "digital transformation",
            "digital processes",
            "workflow solutions",
            "Microsoft Power Platform",
            "low-code",
            "Make",
            "consulting",
        ],
        risks=[
            "Consulting strategy focus",
            "May require deeper Camunda/AEM Forms or process architecture",
            "Remote/work location unclear",
        ],
        cv=cv_for("Cluster A", "English"),
        headline="Digital Process Automation Consultant | Power Platform, Python, M365 Workflows, Documentation",
        note="Good stretch for digital-transformation positioning; tailor around process analysis and automation demos.",
    ),
    make_row(
        fit=6.8,
        title="Technischer Projektleiter Automatisierungstechnik",
        company="ECT System GmbH",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time",
        source="BeBee jobs mirror",
        url="https://bebee.com/de/jobs/technischer-projektleiter-automatisierungstechnik-ect-system-gmbh-munchen--t7xk-809732041",
        date="Published about 2026-09-04; deadline 2026-10-19 in search result",
        direct="Direct employer via job board",
        end_client="Known - ECT System GmbH",
        cluster="Cluster B - industrial process automation; Technical project engineering",
        why="Industrial automation and automotive production-systems context with documentation, commissioning, FAT/SAT and quality requirements.",
        keywords=[
            "automation technology",
            "automotive production systems",
            "FAT",
            "SAT",
            "commissioning",
            "documentation",
            "quality requirements",
        ],
        risks=[
            "PLC/HMI/SCADA/KUKA/TIA requirements",
            "Project-lead seniority",
            "Less M365/Python relevance",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Technical Project Engineer Automation | Industrial Engineering, Validation Documentation, Process Improvement",
        note="Borderline stretch; apply only if PLC/commissioning expectations are not mandatory.",
    ),
]


EXCLUSIONS = [
    {
        "title": "Digital Automation & AI Professional",
        "company": "Dr. Sasse Gruppe",
        "reason": "StepStone URL returned 410 Gone and direct career page did not show the job.",
    },
    {
        "title": "Praktikum im Bereich strategische Digitalisierung / Agentic AI",
        "company": "BMW Group",
        "reason": "Interesting AI/quality-management project but internship-only and likely requires active student status.",
    },
    {
        "title": "Technical Lead - Citizen Developer Consultant",
        "company": "Bosch",
        "reason": "Strong low-code theme but direct exact posting could not be verified and lead/senior scope is high.",
    },
    {
        "title": "Solution Architect Business Automation",
        "company": "qards GmbH",
        "reason": "Active direct posting, but mainly senior architecture plus Java/Spring/cloud and C2 German.",
    },
    {
        "title": "Entwickler: IT-Automation, SharePoint, Power Platform",
        "company": "VINCI Energies",
        "reason": "Excellent keyword match but Mannheim location with no clear remote-Germany evidence.",
    },
    {
        "title": "AI Automation Product Owner",
        "company": "ZEIT SPRACHEN",
        "reason": "Fixed-term media product-owner role with weaker fit and older posting.",
    },
]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            clean = {field: (row.get(field, "") or "").strip() for field in FIELDNAMES}
            rows.append(clean)
        return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def backup_files() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"latest_update_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for path in [
        CONTINUED_CSV,
        CONTINUED_MD,
        NEW_ONLY_CSV,
        TOP30_MD,
        APPLY_TODAY_MD,
        FOLLOW_UP_MD,
        DAILY_LOG_MD,
        CV_MAPPING_MD,
        MISSING_SKILLS_MD,
        APPLICATION_PLAN_MD,
        RECRUITER_MESSAGES_MD,
    ]:
        if path.exists():
            shutil.copy2(path, dest / path.name)
    return dest


def dedupe_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[tuple[dict[str, str], str]]]:
    seen_urls: dict[str, dict[str, str]] = {}
    seen_titles: dict[str, dict[str, str]] = {}
    protected_addition_urls = {normalize_url(row["SourceURL"]) for row in ADDITIONS}
    kept: list[dict[str, str]] = []
    removed: list[tuple[dict[str, str], str]] = []
    for row in rows:
        url_key = normalize_url(row.get("SourceURL", ""))
        title_key = f"{normalize_text(row.get('Company', ''))}|{normalize_text(row.get('JobTitle', ''))}"
        if url_key and url_key in seen_urls:
            kept_row = seen_urls[url_key]
            row["DuplicateOf"] = f"{kept_row.get('Company')} - {kept_row.get('JobTitle')}"
            removed.append((row, "same source URL"))
            continue
        if title_key in seen_titles and url_key not in protected_addition_urls:
            kept_row = seen_titles[title_key]
            row["DuplicateOf"] = f"{kept_row.get('Company')} - {kept_row.get('JobTitle')}"
            removed.append((row, "same company/title"))
            continue
        kept.append(row)
        if url_key:
            seen_urls[url_key] = row
        seen_titles[title_key] = row
    return kept, removed


def sort_and_rank(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    source_preference = {
        "Direct employer": 0,
        "Direct employer via job board": 1,
        "Agency / recruiter": 2,
    }

    def sort_key(row: dict[str, str]) -> tuple[float, int, int, str]:
        direct = row.get("DirectOrAgency", "")
        return (
            -score_value(row),
            source_preference.get(direct, 1),
            0 if row.get("NewOrExisting") == "New" else 1,
            normalize_text(row.get("Company", "") + " " + row.get("JobTitle", "")),
        )

    rows = sorted(rows, key=sort_key)
    for index, row in enumerate(rows, start=1):
        score = score_value(row)
        row["Rank"] = str(index)
        row["ApplicationPriority"] = priority_for_score(score)
        row["ApplyToday"] = "Yes" if index <= 10 else "No"
        if not row.get("CheckedAt"):
            row["CheckedAt"] = CHECKED_AT
    return rows


def md_escape(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def markdown_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> str:
    lines = []
    lines.append("| " + " | ".join(label for label, _ in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        cells = [md_escape(row.get(field, "")) for _, field in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def source_link(row: dict[str, str]) -> str:
    url = row.get("SourceURL", "")
    return f"[Source]({url})" if url else ""


def top_keywords(row: dict[str, str], n: int = 5) -> list[str]:
    parts = [p.strip() for p in row.get("MatchingKeywords", "").split(";") if p.strip()]
    return parts[:n]


def interview_topics(row: dict[str, str]) -> list[str]:
    cluster = row.get("RoleCluster", "")
    if "Quality" in cluster or "Validation" in cluster:
        return [
            "How you handled traceability and quality documentation at Bertrandt",
            "Root-cause analysis examples and how you documented evidence",
            "Validation/test-document workflows and handover quality",
            "How BMW production/process exposure informs your work",
            "How Python or Excel automation can reduce manual quality reporting",
        ]
    if "AI" in cluster:
        return [
            "Concrete AI-agent workflow project scope and boundaries",
            "How you would validate LLM output before business use",
            "Where Power Automate/n8n fits versus Python scripts",
            "How you document workflow requirements and exceptions",
            "How you would start a small RAG or automation proof of concept",
        ]
    return [
        "Power Automate and SharePoint workflow examples",
        "Python/OpenPyXL/Pandas reconciliation and validation scripts",
        "Requirements gathering and process mapping",
        "Error handling, approvals and traceability in workflows",
        "How to measure automation impact and maintain documentation",
    ]


def german_message(row: dict[str, str]) -> str:
    title = row["JobTitle"]
    company = row["Company"]
    keywords = ", ".join(top_keywords(row, 3))
    return (
        f"Guten Tag, ich bewerbe mich auf die Position {title} bei {company}. "
        f"Mein Profil verbindet Wirtschaftsingenieurwesen, Bertrandt-Automotive-Erfahrung, "
        f"Prozessautomatisierung mit Power Automate/SharePoint und Python-basierte Datenpruefung. "
        f"Besonders passend sehe ich {keywords}. Ich arbeite strukturiert, dokumentiere nachvollziehbar "
        f"und kann Automatisierungen mit klaren Pruef- und Freigabegrenzen umsetzen. "
        f"Ich freue mich auf ein kurzes Gespraech."
    )


def english_message(row: dict[str, str]) -> str:
    title = row["JobTitle"]
    company = row["Company"]
    keywords = ", ".join(top_keywords(row, 3))
    return (
        f"Hello, I would like to apply for the {title} role at {company}. "
        f"My profile combines industrial engineering, Bertrandt automotive experience, "
        f"Power Automate/SharePoint workflow automation and Python-based data validation. "
        f"The strongest match is around {keywords}. I can contribute structured documentation, "
        f"traceable automation logic and pragmatic AI/process workflow prototypes. "
        f"I would welcome a short conversation."
    )


def write_application_pack(row: dict[str, str], index: int) -> None:
    company_slug = re.sub(r"[^a-z0-9]+", "_", normalize_text(row["Company"]))[:32].strip("_")
    title_slug = re.sub(r"[^a-z0-9]+", "_", normalize_text(row["JobTitle"]))[:48].strip("_")
    path = APP_READY / f"{index:02d}_{company_slug}_{title_slug}_application_pack.md"
    risks = [p.strip() for p in row["MissingOrRiskAreas"].split(";") if p.strip()][:3]
    questions = [
        "Which business process or workflow would this role improve first?",
        "Which tools are already approved internally for automation and AI use cases?",
        "How is success measured: saved time, quality, compliance, adoption or cost?",
    ]
    checklist = [
        "Open the source URL and confirm the posting is still active.",
        f"Use {row['RecommendedCVVersion']}.",
        "Tailor only headline, summary and top skills to this job.",
        "Mention one Power Automate/SharePoint or Python automation example.",
        "Record application date, portal, CV version and follow-up owner in tracker.",
    ]
    body = [
        f"# {row['Company']} - {row['JobTitle']}",
        "",
        f"- Source URL: {row['SourceURL']}",
        f"- Fit score: {row['FitScore']}/10",
        f"- Recommended CV version: {row['RecommendedCVVersion']}",
        f"- Tailored headline: {row['RecommendedHeadline']}",
        "",
        "## Why It Fits",
        row["WhyItFits"],
        "",
        "## Top 5 CV Keywords",
        "\n".join(f"- {item}" for item in top_keywords(row, 5)),
        "",
        "## German Application Message",
        german_message(row),
        "",
        "## English Application Message",
        english_message(row),
        "",
        "## Likely Interview Questions",
        "\n".join(f"- {item}" for item in interview_topics(row)),
        "",
        "## Honest Weak Points",
        "\n".join(f"- {item}" for item in risks),
        "",
        "## Questions To Ask Employer",
        "\n".join(f"- {item}" for item in questions),
        "",
        "## Immediate Application Checklist",
        "\n".join(f"- {item}" for item in checklist),
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")


def write_main_report(rows: list[dict[str, str]], previous_count: int, added_count: int, removed_dupes: int) -> None:
    role_counts = Counter(row["RoleCluster"].split(";")[0].strip() for row in rows)
    new_rows = [row for row in rows if row["NewOrExisting"] == "New"]
    top20 = rows[:20]
    top10 = rows[:10]
    columns = [
        ("Rank", "Rank"),
        ("Fit", "FitScore"),
        ("Title", "JobTitle"),
        ("Company", "Company"),
        ("Location", "Location"),
        ("Mode", "RemoteHybridOnsite"),
        ("Type", "EmploymentType"),
        ("Source", "Source"),
        ("URL", "SourceURL"),
        ("Date", "PostingDate"),
        ("Direct/Agency", "DirectOrAgency"),
        ("Cluster", "RoleCluster"),
        ("CV", "RecommendedCVVersion"),
        ("Priority", "ApplicationPriority"),
        ("Today", "ApplyToday"),
    ]
    excluded_text = "\n".join(
        f"- {item['company']} - {item['title']}: {item['reason']}" for item in EXCLUSIONS
    )
    report = [
        "# Munich / Bavaria Job Matches for Michal Dembski - Continued Update",
        "",
        "## 1. Executive Summary",
        (
            f"Loaded {previous_count} previously tracked suitable jobs, appended {added_count} new suitable jobs, "
            f"removed {removed_dupes} duplicates during this update, and kept {len(rows)} active candidate-matched jobs. "
            "The strongest evidence remains Power Platform/M365 automation and practical process automation, with AI-automation roles useful when they are workflow-oriented rather than senior ML/platform roles."
        ),
        "",
        "## 2. Number Of Jobs Found",
        f"- Total suitable jobs in continued list: {len(rows)}",
        f"- Rows marked new from continued searches: {len(new_rows)}",
        f"- Newly appended in this update: {added_count}",
        "",
        "## 3. Number Of Jobs Excluded And Why",
        f"- Excluded in this search pass: {len(EXCLUSIONS)}",
        excluded_text,
        "",
        "## 4. Ranked Table Of All Included Jobs",
        markdown_table(rows, columns),
        "",
        "## 5. Top 20 Shortlist",
        markdown_table(
            top20,
            [
                ("Rank", "Rank"),
                ("Fit", "FitScore"),
                ("Title", "JobTitle"),
                ("Company", "Company"),
                ("Location", "Location"),
                ("Mode", "RemoteHybridOnsite"),
                ("URL", "SourceURL"),
                ("CV", "RecommendedCVVersion"),
                ("Headline", "RecommendedHeadline"),
            ],
        ),
        "",
        "## 6. Top 10 Apply-Today List",
        "\n".join(
            f"{row['Rank']}. {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10) - {source_link(row)}"
            for row in top10
        ),
        "",
        "## 7. Role Cluster Analysis",
        "\n".join(f"- {cluster}: {count}" for cluster, count in role_counts.most_common()),
        "",
        "## 8. Best Companies To Monitor Daily",
        "- Workspacer",
        "- Campana & Schott",
        "- RATHGEBER",
        "- Bertrandt Group",
        "- ADAC / ADAC IT Service / ADAC Versicherung",
        "- TUV SUD",
        "- Skaylink",
        "- adesso",
        "- ARRK Engineering",
        "- BMW Group",
        "",
        "## 9. Missing Skills Repeated Across The Market",
        "- Power Platform governance, environments, Dataverse and licensing",
        "- Power Apps canvas/model-driven delivery beyond Power Automate",
        "- Copilot Studio, Azure OpenAI, LLM APIs and responsible AI guardrails",
        "- n8n/Make/Zapier workflow implementation examples",
        "- BPMN/DMN process modelling",
        "- Power BI, Power Query and SQL for reporting-heavy roles",
        "- Automotive quality methods: 8D, FMEA, VDA 6.3, APQP/PPAP, SAP QM",
        "",
        "## 10. CV Version Recommendation",
        "Use ATS Process Automation CV - German most often for Munich/Bavaria portals because the strongest current cluster is German-language Power Platform, M365, process automation and digitalization. Use ATS Quality & Validation CV - German for Bertrandt, MAN, TUV and automotive validation/quality postings. Use English only for international AI-automation or tech-consulting roles.",
        "",
        "## 11. Application Plan For Today",
        "- Re-open and verify the top 20 links.",
        "- Submit 5-8 applications from the top 10 list, starting with direct company portals.",
        "- Tailor only headline, professional summary and top skills for each role.",
        "- Send 3-5 recruiter messages for Workspacer, Campana & Schott, RATHGEBER, Vogel and Dataciders/Skaylink.",
        "- Record every application in the tracker with CV version, portal, contact and follow-up date.",
        "",
        "## 12. Application Plan For The Next 7 Days",
        "- Daily: monitor direct portals for Workspacer, Bertrandt, ADAC, TUV SUD, Skaylink, adesso, BMW and ARRK.",
        "- Every second day: search LinkedIn/StepStone/Indeed for Power Automate, Power Platform, n8n, Copilot Studio, Prozessautomatisierung and Validierungsingenieur.",
        "- Build one small portfolio proof: Power Automate + SharePoint approval workflow or Python/OpenPyXL reconciliation demo.",
        "- Prepare concise interview stories for Bertrandt quality documentation, BMW production exposure and AI-agent evidence checks.",
        "",
    ]
    CONTINUED_MD.write_text("\n".join(report), encoding="utf-8")


def write_shortlists(rows: list[dict[str, str]]) -> None:
    top30 = rows[:30]
    top10 = rows[:10]
    TOP30_MD.write_text(
        "\n".join(
            [
                "# Top 30 Application Shortlist - Updated",
                "",
                markdown_table(
                    top30,
                    [
                        ("Rank", "Rank"),
                        ("Fit", "FitScore"),
                        ("Title", "JobTitle"),
                        ("Company", "Company"),
                        ("Location", "Location"),
                        ("Mode", "RemoteHybridOnsite"),
                        ("Cluster", "RoleCluster"),
                        ("CV", "RecommendedCVVersion"),
                        ("URL", "SourceURL"),
                        ("Priority", "ApplicationPriority"),
                    ],
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    APPLY_TODAY_MD.write_text(
        "\n".join(
            [
                "# Apply Today Priority List",
                "",
                "Target for today: 5-8 high-quality applications plus 3-5 recruiter messages.",
                "",
                "\n".join(
                    f"{row['Rank']}. **{row['Company']} - {row['JobTitle']}** ({row['FitScore']}/10)\n"
                    f"   - CV: {row['RecommendedCVVersion']}\n"
                    f"   - Headline: {row['RecommendedHeadline']}\n"
                    f"   - Note: {row['ApplicationNoteShort']}\n"
                    f"   - URL: {row['SourceURL']}"
                    for row in top10
                ),
                "",
                "No-nonsense order: submit direct company portals first, then StepStone/LinkedIn/job-board duplicates only where the direct portal is not available.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_support_files(rows: list[dict[str, str]], previous_count: int, added_count: int, removed_dupes: int, backup_dir: Path) -> None:
    top20 = rows[:20]
    top10 = rows[:10]
    CV_MAPPING_MD.write_text(
        "\n".join(
            [
                "# CV Version Mapping For Top 20 Jobs",
                "",
                markdown_table(
                    top20,
                    [
                        ("Rank", "Rank"),
                        ("Company", "Company"),
                        ("Job", "JobTitle"),
                        ("CV Version", "RecommendedCVVersion"),
                        ("Headline", "RecommendedHeadline"),
                        ("Reason", "WhyItFits"),
                    ],
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    FOLLOW_UP_MD.write_text(
        "\n".join(
            [
                "# Follow-Up Recruiter Targets",
                "",
                "## Highest-Value Outreach Targets",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']}: ask for a short exchange around {', '.join(top_keywords(row, 3))}. URL: {row['SourceURL']}"
                    for row in top10
                ),
                "",
                "## Message Discipline",
                "- Keep each LinkedIn note under 900 characters.",
                "- Mention two concrete matching technologies or workflows.",
                "- Avoid claiming production AI architecture; frame AI-agent work as personal R&D and workflow prototyping.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    RECRUITER_MESSAGES_MD.write_text(
        "\n".join(
            [
                "# Recruiter Messages For Top Jobs",
                "",
                "\n\n".join(
                    f"## {row['Rank']}. {row['Company']} - {row['JobTitle']}\n\n{german_message(row)}"
                    for row in top10
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    APPLICATION_PLAN_MD.write_text(
        "\n".join(
            [
                "# Application Plan Today",
                "",
                "Assumption: 3-5 focused hours available today.",
                "",
                "1. Verify top 20 links and remove anything that has closed.",
                "2. Choose 5-8 applications from the top 10 list; prioritize direct portals.",
                "3. Use ATS Process Automation CV - German for most Power Platform/process roles.",
                "4. Use ATS Quality & Validation CV - German for Bertrandt/MAN/TUV quality roles.",
                "5. Tailor headline, professional summary and top skills only.",
                "6. Submit applications and save portal confirmations.",
                "7. Send 3-5 recruiter messages to Workspacer, Campana & Schott, RATHGEBER, Vogel and Dataciders/Skaylink.",
                "8. Update tracker with source URL, CV version, contact and follow-up date.",
                "9. Prepare tomorrow's follow-up searches: Copilot Studio, n8n, Power Platform Consultant, Prozessautomatisierung KI, Validierungsingenieur.",
                "",
                "Recommended daily target: 5-8 quality applications, 3-5 recruiter messages, 1 tracker update.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    MISSING_SKILLS_MD.write_text(
        "\n".join(
            [
                "# Missing Skills Market Gap",
                "",
                "This update found repeated demand for Power Platform governance, Copilot Studio/Azure OpenAI, n8n/Make, BPMN and automotive quality methods. The recommendations below are tied to observed postings, not generic trend chasing.",
                "",
                "## Immediate Learning, 1-2 Days",
                "- Power Platform environments, licensing and governance basics: repeated in Power Platform consultant/specialist roles.",
                "- Copilot Studio basics: visible in Bayern Facility, WashTec and Microsoft-oriented roles.",
                "- n8n basics: repeated in Workspacer, Vogel and WashTec roles.",
                "- RAG concepts, embeddings and vector stores: useful for CIB, ADAC AI-agent and applied-AI automation roles.",
                "- BPMN/DMN refresher: appears in ADAC and workflow/process management postings.",
                "",
                "## Short-Term Portfolio, 1-2 Weeks",
                "- Power Automate + SharePoint approval workflow with Forms input, Outlook notification and evidence log.",
                "- Python/OpenPyXL reconciliation tool with sample Excel files, exception report and traceability notes.",
                "- n8n mini workflow using an LLM API with a human approval step.",
                "- Industrial documentation RAG assistant demo using a small synthetic quality-document set.",
                "",
                "## Longer-Term Certification, 1-3 Months",
                "- PL-900 first, because it supports nearly every Power Platform role.",
                "- PL-200 next if consultant/business automation roles remain the main target.",
                "- MS-900 for Microsoft 365 credibility.",
                "- Azure AI Fundamentals for AI-automation roles using Copilot Studio/Azure OpenAI.",
                "- PL-400 only if moving toward developer-heavy Power Platform work.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    DAILY_LOG_MD.write_text(
        "\n".join(
            [
                "# Daily Search Log",
                "",
                f"- Search date/time: {CHECKED_AT}",
                "- Sources searched: LinkedIn search results, StepStone, Indeed Germany, Bundesagentur fuer Arbeit mirrors, Workwise/Workwise-style postings, XING snippets, Freelancermap, RapidJob, direct company portals including RATHGEBER, Tyczka, ADAC, CIB, WashTec, Bertrandt and CHECK24.",
                "- Queries used: Power Platform Consultant Muenchen; Power Automate Developer Muenchen; SharePoint Power Platform Muenchen; Microsoft 365 Automation Muenchen; Process Automation Engineer Muenchen; Python Automation Engineer Muenchen; n8n Automation Muenchen; AI Automation Engineer Muenchen; KI Automatisierung Muenchen; Validierungsingenieur Muenchen; Qualitaetsingenieur Automotive Muenchen; Reklamationsmanagement Schienenfahrzeuge; Copilot Studio Bayern.",
                f"- Previous jobs loaded: {previous_count}",
                f"- New suitable jobs appended in this update: {added_count}",
                f"- Duplicates removed during this update: {removed_dupes}",
                f"- Final suitable jobs in continued list: {len(rows)}",
                f"- Backup folder: {backup_dir}",
                "",
                "## Best New Matches",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10): {row['SourceURL']}"
                    for row in ADDITIONS[:8]
                ),
                "",
                "## Excluded This Pass",
                "\n".join(f"- {item['company']} - {item['title']}: {item['reason']}" for item in EXCLUSIONS),
                "",
                "## Weak Recurring Skill Gaps",
                "- Copilot Studio and Azure OpenAI implementation exposure",
                "- Dataverse/Power Apps beyond Power Automate",
                "- n8n/Make/Zapier portfolio evidence",
                "- BPMN/DMN process-modelling vocabulary",
                "- SQL/Power BI for reporting-heavy analyst roles",
                "- Automotive quality methods such as 8D, FMEA, VDA 6.3 and SAP QM",
                "",
                "## Recommended Next Search Terms",
                "- Copilot Studio Consultant Muenchen",
                "- Power Platform Governance Bayern",
                "- Prozessautomatisierung KI Muenchen",
                "- n8n Automatisierung Remote Deutschland",
                "- Junior AI Automation Consultant Germany",
                "- Qualitaetsdokumentation Power BI Automotive Bayern",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    source_csv = Path(os.environ.get("JOB_SEARCH_BASE_CSV", str(CONTINUED_CSV)))
    if not source_csv.exists():
        raise FileNotFoundError(f"Missing source CSV: {source_csv}")
    APP_READY.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_files()
    previous_rows = load_rows(source_csv)
    previous_count = len(previous_rows)
    combined, removed = dedupe_rows(previous_rows + ADDITIONS)
    rows = sort_and_rank(combined)
    added_urls = {normalize_url(row["SourceURL"]) for row in ADDITIONS}
    added_kept = sum(1 for row in rows if normalize_url(row.get("SourceURL", "")) in added_urls)
    write_csv(CONTINUED_CSV, rows)
    write_csv(NEW_ONLY_CSV, [row for row in rows if row.get("NewOrExisting") == "New"])
    write_main_report(rows, previous_count, added_kept, len(removed))
    write_shortlists(rows)
    write_support_files(rows, previous_count, added_kept, len(removed), backup_dir)
    for index, row in enumerate(rows[:10], start=1):
        write_application_pack(row, index)
    print(f"Previous rows: {previous_count}")
    print(f"New additions kept: {added_kept}")
    print(f"Duplicates removed: {len(removed)}")
    print(f"Final rows: {len(rows)}")
    print(f"Backup: {backup_dir}")


if __name__ == "__main__":
    main()
