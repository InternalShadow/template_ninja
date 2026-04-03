from pydantic import BaseModel


class Contact(BaseModel):
    """User contact information."""

    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class Experience(BaseModel):
    """A single work-experience entry."""

    company: str
    title: str
    dates: str
    bullets: list[str] = []
    description: str | None = None


class Education(BaseModel):
    """A single education entry."""

    degree: str
    school: str
    dates: str
    gpa: str | None = None
    bullets: list[str] = []


class Skill(BaseModel):
    """A group of related skills under one category."""

    category: str
    items: list[str]


class Project(BaseModel):
    """A single project entry."""

    name: str
    title: str | None = None
    dates: str | None = None
    bullets: list[str] = []
    description: str | None = None
    url: str | None = None


class ResumeContent(BaseModel):
    """All user-supplied resume data, independent of visual layout."""

    name: str
    title: str | None = None
    summary: str | None = None
    contact: Contact = Contact()
    skills: list[Skill] = []
    experience: list[Experience] = []
    education: list[Education] = []
    projects: list[Project] = []
