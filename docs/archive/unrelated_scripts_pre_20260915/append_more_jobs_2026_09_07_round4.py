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
    FIELDNAMES,
    FOLLOW_UP_MD,
    MISSING_SKILLS_MD,
    NEW_ONLY_CSV,
    RECRUITER_MESSAGES_MD,
    TOP30_MD,
    cv_for,
    german_message,
    load_rows,
    make_row,
    markdown_table,
    normalize_text,
    normalize_url,
    priority_for_score,
    score_value,
    top_keywords,
    write_application_pack,
    write_csv,
)


CHECKED_AT = datetime.now().strftime("%Y-%m-%d %H:%M CET")


ADDITIONS = [
    make_row(
        fit=8.2,
        title="AI Implementation Engineer (m/w/d)",
        company="Liebherr-IT Services GmbH",
        location="Kirchdorf/Oberopfingen, southern Germany",
        remote="Hybrid / Flex Office",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.liebherr.com/de-de/j/karriere/offene-stellen/80508-de-3364214",
        date="Direct Liebherr page active; LinkedIn shows recent activity; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Liebherr Group internal customers",
        cluster="Cluster D - AI automation; Cluster A - Power Platform / Copilot automation",
        why="Strong direct-company match for AI workflow implementation using Microsoft Copilot, Copilot Studio and Power Platform, including API integration, data connections, governance, security and quality validation.",
        keywords=[
            "Microsoft Copilot",
            "Copilot Studio",
            "Power Platform",
            "AI workflows",
            "API integration",
            "quality validation",
            "governance",
            "hybrid",
        ],
        risks=[
            "Location is outside Munich and close to the Bavaria/Baden-Wuerttemberg border",
            "Production AI implementation expectations may be higher than current evidence",
            "Need fast preparation on Copilot Studio and governance",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Implementation Engineer | Power Platform, Copilot Studio, Python, Quality-Controlled Workflows",
        note="Very relevant new direct-company target; emphasize Power Automate/M365 automation, Python data validation and controlled AI workflow R&D.",
    ),
    make_row(
        fit=7.9,
        title="AI Configuration & Implementation Engineer (m/w/d)",
        company="Liebherr-IT Services GmbH",
        location="Kirchdorf/Oberopfingen, southern Germany",
        remote="Hybrid / Flex Office",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.liebherr.com/de-de/j/karriere/offene-stellen/83146-de-3364214",
        date="Direct Liebherr page active; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Liebherr Group internal customers",
        cluster="Cluster D - AI automation; Cluster A - low-code / Power Automate",
        why="Good AI configuration and workflow implementation role with Copilot Studio, Power Automate, SAP Build and agentic AI concepts. Useful for the candidate's AI automation direction, but lower than the implementation role because configuration/governance depth may be expected.",
        keywords=[
            "Copilot Studio",
            "Power Automate",
            "SAP Build",
            "agentic AI",
            "AI configuration",
            "implementation",
            "governance",
        ],
        risks=[
            "SAP Build and enterprise configuration experience may be a gap",
            "Location outside Munich",
            "Could expect experienced application-engineer background",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Configuration & Workflow Automation Engineer | Power Automate, Copilot Studio, Process Documentation",
        note="Good second Liebherr target; use after the AI Implementation Engineer application.",
    ),
    make_row(
        fit=8.0,
        title="(Junior) Specialist Digitalization & Automation R&D (m/w/d)",
        company="Hochland R&D GmbH",
        location="Heimenkirch, Bavaria",
        remote="Home office possible",
        employment="Full-time, permanent, junior/specialist",
        source="Direct company portal",
        url="https://karriere.hochland.com/jobs/junior-specialist-digitalization-automation-r-d-m-w-d/b1628f3f-22d4-4147-b7fa-849ab2c8c5f6",
        date="Direct page active; BA shows 2026-08-22; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Hochland R&D GmbH",
        cluster="Cluster B - process automation / digitalization; Cluster A - workflow automation",
        why="Strong fit for two B.Eng. degrees and industrial digitalization: junior-labelled R&D digitalization/automation, improvement potential analysis, concrete quick wins and process-oriented implementation.",
        keywords=[
            "junior",
            "digitalization",
            "automation",
            "R&D",
            "process improvement",
            "quick wins",
            "home office",
            "Bavaria",
        ],
        risks=[
            "Food/R&D domain instead of automotive",
            "Exact tooling should be confirmed on the direct page",
            "Location is Allgaeu, not Munich",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Junior Digitalization & Automation Specialist | Industrial Engineering, Process Automation, Python",
        note="Very good non-automotive industrial target; present both B.Eng. programs as a core advantage.",
    ),
    make_row(
        fit=7.8,
        title="Solution Architect Automatisierung & KI (m/w/d)",
        company="SKOUZ",
        location="Lindau, Bavaria",
        remote="Hybrid",
        employment="Full-time, junior/senior range",
        source="Direct company portal",
        url="https://www.skouz.de/karriere/solution-architect-automatisierung-ki-mwd",
        date="Direct page active; LinkedIn/search crawl recent; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - SKOUZ customers",
        cluster="Cluster D - AI automation; Cluster A - Power Platform / process automation",
        why="Very good process-first AI role: requirements, data model, integration, productive operation, Azure, Power Platform and practical AI. Score is capped because of the architect title, but the page explicitly mentions junior/senior range.",
        keywords=[
            "process automation",
            "AI",
            "Power Platform",
            "Azure",
            "requirements",
            "data model",
            "integration",
            "junior/senior",
        ],
        risks=[
            "Architect title may still screen for deeper experience",
            "Azure and solution-design depth need preparation",
            "Lindau hybrid location",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Automation & AI Solution Consultant | Power Automate, Python, Process Analysis, Human Review Workflows",
        note="Good direct-company stretch because it values understanding processes before applying AI.",
    ),
    make_row(
        fit=7.5,
        title="AI Solution Engineer (m/w/d)",
        company="Kardex Group",
        location="Neuburg an der Kammel, Bavaria / mobile work",
        remote="Mobile work",
        employment="Full-time, permanent",
        source="WeAreDevelopers / job board mirror",
        url="https://www.wearedevelopers.com/jobs/ext/1646738-ai-solution-engineer",
        date="WeAreDevelopers page active and crawled 2026-09-07; source references recent Indeed/direct posting",
        direct="Direct employer via job board",
        end_client="Known - Kardex Group",
        cluster="Cluster D - AI automation; Cluster B - systems/process integration",
        why="Good applied AI builder role: AI agents, process automation, APIs, MCP interfaces, human-digital-workforce wording, Azure and Power Automate. Location is Bavaria and mobile work is available.",
        keywords=[
            "AI agents",
            "process automation",
            "APIs",
            "MCP interfaces",
            "Power Automate",
            "Azure",
            "Generative AI",
        ],
        risks=[
            "Source is a job-board mirror rather than the direct apply page",
            "People & Culture domain rather than industrial engineering",
            "Azure and production AI experience may be expected",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Solution Engineer | Python, Power Automate, APIs, MCP/Agent Workflow Concepts",
        note="Good AI-agent/process automation stretch; apply if direct Kardex application route is easy to find from the board.",
    ),
    make_row(
        fit=7.3,
        title="AI Adoption & Change Manager (m/w/d)",
        company="Liebherr-IT Services GmbH",
        location="Kirchdorf/Oberopfingen, southern Germany",
        remote="Hybrid / Flex Office",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.liebherr.com/de-de/j/karriere/offene-stellen/83071-de-3364214",
        date="Direct Liebherr page active; jobs-im-allgaeu mirror shows 2026-06-15; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Liebherr Group internal customers",
        cluster="Cluster D - AI adoption / process transformation",
        why="Useful business-consultant AI adoption role around scalable AI standard-product adoption and change. It fits engineering-management/process improvement better than deep coding, but is less direct than implementation roles.",
        keywords=[
            "AI adoption",
            "change management",
            "business consultant",
            "AI standard products",
            "roadmap",
            "process transformation",
        ],
        risks=[
            "Change-management ownership may outweigh technical automation",
            "Location outside Munich",
            "Could require corporate adoption experience",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Adoption & Process Automation Consultant | Industrial Engineering, M365 Workflows, Documentation",
        note="Selective application; useful if you want an AI/process transformation role rather than hands-on development.",
    ),
    make_row(
        fit=7.2,
        title="IT Consultant Analytics (m/w/d)",
        company="Hochland SE",
        location="Heimenkirch, Bavaria",
        remote="Home office possible unclear / hybrid likely",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://karriere.hochland.com/jobs/it-consultant-analytics-m-w-d/29216148-dbbb-474b-acb3-b6ea03a71328",
        date="Direct page active; LinkedIn shows recent activity; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Hochland SE",
        cluster="Cluster B - industrial data / analytics",
        why="Industrial analytics consultant role in Bavaria. Relevant through data analysis, reporting, process-oriented analytics and engineering-management profile, but likely more SAP Analytics Cloud/Datasphere than Python/Power Automate.",
        keywords=[
            "analytics",
            "reporting",
            "SAP Analytics Cloud",
            "SAP Datasphere",
            "business data",
            "consulting",
            "Bavaria",
        ],
        risks=[
            "SAP Analytics/Datasphere likely stronger requirement than current evidence",
            "Less direct Power Automate/Python match",
            "Location is Allgaeu",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Industrial Data & Analytics Consultant | Python/Excel Validation, Process Documentation, BI Learning Path",
        note="Backup data/analytics option; prioritize the Hochland junior digitalization role first.",
    ),
]


EXCLUSIONS = [
    "Tri.Merge AI- & Agentic Workflow Engineer - strong wording, but Friedrichshafen/Baden-Wuerttemberg and older listing; keep as monitor, not appended now.",
    "Senacor AI-Native Software Engineer - workflow automation theme, but Hamburg and software/platform-heavy.",
    "Liebherr senior/head PMO and ServiceNow roles - too senior or too pure IT platform/admin.",
    "Hochland Corporate People Digitalization Manager - relevant digitalization but HR/change-management heavy and less aligned than R&D automation.",
]


def backup_current_outputs() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"round4_append_{stamp}"
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


def merge_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str], int]:
    seen_urls = {normalize_url(row.get("SourceURL", "")): row for row in rows if row.get("SourceURL")}
    seen_titles = {
        f"{normalize_text(row.get('Company', ''))}|{normalize_text(row.get('JobTitle', ''))}": row
        for row in rows
    }
    kept = list(rows)
    duplicate_reasons: list[str] = []
    added = 0
    for addition in ADDITIONS:
        url_key = normalize_url(addition.get("SourceURL", ""))
        title_key = f"{normalize_text(addition.get('Company', ''))}|{normalize_text(addition.get('JobTitle', ''))}"
        if url_key and url_key in seen_urls:
            original = seen_urls[url_key]
            duplicate_reasons.append(f"{addition['Company']} - {addition['JobTitle']} duplicate URL of {original.get('Company')} - {original.get('JobTitle')}")
            continue
        if title_key in seen_titles:
            original = seen_titles[title_key]
            duplicate_reasons.append(f"{addition['Company']} - {addition['JobTitle']} duplicate company/title of {original.get('Company')} - {original.get('JobTitle')}")
            continue
        kept.append(addition)
        added += 1
        if url_key:
            seen_urls[url_key] = addition
        seen_titles[title_key] = addition
    return kept, duplicate_reasons, added


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


def write_outputs(rows: list[dict[str, str]], previous_count: int, added: int, dupes: int, backup_dir: Path) -> None:
    new_rows = [row for row in rows if row.get("NewOrExisting") == "New"]
    role_counts = Counter(row.get("RoleCluster", "").split(";")[0].strip() for row in rows)
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

    write_csv(CONTINUED_CSV, rows)
    write_csv(NEW_ONLY_CSV, new_rows)

    CONTINUED_MD.write_text(
        "\n".join(
            [
                "# Munich / Bavaria Job Matches for Michal Dembski - Continued Update",
                "",
                "## 1. Executive Summary",
                (
                    f"Loaded {previous_count} suitable jobs from the cleaned continued list and appended {added} further suitable roles from direct company portals and specialist boards. "
                    f"Skipped {dupes} duplicate(s). Final list now contains {len(rows)} suitable jobs. The new batch strengthens the industrial digitalization and AI-low-code lane, especially through Liebherr IT, Hochland R&D and SKOUZ. Both completed B.Eng. programs were considered positively for industrial process, engineering-management, R&D digitalization and technical project roles."
                ),
                "",
                "## 2. Number Of Jobs Found",
                f"- Total suitable jobs in continued list after this update: {len(rows)}",
                f"- Rows marked new from all continued searches: {len(new_rows)}",
                f"- Newly appended in this latest pass: {added}",
                "",
                "## 3. Number Of Jobs Excluded And Why",
                "\n".join(f"- {item}" for item in EXCLUSIONS),
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
                "- Liebherr-IT Services",
                "- Hochland",
                "- 42watt",
                "- Deloitte",
                "- Bertrandt Group",
                "- TUV SUD",
                "",
                "## 9. Missing Skills Repeated Across The Market",
                "- Copilot Studio, AI Builder and Microsoft agent governance.",
                "- Dataverse, Power Apps and Power Platform ALM/governance.",
                "- RAG, embeddings, vector stores, function calling/tool use and LLM evals.",
                "- n8n/Make, API/webhook automation and structured error handling.",
                "- SQL, Power BI, Power Query and basic DAX.",
                "- UiPath/Blue Prism for RPA roles.",
                "- DOORS/Polarion, ASPICE/ISO 26262 and model-based testing for automotive validation roles.",
                "",
                "## 10. CV Version Recommendation",
                "Use ATS Process Automation CV - German most often. For the new Liebherr, Hochland and SKOUZ roles, also use ATS Process Automation CV - German. Use ATS Quality & Validation CV - German for MEKRA/b-plus/ALTEN/Bertrandt validation jobs.",
                "",
                "## 11. Application Plan For Today",
                "- Apply to 5-8 high-quality roles only.",
                "- Keep the first wave focused on Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, REPA Junior Data Analyst, Liebherr AI Implementation and Hochland Junior Digitalization.",
                "- Tailor only headline, summary and top skills.",
                "- Send 3-5 recruiter messages to Workspacer, RATHGEBER, REPA, Liebherr/Hochland recruiters and Reply.",
                "",
                "## 12. Application Plan For The Next 7 Days",
                "- Days 1-2: Power Platform, M365, process automation and junior industrial digitalization.",
                "- Day 3: AI implementation and applied AI roles at Liebherr, Reply, SUXXEED, Deloitte and MEKRA.",
                "- Day 4: Quality/validation backup roles at Bertrandt, MEKRA, b-plus, ALTEN and Webasto.",
                "- Day 5: Direct company portal recheck for BMW, Siemens, MAN, IAV, EDAG, ARRK, Expleo and Akkodis.",
                "- Days 6-7: Recruiter follow-up and portfolio proof for Power Automate + SharePoint and Python/OpenPyXL reconciliation.",
                "",
                f"Backup folder for this update: {backup_dir}",
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
                "## Best Additional Jobs Found In Latest Pass",
                "\n".join(
                    f"- **{row['Company']} - {row['JobTitle']}** ({row['FitScore']}/10): {row['SourceURL']}"
                    for row in ADDITIONS
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
                "\n".join(f"- {row['Company']} - {row['JobTitle']}: {row['SourceURL']}" for row in ADDITIONS[:8]),
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
                "2. Choose 5-8 applications: prioritize Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, REPA Junior Data Analyst, Liebherr AI Implementation and Hochland Junior Digitalization.",
                "3. Use ATS Process Automation CV - German for most roles.",
                "4. Use ATS Quality & Validation CV - German only for quality/validation roles.",
                "5. Tailor headline, summary and top skills only.",
                "6. Submit applications and save source URL, CV version and date.",
                "7. Send 3-5 recruiter messages to Workspacer, REPA, Liebherr/Hochland recruiters, Reply and RATHGEBER.",
                "8. Prepare tomorrow's follow-up and one portfolio proof screenshot/summary.",
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
                "- Copilot Studio and AI Builder: repeated in Campana & Schott, fly-tech, Liebherr, CONET, CANCOM and Avanade-style postings.",
                "- Dataverse and Power Platform governance/ALM: repeated in Power Platform consultant/developer roles.",
                "- RAG, embeddings, vector stores and function calling/tool use: repeated in Reply, Deloitte, REPA, SUXXEED, smartvillage, Drees & Sommer and Liebherr-style AI roles.",
                "- n8n/Make/webhooks/API basics: repeated in Workspacer, 42watt, Kevin Meyer Consulting, Vogel and AI automation roles.",
                "- SQL, Power Query, Power BI and basic DAX: repeated in REPA, DB InfraGO, TUV SUD and Hochland analytics roles.",
                "",
                "## Short-Term Portfolio, 1-2 Weeks",
                "- Power Automate + SharePoint approval workflow with Forms input, evidence log and Outlook notification.",
                "- Python/OpenPyXL/Pandas reconciliation tool with exception report and validation rules.",
                "- n8n or Make workflow using an LLM API, human approval and structured output validation.",
                "- Mini RAG assistant for industrial/quality documentation with citations and cannot-answer behavior.",
                "- One-page Power BI dashboard from cleaned Excel/CSV data.",
                "",
                "## Longer-Term Certification, 1-3 Months",
                "- PL-900 first.",
                "- MS-900 for Microsoft 365 foundation.",
                "- PL-200 if Power Platform consulting remains the main lane.",
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
                "- Sources searched: direct Liebherr careers, direct Hochland careers, direct SKOUZ careers, Kardex via WeAreDevelopers, LinkedIn, StepStone, Indeed and specialist job mirrors.",
                "- Queries used: Liebherr AI Implementation Engineer Copilot Power Platform; AI Configuration Implementation Engineer Power Automate; Hochland Junior Digitalization Automation R&D; Solution Architect Automatisierung KI Power Platform; Kardex AI Solution Engineer MCP Power Automate.",
                f"- Previous suitable jobs loaded before this pass: {previous_count}",
                f"- New jobs appended in this pass: {added}",
                f"- Duplicates skipped/removed in this pass: {dupes}",
                f"- Final suitable active/recently active jobs in continued list: {len(rows)}",
                f"- Backup folder: {backup_dir}",
                "",
                "## Best New Matches",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10): {row['SourceURL']}"
                    for row in ADDITIONS
                ),
                "",
                "## Weak Recurring Skill Gaps",
                "- Copilot Studio, AI Builder and Power Platform governance.",
                "- Dataverse, Power Apps and custom connectors.",
                "- RAG, function calling/tool use, LLM evals and production monitoring.",
                "- SQL, Power BI, Power Query and basic DAX.",
                "",
                "## Recommended Next Search Terms",
                "- AI Implementation Engineer Copilot Studio Power Platform Bayern",
                "- Junior Specialist Digitalization Automation R&D Bayern",
                "- AI Solution Engineer Power Automate MCP Bayern",
                "- Process Automation Consultant Power Platform Azure Bayern",
                "",
                "## Excluded This Pass",
                "\n".join(f"- {item}" for item in EXCLUSIONS),
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
    backup_dir = backup_current_outputs()
    merged, duplicate_reasons, added = merge_rows(previous_rows)
    rows = rank_rows(merged)
    write_outputs(rows, previous_count, added, len(duplicate_reasons), backup_dir)
    print(f"Previous rows: {previous_count}")
    print(f"New additions kept: {added}")
    print(f"Duplicates skipped: {len(duplicate_reasons)}")
    print(f"Final rows: {len(rows)}")
    print(f"Backup: {backup_dir}")
    print("Top 12:")
    for row in rows[:12]:
        print(f"{row['Rank']}. {row['FitScore']} - {row['Company']} - {row['JobTitle']}")


if __name__ == "__main__":
    main()
