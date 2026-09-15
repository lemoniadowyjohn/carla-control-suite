from __future__ import annotations

import csv
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from append_latest_jobs_2026_09_07 import (
    APP_READY,
    APPLICATION_PLAN_MD,
    APPLY_TODAY_MD,
    BACKUP_ROOT,
    CONTINUED_CSV,
    CONTINUED_MD,
    CV_MAPPING_MD,
    DAILY_LOG_MD,
    FIELDNAMES,
    FOLLOW_UP_MD,
    MISSING_SKILLS_MD,
    NEW_ONLY_CSV,
    RECRUITER_MESSAGES_MD,
    TOP30_MD,
    cv_for,
    english_message,
    german_message,
    interview_topics,
    load_rows,
    make_row,
    markdown_table,
    normalize_text,
    normalize_url,
    priority_for_score,
    score_value,
    source_link,
    top_keywords,
    write_application_pack,
    write_csv,
)


CHECKED_AT = datetime.now().strftime("%Y-%m-%d %H:%M CET")


ADDITIONS = [
    make_row(
        fit=8.6,
        title="AI Automation Builder",
        company="Kevin Meyer Consulting GmbH",
        location="Remote Germany / Munich company",
        remote="Remote Germany / DACH timezone",
        employment="Full-time, part-time, working student or freelance possible",
        source="Direct company portal",
        url="https://www.kevinmeyerconsulting.de/jobs/ai-automation-builder",
        date="Direct page active; XING shows published 2 days ago; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Kevin Meyer Consulting GmbH",
        cluster="Cluster D - AI automation; Cluster B - Python/process automation",
        why="Very strong AI-workflow automation match: n8n/Make-style automations, API/webhook integration, LLM logic, documentation, monitoring and error handling. The role explicitly accepts different levels and work models.",
        keywords=[
            "AI automation",
            "n8n",
            "Make",
            "APIs",
            "webhooks",
            "LLM logic",
            "documentation",
            "Python plus",
        ],
        risks=[
            "Needs portfolio proof of built automations",
            "Go-to-market/customer systems domain rather than industrial automotive",
            "Remote independence and practical challenge likely",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Automation Builder | Python, Power Automate, n8n/Make Concepts, AI-Agent Workflow R&D",
        note="Apply with a compact automation portfolio story and be ready for a practical workflow task.",
    ),
    make_row(
        fit=8.3,
        title="Data Engineer:in Projektmanagement",
        company="DB InfraGO AG / Deutsche Bahn",
        location="Munich, Bavaria",
        remote="Hybrid / mobile work possible",
        employment="Full-time, permanent",
        source="Indeed Germany / JobStairs / LinkedIn",
        url="https://de.indeed.com/viewjob?jk=00a9c1c915acaff0",
        date="LinkedIn and JobStairs show about 1 day old; Indeed page says application still possible; checked 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - DB InfraGO AG",
        cluster="Cluster B - Python automation / industrial data; Cluster A - M365 automation",
        why="Excellent industrial data/process role: SQL, Excel, SharePoint, SAP, Power BI, Power Automate, Python-linked automation and documentation of queries/code.",
        keywords=[
            "Python",
            "SQL",
            "Excel",
            "Power Query",
            "SharePoint",
            "Power BI",
            "Power Automate",
            "documentation",
        ],
        risks=[
            "Advanced SQL and Power BI may be tested",
            "Rail infrastructure instead of automotive",
            "German working language",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Data & Process Automation Engineer | Python, Excel, SharePoint, Power Automate, Technical Documentation",
        note="One of the best data/process additions; emphasize Excel/OpenPyXL/Pandas reconciliation and documentation discipline.",
    ),
    make_row(
        fit=8.0,
        title="Power Platform Consultant, remote oder hybrid bundesweit",
        company="PCG - Public Cloud Group",
        location="Remote Germany / Munich office option",
        remote="Remote Germany or hybrid",
        employment="Full-time",
        source="LinkedIn Jobs",
        url="https://de.linkedin.com/jobs/view/power-platform-consultant-m-w-d-remote-oder-hybrid-bundesweit-at-pcg-public-cloud-group-4327918952",
        date="LinkedIn shows published about 20 hours ago; checked 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - PCG - Public Cloud Group",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Strong Power Platform/M365 consultant role with process automation, Power Automate, Power Apps, Dataverse, SharePoint/Teams, Copilot agents and PowerShell/API automation.",
        keywords=[
            "Power Platform",
            "Power Automate",
            "Power Apps",
            "Dataverse",
            "SharePoint Online",
            "Microsoft Teams",
            "Copilot Agents",
            "PowerShell",
        ],
        risks=[
            "Requires 3+ years Power Platform development",
            "Canvas Apps and Dataverse experience may be a gap",
            "Azure Logic Apps/Functions expected",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform & M365 Automation Consultant | Power Automate, SharePoint, Python, Process Automation",
        note="Strong target if Power Platform experience can be presented through concrete workflows and fast learning plan for Dataverse.",
    ),
    make_row(
        fit=7.8,
        title="(Senior) Microsoft 365 SharePoint Online Consultant",
        company="evia",
        location="Munich, Bavaria",
        remote="Hybrid / flexible work unclear",
        employment="Full-time",
        source="SimplyHired",
        url="https://www.simplyhired.de/job/xr8rNkJjZDelVfU3d1G1TUfkYFH97bIC_ZhHlJcO62ChU56iBnopnQ",
        date="Crawled 2 weeks ago; page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - evia",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Good M365/SharePoint consultant fit: requirements analysis, M365 governance, SharePoint information architecture, Power Automate and Power Apps implementation.",
        keywords=[
            "SharePoint Online",
            "Microsoft 365",
            "Power Automate",
            "Power Apps",
            "governance",
            "requirements analysis",
            "documentation",
        ],
        risks=[
            "Senior label",
            "M365 governance/permissions depth may be expected",
            "Some support/incident-management wording",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="M365 & SharePoint Automation Consultant | Power Automate, Process Documentation, Python Support",
        note="Good M365 fallback; apply selectively if the ad allows consultant rather than senior-only scope.",
    ),
    make_row(
        fit=7.8,
        title="Senior Consultant - Smart Work / Power Plattform & KI",
        company="Provectus Technologies GmbH",
        location="Munich, Bavaria / remote",
        remote="Remote up to 100%",
        employment="Full-time or part-time",
        source="Direct company portal - Softgarden",
        url="https://provectus.softgarden.io/job/63649909/Senior-Consultant-Smart-Work-Power-Plattform-KI-m-w-d-?l=de",
        date="Published 2026-07-01; page active in search index on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Provectus Technologies GmbH",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster D - AI automation",
        why="Exact smart-work automation theme: Power Platform, M365, SharePoint/Teams, Copilot Studio, AI agents, low-code concepts, governance and rollout.",
        keywords=[
            "Power Platform",
            "Power Automate",
            "Power BI",
            "Microsoft 365",
            "SharePoint",
            "Copilot Studio",
            "AI agents",
            "process optimization",
        ],
        risks=[
            "Senior role with deep Power Platform experience expected",
            "Dataverse/Copilot Studio experience is a gap",
            "Consulting workshop responsibility",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform & AI Workflow Consultant | Power Automate, SharePoint, Process Automation, Documentation",
        note="Useful stretch for a Munich Microsoft partner; do not overclaim senior Power Platform depth.",
    ),
    make_row(
        fit=7.7,
        title="Data Analytics Consultant - Operational Insights",
        company="TUV SUD Digital Service GmbH",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://jobs.tuvsud.com/job/Data-Analytics-Consultant-Operational-Insights-%28mwd%29/6154-de_DE/",
        date="Active since 2026-07-18; updated 2026-08-14 on JobPortal; BA shows recent publication/editing; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - TUV SUD Digital Service GmbH",
        cluster="Cluster B - Python automation / industrial data",
        why="Good data/process improvement role with KPI design, Power BI dashboards, SQL, Python, analytical models and operational-process optimization.",
        keywords=[
            "Power BI",
            "SQL",
            "Python",
            "KPI design",
            "operational insights",
            "data analytics",
            "AI",
            "process improvement",
        ],
        risks=[
            "Requires about 3 years BI/analytics experience",
            "Power BI/SQL may be deeper than current evidence",
            "Consulting and management-presentation expectations",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Industrial Data Analyst | Python, Excel Automation, Power BI, Process Improvement, Documentation",
        note="Good analytical stretch; emphasize reconciliation, validation and documented data workflows.",
    ),
    make_row(
        fit=7.6,
        title="Software Verification and Validation Engineer",
        company="ALTEN",
        location="Bavaria, Germany",
        remote="Hybrid/mobile work possible",
        employment="Full-time, permanent",
        source="Direct company portal - SmartRecruiters",
        url="https://jobs.smartrecruiters.com/ALTEN/744000143760470-software-verification-and-validation-engineer-all-gender-",
        date="Crawled 2 weeks ago; page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - ALTEN project client not specified",
        cluster="Cluster C - Automotive quality / validation",
        why="Good validation/documentation match: requirements traceability, defect/root-cause analysis, test procedures, regression testing and certification/compliance evidence.",
        keywords=[
            "verification",
            "validation",
            "traceability",
            "root-cause analysis",
            "test procedures",
            "certification evidence",
            "compliance documentation",
        ],
        risks=[
            "Software/embedded V&V depth may be expected",
            "Specific test environment experience may be required",
            "Less M365/process automation relevance",
        ],
        cv=cv_for("Cluster C", "English", quality=True),
        headline="Quality & Validation Engineer | Requirements Traceability, Test Documentation, Automotive Process Support",
        note="Good quality/validation target; prepare honest examples around traceability and documentation support.",
    ),
    make_row(
        fit=7.6,
        title="Industrial Automation Engineer OT / IT - PLC & Traceability, Battery Manufacturing",
        company="Webasto",
        location="Munich, Bavaria",
        remote="On-site / travel; hybrid unclear",
        employment="Permanent",
        source="Indeed Germany",
        url="https://de.indeed.com/viewjob?jk=d1aa0a21db6f57e6",
        date="Crawled 3 weeks ago; page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Webasto",
        cluster="Cluster B - industrial process automation; Cluster C - traceability / quality",
        why="Strong industrial automation and traceability role: production facility requirements, acceptance tests, process/machine data acquisition, NOK handling, Python as desirable skill and battery manufacturing.",
        keywords=[
            "industrial automation",
            "traceability",
            "process data",
            "acceptance tests",
            "NOK handling",
            "Python",
            "battery manufacturing",
            "PLC",
        ],
        risks=[
            "Siemens TIA/PLC is a major gap",
            "International travel",
            "Battery manufacturing experience preferred",
        ],
        cv=cv_for("Cluster B", "English"),
        headline="Industrial Process Automation Engineer | Traceability, Python, Quality Documentation, Battery/Automotive Interest",
        note="Strategic industrial target; apply if willing to address PLC/TIA as the main learning gap.",
    ),
    make_row(
        fit=7.4,
        title="Automation Engineer",
        company="CHECK24 Services Personal GmbH",
        location="Munich, Bavaria",
        remote="Munich / flexibility not clearly stated",
        employment="Full-time, permanent; junior",
        source="Direct company portal",
        url="https://jobs.check24.de/de/jobs/app-web-full-stack-inkl-devops/REF290A-automation-engineer-mwd/?employment_types=vollzeit&locations=munich",
        date="BA shows published 30+ days ago and edited yesterday; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - CHECK24 Services Personal GmbH",
        cluster="Cluster B - Python automation / process automation",
        why="Distinct CHECK24 automation role focused on digitizing HR services, orchestrating cloud apps through APIs, internal services and monitoring.",
        keywords=[
            "automation",
            "Python",
            "Django",
            "REST APIs",
            "cloud applications",
            "monitoring",
            "internal services",
        ],
        risks=[
            "Software-heavy full-stack role",
            "React/TypeScript/Django depth likely tested",
            "Less Power Platform/SharePoint relevance",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Python Automation Engineer | Process Automation, APIs, Data Validation, AI Workflow Projects",
        note="Stretch into software automation; separate from the existing CHECK24 HR-Automation full-stack posting.",
    ),
    make_row(
        fit=7.4,
        title="Ingenieur Fahrzeugtechnik & Homologation",
        company="Brunel GmbH NL Muenchen",
        location="Munich, Bavaria",
        remote="On-site; no home office",
        employment="Full-time",
        source="StudySmarter jobs mirror",
        url="https://talents.studysmarter.de/companies/brunel-gmbh-nl-muenchen/ingenieur-fahrzeugtechnik-homologation-w-m-d-42364096/",
        date="Crawled 4 days ago; page active on 2026-09-07",
        direct="Engineering service provider / agency-like",
        end_client="Hidden",
        cluster="Cluster C - Automotive quality / validation; Technical documentation",
        why="Strong documentation/validation process match: technical documentation, planning and tracking validations/tests, supplier/authority coordination and process optimization.",
        keywords=[
            "technical documentation",
            "validation",
            "tests",
            "homologation",
            "supplier coordination",
            "quality",
            "process optimization",
        ],
        risks=[
            "Homologation/regulatory knowledge may be required",
            "No home office",
            "End client hidden",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Quality & Validation Documentation Engineer | Automotive Testing, Traceability, Process Improvement",
        note="Good quality fallback; use Bertrandt/BMW production/process exposure heavily.",
    ),
    make_row(
        fit=7.3,
        title="Solution Architect Microsoft Power Platform",
        company="Arineo GmbH",
        location="Remote Germany / Munich / Nuremberg-Fuerth",
        remote="Remote Germany / hybrid office options",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://jobs.arineo.com/jobs/jobdetails/2408719/solution-architect-microsoft-power-platform-all-genders?lang=de",
        date="BA shows published about 10 days ago; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Arineo GmbH",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster D - AI automation",
        why="Exact Microsoft partner role around Power Platform, Copilot Studio, Power Automate, Power Apps, governance, ALM, M365 and AI adoption.",
        keywords=[
            "Power Platform",
            "Power Automate",
            "Power Apps",
            "Copilot Studio",
            "Dataverse",
            "Azure",
            "M365",
            "governance",
        ],
        risks=[
            "Architect title and several years experience expected",
            "Dataverse/Azure/ALM gaps",
            "Customer workshops and mentoring responsibility",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Automation Consultant | Power Automate, SharePoint/M365, Python, AI Workflow R&D",
        note="Apply selectively or use for networking; seniority risk is real.",
    ),
    make_row(
        fit=7.1,
        title="Mitarbeiter Wareneingang / Qualitaetssicherung",
        company="Bertrandt Group",
        location="Munich / Garching bei Muenchen",
        remote="On-site",
        employment="Full-time",
        source="Direct company portal - SAP SuccessFactors",
        url="https://bertrandt.jobs.hr.cloud.sap/job/Mitarbeiter-Qualit%C3%A4tssicherung-%28mwd%29/1894-de_DE/",
        date="Crawled last month; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Bertrandt Group",
        cluster="Cluster C - Automotive quality / validation",
        why="Bertrandt continuity with quality assurance, incoming-goods inspection, supplier complaints, interface work with production/logistics/purchasing/development and MS Office/ERP.",
        keywords=[
            "quality assurance",
            "incoming goods inspection",
            "supplier complaints",
            "MS Office",
            "ERP",
            "production",
            "automotive",
        ],
        risks=[
            "Technician/operator-level role",
            "Five years manufacturing QA requested",
            "Low automation career value",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Quality Documentation & Process Support Specialist | Bertrandt Automotive, Traceability, MS Office",
        note="Use only as a Bertrandt quality fallback, not as a main automation target.",
    ),
    make_row(
        fit=6.9,
        title="(Junior) Softwareingenieur Embedded Integration",
        company="Guldberg GmbH",
        location="Munich, Bavaria",
        remote="On-site / fixed hours",
        employment="Full-time",
        source="HeyJobs",
        url="https://www.heyjobs.co/en-de/jobs/df3d993e-8793-4b24-92b2-159e1a04744c",
        date="Crawled 5 months ago; page active in search index on 2026-09-07",
        direct="Agency / engineering service provider",
        end_client="Hidden",
        cluster="Cluster C - Automotive validation/documentation; embedded stretch",
        why="Junior-labelled automotive/defence integration role with validation, V-model, ASPICE, ISO 26262 and technical documentation. Useful only as a validation/documentation stretch.",
        keywords=[
            "junior",
            "integration",
            "validation",
            "V-model",
            "ASPICE",
            "ISO 26262",
            "technical documentation",
        ],
        risks=[
            "Embedded/AUTOSAR knowledge likely required",
            "End client hidden",
            "Less process automation relevance",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Junior Validation & Technical Documentation Engineer | Automotive Processes, Traceability, Python Basics",
        note="Borderline; apply only if the job ad does not insist on embedded software depth.",
    ),
    make_row(
        fit=6.9,
        title="Ingenieur / Techniker Fahrerassistenzsysteme / Autonomes Fahren",
        company="Bertrandt Group",
        location="Munich, Bavaria",
        remote="On-site; travel for test drives",
        employment="Full-time",
        source="Direct company portal - SAP SuccessFactors",
        url="https://bertrandt.jobs.hr.cloud.sap/job/Ingenieur-Techniker-f%C3%BCr-Fahrerassistenzsysteme-Autonomes-Fahren-%28mwd%29/910-de_DE/",
        date="Crawled last week; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Bertrandt Group",
        cluster="Cluster C - Automotive validation; autonomous-driving stretch",
        why="Matches CARLA/OpenDRIVE/autonomous-driving interest and includes component validation, vehicle testing and documentation of results.",
        keywords=[
            "ADAS",
            "autonomous driving",
            "validation",
            "vehicle testing",
            "documentation",
            "automotive",
        ],
        risks=[
            "Kfz-mechatronics/technician background requested",
            "ADAS hands-on experience likely expected",
            "Travel and testing role rather than automation role",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Automotive Validation Engineer | CARLA/OpenDRIVE Thesis, Test Documentation, Traceability",
        note="Strategic Bertrandt/autonomous-driving stretch; not a priority compared with automation roles.",
    ),
]


EXCLUSIONS = [
    "AllDent Power Platform / KI-CoE Lead - exact keywords but CoE lead with 4+ years Power Platform and governance ownership.",
    "LTM Microsoft Power Platform CoPilot Architect - contract architect role with deep Azure/RAG/DevOps requirements.",
    "DYN-IT Senior Consultant Copilot Studio & Power Platform - freelance senior consultant; useful market signal but not realistic first target.",
    "BMW / Siemens / AURELIUS / ProGlove student AI automation roles - good keyword matches but require active enrollment.",
    "Bertrandt Senior Quality Manager Customer & Project Quality - relevant quality keywords but senior escalation/management scope.",
    "ALTEN AMS Verification Engineer - electronics/AMS simulation verification, not candidate's main evidence.",
]


def backup_files_round2() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"latest_search_round2_{stamp}"
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
    obsolete_dir = dest / "previous_application_packs"
    obsolete_dir.mkdir(exist_ok=True)
    for pack in APP_READY.glob("*application_pack.md"):
        shutil.move(str(pack), obsolete_dir / pack.name)
    return dest


def dedupe(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[tuple[dict[str, str], str]]]:
    seen_urls: dict[str, dict[str, str]] = {}
    seen_titles: dict[str, dict[str, str]] = {}
    kept: list[dict[str, str]] = []
    removed: list[tuple[dict[str, str], str]] = []
    for row in rows:
        url_key = normalize_url(row.get("SourceURL", ""))
        title_key = f"{normalize_text(row.get('Company', ''))}|{normalize_text(row.get('JobTitle', ''))}"
        if url_key and url_key in seen_urls:
            row["DuplicateOf"] = f"{seen_urls[url_key].get('Company')} - {seen_urls[url_key].get('JobTitle')}"
            removed.append((row, "same URL"))
            continue
        if title_key in seen_titles:
            row["DuplicateOf"] = f"{seen_titles[title_key].get('Company')} - {seen_titles[title_key].get('JobTitle')}"
            removed.append((row, "same company/title"))
            continue
        kept.append(row)
        if url_key:
            seen_urls[url_key] = row
        seen_titles[title_key] = row
    return kept, removed


def write_main_report(rows: list[dict[str, str]], previous_count: int, added_count: int, dupes: int) -> None:
    role_counts = Counter(row["RoleCluster"].split(";")[0].strip() for row in rows)
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
    report = [
        "# Munich / Bavaria Job Matches for Michal Dembski - Continued Update",
        "",
        "## 1. Executive Summary",
        (
            f"Loaded {previous_count} previously tracked suitable jobs and appended {added_count} additional verified jobs in this search pass. "
            f"The final deduped list now contains {len(rows)} suitable jobs. The newest additions strengthen AI automation, Power Platform/M365, industrial data automation, and automotive validation/documentation coverage."
        ),
        "",
        "## 2. Number Of Jobs Found",
        f"- Total suitable jobs in continued list: {len(rows)}",
        f"- Newly appended in this search pass: {added_count}",
        f"- Duplicates removed in this pass: {dupes}",
        "",
        "## 3. Number Of Jobs Excluded And Why",
        "\n".join(f"- {item}" for item in EXCLUSIONS),
        "",
        "## 4. Ranked Table Of All Included Jobs",
        markdown_table(rows, columns),
        "",
        "## 5. Top 20 Shortlist",
        markdown_table(
            rows[:20],
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
            for row in rows[:10]
        ),
        "",
        "## 7. Role Cluster Analysis",
        "\n".join(f"- {cluster}: {count}" for cluster, count in role_counts.most_common()),
        "",
        "## 8. Best Companies To Monitor Daily",
        "- Workspacer",
        "- RATHGEBER",
        "- Campana & Schott",
        "- Bertrandt Group",
        "- TUV SUD",
        "- ADAC",
        "- PCG / Microsoft partner ecosystem",
        "- Arineo / Provectus / Skaylink",
        "- DB InfraGO / Deutsche Bahn",
        "- Webasto / automotive suppliers",
        "",
        "## 9. Missing Skills Repeated Across The Market",
        "- Dataverse, Power Apps and Power Platform ALM/governance",
        "- Copilot Studio agents, Microsoft Foundry and Azure OpenAI basics",
        "- n8n/Make automation portfolio proof",
        "- SQL and Power BI beyond Excel/OpenPyXL",
        "- BPMN/DMN and requirements traceability vocabulary",
        "- Automotive quality methods: 8D, FMEA, ASPICE, ISO 26262, VDA 6.3, SAP QM",
        "- PLC/TIA Portal for industrial automation/traceability roles",
        "",
        "## 10. CV Version Recommendation",
        "Use ATS Process Automation CV - German for most applications. Use ATS Quality & Validation CV - German/English only for ALTEN, Bertrandt, Brunel, Webasto and automotive validation roles. Use English for international AI/software-oriented postings such as Workspacer Junior, Webasto and ALTEN where the ad is English-language.",
        "",
        "## 11. Application Plan For Today",
        "- Apply first to Workspacer, RATHGEBER, Campana & Schott, fly-tech IT, Keller & Kalmbach, Kevin Meyer Consulting, Vogel and TPG.",
        "- Submit 5-8 applications, not all 10, if time is limited.",
        "- Tailor headline/summary/top skills only; keep experience honest.",
        "- Send recruiter messages to Workspacer, RATHGEBER, Kevin Meyer Consulting, Campana & Schott and TPG.",
        "- Record every submission in the tracker with source URL and CV version.",
        "",
        "## 12. Application Plan For The Next 7 Days",
        "- Day 1-2: Power Platform/process automation roles.",
        "- Day 3: AI automation roles with n8n/Make/Copilot Studio.",
        "- Day 4: Quality/validation backup roles at Bertrandt, ALTEN, Brunel and Webasto.",
        "- Day 5-7: Follow-ups, recruiter messages and portfolio mini-demo preparation.",
        "",
    ]
    CONTINUED_MD.write_text("\n".join(report), encoding="utf-8")


def write_outputs(rows: list[dict[str, str]], previous_count: int, added_count: int, dupes: int, backup_dir: Path) -> None:
    write_csv(CONTINUED_CSV, rows)
    write_csv(NEW_ONLY_CSV, [row for row in rows if row.get("NewOrExisting") == "New"])
    write_main_report(rows, previous_count, added_count, dupes)
    TOP30_MD.write_text(
        "# Top 30 Application Shortlist - Updated\n\n"
        + markdown_table(
            rows[:30],
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
        )
        + "\n",
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
                    for row in rows[:10]
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    CV_MAPPING_MD.write_text(
        "# CV Version Mapping For Top 20 Jobs\n\n"
        + markdown_table(
            rows[:20],
            [
                ("Rank", "Rank"),
                ("Company", "Company"),
                ("Job", "JobTitle"),
                ("CV Version", "RecommendedCVVersion"),
                ("Headline", "RecommendedHeadline"),
                ("Reason", "WhyItFits"),
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    FOLLOW_UP_MD.write_text(
        "\n".join(
            [
                "# Follow-Up Recruiter Targets",
                "",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']}: ask about {', '.join(top_keywords(row, 3))}. URL: {row['SourceURL']}"
                    for row in rows[:12]
                ),
                "",
                "Prioritize direct messages for Workspacer, RATHGEBER, Kevin Meyer Consulting, Campana & Schott, TPG and PCG.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    RECRUITER_MESSAGES_MD.write_text(
        "\n\n".join(
            ["# Recruiter Messages For Top Jobs", ""]
            + [
                f"## {row['Rank']}. {row['Company']} - {row['JobTitle']}\n\n{german_message(row)}"
                for row in rows[:10]
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    APPLICATION_PLAN_MD.write_text(
        "\n".join(
            [
                "# Application Plan Today",
                "",
                "Assumption: 3-5 focused hours available today.",
                "",
                "1. Verify the top 20 links.",
                "2. Apply to 5-8 top roles, starting with direct company portals.",
                "3. Use ATS Process Automation CV - German for the first batch.",
                "4. Tailor headline, summary and top skills for each application.",
                "5. Send 3-5 recruiter messages.",
                "6. Update the tracker immediately after each submission.",
                "7. Prepare short project evidence for Power Automate, Python reconciliation and AI-agent workflow R&D.",
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
                "## Immediate Learning, 1-2 Days",
                "- Copilot Studio agents and actions: repeated in PCG, Provectus, Arineo, Skaylink, Bayern Facility and WashTec roles.",
                "- Dataverse and Power Platform environment/governance basics: repeated in consultant and architect postings.",
                "- n8n/Make/webhook/API basics: repeated in Kevin Meyer Consulting, Workspacer, Vogel and AI automation postings.",
                "- SQL + Power BI refresh: repeated in DB InfraGO, TUV SUD and data/process roles.",
                "",
                "## Short-Term Portfolio, 1-2 Weeks",
                "- Power Automate + SharePoint approval workflow with evidence log.",
                "- Python/OpenPyXL reconciliation tool with exception report and traceability notes.",
                "- n8n workflow using an LLM API with human approval and error handling.",
                "- Mini Power BI dashboard fed by cleaned Excel/CSV data.",
                "",
                "## Longer-Term Certification, 1-3 Months",
                "- PL-900 first.",
                "- PL-200 second if Power Platform consulting remains the main target.",
                "- MS-900 for M365 credibility.",
                "- Azure AI Fundamentals for Copilot Studio/Azure OpenAI roles.",
                "- PL-400 only after stronger Power Apps/Dataverse project evidence.",
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
                "- Sources searched: direct company portals, LinkedIn Jobs, StepStone, Indeed Germany, BA Jobsuche mirrors, XING, SmartRecruiters, Softgarden, Personio, JobStairs, StudySmarter, HeyJobs.",
                "- New search terms: Copilot Studio Power Platform Muenchen; AI Automation Builder Muenchen n8n; Data Engineer Projektmanagement Power Automate; Software Verification Validation Engineer Bayern; Industrial Automation Traceability Battery Manufacturing; Microsoft Power Platform Solution Architect remote Germany.",
                f"- Previous suitable jobs loaded: {previous_count}",
                f"- New suitable jobs added in this pass: {added_count}",
                f"- Duplicates removed in this pass: {dupes}",
                f"- Final suitable jobs in continued list: {len(rows)}",
                f"- Backup folder: {backup_dir}",
                "",
                "## Best New Matches",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10): {row['SourceURL']}"
                    for row in ADDITIONS[:10]
                ),
                "",
                "## Excluded This Pass",
                "\n".join(f"- {item}" for item in EXCLUSIONS),
                "",
                "## Recommended Next Search Terms",
                "- Power Platform Functional Consultant Bayern junior",
                "- Copilot Studio Consultant Muenchen remote",
                "- Python Excel SharePoint Power Automate Muenchen",
                "- Validierungsingenieur Traceability Python Bayern",
                "- Prozessautomatisierung Power BI Power Automate Bayern",
                "",
            ]
        ),
        encoding="utf-8",
    )
    for index, row in enumerate(rows[:10], start=1):
        write_application_pack(row, index)


def main() -> None:
    APP_READY.mkdir(parents=True, exist_ok=True)
    previous_rows = load_rows(CONTINUED_CSV)
    previous_count = len(previous_rows)
    backup_dir = backup_files_round2()
    combined, removed = dedupe(previous_rows + ADDITIONS)
    rows = sorted(
        combined,
        key=lambda row: (
            -score_value(row),
            0 if row.get("DirectOrAgency") == "Direct employer" else 1,
            normalize_text(row.get("Company", "") + " " + row.get("JobTitle", "")),
        ),
    )
    for index, row in enumerate(rows, start=1):
        score = score_value(row)
        row["Rank"] = str(index)
        row["ApplicationPriority"] = priority_for_score(score)
        row["ApplyToday"] = "Yes" if index <= 10 else "No"
        if not row.get("CheckedAt"):
            row["CheckedAt"] = CHECKED_AT
    addition_urls = {normalize_url(row["SourceURL"]) for row in ADDITIONS}
    added_count = sum(1 for row in rows if normalize_url(row.get("SourceURL", "")) in addition_urls)
    write_outputs(rows, previous_count, added_count, len(removed), backup_dir)
    print(f"Previous rows: {previous_count}")
    print(f"New additions kept: {added_count}")
    print(f"Duplicates removed: {len(removed)}")
    print(f"Final rows: {len(rows)}")
    print(f"Backup: {backup_dir}")


if __name__ == "__main__":
    main()
