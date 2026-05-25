"""John Doe scaffold Resume. Used by /api/resume/scaffold to seed a Qdrant
point when the user starts without uploading their own file."""
from app.models.resume_schema import (
    Resume,
    ContactInfo,
    ExperienceEntry,
    EducationEntry,
    ProjectEntry,
    SkillCategory,
)
from app.core.renderer import _DEFAULT_ORDER


def build_sample_resume() -> Resume:
    """Return a fully-populated John Doe Resume suitable as an editing scaffold."""
    return Resume(
        name="John Doe",
        contact=ContactInfo(
            email="john.doe@example.com",
            phone="(555) 123-4567",
            location="San Francisco, CA",
            linkedin="linkedin.com/in/johndoe",
            github="github.com/johndoe",
        ),
        summary=(
            "Software engineer with experience building backend services and data "
            "pipelines. Comfortable across the stack from API design to deployment."
        ),
        experience=[
            ExperienceEntry(
                title="Software Engineer",
                company="Acme Corp",
                location="San Francisco, CA",
                start_date="Jan 2023",
                end_date="Present",
                bullets=[
                    "Built REST APIs serving 2M+ requests per day with sub-100ms p95 latency.",
                    "Designed PostgreSQL schemas and optimized queries to cut report generation time by 60%.",
                    "Owned CI/CD pipeline migration from Jenkins to GitHub Actions across 12 services.",
                ],
            ),
            ExperienceEntry(
                title="Junior Software Engineer",
                company="Beta Labs",
                location="Remote",
                start_date="Jun 2021",
                end_date="Dec 2022",
                bullets=[
                    "Shipped customer-facing dashboard features in React and TypeScript.",
                    "Wrote unit and integration tests, raising coverage from 45% to 78%.",
                ],
            ),
        ],
        projects=[
            ProjectEntry(
                name="Resume Matcher",
                tech="Python, FastAPI, Qdrant",
                date="2024",
                bullets=[
                    "Open-source tool that scores resumes against job descriptions using hybrid keyword + semantic matching.",
                    "Reduced false-positive matches by 35% with skill taxonomy normalization.",
                ],
            ),
            ProjectEntry(
                name="Task Queue Library",
                tech="Go, Redis",
                date="2023",
                bullets=[
                    "Lightweight distributed task queue with at-least-once delivery and dead-letter handling.",
                    "Benchmarked at 50k jobs/sec on a single Redis instance.",
                ],
            ),
        ],
        skills=[
            SkillCategory(
                category="Languages",
                skills=["Python", "TypeScript", "Go", "SQL"],
            ),
            SkillCategory(
                category="Frameworks",
                skills=["FastAPI", "React", "Next.js", "Django"],
            ),
            SkillCategory(
                category="Tools",
                skills=["Docker", "PostgreSQL", "Redis", "AWS", "GitHub Actions"],
            ),
        ],
        education=[
            EducationEntry(
                institution="State University",
                degree="Bachelor of Science",
                field="Computer Science",
                location="Berkeley, CA",
                start_date="Aug 2017",
                end_date="May 2021",
                gpa="3.7",
            ),
        ],
        certifications=[
            "AWS Certified Solutions Architect – Associate",
        ],
        section_order=list(_DEFAULT_ORDER),
        hidden_sections=[],
    )
