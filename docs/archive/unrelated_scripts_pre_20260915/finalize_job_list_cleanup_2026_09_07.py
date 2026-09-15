from __future__ import annotations

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
    FOLLOW_UP_MD,
    MISSING_SKILLS_MD,
    NEW_ONLY_CSV,
    RECRUITER_MESSAGES_MD,
    TOP30_MD,
    english_message,
    german_message,
    interview_topics,
    load_rows,
    markdown_table,
    normalize_text,
    priority_for_score,
    score_value,
    top_keywords,
    write_application_pack,
    write_csv,
)


CHECKED_AT = datetime.now().strftime("%Y-%m-%d %H:%M CET")
BASELINE_PREVIOUS_COUNT = 208
LATEST_APPEND_COUNT = 25
LATEST_UPDATED_EXISTING = 1
LATEST_DUPLICATES_SKIPPED = 1

LATEST_PASS_HIGHLIGHTS = [
    ("REPA Deutschland GmbH / REPA GROUP", "Junior Data Analyst & Data Operations Specialist (m/f/d)", "8.4", "https://jobs.smartrecruiters.com/REPAGROUP/744000145955800-junior-data-analyst-data-operations-specialist-m-f-d-"),
    ("Portal Systems / PSC Portal Systems Consulting GmbH", "ECM Consultant for Microsoft 365 (m/f/d)", "8.1", "https://www.portalsystems.de/en/jobs-career/ecm-consultants-microsoft-365/"),
    ("SUXXEED Sales for your Success GmbH", "Junior AI Engineer (m/w/d)", "8.0", "https://www.xing.com/jobs/nuernberg-junior-ai-engineer-156908279"),
    ("CONET Technologies Holding GmbH / CONET", "Microsoft 365 Consultant - AI & Modern Work", "7.8", "https://www.conet.de/de/karriere/jobs/2026-104-microsoft-365-consultant-ai-modern-work/"),
    ("Reply Deutschland SE", "(Junior) Projektmanager AI & Computer Vision (m/w/d)", "7.8", "https://www.jobteaser.com/en/job-offers/83762351-94fe-4bd5-b88d-7286e3719503-reply-deutschland-se-junior-projektmanager-ai-computer-vision-m-w-d"),
    ("Deloitte", "Consultant Intelligent Automation - Einstieg in AI & Data (m/w/d)", "7.7", "https://job.deloitte.com/job-consultant-intelligent-automation-dein-einstieg-in-ai-data-mwd-_49502"),
    ("Deloitte", "Consultant KI in Operations - Einkauf, Supply Chain, Produktion oder Qualitaet (m/w/d)", "7.7", "https://job.deloitte.com/job-consultant-ki-in-operations-einkauf-supply-chain-produktion-oder-qualitaet-mwd-_50177"),
    ("REPA Deutschland GmbH / REPA GROUP", "AI Engineer / Specialist (m/f/d)", "7.7", "https://jobs.smartrecruiters.com/REPAGROUP/744000144725420-ai-engineer-specialist-m-f-d-"),
    ("Reply Deutschland SE", "Junior AI Solutions Engineer (m/w/d)", "7.6", "https://www.reply.com/de/about/careers/de/job-details/JOB-11382?country=de"),
    ("MEKRA Lang GmbH & Co. KG", "Junior AI Engineer (m/w/d)", "7.6", "https://websiteold.mekra.de/en/karriere/stellenangebote/stellenangebote/junior-ai-engineer-m-w-d-detail/cj20057"),
    ("YER", "RPA Developer (m/w/d)", "7.5", "https://www.yer.de/de/jobangebote/rpa-developer-mwd-augsburg-1791/"),
    ("Allianz Technology", "AI Transformation Analyst (m/f/d)", "7.5", "https://www.xing.com/jobs/muenchen-ai-transformation-analyst-157184194"),
]

EXCLUSIONS_AND_REMOVALS = [
    "Removed STARK - Automation Engineer (All genders): latest source check showed the posting is no longer accepting applications.",
    "Excluded WBS Gruppe Junior Power Platform Developer: Remotely page says not available since 2026-03-24.",
    "Excluded Neovaro Automation Engineer: source page says no longer available.",
    "Excluded Allianz Business Analyst Systemintegration & Prozesssteuerung: direct Allianz page showed job filled despite third-party mirrors.",
    "Excluded BMW senior/founding AI roles: too senior/deep AI for current evidence.",
    "Excluded Infineon Principal Engineer Agentic Software Development and Verification: principal-level scope.",
    "Excluded Apple E-Commerce & AI Specialist: partner/e-commerce sales scope, weak engineering-process match.",
    "Excluded elunic AI Sales Consultant roles: sales-led roles.",
]


