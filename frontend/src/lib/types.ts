// ------------------------------------------------------------------
// TypeScript types mirroring backend/app/models/ Pydantic models.
// Keep in sync — any backend model change must be reflected here.
// ------------------------------------------------------------------

// --- blueprint.py ---

export interface Column {
  id: string;
  x0: number;
  x1: number;
  y_top: number;
  y_bottom: number;
}

export interface BackgroundRegion {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  color: [number, number, number];
  opacity: number;
}

export interface ElementStyle {
  font: string;
  size: number;
  color: [number, number, number];
  bold: boolean;
  italic: boolean;
  align: string;
  leading: number;
  bg_color: [number, number, number] | null;
  bar_height: number;
  spacing_before: number;
  spacing_after: number;
  bullet_char: string;
  col_idx: number;
}

export interface Section {
  label: string;
  content_key: string;
}

export interface Blueprint {
  page_width: number;
  page_height: number;
  layout_type: string;
  background_regions: BackgroundRegion[];
  columns: Column[];
  element_styles: Record<string, ElementStyle>;
  section_map: Record<string, Section[]>;
  skill_format: string;
  job_entry_format: string;
  job_body_format: string;
  line_spacing: number;
  section_spacing: number;
  entry_spacing: number;
  bullet_indent: number;
}

// --- content.py ---

export interface Contact {
  email: string | null;
  phone: string | null;
  location: string | null;
  linkedin: string | null;
  github: string | null;
  website: string | null;
}

export interface Experience {
  company: string;
  title: string;
  dates: string;
  bullets: string[];
  description: string | null;
}

export interface Education {
  degree: string;
  school: string;
  dates: string;
  gpa: string | null;
  bullets: string[];
}

export interface Skill {
  category: string;
  items: string[];
}

export interface Project {
  name: string;
  title: string | null;
  dates: string | null;
  bullets: string[];
  description: string | null;
  url: string | null;
}

export interface ResumeContent {
  name: string;
  title: string | null;
  summary: string | null;
  contact: Contact;
  skills: Skill[];
  experience: Experience[];
  education: Education[];
  projects: Project[];
}

// --- template.py ---

export interface TemplateMeta {
  id: string;
  name: string;
  created_at: string; // ISO 8601 datetime
  updated_at: string; // ISO 8601 datetime
  has_source: boolean;
  has_blueprint: boolean;
}

export interface TemplateDetail extends TemplateMeta {
  blueprint: Blueprint | null;
}
