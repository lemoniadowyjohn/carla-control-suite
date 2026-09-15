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
    top_keywords,
    write_application_pack,
    write_csv,
)


CHECKED_AT = datetime.now().strftime("%Y-%m-%d %H:%M CET")


ADDITIONS = [
    make_row(
        fit=8.5,
        title="Automation Engineer (gn)",
        company="42watt",
        location="Munich, Bavaria",
        remote="Hybrid / Munich",
        employment="Full-time, permanent",
        source="Direct company portal - Personio",
        url="https://42watt.jobs.personio.de/",
        date="Date unclear; Personio career page active and job listed on 2026-09-07",
        direct="Direct employer",
        end_client="Known - 42watt",
        cluster="Cluster D - AI automation; Cluster B - process automation",
        why="Strong practical automation match: low-code/no-code automation, API/data connections and business-process workflow delivery. The role rewards hands-on builders, which fits the Power Automate, Python automation and AI-agent workflow profile.",
        keywords=[
            "automation",
            "low-code",
            "no-code",
            "n8n",
            "Make",
            "APIs",
            "AI workflows",
            "process automation",
        ],
        risks=[
            "Startup/service context rather than automotive",
            "Need concrete automation portfolio examples",
            "Exact tool stack must be verified on the Personio application page",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Automation Engineer | Power Automate, Python, n8n/Make Concepts, AI Workflow R&D",
        note="Very relevant new target; apply with a short portfolio note on Power Automate/SharePoint, Python reconciliation and AI-agent workflow checks.",
    ),
    make_row(
        fit=8.4,
        title="Junior Data Analyst & Data Operations Specialist (m/f/d)",
        company="REPA Deutschland GmbH / REPA GROUP",
        location="Bergkirchen near Munich; relocates to Unterschleissheim end of 2027",
        remote="Hybrid, regular on-site presence",
        employment="Full-time",
        source="Direct company portal - SmartRecruiters",
        url="https://jobs.smartrecruiters.com/REPAGROUP/744000145955800-junior-data-analyst-data-operations-specialist-m-f-d-",
        date="Direct SmartRecruiters page active; BilingualJobs shows posted 2026-08-27; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - REPA Deutschland GmbH",
        cluster="Cluster B - Python automation / industrial data; Cluster A - Power Platform / M365 automation",
        why="Excellent junior data/process role: Excel, Power BI, SQL, Power Query, Power Automate, data quality checks, migration validation, documentation of validation rules and simple automation use cases.",
        keywords=[
            "Excel",
            "Power BI",
            "SQL",
            "Power Query",
            "Power Automate",
            "data quality",
            "validation checks",
            "documentation",
        ],
        risks=[
            "Power BI, SQL and DAX should be refreshed before interview",
            "Regular Bergkirchen on-site presence",
            "Commercial product/master-data domain instead of automotive",
        ],
        cv=cv_for("Cluster B", "English"),
        headline="Junior Data & Process Automation Analyst | Excel, Python, Power Automate, Data Validation",
        note="One of the best new additions because it explicitly combines junior level, data validation, Excel/Power BI and Power Automate.",
    ),
    make_row(
        fit=8.1,
        title="ECM Consultant for Microsoft 365 (m/f/d)",
        company="Portal Systems / PSC Portal Systems Consulting GmbH",
        location="Germany-wide home office; Munich office presence possible",
        remote="Germany-wide home office",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://www.portalsystems.de/en/jobs-career/ecm-consultants-microsoft-365/",
        date="Date unclear; direct page active and third-party crawl checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Portal Systems customers",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster C - documentation / QM",
        why="Very strong Microsoft 365 and SharePoint document-workflow role. Portal Systems builds SharePoint/M365-based ECM, document management, document control/QM and invoice workflows, which matches SharePoint, M365 workflow and technical documentation evidence.",
        keywords=[
            "Microsoft 365",
            "SharePoint",
            "ECM",
            "DMS",
            "document control",
            "quality management",
            "Power Automate",
            "business applications",
        ],
        risks=[
            "Customer consulting and SharePoint product knowledge expected",
            "JavaScript/HTML/CSS/XML/JSON may appear in interviews",
            "Less Python relevance than M365/document workflow relevance",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Microsoft 365 & SharePoint Workflow Consultant | Power Automate, Documentation, Process Automation",
        note="High-quality direct target for SharePoint/M365 plus document control; emphasize quality documentation and traceable workflows.",
    ),
    make_row(
        fit=8.0,
        title="Junior AI Engineer (m/w/d)",
        company="SUXXEED Sales for your Success GmbH",
        location="Nuremberg, Bavaria",
        remote="Hybrid",
        employment="Full-time / trainee-style entry",
        source="XING Jobs / Remotely",
        url="https://www.xing.com/jobs/nuernberg-junior-ai-engineer-156908279",
        date="XING crawled 2026-09-06; Remotely shows about 3 weeks old; checked 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - SUXXEED",
        cluster="Cluster D - AI automation; Cluster A - M365 automation",
        why="Good junior AI role with Multi-Agent systems, Enterprise RAG, Voice AI, Microsoft Copilot, Microsoft 365, Azure OpenAI, APIs and business-process efficiency. The junior level fits the candidate better than senior AI engineer postings.",
        keywords=[
            "Junior AI Engineer",
            "RAG",
            "Multi-Agent systems",
            "Microsoft Copilot",
            "Microsoft 365",
            "Azure OpenAI",
            "APIs",
            "process efficiency",
        ],
        risks=[
            "Sales/marketing/service domain rather than industrial engineering",
            "Need credible RAG/agent vocabulary and project proof",
            "Nuremberg hybrid distance",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior AI Automation Engineer | Python, Microsoft 365, RAG Concepts, Agent Workflow R&D",
        note="Good junior AI option; apply after top Power Platform/process roles and prepare a simple RAG/agent explanation.",
    ),
    make_row(
        fit=7.8,
        title="Microsoft 365 Consultant - AI & Modern Work",
        company="CONET Technologies Holding GmbH / CONET",
        location="Munich and other German locations",
        remote="Hybrid / remote by arrangement",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.conet.de/de/karriere/jobs/2026-104-microsoft-365-consultant-ai-modern-work/",
        date="Date unclear; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - CONET customers",
        cluster="Cluster A - Power Platform / M365 Automation; Cluster D - AI automation",
        why="Strong Microsoft partner consulting target around Microsoft 365, Modern Work, AI/Copilot enablement and business-process improvement. Good fit for M365/SharePoint/Power Automate positioning.",
        keywords=[
            "Microsoft 365",
            "Modern Work",
            "Copilot",
            "AI",
            "SharePoint",
            "Power Platform",
            "consulting",
            "process improvement",
        ],
        risks=[
            "Consulting experience and client workshop skills expected",
            "Copilot/AI governance depth may be tested",
            "Some M365 admin architecture requirements possible",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Microsoft 365 Automation Consultant | Power Automate, SharePoint, Copilot Readiness, Process Workflows",
        note="Good Microsoft partner target; emphasize M365 workflow automation, SharePoint and structured stakeholder documentation.",
    ),
    make_row(
        fit=7.8,
        title="(Junior) Projektmanager AI & Computer Vision (m/w/d)",
        company="Reply Deutschland SE",
        location="Munich, Bavaria",
        remote="Partial remote / hybrid",
        employment="Full-time",
        source="Direct company portal / JobTeaser",
        url="https://www.jobteaser.com/en/job-offers/83762351-94fe-4bd5-b88d-7286e3719503-reply-deutschland-se-junior-projektmanager-ai-computer-vision-m-w-d",
        date="JobTeaser shows published 2026-08-23; direct Reply listing checked 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Reply customers",
        cluster="Cluster D - AI automation / computer vision; Cluster B - technical project engineering",
        why="Realistic stretch because it is junior-labelled and uses AI/computer vision project coordination, requirements, milestones, quality and visualization. It connects well to the robotics/computer-vision thesis and engineering-management studies.",
        keywords=[
            "junior",
            "AI",
            "computer vision",
            "project management",
            "requirements",
            "quality",
            "data analysis",
            "visualization",
        ],
        risks=[
            "First ML/CV project-management experience expected",
            "Less Power Automate/M365 relevance",
            "Need concise explanation of thesis and practical CV work",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior AI & Computer Vision Project Engineer | Robotics Thesis, Process Documentation, Quality Tracking",
        note="Good bridge from the computer-vision thesis into applied AI project work; apply if willing to pitch project coordination strength.",
    ),
    make_row(
        fit=7.7,
        title="Consultant Intelligent Automation - Einstieg in AI & Data (m/w/d)",
        company="Deloitte",
        location="Munich and other German locations",
        remote="Hybrid / client-dependent",
        employment="Full-time, graduate/consultant",
        source="Direct company portal",
        url="https://job.deloitte.com/job-consultant-intelligent-automation-dein-einstieg-in-ai-data-mwd-_49502",
        date="Date unclear; direct Deloitte page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Deloitte clients",
        cluster="Cluster D - AI automation; Cluster B - process automation",
        why="Good graduate-friendly automation consulting role: intelligent automation, AI/Data, conversational AI or document processing, Python/JavaScript and business-process implementation.",
        keywords=[
            "Intelligent Automation",
            "AI & Data",
            "Python",
            "JavaScript",
            "document processing",
            "process automation",
            "consulting",
        ],
        risks=[
            "Consulting travel and case interview likely",
            "Conversational AI/IDP tools need preparation",
            "May prefer computer-science or business-informatics background",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Intelligent Automation Consultant | Python, Power Automate, Process Documentation, AI Workflow R&D",
        note="Strong consulting option; use the two B.Eng. degrees as evidence of engineering plus management/process thinking.",
    ),
    make_row(
        fit=7.7,
        title="Consultant KI in Operations - Einkauf, Supply Chain, Produktion oder Qualitaet (m/w/d)",
        company="Deloitte",
        location="Munich and other German locations",
        remote="Hybrid / client-dependent",
        employment="Full-time, consultant",
        source="Direct company portal",
        url="https://job.deloitte.com/job-consultant-ki-in-operations-einkauf-supply-chain-produktion-oder-qualitaet-mwd-_50177",
        date="Date unclear; direct Deloitte page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Deloitte clients",
        cluster="Cluster D - AI automation; Cluster C - production / quality process",
        why="Good domain bridge: AI use cases in operations, supply chain, production and quality. It fits the candidate's industrial engineering degrees, BMW/automotive production exposure, quality documentation and AI workflow interest.",
        keywords=[
            "AI in Operations",
            "production",
            "quality",
            "supply chain",
            "GenAI",
            "agentic AI",
            "process improvement",
            "consulting",
        ],
        risks=[
            "Broader management consulting scope",
            "ML/GenAI method credibility must be built fast",
            "Travel and stakeholder-facing delivery",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI & Operations Consultant | Industrial Engineering, Process Automation, Quality Documentation",
        note="Apply selectively as an operations/quality AI consulting bridge; do not present as a deep ML engineer.",
    ),
    make_row(
        fit=7.7,
        title="AI Engineer / Specialist (m/f/d)",
        company="REPA Deutschland GmbH / REPA GROUP",
        location="Bergkirchen near Munich; relocates to Unterschleissheim end of 2027",
        remote="Hybrid",
        employment="Full-time",
        source="Direct company portal - SmartRecruiters",
        url="https://jobs.smartrecruiters.com/REPAGROUP/744000144725420-ai-engineer-specialist-m-f-d-",
        date="SmartRecruiters page crawled 3 days ago; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - REPA Deutschland GmbH",
        cluster="Cluster D - AI automation; Cluster B - data/process automation",
        why="Relevant applied AI/process role: GenAI apps, AI agents, RAG, Python, SQL, APIs, automation technologies, data quality, requirements translation and AI governance. It is a stretch but closer than senior ML research jobs.",
        keywords=[
            "Generative AI",
            "AI agents",
            "RAG",
            "Python",
            "SQL",
            "APIs",
            "automation",
            "data quality",
        ],
        risks=[
            "Hands-on AI/ML engineering experience expected",
            "Azure/Azure OpenAI and production deployment may be gaps",
            "Need portfolio proof beyond private R&D notes",
        ],
        cv=cv_for("Cluster D", "English"),
        headline="Applied AI Automation Engineer | Python, RAG Concepts, APIs, Data Quality, Human Review Workflows",
        note="Apply if you can attach or describe one defensible AI-agent/RAG mini-project with validation and human approval boundaries.",
    ),
    make_row(
        fit=7.6,
        title="Junior AI Solutions Engineer (m/w/d)",
        company="Reply Deutschland SE",
        location="Munich, Bavaria",
        remote="Hybrid / office-dependent",
        employment="Full-time, junior",
        source="Direct company portal",
        url="https://www.reply.com/de/about/careers/de/job-details/JOB-11382?country=de",
        date="Direct Reply page active; JobTeaser and Indeed crawls show recent listing; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Reply customers",
        cluster="Cluster D - AI automation / applied AI",
        why="Junior role around generative AI and agentic AI applications, developer support and AI solution implementation. It matches the personal AI-agent workflow R&D better than senior AI/ML postings.",
        keywords=[
            "Junior AI Solutions Engineer",
            "Generative AI",
            "Agentic AI",
            "AI applications",
            "technical implementation",
            "documentation",
        ],
        risks=[
            "Software development and AI engineering depth may be tested",
            "Less direct M365/Power Platform wording",
            "Need GitHub/project evidence",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior AI Solutions Engineer | Python Automation, Agent Workflow R&D, Technical Documentation",
        note="Good junior AI target; prepare a concise technical story from the AI-agent workflow project.",
    ),
    make_row(
        fit=7.6,
        title="Junior AI Engineer (m/w/d)",
        company="MEKRA Lang GmbH & Co. KG",
        location="Ergersheim, Bavaria",
        remote="Hybrid according to XING; direct page remote unclear",
        employment="Full-time, permanent, career entrant",
        source="Direct company portal / XING",
        url="https://websiteold.mekra.de/en/karriere/stellenangebote/stellenangebote/junior-ai-engineer-m-w-d-detail/cj20057",
        date="Direct page active; BA listing shows changed 2026-08-29; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - MEKRA Lang",
        cluster="Cluster D - AI automation; Cluster C - automotive",
        why="Automotive/vehicle-manufacturing junior AI role. It is useful because it combines AI ecosystem/governance with an automotive supplier context, and the candidate has automotive, CV/robotics thesis and AI workflow R&D evidence.",
        keywords=[
            "Junior AI Engineer",
            "automotive",
            "AI ecosystem",
            "AI governance",
            "career entrant",
            "computer vision",
            "technical documentation",
        ],
        risks=[
            "Location is farther from Munich",
            "Direct page has limited technical detail",
            "Need proof of AI project maturity",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior AI Engineer | Automotive Experience, Computer Vision Thesis, AI Workflow R&D",
        note="Good Bavaria automotive-AI option; apply with German CV and keep AI claims concrete.",
    ),
    make_row(
        fit=7.5,
        title="RPA Developer (m/w/d)",
        company="YER",
        location="Augsburg, Bavaria",
        remote="Hybrid / home office possible",
        employment="Full-time, permanent",
        source="Direct agency portal",
        url="https://www.yer.de/de/jobangebote/rpa-developer-mwd-augsburg-1791/",
        date="BA search showed published about 4 days ago; direct page active in search index on 2026-09-07",
        direct="Agency",
        end_client="Hidden",
        cluster="Cluster A - Power Platform / RPA automation; Cluster B - Python automation",
        why="Good RPA/process automation fit with Power Automate, UiPath/Blue Prism-style automation, Python/C#/Java options, bot monitoring and maintenance.",
        keywords=[
            "RPA",
            "Power Automate",
            "UiPath",
            "Blue Prism",
            "Python",
            "process automation",
            "bot monitoring",
        ],
        risks=[
            "End client hidden",
            "UiPath/Blue Prism experience may be expected",
            "Agency screening may be keyword-heavy",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="RPA & Process Automation Engineer | Power Automate, Python, Workflow Documentation",
        note="Good Augsburg automation option; be honest that Power Automate is strongest and UiPath is a learning target.",
    ),
    make_row(
        fit=7.5,
        title="Agentic AI Developer im Deloitte aiStudio (m/w/d)",
        company="Deloitte",
        location="Munich and other German locations",
        remote="Hybrid / client-dependent",
        employment="Full-time, graduate-friendly",
        source="Direct company portal",
        url="https://job.deloitte.com/job-machine-learning-ops-engineer-mwd-_49806",
        date="Date unclear; direct Deloitte page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - Deloitte clients",
        cluster="Cluster D - AI automation / agentic AI",
        why="Agentic AI role with graduate-friendly wording, solution requirements, development/testing, productive operation, process support, tooling and documentation. Relevant to the candidate's AI-agent R&D, but not a pure beginner role.",
        keywords=[
            "Agentic AI",
            "requirements",
            "development",
            "testing",
            "documentation",
            "processes",
            "AI applications",
        ],
        risks=[
            "The URL slug mentions MLOps; clarify actual job scope before applying",
            "Production AI engineering depth may be expected",
            "Consulting and risk/advisory context",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Agentic AI Automation Developer | Python, Human Review Workflows, Documentation, Testing",
        note="Apply after stronger Power Platform/process roles; do not overclaim MLOps or cloud architecture.",
    ),
    make_row(
        fit=7.5,
        title="AI Transformation Analyst (m/f/d)",
        company="Allianz Technology",
        location="Unterfoehring / Munich area",
        remote="Hybrid / on-site unclear",
        employment="Full-time, entry level",
        source="XING Jobs / LinkedIn Jobs",
        url="https://www.xing.com/jobs/muenchen-ai-transformation-analyst-157184194",
        date="LinkedIn shows 2026-08-25; XING page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Allianz Technology",
        cluster="Cluster D - AI automation; Cluster B - process transformation",
        why="Entry-level AI transformation role in an AI automation team. It fits business-process AI, governance/evidence checks and structured analytical work, with Munich-area location.",
        keywords=[
            "AI Transformation",
            "AI Automation",
            "entry level",
            "process transformation",
            "analysis",
            "governance",
            "Unterfoehring",
        ],
        risks=[
            "Direct Allianz career page appeared inconsistent in one search result",
            "Insurance/finance domain instead of automotive",
            "May require stronger enterprise transformation experience",
        ],
        cv=cv_for("Cluster D", "English"),
        headline="AI Transformation Analyst | Process Automation, Python, M365 Workflows, Evidence-Based AI Use Cases",
        note="Good Munich-area AI transformation stretch; verify direct Allianz apply page before submitting.",
    ),
    make_row(
        fit=7.5,
        title="Microsoft Dynamics 365 CRM Consultant Power Platform (w/m/d)",
        company="affinis AG",
        location="Munich and Germany-wide home office",
        remote="Home office / hybrid",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://jobs.affinis.de/de?id=fb5bce",
        date="Date unclear; direct page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - affinis AG customers",
        cluster="Cluster A - Power Platform / M365 Automation",
        why="Existing row upgraded to direct source: Power Apps, Power Automate, Dataverse, customer process analysis and Microsoft Dynamics 365 CRM. Good fit for Power Platform/process automation, with CRM depth as the main risk.",
        keywords=[
            "Power Apps",
            "Power Automate",
            "Dataverse",
            "Dynamics 365",
            "process analysis",
            "low-code",
            "German",
            "English",
        ],
        risks=[
            "Three-plus years CRM experience requested",
            "Dynamics 365 CRM is weaker than Power Automate/SharePoint evidence",
            "Consulting responsibility",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="Power Platform Consultant | Power Automate, SharePoint/M365, Process Automation, CRM Learning Path",
        note="Use as a Power Platform consultant option; prepare a clear answer on Power Automate vs Dynamics/Dataverse experience.",
    ),
    make_row(
        fit=7.5,
        title="Consultant (m/w/d) - Automation & AI (UiPath)",
        company="Reply",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time",
        source="Direct company portal",
        url="https://www.reply.com/de/about/careers/de/job-details/JOB-11188",
        date="Direct Reply page active; search crawled within the last week; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Reply customers",
        cluster="Cluster D - AI automation; Cluster A - RPA / workflow automation",
        why="Existing row upgraded to direct source: automation and AI consulting on UiPath, from use-case idea to stable operation. Good workflow automation target if Power Automate experience is positioned as transferable RPA/process thinking.",
        keywords=[
            "Automation",
            "AI",
            "UiPath",
            "RPA",
            "use cases",
            "stable operation",
            "process automation",
        ],
        risks=[
            "UiPath-specific stack may be a gap",
            "Consulting delivery pressure",
            "Less SharePoint/M365 emphasis than Power Platform roles",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Automation & AI Consultant | Power Automate, Python, RPA Concepts, Quality-Controlled Workflows",
        note="Apply selectively; present Power Automate workflow logic and fast UiPath onboarding readiness.",
    ),
    make_row(
        fit=7.4,
        title="Requirements Engineer (m/f/d)",
        company="b-plus Group",
        location="Deggendorf, Bavaria",
        remote="Hybrid / details unclear",
        employment="Full-time",
        source="Direct company portal - Personio",
        url="https://b-plus.jobs.personio.de/job/2601935?language=de",
        date="Personio page active; third-party crawl shows recent publication around 2026-09-03; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - b-plus customers",
        cluster="Cluster C - Automotive quality / validation; requirements traceability",
        why="Good requirements/traceability role: analysis, derivation and management of requirements, traceability, coordination with departments/development/partners, and software-concept optimization in an automotive-style engineering environment.",
        keywords=[
            "requirements engineering",
            "traceability",
            "documentation",
            "software concepts",
            "stakeholders",
            "automotive",
            "quality",
        ],
        risks=[
            "Requirements tools such as DOORS/Polarion may be expected",
            "Location is Deggendorf",
            "Less automation/Power Platform relevance",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Requirements & Validation Engineer | Automotive Traceability, Technical Documentation, Process Improvement",
        note="Useful automotive quality/traceability fallback; connect Bertrandt quality documentation and CARLA/OpenDRIVE thesis clearly.",
    ),
    make_row(
        fit=7.4,
        title="AI Solutions Engineer (m/w/d)",
        company="handz.on GmbH",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time",
        source="Direct employer page via JOIN",
        url="https://join.com/companies/on/16631739-ai-solutions-engineer-m-w-d",
        date="JOIN shows published 2026-08-27; LinkedIn shows recent activity; checked 2026-09-07",
        direct="Direct employer via JOIN",
        end_client="Known - handz.on customers",
        cluster="Cluster D - AI automation / applied AI",
        why="AI consultancy role for a hands-on generalist connecting software development, operations, infrastructure and AI-agent/language-system interest. Relevant but more software-integration-heavy than the candidate's strongest evidence.",
        keywords=[
            "AI Solutions Engineer",
            "AI agents",
            "language systems",
            "consulting",
            "operations",
            "infrastructure",
            "implementation",
        ],
        risks=[
            "Software, operations and infrastructure depth may be required",
            "Consulting/client delivery role",
            "Need stronger production AI project proof",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Solutions Engineer | Python Automation, Agent Workflow R&D, Technical Documentation",
        note="Good applied AI stretch in Munich; apply after stronger junior/process automation roles.",
    ),
    make_row(
        fit=7.4,
        title="Junior Forward Deployed Engineer - Applied AI (m/w/d)",
        company="Reply Deutschland SE",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time, junior",
        source="Direct company portal",
        url="https://www.reply.com/de/about/careers/de/job-details/JOB-11299",
        date="Direct Reply page active; JobTeaser shows listing about 7 days old; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Reply customers",
        cluster="Cluster D - Applied AI / AI automation",
        why="Junior applied AI role focused on implementing, integrating and testing AI features in customer systems from prototype to production-near solutions. Relevant to AI-agent workflow R&D and engineering-management profile.",
        keywords=[
            "Junior",
            "Applied AI",
            "AI features",
            "integration",
            "testing",
            "prototype",
            "customer systems",
        ],
        risks=[
            "Could require stronger software integration/cloud skills",
            "Customer-facing consulting pace",
            "Less Power Platform relevance",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior Applied AI Engineer | Python Automation, AI Workflow Validation, Technical Documentation",
        note="Good junior AI stretch; prepare one clear prototype-to-validation story.",
    ),
    make_row(
        fit=7.3,
        title="(Junior) Data & AI Consultant (m/w/d)",
        company="Reply Deutschland SE",
        location="Munich, Bavaria",
        remote="Hybrid",
        employment="Full-time, junior/consultant",
        source="DataCareer / StepStone",
        url="https://www.datacareer.de/job/19050/junior-data-ai-consultant-m-f-d/",
        date="DataCareer shows 2026-08-26; StepStone showed last week; checked 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Reply customers",
        cluster="Cluster D - AI/data consulting; Cluster B - industrial data stretch",
        why="Good junior consulting option for data and AI projects. It is less directly tied to Power Platform, but it supports the target move toward applied AI and industrial data analysis.",
        keywords=[
            "Data & AI",
            "junior consultant",
            "data analytics",
            "AI",
            "software engineering",
            "consulting",
        ],
        risks=[
            "Data engineering/analytics stack may be broader than current evidence",
            "Consulting interviews",
            "Need SQL/BI refresh",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Junior Data & AI Consultant | Python Automation, Data Validation, Process Documentation",
        note="Apply if the role description remains junior and project-facing rather than senior data engineering.",
    ),
    make_row(
        fit=7.2,
        title="Business Consultant Prozessoptimierung & Automatisierung (m/w/d)",
        company="Holon Consulting GmbH",
        location="Gruenwald near Munich",
        remote="Hybrid",
        employment="Full-time",
        source="Indeed Germany",
        url="https://de.indeed.com/viewjob?jk=140fdf79dd50dea1",
        date="Date unclear; Indeed page active on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - Holon Consulting customers",
        cluster="Cluster B - process automation; Cluster D - AI automation",
        why="Strong process/digitalization/automation wording: E2E process analysis, workflow/integration/automation solutions, AI technologies, KPI dashboards, Microsoft Power Automate/UiPath and Python/JavaScript/PowerShell.",
        keywords=[
            "process optimization",
            "automation",
            "AI",
            "Power Automate",
            "UiPath",
            "Python",
            "KPI dashboards",
            "workflow",
        ],
        risks=[
            "Four years process/digitalization experience requested",
            "Master/Diplom wording may be a risk despite two B.Eng. degrees",
            "C1 German likely required",
        ],
        cv=cv_for("Cluster B", "German"),
        headline="Process Automation Consultant | Power Automate, Python, AI Workflow R&D, Industrial Engineering",
        note="Good but experience-heavy consulting stretch; use two B.Eng. programs and practical workflow evidence.",
    ),
    make_row(
        fit=7.2,
        title="Forward Deployed Engineer (m/w/d)",
        company="elunic AG",
        location="Munich, Bavaria",
        remote="Up to 100% home office possible, customer appointments on site",
        employment="Full-time, permanent",
        source="Direct company portal",
        url="https://jobs.elunic.com/job/ai-tech-consultant-m-w-d",
        date="Direct page active; LinkedIn/Indeed showed recent activity in early September 2026; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - elunic industrial customers",
        cluster="Cluster D - industrial AI automation; Cluster B - process automation",
        why="Industrial AI role at a Munich AI/automation company. It involves understanding customer problems and bringing AI/cloud solutions from prototype to productive use, which fits process-analysis and applied AI interests.",
        keywords=[
            "Forward Deployed Engineer",
            "industrial AI",
            "prototype",
            "productive use",
            "customer processes",
            "automation",
            "Munich",
        ],
        risks=[
            "Salary/scope suggests more experience than candidate may have",
            "Cloud/software delivery depth likely",
            "Customer-facing seniority",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Industrial AI Automation Engineer | Process Analysis, Python, Workflow Validation, Documentation",
        note="Useful stretch/networking target; apply only with a concrete AI workflow prototype story.",
    ),
    make_row(
        fit=7.2,
        title="Specialist AI Enterprise Workplace (m/w/d)",
        company="CANCOM SE",
        location="Jettingen-Scheppach, Bavaria",
        remote="Hybrid / partly home office",
        employment="Full-time",
        source="StepStone",
        url="https://www.stepstone.de/stellenangebote--Specialist-AI-Enterprise-Workplace-m-w-d-Jettingen-Scheppach-CANCOM-SE--14038856-inline.html",
        date="StepStone page active in search index on 2026-09-07",
        direct="Direct employer via job board",
        end_client="Known - CANCOM SE customers/internal teams",
        cluster="Cluster A - M365 / AI workplace; Cluster D - AI automation",
        why="Relevant Microsoft workplace/AI role in Bavaria, likely around M365/Copilot/Power Platform adoption and enterprise workplace automation. Useful as a Microsoft-partner-adjacent target, though probably expects deeper M365 practice.",
        keywords=[
            "AI Enterprise Workplace",
            "Microsoft 365",
            "Copilot",
            "Power Platform",
            "automation",
            "digital workplace",
        ],
        risks=[
            "Exact seniority and requirements should be checked on StepStone",
            "Enterprise workplace architecture may be deeper than current evidence",
            "Jettingen-Scheppach commute/location",
        ],
        cv=cv_for("Cluster A", "German"),
        headline="M365 & AI Workplace Automation Specialist | Power Automate, SharePoint, Process Workflows",
        note="Apply selectively after stronger Munich/remote M365 automation roles.",
    ),
    make_row(
        fit=7.1,
        title="AI Engineer (w/m/d)",
        company="Drees & Sommer SE",
        location="Munich and other German cities",
        remote="Partial home office",
        employment="Full-time",
        source="Direct company portal - SmartRecruiters",
        url="https://jobs.smartrecruiters.com/DreesSommerSE/744000146440070-ai-engineer-w-m-d-",
        date="SmartRecruiters page active; third-party sources show posted 2026-08-31; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Drees & Sommer internal/projects",
        cluster="Cluster D - applied AI; Cluster B - process automation stretch",
        why="Applied AI role for business, AI, data and IT teams to build concrete AI solutions. It is a stretch, but relevant to AI workflow R&D and process automation if the work is implementation-oriented.",
        keywords=[
            "AI Engineer",
            "LLM",
            "RAG",
            "AI solutions",
            "business teams",
            "implementation",
            "partial home office",
        ],
        risks=[
            "Likely requires stronger professional AI engineering",
            "Cloud/software depth may be tested",
            "Less automotive or Power Platform fit",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="Applied AI Automation Engineer | Python, RAG Concepts, Process Workflows, Documentation",
        note="Strategic stretch only; do not prioritize over junior/Power Platform roles.",
    ),
    make_row(
        fit=7.1,
        title="Testmanager (m/w/d)",
        company="MEKRA Lang GmbH & Co. KG",
        location="Ergersheim, Bavaria",
        remote="Remote/hybrid unclear",
        employment="Full-time, experienced",
        source="Direct company portal",
        url="https://websiteold.mekra.de/en/karriere/stellenangebote/stellenangebote/testmanager-m-w-d-detail/cj20220",
        date="Direct page shows 2026-07-20; LinkedIn shows recent activity; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - MEKRA Lang",
        cluster="Cluster C - Automotive quality / validation; Cluster D - AI-supported testing",
        why="Relevant to validation, test concepts, integration/system tests, FMEA, quality analyses, test specifications and future AI methods in an automotive supplier environment.",
        keywords=[
            "test management",
            "verification",
            "validation",
            "FMEA",
            "quality analyses",
            "test specifications",
            "Python",
            "AI methods",
        ],
        risks=[
            "Experienced test-management scope",
            "Embedded systems and ISO 26262/ASPICE may be expected",
            "Location outside Munich",
        ],
        cv=cv_for("Cluster C", "German", quality=True),
        headline="Validation & Test Documentation Engineer | Automotive Traceability, Quality Workflows, Python Basics",
        note="Quality/validation stretch; better as a backup than main automation target.",
    ),
    make_row(
        fit=7.1,
        title="E-Commerce & AI Integration Specialist (m/w/d)",
        company="Goodsmith GmbH",
        location="Planegg / Munich area",
        remote="Hybrid",
        employment="Full-time",
        source="Direct company portal",
        url="https://good-smith.com/pages/jobs-bei-goodsmith",
        date="Direct page crawled 2026-09-06 and lists role active; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - Goodsmith GmbH",
        cluster="Cluster D - AI automation; Cluster B - data/process automation stretch",
        why="Practical AI/automation integration role involving modern AI tools to automate shop management, content creation and data maintenance. Relevant as an applied automation stretch, but outside engineering/industrial domain.",
        keywords=[
            "AI integration",
            "automation",
            "data maintenance",
            "process automation",
            "technical shop operations",
            "hybrid Munich",
        ],
        risks=[
            "E-commerce/SEO/content focus",
            "Less engineering and automotive relevance",
            "May expect web/shop-system experience",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Automation & Data Integration Specialist | Python, Workflow Automation, Data Quality",
        note="Apply selectively if interested in smaller-company AI automation outside automotive.",
    ),
    make_row(
        fit=7.0,
        title="Integration Specialist (m/f/d)",
        company="REPA Deutschland GmbH / REPA GROUP",
        location="Bergkirchen near Munich; relocates to Unterschleissheim end of 2027",
        remote="Hybrid",
        employment="Full-time",
        source="Direct company portal - SmartRecruiters",
        url="https://jobs.smartrecruiters.com/REPAGROUP/744000132880239-integration-specialist-m-f-d-",
        date="SmartRecruiters page active; LinkedIn showed recent activity around 2026-09-01; checked 2026-09-07",
        direct="Direct employer",
        end_client="Known - REPA Deutschland GmbH",
        cluster="Cluster B - data/integration automation",
        why="Relevant around automated electronic data exchange, integration solutions, documentation, standards and business systems. It is more EDI/integration-specialist than Power Automate, so score stays selective.",
        keywords=[
            "integration",
            "automated electronic data exchange",
            "documentation",
            "ERP",
            "WMS",
            "middleware",
            "business systems",
        ],
        risks=[
            "EDI standards and integration-platform experience likely required",
            "Less direct Power Platform fit",
            "May not be junior",
        ],
        cv=cv_for("Cluster B", "English"),
        headline="Data Integration & Automation Specialist | Python, Data Validation, Process Documentation",
        note="Backup role only; better if REPA becomes a target company after applying to the junior data analyst role.",
    ),
    make_row(
        fit=7.0,
        title="AI & Automation Engineer (m/w/d)",
        company="smartvillage GmbH",
        location="Munich, Berlin or Cologne",
        remote="Hybrid",
        employment="Full-time or part-time, permanent",
        source="Direct company portal - Personio",
        url="https://smartvillage.jobs.personio.de/job/2597591?language=de",
        date="Direct Personio page active on 2026-09-07",
        direct="Direct employer",
        end_client="Known - smartvillage",
        cluster="Cluster D - AI automation / agentic workflows",
        why="Excellent keyword match around LLM agents, tool/API integration, human-in-the-loop workflows, structured outputs, CRM/PostgreSQL data flows, evals and monitoring. Score is capped because the job asks for 3-6 years and at least one production LLM application.",
        keywords=[
            "LLM agents",
            "API integration",
            "human-in-the-loop",
            "structured outputs",
            "RAG",
            "Python",
            "PostgreSQL",
            "evals",
        ],
        risks=[
            "Requires 3-6 years software/data/ML engineering",
            "Requires production LLM application evidence",
            "Engineering basics include Linux, CI/CD and deployment",
        ],
        cv=cv_for("Cluster D", "German"),
        headline="AI Workflow Automation Engineer | Python, Human Review, RAG Concepts, Process Automation",
        note="Strong keyword match but seniority risk; use mainly for networking or if you can show a strong practical project.",
    ),
]


UPDATES = [
    {
        "company_contains": "affinis",
        "title_contains": "microsoft dynamics 365 crm consultant",
        "replacement": ADDITIONS[14],
    },
    {
        "company_contains": "reply",
        "title_contains": "consultant automation ai uipath",
        "replacement": ADDITIONS[15],
    },
]


EXCLUSIONS = [
    "WBS Gruppe Junior Power Platform Developer - excellent keyword fit but Remotely page states the job has not been available since 2026-03-24.",
    "STARK Automation Engineer - source page states the job is no longer accepting applications.",
    "Neovaro Automation Engineer - source page states the job is no longer available.",
    "Allianz Business Analyst Systemintegration & Prozesssteuerung - direct Allianz page showed job filled despite third-party mirrors still listing it.",
    "smartvillage Data Science Engineer - adjacent role but less aligned than AI & Automation Engineer and likely heavier analytics/statistics.",
    "BMW Senior Applied AI / ML Engineer and Founding Data Scientist postings - too senior/deep AI for the current CV evidence.",
    "Infineon Principal Engineer Agentic Software Development and Verification - senior/principal scope, not realistic for this search.",
    "Apple E-Commerce & AI Specialist - e-commerce/partner sales scope, weak engineering-process match.",
    "elunic AI Sales Consultant roles - sales-led, excluded by rule.",
]


def backup_files_round3() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"latest_search_round3_{stamp}"
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
        pack_backup = dest / "previous_application_ready_today"
        pack_backup.mkdir(exist_ok=True)
        for pack in APP_READY.glob("*.md"):
            shutil.copy2(pack, pack_backup / pack.name)
            pack.unlink()
    return dest


def title_match(row_title: str, needle: str) -> bool:
    title = normalize_text(row_title)
    return all(part in title for part in normalize_text(needle).split())


def apply_updates(rows: list[dict[str, str]]) -> int:
    updated = 0
    for row in rows:
        company_norm = normalize_text(row.get("Company", ""))
        for update in UPDATES:
            if update["company_contains"] not in company_norm:
                continue
            if not title_match(row.get("JobTitle", ""), update["title_contains"]):
                continue
            replacement = update["replacement"]
            keep_rank = row.get("Rank", "")
            keep_status = row.get("NewOrExisting", "Existing") or "Existing"
            row.update({field: replacement.get(field, "") for field in FIELDNAMES})
            row["Rank"] = keep_rank
            row["NewOrExisting"] = keep_status
            row["DuplicateOf"] = ""
            row["CheckedAt"] = CHECKED_AT
            updated += 1
            break
    return updated


def merge_rows(previous_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str], int]:
    seen_urls = {normalize_url(row.get("SourceURL", "")): row for row in previous_rows if row.get("SourceURL")}
    seen_titles = {
        f"{normalize_text(row.get('Company', ''))}|{normalize_text(row.get('JobTitle', ''))}": row
        for row in previous_rows
    }
    kept = list(previous_rows)
    duplicate_reasons: list[str] = []
    additions_kept = 0

    update_urls = {normalize_url(update["replacement"]["SourceURL"]) for update in UPDATES}
    update_title_keys = {
        f"{normalize_text(update['replacement']['Company'])}|{normalize_text(update['replacement']['JobTitle'])}"
        for update in UPDATES
    }

    for addition in ADDITIONS:
        url_key = normalize_url(addition.get("SourceURL", ""))
        title_key = f"{normalize_text(addition.get('Company', ''))}|{normalize_text(addition.get('JobTitle', ''))}"
        if url_key in update_urls or title_key in update_title_keys:
            continue
        if url_key and url_key in seen_urls:
            original = seen_urls[url_key]
            duplicate_reasons.append(f"{addition['Company']} - {addition['JobTitle']} duplicate URL of {original.get('Company')} - {original.get('JobTitle')}")
            continue
        if title_key in seen_titles:
            original = seen_titles[title_key]
            duplicate_reasons.append(f"{addition['Company']} - {addition['JobTitle']} duplicate title of {original.get('Company')} - {original.get('JobTitle')}")
            continue
        kept.append(addition)
        additions_kept += 1
        if url_key:
            seen_urls[url_key] = addition
        seen_titles[title_key] = addition
    return kept, duplicate_reasons, additions_kept


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


def write_main_report(rows: list[dict[str, str]], previous_count: int, added_count: int, duplicate_count: int, updated_count: int, backup_dir: Path) -> None:
    new_rows = [row for row in rows if row.get("NewOrExisting") == "New"]
    role_counts = Counter(row.get("RoleCluster", "").split(";")[0].strip() for row in rows)
    source_counts = Counter(row.get("Source", "").split("/")[0].strip() for row in rows)
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
            f"Loaded {previous_count} previously tracked suitable jobs, appended {added_count} additional suitable jobs, "
            f"upgraded {updated_count} existing rows to cleaner direct-source data, removed/skipped {duplicate_count} duplicates, "
            f"and now keep {len(rows)} suitable active or recently active roles. The two B.Eng. study programs were considered as positive evidence for industrial engineering, engineering management, process improvement, requirements work and technical project coordination; they were not used to over-score senior AI/ML or cloud architecture jobs."
        ),
        "",
        "## 2. Number Of Jobs Found",
        f"- Total suitable jobs in continued list: {len(rows)}",
        f"- Rows marked new from all continued searches: {len(new_rows)}",
        f"- Newly appended in this latest pass: {added_count}",
        f"- Existing rows updated with direct-source data: {updated_count}",
        "",
        "## 3. Number Of Jobs Excluded And Why",
        f"- Excluded in this latest pass: {len(EXCLUSIONS)}",
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
        "- Deloitte",
        "- REPA Deutschland / REPA GROUP",
        "- 42watt",
        "- Bertrandt Group",
        "- BMW Group",
        "- Siemens / Siemens Mobility",
        "- TUV SUD",
        "",
        "## 9. Missing Skills Repeated Across The Market",
        "- Copilot Studio, AI Builder and Microsoft agent governance.",
        "- Dataverse, Power Apps and Power Platform ALM/governance.",
        "- n8n/Make, API/webhook automation and structured error handling.",
        "- SQL, Power BI, Power Query and basic DAX for data/process analyst roles.",
        "- RAG, embeddings, vector stores, function calling/tool use and LLM evals.",
        "- UiPath/Blue Prism for RPA roles.",
        "- DOORS/Polarion, ASPICE/ISO 26262 and model-based testing for automotive validation roles.",
        "",
        "## 10. CV Version Recommendation",
        "Use ATS Process Automation CV - German most often. Switch to ATS Quality & Validation CV - German for Bertrandt/MEKRA/b-plus/ALTEN validation roles. Use English for international AI/data postings such as REPA AI Engineer or English-language consulting roles.",
        "",
        "## 11. Application Plan For Today",
        "- Apply to 5-8 high-quality roles, not the whole list.",
        "- Start with direct portals for Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, 42watt, REPA Junior Data Analyst and TPG.",
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
        "## Source Mix",
        "\n".join(f"- {source or 'Unclear'}: {count}" for source, count in source_counts.most_common(12)),
        "",
        f"Backup folder for this update: {backup_dir}",
        "",
    ]
    CONTINUED_MD.write_text("\n".join(report), encoding="utf-8")


def write_outputs(rows: list[dict[str, str]], previous_count: int, added_count: int, duplicate_count: int, updated_count: int, backup_dir: Path) -> None:
    write_csv(CONTINUED_CSV, rows)
    write_csv(NEW_ONLY_CSV, [row for row in rows if row.get("NewOrExisting") == "New"])
    write_main_report(rows, previous_count, added_count, duplicate_count, updated_count, backup_dir)

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
                    for row in sorted(ADDITIONS[:], key=score_value, reverse=True)[:10]
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
                    f"- {row['Company']} - {row['JobTitle']}: {row['SourceURL']}"
                    for row in sorted(ADDITIONS[:], key=score_value, reverse=True)[:12]
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
            + [
                "## Latest-Pass Direct Outreach Targets",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']}: {german_message(row)}"
                    for row in sorted(ADDITIONS[:], key=score_value, reverse=True)[:5]
                ),
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
                "2. Choose 5-8 applications: prioritize Workspacer, Campana & Schott, fly-tech, Keller & Kalmbach, RATHGEBER, 42watt, REPA Junior Data Analyst and TPG.",
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
                "- Mini RAG assistant for industrial/quality documentation with citations and 'cannot answer' behavior.",
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
                f"- Previous suitable jobs loaded: {previous_count}",
                f"- New jobs found and appended in this pass: {added_count}",
                f"- Existing rows upgraded: {updated_count}",
                f"- Duplicates skipped/removed in this pass: {duplicate_count}",
                f"- Final suitable jobs in continued list: {len(rows)}",
                f"- Backup folder: {backup_dir}",
                "",
                "## Best New Matches",
                "\n".join(
                    f"- {row['Company']} - {row['JobTitle']} ({row['FitScore']}/10): {row['SourceURL']}"
                    for row in sorted(ADDITIONS[:], key=score_value, reverse=True)[:12]
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
    backup_dir = backup_files_round3()
    updated_count = apply_updates(previous_rows)
    merged, duplicate_reasons, additions_kept = merge_rows(previous_rows)
    rows = rank_rows(merged)
    write_outputs(rows, previous_count, additions_kept, len(duplicate_reasons), updated_count, backup_dir)
    print(f"Previous rows: {previous_count}")
    print(f"New additions kept: {additions_kept}")
    print(f"Existing rows updated: {updated_count}")
    print(f"Duplicates skipped: {len(duplicate_reasons)}")
    print(f"Final rows: {len(rows)}")
    print(f"Backup: {backup_dir}")
    print("Top 12:")
    for row in rows[:12]:
        print(f"{row['Rank']}. {row['FitScore']} - {row['Company']} - {row['JobTitle']}")


if __name__ == "__main__":
    main()