def backup_current_outputs() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"closed_cleanup_{stamp}"
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
    if APP_READY.exists():
        pack_backup = dest / "application_ready_today"
        pack_backup.mkdir(exist_ok=True)
        for pack in APP_READY.glob("*.md"):
            shutil.copy2(pack, pack_backup / pack.name)
            pack.unlink()
    return dest


def is_closed_stark_automation(row: dict[str, str]) -> bool:
    return (
        normalize_text(row.get("Company", "")) == "stark"
        and normalize_text(row.get("JobTitle", "")) == "automation engineer"
        and "4454100900" in row.get("SourceURL", "")
    )


def rank_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = sorted(
        rows,
        key=lambda row: (
            -score_value(row),
            0 if "Direct employer" in row.get("DirectOrAgency", "") else 1,
            normalize_text(row.get("Company", "")),
            normalize_text(row.get("JobTitle", "")),
        ),
    )
    for index, row in enumerate(rows, start=1):
        score = score_value(row)
        row["Rank"] = str(index)
        row["ApplicationPriority"] = priority_for_score(score)
        row["ApplyToday"] = "Yes" if index <= 10 else "No"
        if not row.get("CheckedAt"):
            row["CheckedAt"] = CHECKED_AT
    return rows


def write_reports(rows: list[dict[str, str]], removed_closed: list[dict[str, str]], backup_dir: Path) -> None:
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
    role_counts = Counter(row.get("RoleCluster", "").split(";")[0].strip() for row in rows)
    new_rows = [row for row in rows if row.get("NewOrExisting") == "New"]

    write_csv(CONTINUED_CSV, rows)
    write_csv(NEW_ONLY_CSV, new_rows)

    CONTINUED_MD.write_text(
        "\n".join(
            [
                "# Munich / Bavaria Job Matches for Michal Dembski - Continued Update",
                "",
                "## 1. Executive Summary",
                (
                    f"Loaded {BASELINE_PREVIOUS_COUNT} previously tracked suitable jobs, appended {LATEST_APPEND_COUNT} additional suitable jobs in the latest search pass, "
                    f"upgraded {LATEST_UPDATED_EXISTING} existing row to cleaner direct-source data, skipped {LATEST_DUPLICATES_SKIPPED} duplicate and removed {len(removed_closed)} stale/closed posting. "
                    f"The active suitable list now contains {len(rows)} jobs. Both B.Eng. study programs were considered for industrial engineering, engineering management, process improvement, requirements work and technical project coordination; scores were still capped where ads require senior AI/ML/cloud architecture experience."
                ),
                "",
                "## 2. Number Of Jobs Found",
                f"- Total suitable jobs in continued list after cleanup: {len(rows)}",
                f"- Rows marked new from all continued searches: {len(new_rows)}",
                f"- Newly appended in the latest search pass: {LATEST_APPEND_COUNT}",
                f"- Removed closed/stale postings after verification: {len(removed_closed)}",
                "",
                "## 3. Number Of Jobs Excluded And Why",
                "\n".join(f"- {item}" for item in EXCLUSIONS_AND_REMOVALS),
                "",
                "## 4. Ranked Table Of All Included Jobs",
                markdown_table(rows, columns),
                "",
                "## 5. Top 20 Shortlist",
                markdown_table(rows[:20], columns),
                "",
                "## 6. Top 10 Apply-Today List",
                "\n".join(
                    f"{row['Rank']}. {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10) - {row['RecommendedCVVersion']} - {row['SourceURL']}"
                    for row in rows[:10]
                ),
                "",
                "## 7. Role Cluster Analysis",
                "\n".join(f"- {cluster or 'Unclear'}: {count}" for cluster, count in role_counts.most_common()),
                "",
                "## 8. Best Companies To Monitor Daily",
                "- Workspacer",
                "- Campana & Schott",
                "- Reply / Machine Learning Reply",
                "- REPA Deutschland / REPA GROUP",
                "- 42watt",
                "- Deloitte",
                "- Bertrandt Group",
                "- BMW Group",
                "- Siemens / Siemens Mobility",
                "- TUV SUD",
                "",
                "## 9. Missing Skills Repeated Across The Market",
                "- Copilot Studio, AI Builder and Microsoft agent governance.",
                "- Dataverse, Power Apps and Power Platform ALM/governance.",
                "- n8n/Make, API/webhook automation and structured error handling.",
                "- SQL, Power BI, Power Query and basic DAX.",
                "- RAG, embeddings, vector stores, function calling/tool use and LLM evals.",
                "- UiPath/Blue Prism for RPA roles.",
                "- DOORS/Polarion, ASPICE/ISO 26262 and model-based testing for automotive validation roles.",
                "",
                "## 10. CV Version Recommendation",
                "Use ATS Process Automation CV - German most often. Use ATS Quality & Validation CV - German for Bertrandt/MEKRA/b-plus/ALTEN validation roles. Use English for international AI/data postings such as REPA AI Engineer or English-language consulting roles.",
                "",
                "## 11. Application Plan For Today",
                "- Apply to 5-8 high-quality roles, not the whole list.",
                "- Start with Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, REPA Junior Data Analyst, TPG and 42watt.",
                "- Tailor only headline, summary and top skills.",
                "- Send 3-5 recruiter messages to Workspacer, RATHGEBER, 42watt, REPA and Reply.",
                "- Update the tracker immediately after each application.",
                "",
                "## 12. Application Plan For The Next 7 Days",
                "- Days 1-2: Power Platform, M365, process automation and REPA/42watt additions.",
                "- Day 3: Junior AI/applied AI roles at Reply, SUXXEED, Deloitte and MEKRA.",
                "- Day 4: Quality/validation backup roles at Bertrandt, MEKRA, b-plus, ALTEN and Webasto.",
                "- Day 5: Direct company portal recheck for BMW, Siemens, MAN, IAV, EDAG, ARRK, Expleo and Akkodis.",
                "- Days 6-7: Recruiter follow-up and small portfolio proof for Power Automate + SharePoint and Python/OpenPyXL reconciliation.",
                "",
                f"Backup folder for this cleanup: {backup_dir}",
                "",
            ]
        ),
        encoding="utf-8",
    )

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
                "## Top 10 Overall",
                "\n".join(
                    f"{row['Rank']}. **{row['Company']} - {row['JobTitle']}** ({row['FitScore']}/10)\n"
                    f"   - CV: {row['RecommendedCVVersion']}\n"
                    f"   - Headline: {row['RecommendedHeadline']}\n"
                    f"   - Note: {row['ApplicationNoteShort']}\n"
                    f"   - URL: {row['SourceURL']}"
                    for row in rows[:10]
                ),
                "",
                "## Best Additional Jobs Found Or Rechecked In Latest Pass",
                "\n".join(
                    f"- **{company} - {title}** ({fit}/10): {url}"
                    for company, title, fit, url in LATEST_PASS_HIGHLIGHTS
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    CV_MAPPING_MD.write_text(
        "# CV Version Mapping For Top 30 Jobs\n\n"
        + markdown_table(
            rows[:30],
            [
                ("Rank", "Rank"),
                ("Company", "Company"),
                ("Job", "JobTitle"),
                ("CV Version", "RecommendedCVVersion"),
                ("Headline", "RecommendedHeadline"),
                ("Priority", "ApplicationPriority"),
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
                "## Highest Priority",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']}: ask about {', '.join(top_keywords(row, 3))}. URL: {row['SourceURL']}"
                    for row in rows[:12]
                ),
                "",
                "## Latest-Pass Additions Worth Messaging",
                "\n".join(
                    f"- {company} - {title}: {url}" for company, title, _fit, url in LATEST_PASS_HIGHLIGHTS[:10]
                ),
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
                "1. Verify top 20 links, starting with direct company portals.",
                "2. Choose 5-8 applications: prioritize Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, REPA Junior Data Analyst, TPG and 42watt.",
                "3. Use ATS Process Automation CV - German for most roles.",
                "4. Use ATS Quality & Validation CV - German only for quality/validation roles.",
                "5. Tailor headline, summary and top skills only.",
                "6. Submit applications and save source URL, CV version and date.",
                "7. Send 3-5 recruiter messages to 42watt, REPA, Workspacer, Reply and RATHGEBER.",
                "8. Prepare tomorrow's follow-up and one portfolio proof screenshot/summary.",
                "",
                "Quality target: 5-8 applications, 3-5 recruiter messages, 1 updated tracker.",
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
                "- Copilot Studio agents/actions and AI Builder: repeated across Campana & Schott, fly-tech, PCG, CONET, CANCOM, WBS-style postings and Avanade/Power Platform roles.",
                "- Dataverse basics: repeated in Power Platform consultant/developer postings, including affinis, PCG and WBS-style roles.",
                "- RAG, embeddings, vector stores and function calling/tool use: repeated across Reply, Deloitte, REPA, SUXXEED, smartvillage and Drees & Sommer.",
                "- n8n/Make/webhooks/API basics: repeated in Workspacer, 42watt, Kevin Meyer Consulting, Vogel, smartvillage and other AI-automation roles.",
                "- SQL, Power Query, Power BI and basic DAX: repeated in REPA Junior Data Analyst, DB InfraGO, TUV SUD and industrial data roles.",
                "",
                "## Short-Term Portfolio, 1-2 Weeks",
                "- Power Automate + SharePoint approval workflow with Forms input, evidence log and Outlook notification.",
                "- Python/OpenPyXL/Pandas reconciliation tool with exception report and validation rules.",
                "- n8n or Make workflow using an LLM API, a human approval step and structured output validation.",
                "- Mini RAG assistant for industrial/quality documentation with citations and cannot-answer behavior.",
                "- One-page Power BI dashboard from cleaned Excel/CSV data.",
                "",
                "## Longer-Term Certification, 1-3 Months",
                "- PL-900 first for Power Platform credibility.",
                "- MS-900 for Microsoft 365 foundation.",
                "- PL-200 if Power Platform consulting becomes the main lane.",
                "- Azure AI Fundamentals for AI/Copilot/RAG roles.",
                "- PL-400 only after stronger Power Apps, Dataverse and connector project evidence.",
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
                "- Sources searched: direct company portals, Personio, SmartRecruiters, Reply careers, Deloitte careers, Portal Systems careers, CONET careers, REPA careers, MEKRA careers, LinkedIn Jobs, XING Jobs, StepStone, Indeed Germany, Remotely, StudySmarter and BA/search mirrors.",
                "- Queries used: Automation Engineer Muenchen n8n; Junior AI Engineer Bayern RAG; Power Platform Copilot Studio Muenchen; Microsoft 365 Consultant AI Modern Work Muenchen; RPA Developer Augsburg Power Automate; Requirements Engineer Traceability Bayern; AI Transformation Analyst Unterfoehring; AI Integration Specialist Muenchen.",
                f"- Previous suitable jobs loaded: {BASELINE_PREVIOUS_COUNT}",
                f"- New jobs found and appended in latest search pass: {LATEST_APPEND_COUNT}",
                f"- Existing rows upgraded: {LATEST_UPDATED_EXISTING}",
                f"- Duplicates skipped/removed in latest search pass: {LATEST_DUPLICATES_SKIPPED}",
                f"- Closed/stale jobs removed after verification: {len(removed_closed)}",
                f"- Final suitable active/recently active jobs in continued list: {len(rows)}",
                f"- Backup folder: {backup_dir}",
                "",
                "## Best New Matches",
                "\n".join(
                    f"- {company} - {title} ({fit}/10): {url}" for company, title, fit, url in LATEST_PASS_HIGHLIGHTS
                ),
                "",
                "## Weak Recurring Skill Gaps",
                "- Dataverse, Power Apps and Power Platform ALM.",
                "- Copilot Studio, RAG, embeddings and function/tool calling.",
                "- n8n/Make production workflow examples.",
                "- SQL, Power BI, Power Query and basic DAX.",
                "- UiPath/Blue Prism for RPA roles.",
                "- DOORS/Polarion, ASPICE/ISO 26262 for automotive validation roles.",
                "",
                "## Recommended Next Search Terms",
                "- Junior Power Platform Developer Bayern Dataverse",
                "- Microsoft 365 Consultant SharePoint Power Automate remote Deutschland",
                "- Junior Data Analyst Power Automate Excel Bayern",
                "- AI Automation Engineer n8n Make Muenchen",
                "- Requirements Engineer Traceability Automotive Bayern junior",
                "- KI Automatisierung Spezialist Mittelstand Muenchen",
                "",
                "## Excluded Or Removed This Pass",
                "\n".join(f"- {item}" for item in EXCLUSIONS_AND_REMOVALS),
                "",
            ]
        ),
        encoding="utf-8",
    )

    for index, row in enumerate(rows[:10], start=1):
        write_application_pack(row, index)


def main() -> None:
    APP_READY.mkdir(parents=True, exist_ok=True)
    rows = load_rows(CONTINUED_CSV)
    backup_dir = backup_current_outputs()
    removed_closed = [row for row in rows if is_closed_stark_automation(row)]
    rows = [row for row in rows if not is_closed_stark_automation(row)]
    rows = rank_rows(rows)
    write_reports(rows, removed_closed, backup_dir)
    print(f"Removed closed rows: {len(removed_closed)}")
    print(f"Final rows: {len(rows)}")
    print(f"Backup: {backup_dir}")
    print("Top 10:")
    for row in rows[:10]:
        print(f"{row['Rank']}. {row['FitScore']} - {row['Company']} - {row['JobTitle']}")


if __name__ == "__main__":
    main()
